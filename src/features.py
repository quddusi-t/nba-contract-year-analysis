"""Feature construction: per-game/per-36 normalization, contract-year flags, filters.

Thresholds below are the pipeline's only tuning knobs — change them deliberately
and document the change in the writeup.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_GAMES = 20    # drop tiny-sample seasons: rate stats get noisy
MIN_MINUTES_PG = 10


def build_features(df: pd.DataFrame, report: list[str] | None = None) -> pd.DataFrame:
    """Build the model's variables. Pass `report` to collect what was done and dropped."""
    df = df.copy()

    def note(msg: str) -> None:
        print(msg)
        if report is not None:
            report.append(msg)

    # normalize minutes to per-game (accept either totals or per-game input)
    if df["minutes"].median() > 48:
        df["minutes_total"] = df["minutes"].astype(float)
        df["minutes_pg"] = df["minutes_total"] / df["games"]
        note("Read 'minutes' as SEASON TOTALS (the typical value is over 48), and "
             "divided by games to get minutes per game.")
    else:
        df["minutes_pg"] = df["minutes"].astype(float)
        df["minutes_total"] = df["minutes_pg"] * df["games"]
        note("Read 'minutes' as PER GAME (the typical value is under 48).")

    # per-36 counting stats when available
    for col in ("pts", "reb", "ast"):
        if col in df.columns:
            df[f"{col}36"] = df[col] / df["minutes_total"] * 36

    # outcome: real composite if present, else z-scored per-36 composite
    if "bpm" not in df.columns:
        parts = [c for c in ("pts36", "reb36", "ast36") if c in df.columns]
        if not parts:
            raise ValueError("Need 'bpm' or pts/reb/ast to build an outcome metric.")
        zs = [(df[c] - df[c].mean()) / df[c].std() for c in parts]
        df["bpm"] = sum(zs) / len(zs)
        note(f"No 'bpm' column, so the outcome was built as a z-scored average of "
             f"{parts} (per-36 rates). Say so in your writeup — it is not the same "
             "metric as real BPM.")
    else:
        missing_bpm = int(df["bpm"].isna().sum())
        if missing_bpm:
            note(f"{missing_bpm} player-seasons have an empty 'bpm'. They are KEPT in "
                 "the file but the regression will ignore them — a missing outcome "
                 "cannot be invented, and imputing performance would fabricate the "
                 "very thing you are measuring.")

    df["contract_year"] = (df["season"] == df["contract_end_season"]).astype(int)

    # post_contract_year: player's season right after a contract year (shirking check)
    df = df.sort_values(["player_id", "season"])
    prev_flag = df.groupby("player_id")["contract_year"].shift(1)
    prev_season = df.groupby("player_id")["season"].shift(1)
    df["post_contract_year"] = (
        (prev_flag == 1) & (df["season"] == prev_season + 1)
    ).astype(int)

    df["age"] = df["age"].astype(int)
    df["age2"] = df["age"] ** 2

    before = len(df)
    df = df[(df["games"] >= MIN_GAMES) & (df["minutes_pg"] >= MIN_MINUTES_PG)]
    dropped = before - len(df)
    if dropped:
        note(f"DROPPED {dropped} of {before} player-seasons for playing under "
             f"{MIN_GAMES} games or under {MIN_MINUTES_PG} minutes per game. A rate "
             "stat computed on a handful of minutes is mostly noise and would widen "
             "the confidence interval for nothing.")

    out_cols = [
        "player_id", "player_name", "season", "age", "age2", "team",
        "games", "minutes_pg", "games_missed", "bpm",
        "pts36", "reb36", "ast36",
        "contract_year", "post_contract_year", "salary", "contract_type",
    ]
    # Some columns are consumed to build others (minutes -> minutes_pg, pts/reb/ast ->
    # per-36 rates, contract_end_season -> contract_year) and don't belong in the
    # output. Saying they were "dropped" would read as data loss, which it isn't.
    CONSUMED = {"minutes", "minutes_total", "contract_end_season", "pts", "reb", "ast"}
    leftover = [c for c in df.columns if c not in out_cols and c not in CONSUMED]
    note("The final file keeps only what the model needs. Columns used to build other "
         "columns are not carried through: minutes → minutes_pg, pts/reb/ast → per-36 "
         "rates, contract_end_season → contract_year. Nothing is lost — they were used.")
    if leftover:
        note(f"These columns were not used by the analysis and are not in the final "
             f"file: {sorted(leftover)}.")
    df = df[[c for c in out_cols if c in df.columns]]
    note(f"Final dataset: {len(df)} player-seasons, {df['player_id'].nunique()} players, "
         f"{df['contract_year'].mean():.1%} of them contract years.")
    return df.round({"minutes_pg": 2, "bpm": 3, "pts36": 2, "reb36": 2, "ast36": 2})
