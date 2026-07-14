# HANDOFF — project history, context, and current state

*Started 2026-07-13 by the session that scaffolded this repo; updated 2026-07-14 by the
session that built and deployed the web console. Audience: future Claude sessions and
human collaborators. Read this, then `docs/METHODOLOGY.md`, before changing anything.*

**If you read only one thing:** the pipeline works and the console is live, but the
project's viability rests on a single unanswered question — whether Arhan's contract data
contains real contract boundaries or merely salaries. See
[🚨 The biggest risk](#-the-biggest-risk-to-this-project-found-2026-07-14).

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

## What was done in the web-console session (2026-07-14, PRs #2–#7)

Arhan can't use GitHub and there was no time to teach him, so the data work needed a
front door that isn't a terminal. Added `app/` — a Streamlit console he reaches by URL.
**It is deployed and working; the whole loop has been verified end-to-end on the live
app, not just locally.**

### The architecture decision that matters

**The console shares the pipeline's code; it does not reimplement it.** `src/ingest.py`
is new and owns multi-file concat, column mapping, and validation. `validate_raw.py` and
`clean.py` became thin adapters over it. The CLI and the website call the *same*
functions, so they cannot disagree about what valid data is — and any drift between two
copies would have been silent *and statistical*, the worst kind. `app/` is presentation
only. **Change a data rule in `src/`, and both follow.**

### What the console does

Upload many sheets → assign each to a table → match columns (auto-guessed via `ALIASES`)
→ validation as a plain-language fix-list → build → download `player_seasons.csv` →
archive the session to the private data repo. Then two teaching tabs: **6 · Next: Stata**
(serves the do-files with explanations, the one-tailed halving rule, "never report a
p-value without an effect size", the limitations worth stating) and **📋 What the app
did** (the audit log, below). Password-gated (`app/auth.py`); storage is the GitHub
Contents API (`app/storage.py`).

### Real gaps this session found and closed

1. **Multiple files per table.** `find_tables()` used to *raise* if two files matched one
   table — but a scrape produces one sheet per season, so that was a wall for the CLI
   too. Files are now stacked (columns unioned, gaps flagged).
2. **Per-season exports carry no `Season` column.** The season only exists in the
   *filename*. It's now read from there and reported loudly, because an off-by-one here
   shifts every contract-year flag and quietly ruins the result.
3. **Traded players** arrive as one row per team *plus* a `TOT` season-total row, which
   tripped the duplicate check. The total is kept, the partials dropped — a partial row
   would understate his games and minutes.
4. **The CLI now auto-applies the alias mapping**, so a raw Basketball-Reference export
   (`Player`/`G`/`MP`/`TRB`) works without hand-editing headers.
5. **Nothing is dropped silently any more.** `merge_tables()` and `build_features()` take
   an optional `report` list and record every row they drop and why. Shown on the
   **📋 What the app did** tab and archived with the data. "Why are there fewer
   player-seasons than I uploaded?" now always has an answer.

### How data is stored

Each save is archived under `sessions/<timestamp>/` in the private repo — the original
sheets, the built dataset, and the session log. **Nothing is overwritten.** Uploads get
iterated on, and being able to see what Tuesday's numbers came from is the difference
between "the numbers changed" and "we know why they changed."
`processed/player_seasons.csv` is kept updated as a pointer to the latest build, so
there's always one obvious file to hand to Stata.

### Verification (all on the live app, with the messy mock export)

- Recovered **+0.805 BPM, CI [0.603, 1.006]** against a true baked-in effect of **+0.8**.
- The `player_seasons.csv` the cloud app produced is **byte-identical** to the local
  CLI's output from the same inputs — the two really do run the same code.
- The salary-grid trap is **refused** at step 3, on the live app.
- The password gate rejects wrong passwords; the sample pipeline still recovers
  **+0.820, CI [0.614, 1.026]** (unchanged since the scaffold).

## 🚨 The biggest risk to this project (found 2026-07-14)

`src/make_mock_upload.py` was written to rehearse the intake before real data arrives:
it fakes a realistic Basketball-Reference export (one sheet per season with no `Season`
column, `Rk`/`G`/`MP`/`TRB` headers, traded players with `TOT` rows, accented names,
salaries as `$40,000,000` text) with the same **+0.8 BPM** effect baked in.

Running it surfaced the finding that matters most:

> **A salary-per-season table is not contract data.** It cannot say where one contract
> ends and the next begins. If you derive "contract ends in the player's last season
> with a salary", you flag only each player's **final season**, every intermediate
> contract year vanishes, and the effect washes out.

On mock data with a true **+0.8** effect, that guess returned **−0.11** — significant-
looking, plausible, and completely wrong. With proper contract boundaries and the *same
messy stats sheets*, the pipeline recovers **+0.805**. So the intake mess is handled;
the contracts table is the whole ballgame.

The pipeline now **blocks** that input rather than guessing (`reshape_wide_contracts`
detects salary runs longer than any legal NBA contract). **Before Arhan does anything
else, confirm his contract data has real boundaries** — a `contract_end_season`, or a
start year + length — not just salaries. Basketball-Reference's contracts page only
shows each player's *current* deal, so it cannot supply history. Spotrac can.

Also note: Basketball-Reference returns **HTTP 403 to automated fetches** — do not write
a scraper. Their tables have a "Share & Export → Get table as CSV" button; that is the
supported route, and almost certainly how Arhan got his sheets.

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

## Current state (end of 2026-07-14)

- ✅ Pipeline, validator, sample data, quick inference: **working, verified**
- ✅ **Web console: live and fully verified.**
  - **https://nba-contract-console.streamlit.app** — password-gated (ask Kutsi)
  - Data repo: **https://github.com/quddusi-t/nba-contract-data** (private)
  - Deploy/runbook, secrets, and the reboot gotcha: `app/README.md`
- ✅ Mock harness (`src/make_mock_upload.py`): fakes a realistic messy export with a
  known +0.8 effect. **This is the intake's regression test** — it caught a wrong answer
  before real data ever arrived (see the risk section above)
- ✅ Stata do-files: written and internally consistent, but **never executed** (no Stata
  in this environment) — the first real run may hit small syntax issues; fix them in
  place, the statistical logic is the deliverable
- ⬜ **Real data: not yet arrived.** Arhan is being asked on 2026-07-15 whether his
  contract data has real boundaries or only salaries. Everything downstream waits on
  that answer
- ⬜ EDA charts: the notebook skeleton exists but was only run against sample data. The
  console has **no EDA charts yet** — the obvious next feature once real data lands

## Likely next steps (in order)

1. **Ask Arhan the one question that decides the project: does his contract data carry
   contract boundaries (an end year, or a start year + length), or only salary per
   season?** If it's salaries only, the study cannot proceed as designed and he needs
   Spotrac contract history. See the risk section above — this is not a detail.
2. He uploads through the console (he does **not** need `data/raw/` or the CLI). Read
   the warnings on the check tab; they are the ones that catch silent errors.
3. **Spot-check the contract-year flag against Spotrac for a few players he knows.** The
   flag definition (last *guaranteed* year; option years excluded) is a judgment call —
   whatever rule is used must be stated in the writeup. No automated check substitutes
   for this.
4. Run the Stata sequence; halve two-tailed p-values when reporting (H₁ is one-tailed).
5. Robustness table + coefplot → writeup per ROADMAP Phase 7.

Still expected as a possible mess: **contract data shaped one-row-per-contract**
(start year, end year). The console handles *wide salary grids* and *long per-season*
contracts, but not per-contract rows yet — that expansion step would go in
`src/ingest.py` (never in `app/`).

## Warnings for future sessions

- **Do not "upgrade" the main analysis to LGBM/XGBoost/neural nets.** That
  temptation is pre-answered in METHODOLOGY.md. ML belongs only in optional
  Phase 8 (residual approach), after the statistics are done.
- **Don't delete `data/sample/`** — it is the regression test for the statistics.
  **Don't delete `src/make_mock_upload.py`** — it is the regression test for the
  *intake*, and it has already earned its keep by catching a wrong answer.
- **Don't put data rules in `app/`.** If the console needs to accept a new column
  spelling or a new check, it goes in `src/ingest.py` so the CLI gets it too. The page
  is presentation only. Two copies of the validation logic would drift silently.
- **Never impute a performance value.** The only value the pipeline fills in is
  `games_missed → 0`. Imputing BPM would fabricate the very thing being measured. Rows
  with a missing outcome are kept in the file and ignored by the regression — and now
  *reported*, not dropped in silence.
- **After merging anything that touches `src/`, REBOOT the Streamlit app** (dashboard →
  ⋮ → Reboot app). Streamlit Cloud re-runs the main script on a new commit but keeps
  already-imported modules cached, so the page updates while the pipeline underneath it
  doesn't. This produces errors that look like code bugs but are stale imports
  (`TypeError: merge_tables() got an unexpected keyword argument 'report'`). A browser
  hard-refresh cannot fix it — the stale module is server-side. Full note in
  `app/README.md`.
- **Never commit `.streamlit/secrets.toml`** (password + GitHub token). It's gitignored;
  keep it that way. The token is fine-grained and scoped to the data repo alone, so a
  leak's blast radius is one private repo of NBA stats — keep it that way too.
- `.gitignore` keeps `data/raw/`, `data/processed/`, and `data/mock/` out of git
  deliberately: the scraped data may have unclear licensing, and this repo is public.
  Real data belongs in the private data repo. Keep it out of here.
- **Basketball-Reference returns HTTP 403 to automated fetches — do not write a
  scraper.** Their tables have a "Share & Export → Get table as CSV" button; that's the
  supported route, and almost certainly how Arhan got his sheets.
- Keep the writing level at "strong undergrad": Arhan should be able to defend
  every line to his professors. Explaining beats impressing. The console's tone is
  deliberately explanatory for the same reason — it is a teaching surface, not just a
  tool.
