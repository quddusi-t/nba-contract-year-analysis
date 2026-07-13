"""Quick Python check of the main result before/without Stata.

Runs the same fixed-effects design as stata/01_main_fe.do:
OLS with player + season dummies, SEs clustered by player. Also runs the
paired Wilcoxon robustness check. On sample data, expect the contract_year
coefficient near +0.8 (the effect built into the synthetic data).

This is a PREVIEW, not the deliverable — Stata remains the estimation tool of
record for the writeup (see docs/METHODOLOGY.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from common import PROCESSED_DIR


@dataclass(frozen=True)
class Result:
    coef: float
    se: float
    ci_low: float
    ci_high: float
    p_one_tailed: float
    n_obs: int
    n_players: int
    wilcoxon_p: float | None
    wilcoxon_diff: float | None
    n_paired: int

    @property
    def rejects_null(self) -> bool:
        return self.p_one_tailed < 0.05 and self.coef > 0


def run_inference(df: pd.DataFrame) -> Result:
    """Player+season FE regression with player-clustered SEs, plus paired Wilcoxon."""
    model = smf.ols(
        "bpm ~ contract_year + age + age2 + minutes_pg + games_missed"
        " + C(player_id) + C(season)",
        data=df,
    ).fit(cov_type="cluster", cov_kwds={"groups": df["player_id"]})

    lo, hi = model.conf_int().loc["contract_year"]

    # paired Wilcoxon: per-player mean BPM, contract vs non-contract seasons.
    # Needs players observed in BOTH states — a panel of only-contract-year players
    # would leave nothing to pair, so guard rather than crash.
    per_player = df.pivot_table(
        index="player_id", columns="contract_year", values="bpm", aggfunc="mean"
    )
    w_p = w_diff = None
    n_paired = 0
    if {0, 1}.issubset(per_player.columns):
        paired = per_player.dropna()
        n_paired = len(paired)
        if n_paired:
            diff = paired[1] - paired[0]
            w_diff = float(diff.mean())
            w_p = float(stats.wilcoxon(diff, alternative="greater").pvalue)

    return Result(
        coef=float(model.params["contract_year"]),
        se=float(model.bse["contract_year"]),
        ci_low=float(lo),
        ci_high=float(hi),
        p_one_tailed=float(model.pvalues["contract_year"]) / 2,  # H1 is one-tailed
        n_obs=int(model.nobs),
        n_players=int(df["player_id"].nunique()),
        wilcoxon_p=w_p,
        wilcoxon_diff=w_diff,
        n_paired=n_paired,
    )


def main() -> None:
    path = PROCESSED_DIR / "player_seasons.csv"
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} player-seasons from {path}\n")

    r = run_inference(df)

    print("=== Fixed-effects regression (player + season FE, clustered SEs) ===")
    print(f"contract_year coefficient: {r.coef:+.3f} BPM  (SE {r.se:.3f})")
    print(f"95% CI: [{r.ci_low:+.3f}, {r.ci_high:+.3f}]")
    print(f"p-value: {r.p_one_tailed * 2:.4f} two-tailed -> "
          f"{r.p_one_tailed:.4f} one-tailed (H1: effect > 0)")

    if r.wilcoxon_p is not None:
        print("\n=== Paired Wilcoxon signed-rank (robustness) ===")
        print(f"{r.n_paired} players with both contract and non-contract seasons")
        print(f"mean within-player difference: {r.wilcoxon_diff:+.3f} BPM")
        print(f"one-tailed p-value: {r.wilcoxon_p:.4f}")

    verdict = "REJECT" if r.rejects_null else "FAIL TO REJECT"
    print(f"\nAt alpha = 0.05 (one-tailed): {verdict} H0.")


if __name__ == "__main__":
    main()
