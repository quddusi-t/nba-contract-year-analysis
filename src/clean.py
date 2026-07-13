"""Normalize identifiers and merge the raw tables into one player-season frame.

merge_tables() is the real work and takes DataFrames, so the web console can call
it on uploads that never touch disk. load_and_merge() is the thin filesystem
adapter used by the CLI.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import normalize_name
from ingest import REQUIRED_TABLES, read_frames


def _ensure_player_id(df: pd.DataFrame, name_to_id: dict[str, int], table: str) -> pd.DataFrame:
    """Guarantee a player_id column, deriving it from normalized names if needed."""
    df = df.copy()
    if "player_id" not in df.columns:
        if "player_name" not in df.columns:
            raise ValueError(f"{table}: needs either 'player_id' or 'player_name'")
        key = df["player_name"].map(normalize_name)
        unknown = df.loc[~key.isin(name_to_id), "player_name"].unique()
        if len(unknown):
            raise ValueError(
                f"{table}: {len(unknown)} player names not found in the stats table, "
                f"e.g. {list(unknown[:5])}. Fix spelling mismatches and re-run."
            )
        df["player_id"] = key.map(name_to_id)
    return df


def load_and_merge(raw_dir: Path) -> pd.DataFrame:
    """Filesystem adapter: read data/raw/ (or data/sample/) and merge it."""
    tables, _ = read_frames(raw_dir)
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        raise FileNotFoundError(
            f"Missing required table(s) {missing} in {raw_dir}. "
            "Files must be named stats*, contracts* (and optionally injuries*)."
        )
    return merge_tables(tables["stats"], tables["contracts"], tables.get("injuries"))


def merge_tables(
    stats: pd.DataFrame,
    contracts: pd.DataFrame,
    injuries: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Merge the three tables on (player_id, season). Frames in, one frame out."""
    stats = stats.copy()
    contracts = contracts.copy()

    # build the name -> id map from the stats table (the identity source of truth)
    if "player_id" not in stats.columns:
        stats["player_id"] = (
            stats["player_name"].map(normalize_name).astype("category").cat.codes + 1
        )
    if "player_name" in stats.columns:
        name_to_id = dict(
            zip(stats["player_name"].map(normalize_name), stats["player_id"])
        )
    else:
        name_to_id = {}

    contracts = _ensure_player_id(contracts, name_to_id, "contracts")
    for df, table in ((stats, "stats"), (contracts, "contracts")):
        df["season"] = pd.to_numeric(df["season"], errors="raise").astype(int)
        dupes = df.duplicated(["player_id", "season"]).sum()
        if dupes:
            raise ValueError(
                f"{table}: {dupes} duplicate player-season rows — deduplicate and re-run."
            )

    merged = stats.merge(
        contracts[
            [c for c in ("player_id", "season", "contract_end_season", "salary", "contract_type")
             if c in contracts.columns]
        ],
        on=["player_id", "season"],
        how="left",
    )

    if injuries is not None and not injuries.empty:
        injuries = _ensure_player_id(injuries, name_to_id, "injuries")
        injuries["season"] = pd.to_numeric(injuries["season"], errors="raise").astype(int)
        merged = merged.merge(
            injuries[["player_id", "season", "games_missed"]],
            on=["player_id", "season"],
            how="left",
        )
    merged["games_missed"] = (
        merged.get("games_missed", pd.Series(0, index=merged.index)).fillna(0).astype(int)
    )

    no_contract = merged["contract_end_season"].isna().sum()
    if no_contract:
        print(
            f"WARNING: dropping {no_contract} player-seasons with no contract info "
            "(cannot label them contract year or not)."
        )
        merged = merged.dropna(subset=["contract_end_season"])
    merged["contract_end_season"] = merged["contract_end_season"].astype(int)

    return merged
