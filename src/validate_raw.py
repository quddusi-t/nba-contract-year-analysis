"""Validate files in data/raw/ against the data contract (docs/DATA_DICTIONARY.md).

Terminal front-end for src/ingest.py — the web console runs the exact same checks,
so if this passes, the website agrees, and vice versa.

Run this every time you add or change raw files. Exit code 0 = ready for
make_dataset.py; 1 = blocking problems listed below.

Usage:
    python src/validate_raw.py            # checks data/raw/
    python src/validate_raw.py --sample   # checks data/sample/ (should always pass)
"""

from __future__ import annotations

import argparse
import sys

from common import RAW_DIR, SAMPLE_DIR
from ingest import read_frames, validate_tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    raw_dir = SAMPLE_DIR if args.sample else RAW_DIR

    tables, problems = read_frames(raw_dir)

    if "injuries" not in tables:
        print("note: no injuries table found — games_missed will default to 0\n")

    for name, df in tables.items():
        print(f"{name}: {len(df)} rows, columns: {list(df.columns)}")

    problems += validate_tables(tables)
    blocking = [p for p in problems if p.blocking]
    advisory = [p for p in problems if not p.blocking]

    print()
    if advisory:
        print(f"{len(advisory)} warning(s) — probably fine, but look:")
        for p in advisory:
            print(f"  - {p.table}: {p.message}")
            print(f"      {p.fix}")
        print()

    if blocking:
        print(f"FAIL — {len(blocking)} problem(s) to fix:")
        for p in blocking:
            print(f"  - {p.table}: {p.message}")
            print(f"      fix: {p.fix}")
        return 1

    print("PASS — raw data matches the contract. Run: python src/make_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
