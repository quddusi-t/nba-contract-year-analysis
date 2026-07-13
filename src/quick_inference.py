"""Quick Python check of the main result before/without Stata.

Runs the same fixed-effects design as stata/01_main_fe.do:
OLS with player + season dummies, SEs clustered by player. Also runs the
paired Wilcoxon robustness check. On sample data, expect the contract_year
coefficient near +0.8 (the effect built into the synthetic data).
"""

from __future__ import annotations

import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

from common import PROCESSED_DIR


def main() -> None:
    path = PROCESSED_DIR / "player_seasons.csv"
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} player-seasons from {path}\n")

    model = smf.ols(
        "bpm ~ contract_year + age + age2 + minutes_pg + games_missed"
        " + C(player_id) + C(season)",
        data=df,
    ).fit(cov_type="cluster", cov_kwds={"groups": df["player_id"]})

    coef = model.params["contract_year"]
    se = model.bse["contract_year"]
    p_two = model.pvalues["contract_year"]
    lo, hi = model.conf_int().loc["contract_year"]

    print("=== Fixed-effects regression (player + season FE, clustered SEs) ===")
    print(f"contract_year coefficient: {coef:+.3f} BPM  (SE {se:.3f})")
    print(f"95% CI: [{lo:+.3f}, {hi:+.3f}]")
    print(f"p-value: {p_two:.4f} two-tailed -> {p_two / 2:.4f} one-tailed (H1: effect > 0)")

    # paired Wilcoxon: per-player mean BPM, contract vs non-contract seasons
    per_player = df.pivot_table(index="player_id", columns="contract_year",
                                values="bpm", aggfunc="mean")
    paired = per_player.dropna()
    diff = paired[1] - paired[0]
    w = stats.wilcoxon(diff, alternative="greater")
    print("\n=== Paired Wilcoxon signed-rank (robustness) ===")
    print(f"{len(paired)} players with both contract and non-contract seasons")
    print(f"mean within-player difference: {diff.mean():+.3f} BPM")
    print(f"one-tailed p-value: {w.pvalue:.4f}")

    verdict = "REJECT" if p_two / 2 < 0.05 and coef > 0 else "FAIL TO REJECT"
    print(f"\nAt alpha = 0.05 (one-tailed): {verdict} H0.")


if __name__ == "__main__":
    main()
