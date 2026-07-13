"""Ingest layer: multi-file concat, column mapping, validation — all frames-in/frames-out.

This is the single source of truth for "does this data satisfy the contract in
docs/DATA_DICTIONARY.md". Both entry points use it, so they cannot drift apart:

    src/validate_raw.py   reads data/raw/  -> validate_tables()   (terminal)
    app/streamlit_app.py  reads uploads    -> validate_tables()   (browser)

Nothing here touches the filesystem except read_frames(), which is the only
function the web app does NOT call (it has uploaded file objects instead).
"""

from __future__ import annotations

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

    return pd.concat(frames, ignore_index=True, sort=False), problems


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
                frames.append(load_table(path))
            except Exception as e:  # unreadable file: report, keep checking the rest
                problems.append(
                    Problem(table, f"could not read {path.name}: {e}",
                            "Re-export the file as .xlsx or .csv.")
                )
        if frames:
            df, concat_problems = concat_frames(frames, table)
            tables[table] = df
            problems.extend(concat_problems)

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
