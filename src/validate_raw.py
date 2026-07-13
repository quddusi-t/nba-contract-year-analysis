"""Validate files in data/raw/ against the data contract (docs/DATA_DICTIONARY.md).

Run this every time you add or change raw files. Exit code 0 = ready for
make_dataset.py; 1 = problems listed below.

Usage:
    python src/validate_raw.py            # checks data/raw/
    python src/validate_raw.py --sample   # checks data/sample/ (should always pass)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from common import RAW_DIR, REQUIRED_TABLES, SAMPLE_DIR, find_tables, load_table

REQUIRED_COLUMNS = {
    "stats": ["season", "age", "games", "minutes"],
    "contracts": ["season", "contract_end_season"],
    "injuries": ["season", "games_missed"],
}


def check_table(name: str, df: pd.DataFrame, problems: list[str]) -> None:
    cols = set(df.columns)

    if "player_id" not in cols and "player_name" not in cols:
        problems.append(f"{name}: needs a 'player_id' or 'player_name' column")

    for col in REQUIRED_COLUMNS[name]:
        if col not in cols:
            problems.append(f"{name}: missing required column '{col}'")

    if name == "stats" and "bpm" not in cols:
        counting = {"pts", "reb", "ast"} - cols
        if counting:
            problems.append(
                "stats: needs 'bpm' (or another composite renamed to bpm) OR all of "
                f"pts/reb/ast for the per-36 fallback — missing {sorted(counting)}"
            )

    if "season" in cols:
        bad = pd.to_numeric(df["season"], errors="coerce").isna().sum()
        if bad:
            problems.append(f"{name}: {bad} rows where 'season' is not a number")
        else:
            seasons = pd.to_numeric(df["season"])
            if seasons.min() < 1990 or seasons.max() > 2030:
                problems.append(
                    f"{name}: season range {seasons.min()}-{seasons.max()} looks wrong "
                    "(use season END year, e.g. 2023-24 -> 2024)"
                )

    key = "player_id" if "player_id" in cols else "player_name"
    if key in cols and "season" in cols:
        dupes = df.duplicated([key, "season"]).sum()
        if dupes:
            problems.append(f"{name}: {dupes} duplicate ({key}, season) rows — deduplicate")

    for col in df.columns:
        if col in ("player_name", "team", "contract_type"):
            continue
        na = df[col].isna().sum()
        if na:
            problems.append(f"{name}: column '{col}' has {na} empty cells (note: may be OK)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    raw_dir = SAMPLE_DIR if args.sample else RAW_DIR

    problems: list[str] = []
    try:
        tables = find_tables(raw_dir)
    except ValueError as e:
        print(f"FAIL: {e}")
        return 1

    for t in REQUIRED_TABLES:
        if t not in tables:
            problems.append(
                f"required table '{t}' not found — add a file named {t}*.xlsx or {t}*.csv"
            )
    if "injuries" not in tables:
        print("note: no injuries table found — games_missed will default to 0\n")

    for name, path in tables.items():
        try:
            df = load_table(path)
        except Exception as e:  # unreadable file: report and keep checking others
            problems.append(f"{name}: could not read {path.name}: {e}")
            continue
        print(f"{name}: {path.name} — {len(df)} rows, columns: {list(df.columns)}")
        check_table(name, df, problems)

    print()
    if problems:
        print(f"FAIL — {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("PASS — raw data matches the contract. Run: python src/make_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
