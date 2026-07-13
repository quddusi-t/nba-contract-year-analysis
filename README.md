# NBA Contract-Year Analysis

Do NBA players perform better in the final year of their contract?

This repo is a complete scaffold for testing the **contract-year effect** with proper
statistical inference: Python handles data cleaning and feature construction, Stata
handles the estimation (fixed-effects panel regression). Built for a university
project (business + MIS double major) — the emphasis is on *inference* (is the effect
real, how big, is it significant), not leaderboard-style prediction.

## The question

- **H₀ (null):** Player performance in a contract year is no different from the same
  player's performance in non-contract years (mean within-player difference = 0).
- **H₁ (alternative):** Performance is *higher* in contract years (one-tailed).

The design compares **each player to himself** (player fixed effects), controlling for
age curves, minutes, and injuries. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md)
for the full reasoning and pitfalls.

## Quickstart (works today, no real data needed)

```bash
git clone https://github.com/quddusi-t/nba-contract-year-analysis.git
cd nba-contract-year-analysis
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# generate synthetic sample data and run the full pipeline on it
.venv/bin/python src/make_sample_data.py
.venv/bin/python src/make_dataset.py --sample

# quick inference in Python (no Stata needed): FE regression + paired Wilcoxon
.venv/bin/python src/quick_inference.py
```

The sample data has a known contract-year effect built in (~+0.8 BPM), so you can
verify the whole pipeline recovers it before touching real data.

## Rehearsing with messy data

`data/sample/` is clean — it proves the *statistics* work. To test the *intake*, generate
a realistically messy fake export (one sheet per season with no Season column, `Rk`/`G`/
`MP`/`TRB` headers, traded players with `TOT` rows, accented names, salaries as text):

```bash
.venv/bin/python src/make_mock_upload.py     # -> data/mock/
```

Drag those files into the web console, or `cp data/mock/* data/raw/` and run the CLI. The
same +0.8 effect is baked in, so if the pipeline doesn't recover it, the intake broke
something. **Read the salary warning in the data dictionary** — that is the one input
that silently produces a wrong answer, and it's why this harness exists.

## Two ways to get data in

Both run the **same code** (`src/ingest.py` → `src/clean.py` → `src/features.py`), so
they always agree on what valid data is. Pick whichever suits you.

### The browser (no git, no Python)

A [Streamlit](https://streamlit.io) console: drag in Excel sheets — one per season is
fine — match your columns to the expected names, see what needs fixing, download a
clean `player_seasons.csv`. Setup and deployment: [`app/README.md`](app/README.md).

```bash
.venv/bin/streamlit run app/streamlit_app.py    # or use the deployed URL
```

### The terminal

1. Read [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) — it defines the three
   input tables (stats, contracts, injuries) and their required columns.
2. Drop your Excel/CSV files into `data/raw/` (named `stats*`, `contracts*`, `injuries*`;
   several files per table is fine).
3. `python src/validate_raw.py` — tells you exactly what's missing or malformed.
4. `python src/make_dataset.py` — builds `data/processed/player_seasons.csv`.

### Then, either way

Open Stata and run the do-files in `stata/` in order. The estimation is Stata's job —
the web console's Python regression is only a preview to catch problems early.

## Repo map

| Path | What it is |
|---|---|
| `ROADMAP.md` | Step-by-step project guide with checkboxes — **start here** |
| `docs/METHODOLOGY.md` | Hypotheses, research design, why FE regression and not ML |
| `docs/DATA_DICTIONARY.md` | The data contract: required tables and columns |
| `src/` | Python pipeline: ingest → clean → features → tidy CSV |
| `app/` | Web console: the same pipeline, in a browser ([setup](app/README.md)) |
| `stata/` | Estimation: main FE model, robustness checks, tables/figures |
| `notebooks/01_eda.ipynb` | Exploratory checks before inference |

## Credits

Project by Arhan (analysis) with scaffold support from Kutsi Tusuz.
Scaffold generated with [Claude Code](https://claude.com/claude-code).
