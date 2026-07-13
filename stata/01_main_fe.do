*==============================================================================
* 01_main_fe.do — Contract-year effect: main fixed-effects model
*
* Run from the stata/ folder. Requires data/processed/player_seasons.csv
* (built by: python src/make_dataset.py)
*
* The coefficient on contract_year IS the test of H0.
* H1 is one-tailed (effect > 0): halve the reported two-tailed p-value.
*==============================================================================
clear all
set more off
capture mkdir output

import delimited using "../data/processed/player_seasons.csv", case(lower) clear

* player_id may arrive as string (if IDs were generated from names) — make numeric
capture confirm numeric variable player_id
if _rc {
    encode player_id, gen(pid)
}
else {
    gen pid = player_id
}

* declare the panel: player i, season t
xtset pid season

* descriptives worth pasting into the report
summarize bpm age minutes_pg games_missed
tab contract_year

*------------------------------------------------------------------------------
* MAIN MODEL
* player fixed effects (fe) + season fixed effects (i.season)
* standard errors clustered by player (a player's seasons are not independent)
*------------------------------------------------------------------------------
xtreg bpm contract_year age age2 minutes_pg games_missed i.season, ///
    fe vce(cluster pid)

* Interpretation guide:
*  - coefficient on contract_year = average within-player change in BPM
*    during contract years, holding age curve / minutes / injuries constant
*  - one-tailed p = two-tailed p / 2 (only if the coefficient is positive)
*  - report effect size + 95% CI, never the p-value alone

* store for the tables script
estimates store main_fe
estimates save "output/main_fe.ster", replace
