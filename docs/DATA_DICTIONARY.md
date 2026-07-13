# Data Dictionary — the data contract

The pipeline reads up to three tables from `data/raw/`. Files can be `.xlsx` or
`.csv`; the filename decides which table it is (case-insensitive prefix):

| Filename starts with | Table | Required? |
|---|---|---|
| `stats` | Player-season statistics | **yes** |
| `contracts` | Contract information | **yes** |
| `injuries` | Injury / games missed | no (defaults to 0 missed) |

**Several files may belong to one table.** A scrape usually produces one sheet per
season — `stats_2019.xlsx`, `stats_2020.xlsx`, … — and all files whose name starts
with `stats` are stacked into a single table. Columns are unioned, so a column present
in only some seasons becomes empty for the others and the validator flags it.

Two ways to run this:

- **Terminal:** drop files into `data/raw/`, run `python src/validate_raw.py`, which
  prints a fix-list, then `python src/make_dataset.py`.
- **Browser:** the web console (`app/`) does the same thing with drag-and-drop, plus a
  column-matching screen. Same code underneath — see `app/README.md`.

Column names are matched case-insensitively and spaces/dashes are treated as
underscores (`Player Name` → `player_name`). Common alternative spellings are
auto-detected (`MP` → `minutes`, `G` → `games`, `TRB` → `reb`); the full alias list is
`ALIASES` in `src/ingest.py`. Anything unrecognized you map by hand in the console, or
rename in the sheet before a terminal run.

## Messy exports the pipeline fixes for you

Verified against `src/make_mock_upload.py`, which fakes a realistic Basketball-Reference
export. You do not need to clean these by hand:

| The mess | What happens |
|---|---|
| One sheet per season, no `Season` column in the file | The season is read from the **filename** (`stats_2019.xlsx` → 2019) and reported, so you can check it. An off-by-one here shifts every contract-year flag. |
| Traded players: one row per team **plus** a `TOT`/`2TM` total row | The total row is kept, the per-team rows dropped. Keeping a partial row would understate the player's games and minutes. |
| Junk columns (`Rk`, `Pos`, `GS`) | Ignored, and listed so you can confirm nothing important was dropped. |
| Accented names (`Dončić`, `Šengün`) | Matched across sheets accent-insensitively. But note: player ids are built from letters only, so two genuinely different players with the same name would merge. |
| Wide contracts (one column per season) | Reshaped to one row per player-season — **but see the salary warning above**. |

---

## `stats` — one row per player per season

| Column | Type | Required | Notes |
|---|---|---|---|
| `player_name` | text | yes* | *or `player_id`; if only names, IDs are generated from normalized names |
| `player_id` | int/text | yes* | stable across seasons for the same player |
| `season` | int | yes | season **end** year (2023-24 season → `2024`) |
| `age` | int | yes | age during the season (Feb 1 convention is fine — be consistent) |
| `team` | text | no | last team of the season if traded |
| `games` | int | yes | games played |
| `minutes` | number | yes | total minutes **or** minutes per game — validator detects which |
| `bpm` | number | preferred | Box Plus/Minus or any composite (PER, WS/48…) — name it `bpm` |
| `pts`, `reb`, `ast` | number | fallback | season totals; used to build a per-36 composite if `bpm` is absent |

At least one of `bpm` or the (`pts`,`reb`,`ast`) trio must be present.

## `contracts` — one row per player per season (or per contract, see below)

| Column | Type | Required | Notes |
|---|---|---|---|
| `player_name` / `player_id` | | yes | must match the stats table |
| `season` | int | yes | season end year |
| `contract_end_season` | int | yes | end year of the **last guaranteed season** of the current contract |
| `salary` | number | no | that season's salary (for optional salary-efficiency analysis) |
| `contract_type` | text | no | e.g. `rookie`, `veteran`, `max`, `extension` |

**The contract-year flag is derived, not stored:**
`contract_year = (season == contract_end_season)`.

### ⚠️ Salary-per-season is NOT contract data

This is the one thing that can quietly sink the study. A table of *what each player was
paid each season* does **not** tell you where one contract ended and the next began —
and without that, the contract-year flag is wrong.

If you hand the pipeline a career salary grid and let it guess "the contract ends in the
last season with a salary", it marks only each player's **final season** as a contract
year. Every intermediate contract year disappears and the effect washes out to nothing.
We tested exactly this: on mock data with a true **+0.8** effect, the salary-grid guess
returned **−0.11** — a confident, plausible-looking, completely wrong answer. The
pipeline now refuses that input instead of guessing (see `reshape_wide_contracts` in
`src/ingest.py`).

So the contracts table must carry **contract boundaries**, one of:

- `contract_end_season` per player-season (what this pipeline wants), or
- contract start year + length, or start/end years per contract (expand to per-season).

Basketball-Reference's contracts page shows only each player's **current** deal, so it
cannot give you history. Spotrac has contract history. Whatever the source, the rule you
use (are option years guaranteed?) must be stated in the writeup.

If your sheet has one row per *contract* (start year, end year) instead of one per
season, that's fine — expand it to per-season rows in Excel or ask an AI assistant to
add an expansion step in `src/clean.py`. (Neither the CLI nor the console does this
expansion yet; it is the most likely first change once real data lands.)

**Decisions to make once and document:** team/player options count as guaranteed or
not (recommended: contract year = last *guaranteed* year); how to treat mid-season
extensions (recommended: a season that started as a contract year counts as one).

## `injuries` — one row per player per season *(optional)*

| Column | Type | Required | Notes |
|---|---|---|---|
| `player_name` / `player_id` | | yes | must match the stats table |
| `season` | int | yes | season end year |
| `games_missed` | int | yes | games missed due to injury that season |

---

## Output: `data/processed/player_seasons.csv`

What the pipeline produces and Stata consumes:

| Column | Source |
|---|---|
| `player_id`, `player_name`, `season`, `age`, `team` | stats |
| `games`, `minutes_pg` | stats (minutes normalized to per-game) |
| `bpm` | stats directly, or per-36 composite fallback |
| `pts36`, `reb36`, `ast36` | built if counting stats present |
| `contract_year` (0/1) | derived from contracts |
| `post_contract_year` (0/1) | derived: first season after a contract ended |
| `games_missed` | injuries (0 if table absent) |
| `age2` | age² |
| `salary`, `contract_type` | contracts, if present |

## Filters applied by the pipeline

- Seasons with `games < 20` or `minutes_pg < 10` are dropped (tiny samples make
  rate stats noisy). Thresholds live at the top of `src/features.py` — change and
  document if needed.
