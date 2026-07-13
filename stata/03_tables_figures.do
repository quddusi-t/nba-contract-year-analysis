*==============================================================================
* 03_tables_figures.do — Publication-style outputs for the report
*
* Run AFTER 01 and 02 in the SAME Stata session (uses stored estimates).
* One-time setup:  ssc install estout   //  ssc install coefplot
*==============================================================================
set more off
capture mkdir output

*------------------------------------------------------------------------------
* Regression table across specifications
*------------------------------------------------------------------------------
esttab main_fe rob_reghdfe rob_pts36 rob_shirking rob_nominutes ///
    using "output/results_table.rtf", replace ///
    keep(contract_year post_contract_year age age2 minutes_pg games_missed) ///
    b(3) se(3) star(* 0.10 ** 0.05 *** 0.01) ///
    stats(N r2_w, labels("Player-seasons" "Within R2")) ///
    mtitles("Main FE" "reghdfe" "PTS/36" "Shirking" "No minutes") ///
    title("The contract-year effect: fixed-effects estimates") ///
    note("SEs clustered by player. Player and season fixed effects in all models.")

* plain-text version for quick reading
esttab main_fe rob_reghdfe rob_pts36 rob_shirking rob_nominutes, ///
    keep(contract_year post_contract_year) b(3) se(3) ///
    star(* 0.10 ** 0.05 *** 0.01)

*------------------------------------------------------------------------------
* Coefficient plot: the headline figure
*------------------------------------------------------------------------------
coefplot main_fe rob_reghdfe rob_pts36 rob_shirking rob_nominutes, ///
    keep(contract_year) xline(0, lpattern(dash)) ///
    title("Contract-year coefficient across specifications") ///
    xtitle("Effect on performance (95% CI)")
graph export "output/coefplot_contract_year.png", replace width(1600)
