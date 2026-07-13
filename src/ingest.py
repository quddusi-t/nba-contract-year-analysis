"""Ingest layer: multi-file concat, column mapping, validation — all frames-in/frames-out.

This is the single source of truth for "does this data satisfy the contract in
docs/DATA_DICTIONARY.md". Both entry points use it, so they cannot drift apart:

    src/validate_raw.py   reads data/raw/  -> validate_tables()   (terminal)
    app/streamlit_app.py  reads uploads    -> validate_tables()   (browser)

Nothing here touches the filesystem except read_frames(), which is the only
function the web app does NOT call (it has uploaded file objects instead).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from common import load_table, normalize_columns

# Canonical columns per table, plus the header spellings we can auto-detect.
# Aliases are matched after normalize_columns(), so 'Player Name' arrives as
# 'player_name'. Sources differ: Basketball-Reference uses G/MP/TRB, Spotrac
# uses different names again — hence the alias lists.
ALIASES: dict[str, list[str]] = {
    "player_name": ["player", "name", "player_name", "playername", "full_name"],
    "player_id": ["player_id", "id", "bbref_id", "playerid"],
    "season": ["season", "year", "season_end", "yr"],
    "age": ["age"],
    "team": ["team", "tm", "franchise"],
    "games": ["games", "g", "gp", "games_played"],
    "minutes": ["minutes", "mp", "min", "minutes_played"],
    "bpm": ["bpm", "box_plus_minus", "per", "ws48", "ws_48"],
    "pts": ["pts", "points", "p"],
    "reb": ["reb", "trb", "rebounds", "rb"],
    "ast": ["ast", "assists", "a"],
    "contract_end_season": [
        "contract_end_season", "contract_end", "end_season", "expires",
        "expiry", "final_year", "last_year",
    ],
    "salary": ["salary", "cap_hit", "pay", "aav"],
    "contract_type": ["contract_type", "type", "deal_type"],
}


@dataclass(frozen=True)
class TableSpec:
    required: tuple[str, ...]
    optional: tuple[str, ...]


# 'player_name' / 'player_id' are handled separately: at least one is required.
TABLE_SPECS: dict[str, TableSpec] = {
    "stats": TableSpec(
        required=("season", "age", "games", "minutes"),
        optional=("player_name", "player_id", "team", "bpm", "pts", "reb", "ast"),
    ),
    "contracts": TableSpec(
        required=("season", "contract_end_season"),
        optional=("player_name", "player_id", "salary", "contract_type"),
    ),
    "injuries": TableSpec(
        required=("season", "games_missed"),
        optional=("player_name", "player_id"),
    ),
}

REQUIRED_TABLES = ("stats", "contracts")


@dataclass(frozen=True)
class Problem:
    """One validation finding. `blocking` problems stop the pipeline; others are advisory."""

    table: str
    message: str
    fix: str
    blocking: bool = True


def suggest_mapping(columns: list[str], table: str) -> dict[str, str]:
    """Guess {source column -> canonical name} for a table's headers.

    Only suggests canonical names that belong to this table, and never maps two
    source columns onto the same canonical name (first match wins, which is why
    ALIASES lists the exact name first).
    """
    spec = TABLE_SPECS[table]
    wanted = set(spec.required) | set(spec.optional)
    if table == "injuries":
        wanted.add("games_missed")

    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for canonical in list(spec.required) + list(spec.optional) + ["games_missed"]:
        if canonical not in wanted or canonical in taken:
            continue
        for alias in ALIASES.get(canonical, [canonical]):
            for col in columns:
                if col in mapping:
                    continue
                if col == alias:
                    mapping[col] = canonical
                    taken.add(canonical)
                    break
            if canonical in taken:
                break
    return mapping


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Rename source columns to canonical names, dropping unmapped ones."""
    keep = {src: dst for src, dst in mapping.items() if dst and src in df.columns}
    return df[list(keep)].rename(columns=keep)


def concat_frames(frames: list[pd.DataFrame], table: str) -> tuple[pd.DataFrame, list[Problem]]:
    """Stack several files belonging to one table (typically one per season).

    Columns are unioned: a column missing from one file becomes NaN for its rows,
    which the validator then reports. That is deliberate — silently dropping a
    column present in only some seasons would corrupt the panel.
    """
    problems: list[Problem] = []
    if not frames:
        return pd.DataFrame(), problems

    frames = [normalize_columns(f) for f in frames]
    if len(frames) > 1:
        shared = set(frames[0].columns)
        for f in frames[1:]:
            shared &= set(f.columns)
        odd = [c for f in frames for c in f.columns if c not in shared]
        if odd:
            problems.append(
                Problem(
                    table,
                    f"these columns are not present in every file: {sorted(set(odd))}",
                    "Rows from files missing a column get empty cells there. Fine if "
                    "intentional (e.g. BPM only exists in later seasons); otherwise "
                    "fix the odd file out.",
                    blocking=False,
                )
            )

    df = pd.concat(frames, ignore_index=True, sort=False)

    # Two shapes that real exports arrive in and the panel cannot use as-is.
    if table == "stats":
        df, p = drop_traded_partials(df)
        problems += p
    if table == "contracts":
        df, p = reshape_wide_contracts(df)
        problems += p

    return df, problems


# A per-season export usually carries no 'Season' column — the season is only in the
# filename ('stats_2019.xlsx'). Recover it, but say so, because a wrong season silently
# misaligns the whole panel.
YEAR_IN_NAME = re.compile(r"(?:19|20)\d{2}")

# '2024-25' or '2024_25' style salary column headers on a wide contracts sheet
SEASON_COL = re.compile(r"^(19|20)\d{2}[-_]\d{2}$")


def season_from_filename(filename: str) -> int | None:
    years = YEAR_IN_NAME.findall(Path(filename).stem)
    return int(years[-1]) if years else None


def looks_wide(df: pd.DataFrame) -> bool:
    """A contracts grid with a column per season, e.g. Basketball-Reference's page."""
    return sum(bool(SEASON_COL.match(str(c))) for c in df.columns) >= 2


def attach_season(
    df: pd.DataFrame, filename: str, table: str
) -> tuple[pd.DataFrame, list[Problem]]:
    """If a file has no season column, take the season from its filename."""
    if "season" in df.columns or df.empty:
        return df, []
    if looks_wide(df):
        return df, []  # a wide sheet gets its season from the reshape, not the filename

    year = season_from_filename(filename)
    if year is None:
        return df, [
            Problem(
                table,
                f"{filename} has no 'season' column and no year in its filename",
                "Either add a Season column to the sheet, or rename the file so it "
                "contains the season END year (2023-24 season -> 'stats_2024.xlsx').",
            )
        ]

    df = df.copy()
    df["season"] = year
    return df, [
        Problem(
            table,
            f"{filename} has no 'season' column — using {year} from the filename",
            f"Make sure {filename} really is the {year - 1}-{str(year)[2:]} season. "
            "Season must be the END year. If it's off by one, every contract-year "
            "flag shifts and the result is garbage.",
            blocking=False,
        )
    ]


# A traded player gets one row per team plus a season-total row. Basketball-Reference
# labels the total 'TOT' (older exports) or '2TM'/'3TM' (newer ones).
TOTAL_TEAM = re.compile(r"^(TOT|\dTM)$", re.IGNORECASE)


def _team_col(df: pd.DataFrame) -> str | None:
    for c in ("team", "tm"):
        if c in df.columns:
            return c
    return None


def drop_traded_partials(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Problem]]:
    """Keep only the season-total row for traded players.

    Without this, a player traded mid-season appears 3 times in one season and the
    duplicate check blocks the build. Keeping a per-team row instead of the total
    would silently understate his games and minutes, so the total is the right one.
    """
    team = _team_col(df)
    name = "player_name" if "player_name" in df.columns else "player"
    if team is None or name not in df.columns or "season" not in df.columns:
        return df, []

    is_total = df[team].astype(str).str.strip().apply(lambda v: bool(TOTAL_TEAM.match(v)))
    if not is_total.any():
        return df, []

    # a player-season is "split" if it has a total row; drop that season's team rows
    split_keys = set(map(tuple, df.loc[is_total, [name, "season"]].to_numpy()))
    keys = list(map(tuple, df[[name, "season"]].to_numpy()))
    keep = [is_total.iloc[i] or keys[i] not in split_keys for i in range(len(df))]

    dropped = len(df) - sum(keep)
    problems = [
        Problem(
            "stats",
            f"{int(is_total.sum())} traded player-seasons had one row per team plus a "
            f"season-total row — kept the total, dropped {dropped} partial rows",
            "This is what you want: the total row has the player's full season. "
            "If your export has no total rows for traded players, sum them yourself.",
            blocking=False,
        )
    ]
    return df[keep].reset_index(drop=True), problems


def _to_money(v: object) -> float:
    """'$40,000,000' -> 40000000.0; blanks and junk -> NaN."""
    if pd.isna(v):
        return float("nan")
    cleaned = re.sub(r"[^0-9.]", "", str(v))
    return float(cleaned) if cleaned else float("nan")


def reshape_wide_contracts(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Problem]]:
    """Turn a one-row-per-player salary grid into one row per player-season.

    Basketball-Reference's contracts page is *wide*: a row per player, a column per
    future season holding that season's salary. The panel needs the long shape, plus
    a contract_end_season. We derive it as the last season the player has a salary
    for — which is a real assumption, not a fact, so it is flagged loudly.
    """
    if "season" in df.columns or not looks_wide(df):
        return df, []  # already long, or not this shape
    season_cols = [c for c in df.columns if SEASON_COL.match(str(c))]

    id_cols = [c for c in df.columns if c in ("player_name", "player", "player_id", "team", "tm")]
    long = df.melt(
        id_vars=id_cols, value_vars=season_cols, var_name="season", value_name="salary"
    )
    long["salary"] = long["salary"].map(_to_money)
    long = long.dropna(subset=["salary"])
    # '2024-25' is the 2024-25 season, whose END year is 2025
    long["season"] = long["season"].str[:4].astype(int) + 1

    key = "player_name" if "player_name" in long.columns else id_cols[0]
    long["contract_end_season"] = long.groupby(key)["season"].transform("max")

    # A salary grid only encodes contract boundaries if each row is ONE contract.
    # If it is a career salary history, "last season with a salary" is the end of the
    # player's career, not the end of his deal — every intermediate contract year
    # vanishes and the effect washes out to nothing. The longest possible NBA contract
    # is 5 years (6 with an extension), so a longer run gives the game away.
    span = long.groupby(key)["season"].nunique()
    if len(span) and span.max() > 6:
        return long, [
            Problem(
                "contracts",
                f"this looks like a salary HISTORY, not a contract: {int((span > 6).sum())} "
                f"player(s) have salaries spanning up to {int(span.max())} seasons, and no "
                "NBA contract runs that long",
                "Salary-per-season alone cannot say where one contract ends and the next "
                "begins, so the contract-year flag would be wrong — it would mark only "
                "each player's final season and wash the effect out to zero. You need "
                "actual contract boundaries: a contract_end_season (or a start year + "
                "length) per player-season. Spotrac has contract history; "
                "Basketball-Reference's contracts page only shows the CURRENT deal.",
            )
        ]

    return long, [
        Problem(
            "contracts",
            f"contracts arrived wide ({len(season_cols)} season columns) — reshaped to "
            f"{len(long)} player-season rows",
            "contract_end_season was set to the LAST season each player has a salary for. "
            "That treats option years as guaranteed, which shifts the contract year by a "
            "season. Spot-check a few players on Spotrac and state the rule you used in "
            "the writeup — this flag drives the entire study.",
            blocking=False,
        )
    ]


def read_frames(raw_dir: Path) -> tuple[dict[str, pd.DataFrame], list[Problem]]:
    """Filesystem adapter: read data/raw/ into one frame per table."""
    from common import find_tables

    paths = find_tables(raw_dir)
    tables: dict[str, pd.DataFrame] = {}
    problems: list[Problem] = []

    for table, files in paths.items():
        frames = []
        for path in files:
            try:
                df = load_table(path)
            except Exception as e:  # unreadable file: report, keep checking the rest
                problems.append(
                    Problem(table, f"could not read {path.name}: {e}",
                            "Re-export the file as .xlsx or .csv.")
                )
                continue
            df, season_problems = attach_season(df, path.name, table)
            problems.extend(season_problems)
            frames.append(df)
        if not frames:
            continue

        df, concat_problems = concat_frames(frames, table)
        problems.extend(concat_problems)

        # The console has a screen for this; the CLI applies the alias guesses silently
        # so a raw Basketball-Reference export (Player/G/MP/TRB) works without hand-
        # editing the sheet. Unrecognized columns (Rk, Pos, GS...) are dropped.
        mapping = suggest_mapping(list(df.columns), table)
        unmapped = [c for c in df.columns if c not in mapping]
        if unmapped:
            problems.append(
                Problem(
                    table,
                    f"ignoring columns the pipeline has no use for: {sorted(unmapped)}",
                    "If one of these is actually your season/minutes/BPM column under an "
                    "unusual name, rename it in the sheet (or add it to ALIASES in "
                    "src/ingest.py) — otherwise ignore this.",
                    blocking=False,
                )
            )
        tables[table] = apply_mapping(df, mapping)

    return tables, problems


def validate_tables(tables: dict[str, pd.DataFrame]) -> list[Problem]:
    """Check merged frames against the data contract. Empty list = ready to build."""
    problems: list[Problem] = []

    for table in REQUIRED_TABLES:
        if table not in tables or tables[table].empty:
            problems.append(
                Problem(table, f"required table '{table}' is missing",
                        f"Upload at least one {table} file.")
            )

    for table, df in tables.items():
        if table not in TABLE_SPECS or df.empty:
            continue
        spec = TABLE_SPECS[table]
        cols = set(df.columns)

        if "player_id" not in cols and "player_name" not in cols:
            problems.append(
                Problem(table, "no player identifier",
                        "Map one of your columns to 'player_name' (or 'player_id').")
            )

        for col in spec.required:
            if col not in cols:
                problems.append(
                    Problem(table, f"missing required column '{col}'",
                            f"Map one of your columns to '{col}' in the mapping step.")
                )

        if table == "stats" and "bpm" not in cols:
            missing = {"pts", "reb", "ast"} - cols
            if missing:
                problems.append(
                    Problem(
                        table,
                        f"no 'bpm' column, and the per-36 fallback needs {sorted(missing)}",
                        "Either map a composite metric (BPM, PER, WS/48) to 'bpm', or "
                        "supply all of pts/reb/ast so a per-36 composite can be built.",
                    )
                )

        if "season" in cols:
            seasons = pd.to_numeric(df["season"], errors="coerce")
            bad = int(seasons.isna().sum())
            if bad:
                problems.append(
                    Problem(table, f"{bad} rows where 'season' is not a number",
                            "Seasons must be the END year as a plain integer: 2023-24 -> 2024.")
                )
            elif len(seasons) and (seasons.min() < 1990 or seasons.max() > 2030):
                problems.append(
                    Problem(
                        table,
                        f"season range {int(seasons.min())}-{int(seasons.max())} looks wrong",
                        "Use the season END year: the 2023-24 season is 2024.",
                    )
                )

        key = "player_id" if "player_id" in cols else "player_name"
        if key in cols and "season" in cols:
            dupes = int(df.duplicated([key, "season"]).sum())
            if dupes:
                problems.append(
                    Problem(
                        table,
                        f"{dupes} duplicate ({key}, season) rows",
                        "One row per player per season. Traded players often appear "
                        "several times (one row per team plus a TOT row) — keep the "
                        "TOT/total row only.",
                    )
                )

        for col in df.columns:
            if col in ("player_name", "team", "contract_type"):
                continue
            na = int(df[col].isna().sum())
            if na:
                problems.append(
                    Problem(table, f"column '{col}' has {na} empty cells",
                            "May be fine; rows with no contract info get dropped later.",
                            blocking=False)
                )

    return problems
