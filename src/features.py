"""Feature construction: per-game/per-36 normalization, contract-year flags, filters.

Thresholds below are the pipeline's only tuning knobs — change them deliberately
and document the change in the writeup.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_GAMES = 20    # drop tiny-sample seasons: rate stats get noisy
MIN_MINUTES_PG = 10


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # normalize minutes to per-game (accept either totals or per-game input)
    if df["minutes"].median() > 48:
        df["minutes_total"] = df["minutes"].astype(float)
        df["minutes_pg"] = df["minutes_total"] / df["games"]
    else:
        df["minutes_pg"] = df["minutes"].astype(float)
        df["minutes_total"] = df["minutes_pg"] * df["games"]

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
        print(f"NOTE: no 'bpm' column — built z-scored composite from {parts}.")

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
        print(f"Filtered {dropped} seasons with games < {MIN_GAMES} or "
              f"minutes_pg < {MIN_MINUTES_PG}.")

    out_cols = [
        "player_id", "player_name", "season", "age", "age2", "team",
        "games", "minutes_pg", "games_missed", "bpm",
        "pts36", "reb36", "ast36",
        "contract_year", "post_contract_year", "salary", "contract_type",
    ]
    df = df[[c for c in out_cols if c in df.columns]]
    return df.round({"minutes_pg": 2, "bpm": 3, "pts36": 2, "reb36": 2, "ast36": 2})
