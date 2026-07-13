"""Generate synthetic sample data with a KNOWN contract-year effect.

Writes stats.csv / contracts.csv / injuries.csv to data/sample/ so the whole
pipeline (and the Stata do-files) can be tested end-to-end before real data exists.
The true effect is +0.8 BPM in contract years — quick_inference.py should recover
roughly that number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import SAMPLE_DIR

TRUE_CONTRACT_YEAR_EFFECT = 0.8  # BPM points
N_PLAYERS = 80
SEED = 42

FIRST = ["Alex", "Jordan", "Chris", "Taylor", "Marcus", "Devin", "Jalen", "Tyler",
         "Kevin", "Anthony", "Luka", "Nikola", "Trae", "Zion", "Deni", "Alperen"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Davis", "Miller", "Wilson",
        "Moore", "Sengun", "Doncic", "Jokic", "Young", "Hayes", "Avdija", "Porter"]


def main() -> None:
    rng = np.random.default_rng(SEED)
    stats_rows, contract_rows, injury_rows = [], [], []

    for pid in range(1, N_PLAYERS + 1):
        name = f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]} {pid}"
        start_season = int(rng.integers(2013, 2021))
        career_len = int(rng.integers(5, 11))
        start_age = int(rng.integers(19, 25))
        talent = rng.normal(0.0, 2.0)

        # contracts: consecutive 3-4 year deals from career start
        contract_ends = []
        end = start_season - 1
        while end < start_season + career_len - 1:
            end += int(rng.integers(3, 5))
            contract_ends.append(end)

        for k in range(career_len):
            season = start_season + k
            age = start_age + k
            contract_end = next(e for e in contract_ends if e >= season)
            is_contract_year = int(season == contract_end)

            games_missed = int(min(rng.poisson(6), 40))
            games = int(np.clip(82 - games_missed - rng.integers(0, 6), 20, 82))
            minutes_pg = float(np.clip(24 + 2.5 * talent + rng.normal(0, 3), 12, 38))

            age_curve = -0.06 * (age - 27) ** 2
            bpm = (
                talent
                + age_curve
                + TRUE_CONTRACT_YEAR_EFFECT * is_contract_year
                + rng.normal(0, 1.0)
            )
            # counting totals loosely consistent with bpm (for the per-36 fallback path)
            total_min = minutes_pg * games
            pts = max(0.0, (14 + 2.2 * bpm + rng.normal(0, 2)) * total_min / 36)
            reb = max(0.0, (6 + 0.7 * bpm + rng.normal(0, 1)) * total_min / 36)
            ast = max(0.0, (4 + 0.6 * bpm + rng.normal(0, 1)) * total_min / 36)

            stats_rows.append({
                "Player Name": name, "player_id": pid, "Season": season, "Age": age,
                "Team": "TM" + str(rng.integers(1, 31)), "Games": games,
                "Minutes": round(total_min, 1), "BPM": round(bpm, 2),
                "PTS": round(pts), "REB": round(reb), "AST": round(ast),
            })
            contract_rows.append({
                "player_id": pid, "Player Name": name, "Season": season,
                "contract_end_season": contract_end,
                "Salary": round(2e6 + 3e6 * max(talent + 2, 0.2) * (1 + 0.1 * k)),
                "contract_type": "rookie" if season <= contract_ends[0] else "veteran",
            })
            injury_rows.append({
                "player_id": pid, "Season": season, "games_missed": games_missed,
            })

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(stats_rows).to_csv(SAMPLE_DIR / "stats.csv", index=False)
    pd.DataFrame(contract_rows).to_csv(SAMPLE_DIR / "contracts.csv", index=False)
    pd.DataFrame(injury_rows).to_csv(SAMPLE_DIR / "injuries.csv", index=False)
    print(f"Wrote {len(stats_rows)} player-seasons for {N_PLAYERS} players to {SAMPLE_DIR}")
    print(f"True contract-year effect built in: +{TRUE_CONTRACT_YEAR_EFFECT} BPM")


if __name__ == "__main__":
    main()
