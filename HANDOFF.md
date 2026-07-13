# HANDOFF — project history, context, and current state

*Written 2026-07-13 by Claude (Fable 5), the session that scaffolded this repo.
Audience: future Claude/Opus/Sonnet sessions and human collaborators. Read this,
then `docs/METHODOLOGY.md`, before changing anything.*

## What this project is

A university summer project for **Arhan** (Kutsi's nephew, business + MIS double
major) testing the **contract-year effect**: do NBA players perform better in the
final year of their contract? His professors expect statistical inference —
hypothesis, test, p-value, confidence interval — not a prediction leaderboard.

The scope decision was made before this repo existed, in a claude.ai conversation
(preserved in `career-lab/docs/brief.md` on Kutsi's machine): three candidate ideas
(contract-year effect, draft-pick value curves, early-season playoff prediction)
were narrowed to contract-year because time is short and it has the cleanest
hypothesis-testing structure.

## What was done in the scaffold session (2026-07-13)

1. **Repo created** at `quddusi-t/nba-contract-year-analysis` (public), built and
   verified locally before pushing. Everything landed in one root commit on `main`;
   subsequent work should use feature branches + PRs.
2. **The full pipeline written and tested**: `src/` goes validate → clean → features
   → `data/processed/player_seasons.csv`; `stata/` do-files run the estimation.
3. **Verified end-to-end on synthetic data**: `src/make_sample_data.py` generates
   591 player-seasons with a known **+0.8 BPM** contract-year effect baked in;
   `src/quick_inference.py` (statsmodels FE regression, clustered SEs) recovered
   **+0.820, 95% CI [0.614, 1.026]** — the design demonstrably works.
   The naive paired comparison gives +1.12 on the same data (inflated by
   age/selection), which is a useful teaching contrast.

## What was done in the web-console session (2026-07-14)

Arhan can't use GitHub and there's no time to teach him, so the data work needed a
front door that isn't a terminal. Added `app/` — a Streamlit console he reaches by URL.

1. **Refactored the pipeline to be frames-in/frames-out.** `src/ingest.py` is new and
   now owns multi-file concat, column mapping, and validation. `validate_raw.py` and
   `clean.py` became thin adapters over it. The point: the CLI and the website call the
   *same* functions, so they can never disagree about what valid data is. Change a data
   rule in `src/`, and both follow.
2. **Multiple files per table now work.** `find_tables()` used to *raise* if two files
   matched one table; a scrape produces one sheet per season, so that was a wall. Files
   are now stacked (columns unioned, gaps flagged). Verified: 16 per-season `.xlsx`
   sheets → the same 591 rows as the single-file path.
3. **The console** (`app/streamlit_app.py`): upload many sheets → assign each to a
   table → match columns to canonical names (auto-guessed via `ALIASES`) → validation
   as a fix-list → clean → download `player_seasons.csv` → save to a private data repo.
   Password-gated (`app/auth.py`); storage is the GitHub Contents API (`app/storage.py`).
4. **Verified:** the sample pipeline still recovers **+0.820, CI [0.614, 1.026]**
   (unchanged), and the web flow reproduces that same number from per-season uploads.
   The password gate rejects wrong passwords; the app degrades gracefully with no
   secrets configured (open, save disabled).

**Still to do:** Kutsi must create the private data repo + token and deploy — the
10-minute runbook is `app/README.md`. Nothing is deployed yet.

## The key decisions and why

| Decision | Why |
|---|---|
| **Fixed-effects panel regression, not ML** for the main analysis | This is an inference question ("is the effect real, how big"). LGBM gives no p-value, no CI, no test of H₀. Professors expect statistics. Full reasoning in `docs/METHODOLOGY.md`. |
| **Python cleans, Stata estimates** | Arhan's course track uses Stata, and panel FE (`xtreg`/`reghdfe`) is Stata's home turf. pandas is better at wrangling scraped Excel sheets. The interface between them is one tidy CSV. |
| **Data contract instead of data** | Arhan's data is scraped Excel sheets on *his* machine — unavailable when scaffolding. So `docs/DATA_DICTIONARY.md` defines the three input tables and `src/validate_raw.py` tells him exactly what to fix when he drops files into `data/raw/`. |
| **Committed synthetic sample with a known effect** | Lets anyone (including Arhan on day one, and future AI sessions) prove the pipeline works without real data, and catches regressions: if `quick_inference.py --sample` stops recovering ~+0.8, something broke. |
| **Outcome is rate-based (`bpm`), never raw totals** | Minutes confound totals — players may get played more in contract years. If no composite exists in the real data, the pipeline builds a z-scored per-36 composite as fallback. |
| **`post_contract_year` flag built into the pipeline** | Enables the "shirking" check (better before signing, worse after) — the two-findings-in-one-dataset angle from the original discussion. |
| **Filters: games ≥ 20, minutes/game ≥ 10** | Rate stats are noise on tiny samples. Constants at the top of `src/features.py`; change deliberately and document. |
| **Web console shares the pipeline's code, doesn't reimplement it** | Two copies of "what is valid data" would drift, and the drift would be silent and statistical. `src/ingest.py` is the single source of truth; `app/` is presentation only. |
| **Data lives in a separate *private* repo, not this one** | The scraped sheets have unclear licensing and this repo is public. The app writes to a private data repo via a fine-grained token, so Arhan gets persistence without ever seeing git. |
| **The console previews the FE model but does not replace Stata** | Stata can't run on free hosting, and the do-files are the deliverable the professors expect. Tab 5 is an early-warning check, labeled as such. |

## Current state

- ✅ Pipeline, validator, sample data, quick inference: **working, verified**
- ✅ Web console: **written and tested locally, not yet deployed** — needs the private
  data repo + token + a Streamlit Cloud deploy (`app/README.md`)
- ✅ Stata do-files: written and internally consistent, but **not executed** (no
  Stata in this environment) — first real Stata run may hit small syntax issues;
  fix them in place, the statistical logic is the deliverable
- ⬜ Real data: **not yet arrived.** Everything from ROADMAP Phase 2 onward waits
  on Arhan's Excel sheets
- ⬜ EDA notebook: skeleton with the four questions to answer; cells run but were
  only exercised against sample data. The console has **no EDA charts yet** — that is
  the obvious next feature once real data lands

## Likely next steps (in order)

1. Arhan drops his sheets into `data/raw/`, runs the validator, fixes what it flags.
   Expect the messy part to be **contract data shaped one-row-per-contract** rather
   than per-season — if so, add an expansion step in `src/clean.py` (noted in
   DATA_DICTIONARY.md).
2. Spot-check the contract-year flag against Spotrac/Basketball-Reference for a few
   known players. The flag definition (last *guaranteed* year; option years excluded)
   is a judgment call — whatever rule is used must be stated in the writeup.
3. Run the Stata sequence; halve two-tailed p-values when reporting (H₁ is one-tailed).
4. Robustness table + coefplot → writeup per ROADMAP Phase 7.

## Warnings for future sessions

- **Do not "upgrade" the main analysis to LGBM/XGBoost/neural nets.** That
  temptation is pre-answered in METHODOLOGY.md. ML belongs only in optional
  Phase 8 (residual approach), after the statistics are done.
- **Don't delete `data/sample/`** — it is the regression test for the pipeline.
- **Don't put data rules in `app/`.** If the console needs to accept a new column
  spelling or a new check, it goes in `src/ingest.py` so the CLI gets it too. The page
  is presentation only. Two copies of the validation logic would drift silently.
- **Never commit `.streamlit/secrets.toml`** (password + GitHub token). It's gitignored;
  keep it that way. The token should be fine-grained and scoped to the data repo alone.
- `.gitignore` keeps `data/raw/` and `data/processed/` out of git deliberately:
  the scraped data may have unclear licensing, and the repo is public. Keep it out.
- Keep the writing level at "strong undergrad": Arhan should be able to defend
  every line to his professors. Explaining beats impressing.
