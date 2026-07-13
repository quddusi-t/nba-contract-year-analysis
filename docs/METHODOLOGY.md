# Methodology

## Research question

Do NBA players systematically perform better in the final year of their contract
("contract year"), when their next payday depends on current performance?

## Hypotheses

- **H₀:** Within-player performance is equal in contract years and non-contract years.
  Formally: the mean within-player difference in performance is zero.
- **H₁:** Within-player performance is **higher** in contract years (one-tailed).

## Design: paired, not pooled

The single most important design decision: **compare each player to himself.**

A naive comparison of contract-year players vs everyone else is confounded by
selection — who reaches a contract year is not random (older players, players good
enough to have earned multi-year deals, players whose teams declined options). Player
fixed effects remove all time-invariant player characteristics (talent, position,
work ethic) so the estimate comes only from within-player variation.

## Main model: fixed-effects panel regression

One row = one player-season.

```
performance_it = β·contract_year_it + f(age_it) + γ·minutes_it
                 + δ·games_missed_it + α_i + λ_t + ε_it
```

- `α_i` — player fixed effects (the paired design, done properly)
- `λ_t` — season fixed effects (absorbs league-wide trends: pace, the three-point
  era, rule changes)
- `f(age)` — age and age² (age curves are hump-shaped: a 24-year-old improves anyway,
  a 33-year-old declines anyway; without this, contract-year timing correlates with
  age and biases β)
- Standard errors **clustered by player** (a player's seasons are not independent)
- **β is the answer.** Its sign, size, confidence interval and p-value directly test H₀.

In Stata: `xtreg` with `fe vce(cluster player_id)`, or `reghdfe` (modern standard).
In Python (for a quick check): `statsmodels` OLS with player/season dummies and
clustered SEs — implemented in `src/quick_inference.py`.

## Outcome metric

Use **rate-based** metrics, not raw totals:

- Preferred: a composite like **BPM** (Box Plus/Minus), PER, or WS/48
- Fallback (if only counting stats are available): per-36-minute stats or the simple
  composite the pipeline builds (`pts36 + reb36 + ast36` z-scored)

Raw season totals are confounded by minutes: players may *get played more* in
contract years, which inflates totals without any true performance change. (Minutes
received is itself an interesting secondary outcome.)

## Controls

| Variable | Why |
|---|---|
| age, age² | hump-shaped career curves |
| minutes per game | role size; also a "bad control" candidate — see limitations |
| games missed (injury) | injury-shortened seasons look worse per-36 too |
| season FE | era effects |
| player FE | everything time-invariant about the player |

Optional refinements if the data allows: usage rate (role change), team change flag,
contract type of the *next* deal (rookie extension vs veteran free agency — the
incentive differs).

## Why not machine learning for the main analysis

This is an **inference** problem ("is this effect real and how big"), not a
**prediction** problem ("guess this player's PER"). Gradient-boosted trees fit the
data happily but produce no p-value, no confidence interval, and no test of H₀.
The professors expect statistics.

The one justified ML use is the **residual approach** (optional Phase 8): train
LightGBM to predict expected performance from everything except contract status,
then test whether residuals (actual − expected) are systematically positive in
contract years. ML builds a flexible counterfactual baseline; a simple t-test on the
residuals does the inference.

## Robustness checks

1. **Wilcoxon signed-rank test** on paired per-player means (contract vs
   non-contract): nonparametric, no functional-form assumptions.
2. **Alternate outcomes:** the conclusion shouldn't flip when swapping BPM for PER
   or WS/48.
3. **The shirking check:** add a `post_contract_year` flag (first season of a new
   deal). Performance rising before signing *and* dipping after is the classic
   moral-hazard pattern — two findings from one dataset.
4. **reghdfe** as an alternative estimator (should match `xtreg` closely).

## Known limitations (state these in the writeup)

- **Contract-year timing is not randomly assigned.** FE removes fixed player traits,
  not time-varying confounders (e.g., a player entering a contract year right at his
  natural peak).
- **Minutes as a control is debatable** ("bad control"): if effort raises minutes,
  controlling for minutes absorbs part of the true effect. Report models with and
  without it.
- **Composite metrics embed their own model assumptions** (BPM is regression-based).
- **Injury reporting quality varies** across sources and eras.
