# Roadmap — Contract-Year Effect Study

Work top to bottom. Each phase has a goal, concrete steps, and what to watch out for.
Check items off as you go. Phases 1–3 are Python; 5–6 are Stata; 7 is writing.

---

## Phase 1 — Setup & dry run ✅ when the sample pipeline runs

- [ ] Clone the repo, create the venv, install requirements (see README quickstart)
- [ ] Run `python src/make_sample_data.py` then `python src/make_dataset.py --sample`
- [ ] Run `python src/quick_inference.py` — you should see a positive, significant
      `contract_year` coefficient (~+0.8, the effect built into the sample data)
- [ ] Open `data/processed/player_seasons.csv` and understand every column

**Why this matters:** you now know the pipeline works and what the final dataset
looks like, before fighting with real data.

## Phase 2 — Data intake

- [ ] Read `docs/DATA_DICTIONARY.md` carefully
- [ ] Export your scraped Excel sheets into `data/raw/` — one file per table,
      named `stats*`, `contracts*`, `injuries*` (.xlsx or .csv both fine)
- [ ] Run `python src/validate_raw.py` and fix everything it reports
- [ ] Re-run until the validator passes

**Watch out for:** player name inconsistencies across sheets ("Luka Dončić" vs
"Luka Doncic"). If you don't have numeric player IDs, the pipeline builds them from
normalized names — check the validator's duplicate warnings.

## Phase 3 — Cleaning & feature construction

- [ ] Run `python src/make_dataset.py` (no `--sample` flag now)
- [ ] Spot-check `data/processed/player_seasons.csv` against sources you trust
      (pick 3 players you know, verify their contract years on Spotrac/Basketball-Reference)
- [ ] Confirm the contract-year flag: a contract year = the season after which the
      player's contract expires

**Watch out for:** rookie-scale contracts with team options — the "contract year" is
the last *guaranteed* year. Document whatever rule you use in the writeup.

## Phase 4 — EDA (`notebooks/01_eda.ipynb`)

- [ ] How many player-seasons total? How many are contract years?
- [ ] Age distribution in contract years vs not (contract years skew older — this is
      exactly why age controls matter)
- [ ] Distribution of the outcome metric; any impossible values?
- [ ] Missingness table: which columns have gaps, are the gaps random?

**Deliverable:** 3–4 descriptive charts and a summary table for the report.

## Phase 5 — Main analysis (Stata)

- [ ] Import: `import delimited data/processed/player_seasons.csv`
- [ ] Run `stata/01_main_fe.do` — the fixed-effects regression:
      `xtreg bpm contract_year age age2 minutes games_missed i.season, fe vce(cluster player_id)`
- [ ] Interpret: the `contract_year` coefficient is the answer to H₀.
      Report sign, magnitude (in outcome units), 95% CI, and p-value (one-tailed: halve it)

**Watch out for:** don't report raw p-values without the effect size. "+0.6 BPM,
p=0.03" is a finding; "p=0.03" alone is not.

## Phase 6 — Robustness (this is what separates an A from a B+)

- [ ] `stata/02_robustness.do`:
  - [ ] Wilcoxon signed-rank (`signrank`) on paired contract vs non-contract means per player
  - [ ] `reghdfe` version of the main model (install: `ssc install reghdfe`)
  - [ ] Alternate outcomes: swap BPM for PER / WS/48 / per-36 composite — does the sign hold?
  - [ ] **Shirking check:** add a `post_contract_year` flag. If performance rises before
        and dips after signing, that's two findings in one dataset
- [ ] `stata/03_tables_figures.do`: `esttab` regression table across specifications,
      `coefplot` of the contract-year coefficient

## Phase 7 — Writeup

- [ ] Structure: Question → Data → Design (why paired/FE) → Results → Robustness → Limitations
- [ ] Limitations to state honestly: selection into contract years isn't random,
      minutes allocation is partly a coach's choice (bad control debate), composite
      metrics have their own biases
- [ ] Include the esttab table and coefplot — professors read tables first

## Phase 8 (optional) — The ML "wow" chapter

- [ ] Train LightGBM to predict expected performance from everything *except*
      contract status; test whether residuals are systematically positive in contract
      years (t-test). ML builds the counterfactual baseline, statistics does the inference.
- [ ] Only do this after Phases 5–7 are done — it's a bonus, not the core.

---

*Handoff note for AI assistants continuing this work: read `docs/METHODOLOGY.md`
first. The design decisions (FE over ML, per-36 over totals, cluster-by-player SEs)
are deliberate — don't "upgrade" the main analysis to a prediction model.*
