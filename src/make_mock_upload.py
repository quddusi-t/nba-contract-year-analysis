"""Generate REALISTICALLY MESSY Excel sheets — a dress rehearsal for real data.

data/sample/ is clean and synthetic: it proves the statistics work. This is the
opposite. It produces the mess a real Basketball-Reference export actually arrives
in, so we can test the whole intake path before a collaborator uploads anything:

  * one stats sheet per season (stats_2015.xlsx … stats_2024.xlsx), not one big file
  * Basketball-Reference headers: Rk / Player / Tm / G / MP / TRB — not our names
  * traded players with one row per team PLUS a 'TOT' season-total row
  * accented names (Dončić, Šengün) that must match across sheets
  * a WIDE contracts sheet: one row per player, one salary column per season
  * salaries as text ('$40,000,000'), stray blank cells, a junk 'Rk' column

The same +0.8 BPM contract-year effect is baked in, so after the pipeline digests
all of this, quick_inference.py should still recover ~+0.8. If it doesn't, the
intake path corrupted the data.

Usage:
    python src/make_mock_upload.py            # -> data/mock/
    python src/make_mock_upload.py --clean    # clean, long contracts instead of wide
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from common import REPO_ROOT

TRUE_EFFECT = 0.8
N_PLAYERS = 120
FIRST_SEASON, LAST_SEASON = 2015, 2024
SEED = 7

FIRST = ["Luka", "Nikola", "Alperen", "Jalen", "Marcus", "Devin", "Trae", "Zion",
         "Kevin", "Anthony", "Tyler", "Chris", "Jordan", "Deni", "Franz", "Josh"]
LAST = ["Dončić", "Jokić", "Šengün", "Brunson", "Smart", "Booker", "Young", "Williamson",
        "Durant", "Edwards", "Herro", "Paul", "Poole", "Avdija", "Wagner", "Giddey"]
TEAMS = ["BOS", "LAL", "DAL", "DEN", "MIA", "PHI", "GSW", "MIL", "NYK", "PHO", "HOU"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clean", action="store_true",
                    help="emit long/tidy contracts instead of the wide BBRef shape")
    args = ap.parse_args()

    rng = np.random.default_rng(SEED)

    # Unique names must differ in LETTERS, not digits: normalize_name() strips digits
    # and accents when it builds player ids, so 'Luka Dončić 7' and 'Luka Dončić 88'
    # would collapse into one player. (Real data has the same hazard with genuine
    # namesakes — two Marcus Williamses would merge.)
    pairs = [(f, la) for f in FIRST for la in LAST]
    picked = rng.choice(len(pairs), size=N_PLAYERS, replace=False)
    names = [f"{pairs[i][0]} {pairs[i][1]}" for i in picked]

    out = REPO_ROOT / "data" / "mock"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*"):
        f.unlink()

    stats_rows: list[dict] = []
    contract_spans: list[dict] = []

    for pid in range(N_PLAYERS):
        name = names[pid]
        start = int(rng.integers(FIRST_SEASON, LAST_SEASON - 2))
        career = int(rng.integers(4, 10))  # truncated below at LAST_SEASON
        start_age = int(rng.integers(19, 26))
        talent = rng.normal(0, 2)

        # consecutive 3-4 year deals
        ends, end = [], start - 1
        while end < start + career - 1:
            end += int(rng.integers(3, 5))
            ends.append(end)

        for k in range(career):
            season = start + k
            if season > LAST_SEASON:
                break
            age = start_age + k
            c_end = next(e for e in ends if e >= season)
            cy = int(season == c_end)

            missed = int(min(rng.poisson(6), 40))
            games = int(np.clip(82 - missed - rng.integers(0, 6), 21, 82))
            mpg = float(np.clip(24 + 2.5 * talent + rng.normal(0, 3), 11, 38))
            bpm = talent - 0.06 * (age - 27) ** 2 + TRUE_EFFECT * cy + rng.normal(0, 1)
            total_min = mpg * games
            pts = max(0.0, (14 + 2.2 * bpm + rng.normal(0, 2)) * total_min / 36)
            trb = max(0.0, (6 + 0.7 * bpm + rng.normal(0, 1)) * total_min / 36)
            ast = max(0.0, (4 + 0.6 * bpm + rng.normal(0, 1)) * total_min / 36)

            base = {"Player": name, "Age": age, "Pos": "SF",
                    "BPM": round(bpm, 1), "season": season}

            # ~12% of player-seasons are trades: TOT row + one row per team
            if rng.random() < 0.12:
                g1 = int(games * 0.55)
                stats_rows.append({**base, "Tm": "TOT", "G": games, "GS": games,
                                   "MP": round(total_min), "PTS": round(pts),
                                   "TRB": round(trb), "AST": round(ast)})
                for frac, tm in ((0.55, TEAMS[rng.integers(len(TEAMS))]),
                                 (0.45, TEAMS[rng.integers(len(TEAMS))])):
                    stats_rows.append({
                        **base, "Tm": tm,
                        "G": g1 if frac > 0.5 else games - g1,
                        "GS": g1 if frac > 0.5 else games - g1,
                        "MP": round(total_min * frac), "PTS": round(pts * frac),
                        "TRB": round(trb * frac), "AST": round(ast * frac),
                    })
            else:
                stats_rows.append({**base, "Tm": TEAMS[rng.integers(len(TEAMS))],
                                   "G": games, "GS": games, "MP": round(total_min),
                                   "PTS": round(pts), "TRB": round(trb),
                                   "AST": round(ast)})

            salary = round(2e6 + 3e6 * max(talent + 2, 0.2) * (1 + 0.1 * k))
            contract_spans.append({"Player": name, "season": season,
                                   "salary": salary, "c_end": c_end,
                                   "Tm": TEAMS[rng.integers(len(TEAMS))]})

    stats = pd.DataFrame(stats_rows)

    # --- one stats sheet per season, with a junk Rk column, BBRef style
    for season, chunk in stats.groupby("season"):
        sheet = chunk.drop(columns=["season"]).reset_index(drop=True)
        sheet.insert(0, "Rk", range(1, len(sheet) + 1))
        sheet = sheet[["Rk", "Player", "Age", "Tm", "Pos", "G", "GS", "MP",
                       "PTS", "TRB", "AST", "BPM"]]
        sheet.to_excel(out / f"stats_{season}.xlsx", index=False)

    contracts = pd.DataFrame(contract_spans)

    if args.clean:
        tidy = contracts.rename(columns={"season": "Season", "c_end": "contract_end_season",
                                         "salary": "Salary"})
        tidy[["Player", "Season", "contract_end_season", "Salary"]].to_excel(
            out / "contracts.xlsx", index=False)
        shape = "long/tidy"
    else:
        # WIDE: one row per player, one salary column per season, money as text
        wide = contracts.pivot_table(index="Player", columns="season",
                                     values="salary", aggfunc="first")
        wide.columns = [f"{int(s) - 1}-{str(int(s))[2:]}" for s in wide.columns]
        wide = wide.map(lambda v: "" if pd.isna(v) else f"${v:,.0f}")
        wide = wide.reset_index()
        wide.insert(0, "Rk", range(1, len(wide) + 1))
        wide.insert(2, "Tm", [TEAMS[i % len(TEAMS)] for i in range(len(wide))])
        wide["Guaranteed"] = ""
        wide.to_excel(out / "contracts_wide.xlsx", index=False)
        shape = "wide (Basketball-Reference style)"

    injuries = (
        stats[stats["Tm"] == "TOT"][["Player", "season"]]
        .assign(games_missed=lambda d: 82 - d["season"].map(lambda _: 70))
        .rename(columns={"season": "Season"})
    )
    injuries.to_excel(out / "injuries.xlsx", index=False)

    n_files = len(list(out.glob("*.xlsx")))
    print(f"Wrote {n_files} messy files to {out}")
    print(f"  {len(stats)} stats rows across {LAST_SEASON - FIRST_SEASON + 1} season sheets "
          f"({int((stats['Tm'] == 'TOT').sum())} traded player-seasons with TOT rows)")
    print(f"  contracts: {shape}")
    print(f"  true contract-year effect baked in: +{TRUE_EFFECT} BPM")
    print("\nNow either drag these into the web console, or:")
    print("  cp data/mock/* data/raw/ && python src/validate_raw.py")


if __name__ == "__main__":
    main()
