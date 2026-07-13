"""Run the full pipeline: raw tables -> tidy player_seasons.csv for Stata.

Usage:
    python src/make_dataset.py            # uses data/raw/ (real data)
    python src/make_dataset.py --sample   # uses data/sample/ (synthetic dry run)
"""

from __future__ import annotations

import argparse

from clean import load_and_merge
from common import PROCESSED_DIR, RAW_DIR, SAMPLE_DIR
from features import build_features


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true",
                        help="run on the synthetic sample data instead of data/raw/")
    args = parser.parse_args()

    raw_dir = SAMPLE_DIR if args.sample else RAW_DIR
    print(f"Reading raw tables from {raw_dir}")
    df = build_features(load_and_merge(raw_dir))

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "player_seasons.csv"
    df.to_csv(out, index=False)

    share = df["contract_year"].mean()
    print(f"\nWrote {out}")
    print(f"  {len(df)} player-seasons, {df['player_id'].nunique()} players, "
          f"seasons {df['season'].min()}-{df['season'].max()}")
    print(f"  contract-year share: {share:.1%}  "
          f"(sanity: typical real-world share is ~25-35%)")


if __name__ == "__main__":
    main()
