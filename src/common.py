"""Shared helpers: paths, file discovery, column normalization."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# filename prefix (case-insensitive) -> table name
TABLE_PREFIXES = {"stats": "stats", "contracts": "contracts", "injuries": "injuries"}
REQUIRED_TABLES = ("stats", "contracts")


def find_tables(raw_dir: Path) -> dict[str, list[Path]]:
    """Map table name -> file paths, based on filename prefix.

    Several files may match one table (a scrape usually produces one sheet per
    season: stats_2019.xlsx, stats_2020.xlsx...). They are concatenated by
    ingest.concat_frames, so order here is just sorted-by-filename.
    """
    tables: dict[str, list[Path]] = {}
    for path in sorted(raw_dir.iterdir()):
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            continue
        for prefix, table in TABLE_PREFIXES.items():
            if path.stem.lower().startswith(prefix):
                tables.setdefault(table, []).append(path)
    return tables


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """'Player Name' -> 'player_name'; strips accents-free, lowercase, underscores."""
    df = df.copy()
    df.columns = [re.sub(r"[\s\-]+", "_", str(c).strip().lower()) for c in df.columns]
    return df


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        df = pd.read_excel(path)
    return normalize_columns(df)


def normalize_name(name: str) -> str:
    """Accent-insensitive, lowercase player-name key ('Luka Dončić' -> 'luka doncic')."""
    ascii_name = (
        unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z ]", "", ascii_name.lower()).strip()
