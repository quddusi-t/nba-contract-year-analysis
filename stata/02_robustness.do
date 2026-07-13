*==============================================================================
* 02_robustness.do — Robustness checks for the contract-year effect
*
* Run AFTER 01_main_fe.do. One-time setup for check 2:  ssc install reghdfe
*==============================================================================
clear all
set more off

import delimited using "../data/processed/player_seasons.csv", case(lower) clear
capture confirm numeric variable player_id
if _rc {
    encode player_id, gen(pid)
}
else {
    gen pid = player_id
}
xtset pid season

*------------------------------------------------------------------------------
* CHECK 1 — Paired Wilcoxon signed-rank (nonparametric, no model assumptions)
* Collapse to one pair per player: mean BPM in contract vs non-contract seasons
*------------------------------------------------------------------------------
preserve
collapse (mean) bpm, by(pid contract_year)
reshape wide bpm, i(pid) j(contract_year)
drop if missing(bpm0) | missing(bpm1)   // need both states per player
signrank bpm1 = bpm0
* one-tailed: if bpm1 > bpm0 on average, halve the two-tailed p
restore

*------------------------------------------------------------------------------
* CHECK 2 — Same model via reghdfe (modern FE estimator; should match xtreg)
*------------------------------------------------------------------------------
capture which reghdfe
if _rc {
    display as error "reghdfe not installed — run: ssc install reghdfe"
}
else {
    reghdfe bpm contract_year age age2 minutes_pg games_missed, ///
        absorb(pid season) vce(cluster pid)
    estimates store rob_reghdfe
}

*------------------------------------------------------------------------------
* CHECK 3 — Alternate outcome: per-36 scoring instead of BPM
* (conclusion shouldn't flip when the metric changes)
*------------------------------------------------------------------------------
capture confirm variable pts36
if !_rc {
    xtreg pts36 contract_year age age2 minutes_pg games_missed i.season, ///
        fe vce(cluster pid)
    estimates store rob_pts36
}

*------------------------------------------------------------------------------
* CHECK 4 — The shirking hypothesis: performance AFTER signing the new deal
* If contract_year > 0 and post_contract_year < 0, that's the classic
* moral-hazard pattern — two findings in one dataset.
*------------------------------------------------------------------------------
xtreg bpm contract_year post_contract_year age age2 minutes_pg games_missed ///
    i.season, fe vce(cluster pid)
estimates store rob_shirking

*------------------------------------------------------------------------------
* CHECK 5 — Minutes as a "bad control": drop it and compare
* (if effort raises minutes, controlling for minutes absorbs real effect)
*------------------------------------------------------------------------------
xtreg bpm contract_year age age2 games_missed i.season, fe vce(cluster pid)
estimates store rob_nominutes
