"""Contract-Year Data Console — the browser front-end to the same pipeline the CLI runs.

Arhan drops Excel sheets in here; the app merges, maps, validates, cleans, and hands
back player_seasons.csv, then archives the session to the private data repo. No git,
no Python, no terminal.

All the actual logic lives in src/ (ingest, clean, features, quick_inference) — this
file is presentation only. If a rule about the data changes, it changes in src/ and
both the CLI and this page follow.

Two things this page is deliberately opinionated about:

  * It EXPLAINS. The person using it is doing the statistics, not the engineering.
    Every screen says what the step is for and what could go wrong.
  * It never drops a row silently. Everything the pipeline does is written to a
    session log, shown on screen and archived with the data — so "why are there
    fewer rows than I uploaded?" always has an answer.

Run locally:  .venv/bin/streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
import traceback
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

# src/ holds the pipeline; app/ holds this page's helpers. `streamlit run` happens to
# add app/ to sys.path but nothing else does, so put both on explicitly.
APP_DIR = Path(__file__).resolve().parent
sys.path[:0] = [str(APP_DIR), str(APP_DIR.parent / "src")]

import storage  # noqa: E402
from auth import check_password  # noqa: E402
from clean import merge_tables  # noqa: E402
from common import REPO_ROOT, TABLE_PREFIXES, normalize_columns  # noqa: E402
from features import MIN_GAMES, MIN_MINUTES_PG, build_features  # noqa: E402
from ingest import (  # noqa: E402
    TABLE_SPECS,
    apply_mapping,
    attach_season,
    concat_frames,
    suggest_mapping,
    validate_tables,
)
from quick_inference import run_inference  # noqa: E402

st.set_page_config(page_title="Contract-Year Data Console", page_icon="🏀", layout="wide")

IGNORE = "— ignore —"

# Plain-language meaning of every column the analysis knows about. Shown on the
# matching screen, because "map MP to minutes" is meaningless without knowing why.
MEANING: dict[str, str] = {
    "player_name": "The player's name. Used to recognise the same player across your "
                   "different sheets, so spelling has to be consistent.",
    "player_id": "A numeric player id, if your source has one. Better than names — "
                 "but optional, we can build one from the names.",
    "season": "The season's **END year**. The 2023-24 season is `2024`. If this is "
              "off by one, every contract-year flag is wrong.",
    "age": "The player's age that season. We control for it: players improve, peak "
           "around 27, then decline, and contract years skew older.",
    "team": "His team. Not used in the analysis — just nice to have.",
    "games": "Games he played that season.",
    "minutes": "Minutes played — either the season total or per-game. Either is fine, "
               "the app works out which you gave it.",
    "bpm": "**The performance number we are testing.** Box Plus/Minus ideally, but "
           "PER or WS/48 work too — any single number that says how good the season "
           "was. It must be a *rate*, not a total: a player in a contract year may "
           "simply be played more, and we are asking whether he played *better*.",
    "pts": "Points. Only needed if you have no BPM — then we build a substitute from "
           "points/rebounds/assists per 36 minutes.",
    "reb": "Rebounds. Same as above: only used if BPM is missing.",
    "ast": "Assists. Same as above: only used if BPM is missing.",
    "contract_end_season": "**The most important column in the project.** The last "
                           "*guaranteed* season of the contract he was on that year. "
                           "The contract-year flag is just `season == this`. Decide "
                           "once whether option years count as guaranteed (recommended: "
                           "no) and say so in your writeup.",
    "salary": "His salary that season. Optional.",
    "contract_type": "Rookie / veteran / max / extension. Optional.",
    "games_missed": "Games missed through injury. We control for it so a bad injury "
                    "season isn't mistaken for a bad player.",
}


def detect_table(filename: str) -> str:
    """Guess which table a file belongs to from its name, same rule as the CLI."""
    stem = Path(filename).stem.lower()
    for prefix, table in TABLE_PREFIXES.items():
        if stem.startswith(prefix):
            return table
    for keyword, table in (("stat", "stats"), ("contract", "contracts"),
                           ("salar", "contracts"), ("injur", "injuries")):
        if keyword in stem:
            return table
    return "stats"


def read_upload(file) -> pd.DataFrame:
    data = file.getvalue()
    if file.name.lower().endswith(".csv"):
        return normalize_columns(pd.read_csv(BytesIO(data)))
    return normalize_columns(pd.read_excel(BytesIO(data)))


def session_log_md() -> str:
    """Everything that happened this session, as markdown. Archived with the data.

    This is not decoration: it is the audit trail. If a number looks wrong later, this
    says exactly which files went in, how their columns were matched, and every row the
    pipeline dropped and why. It is also most of a methodology section.
    """
    sid = st.session_state.get("session_id", "?")
    lines = [
        f"# Session log — {sid}",
        "",
        "Written automatically by the Contract-Year Data Console.",
        "",
        "## Files uploaded",
        "",
    ]
    for name, blob in st.session_state.get("uploaded", []):
        lines.append(f"- `{name}` ({len(blob) / 1024:.0f} KB)")

    lines += ["", "## How your columns were matched", ""]
    for table, mapping in st.session_state.get("mappings", {}).items():
        lines.append(f"**{table}**")
        lines.append("")
        lines.append("| your column | used as |")
        lines.append("|---|---|")
        for src, dst in mapping.items():
            lines.append(f"| `{src}` | `{dst}` |")
        dropped = st.session_state.get("dropped_cols", {}).get(table, [])
        if dropped:
            lines.append("")
            lines.append(f"Ignored (not used by the analysis): {', '.join(f'`{c}`' for c in dropped)}")
        lines.append("")

    warnings = st.session_state.get("all_warnings", [])
    if warnings:
        lines += ["## Notes and warnings", ""]
        for p in warnings:
            lines.append(f"- **{p.table}** — {p.message}")
            lines.append(f"  - {p.fix}")
        lines.append("")

    report = st.session_state.get("report", [])
    if report:
        lines += ["## What the pipeline did to the data", ""]
        for r in report:
            lines.append(f"- {r}")
        lines.append("")

    result = st.session_state.get("result_summary")
    if result:
        lines += ["## Preview of the result (Python, not Stata)", "", result, ""]

    return "\n".join(lines)


if not check_password():
    st.stop()

if "session_id" not in st.session_state:
    st.session_state["session_id"] = pd.Timestamp.now("UTC").strftime("%Y-%m-%d_%H%M")
if "upload_round" not in st.session_state:
    st.session_state["upload_round"] = 0

# ------------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### This session")
    st.code(st.session_state["session_id"], language=None)
    st.caption(
        "Everything you save is filed under this id, so we can always go back and see "
        "exactly what you uploaded and what the app did with it."
    )
    st.divider()
    if st.button("🔄 Start over", use_container_width=True):
        keep = {"authenticated"}
        for k in [k for k in st.session_state if k not in keep]:
            del st.session_state[k]
        st.rerun()
    st.caption(
        "Clears your uploads and starts a fresh session. If the page ever looks stuck "
        "or wrong, do a **hard refresh** — `Ctrl` + `Shift` + `R` — which reloads the "
        "app from scratch."
    )

st.title("🏀 Contract-Year Data Console")
st.markdown(
    "**Hi Arhan.** This page turns your scraped spreadsheets into the one clean file "
    "your analysis needs — `player_seasons.csv` — without you touching any code.\n\n"
    "You're testing whether players perform better in the **final year of their "
    "contract**. To do that we need one tidy row per player per season, with a flag "
    "saying whether that season was a contract year. Your sheets almost certainly "
    "aren't in that shape yet. That's what the steps below are for.\n\n"
    "Work through the tabs **in order** — each one unlocks the next. Nothing you do "
    "here can break anything, so click around freely."
)
st.info(
    "**The statistics still happen in Stata.** This page only prepares the data. "
    "Step 5 shows a preview so you can catch problems early, but the numbers you hand "
    "in come from your Stata do-files — see **6 · Next: Stata**.",
    icon="ℹ️",
)

(tab_upload, tab_map, tab_check, tab_build, tab_preview,
 tab_stata, tab_log, tab_shared) = st.tabs([
    "1 · Upload",
    "2 · Match columns",
    "3 · Check",
    "4 · Clean & download",
    "5 · Peek at the answer",
    "6 · Next: Stata",
    "📋 What the app did",
    "📁 Shared files",
])

# ---------------------------------------------------------------- 1. upload
with tab_upload:
    st.subheader("Step 1 — Drop in your Excel or CSV files")
    st.markdown(
        "**What's happening here:** your data probably lives in lots of separate "
        "sheets. This step gathers them into three tables.\n\n"
        "You can select **many files at once**. One sheet per season is completely "
        "normal (`stats_2019.xlsx`, `stats_2020.xlsx`, …) — they get stacked into one "
        "table for you. If a sheet has no *Season* column, the app reads the year from "
        "the **filename**, so name your files with the season end year."
    )
    st.markdown(
        "**The three tables:**\n"
        "- **stats** *(required)* — how each player performed each season.\n"
        "- **contracts** *(required)* — when each player's contract **ended**. This is "
        "what makes the whole study possible.\n"
        "- **injuries** *(optional)* — games missed. If you don't have it, we assume 0."
    )

    files = st.file_uploader(
        "Excel or CSV files — select as many as you like",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state['upload_round']}",
    )

    if files:
        frames: dict[str, list[pd.DataFrame]] = {}
        concat_warnings = []
        st.markdown("#### Which table is each file?")
        st.caption(
            "The app guesses from the filename. Fix any it got wrong — this is the one "
            "thing it can't work out for itself."
        )
        for i, f in enumerate(files):
            col_name, col_table, col_info = st.columns([3, 2, 3])
            col_name.text(f.name)
            table = col_table.selectbox(
                "table",
                options=["stats", "contracts", "injuries"],
                index=["stats", "contracts", "injuries"].index(detect_table(f.name)),
                key=f"table_{st.session_state['upload_round']}_{i}",
                label_visibility="collapsed",
            )
            try:
                df = read_upload(f)
            except Exception as e:
                col_info.error(f"Could not read: {e}")
                continue

            # a per-season export carries no Season column; take it from the filename
            df, season_problems = attach_season(df, f.name, table)
            concat_warnings += season_problems

            note = f"{len(df):,} rows · {len(df.columns)} columns"
            if season_problems and not season_problems[0].blocking:
                note += f" · season **{int(df['season'].iloc[0])}** (from filename)"
            col_info.caption(note)
            frames.setdefault(table, []).append(df)

        tables: dict[str, pd.DataFrame] = {}
        for table, fs in frames.items():
            df, probs = concat_frames(fs, table)
            tables[table] = df
            concat_warnings += probs

        st.session_state["tables_raw"] = tables
        st.session_state["concat_warnings"] = concat_warnings
        # keep the original bytes so the save step doesn't depend on widget state
        st.session_state["uploaded"] = [(f.name, f.getvalue()) for f in files]

        st.divider()
        st.markdown("#### What you've got")
        cols = st.columns(len(tables))
        for col, (table, df) in zip(cols, tables.items()):
            n_files = len(frames[table])
            col.metric(
                table,
                f"{len(df):,} rows",
                f"from {n_files} file{'s' if n_files > 1 else ''}",
            )

        if concat_warnings:
            st.markdown("#### Things the app noticed")
            st.caption(
                "These are notes, not errors. Read them — they say what the app did to "
                "your data on your behalf."
            )
            for p in concat_warnings:
                st.warning(f"**{p.table}** — {p.message}\n\n{p.fix}", icon="⚠️")

        st.success("Files loaded. Now go to **2 · Match columns**.", icon="✅")

# ---------------------------------------------------------- 2. column mapping
with tab_map:
    st.subheader("Step 2 — Tell the app what your columns mean")
    tables_raw = st.session_state.get("tables_raw")

    if not tables_raw:
        st.info("Nothing to match yet — upload your files in step 1 first.")
    else:
        st.markdown(
            "**What's happening here:** every data source names its columns "
            "differently. Basketball-Reference calls minutes `MP`, games `G`, and "
            "rebounds `TRB`. The analysis needs to know which of *your* columns is "
            "which.\n\n"
            "**Your columns are on the left. What the analysis calls them is in the "
            "middle. Example values from your file are on the right** — use those to "
            "sanity-check you're pointing at the column you think you are.\n\n"
            "The app has already filled in its best guesses. **Your job is just to "
            "check them and fix anything wrong.** Anything set to *— ignore —* is "
            "thrown away, which is fine for columns the analysis doesn't need "
            "(`Rk`, `Pos`, `GS`)."
        )

        with st.expander("📖 What each name means — read this once", expanded=False):
            st.markdown(
                "You don't have to have all of these. The ones marked **required** are "
                "the ones the analysis cannot run without."
            )
            for table, spec in TABLE_SPECS.items():
                st.markdown(f"**{table}**")
                rows = []
                needed = set(spec.required) | (
                    {"games_missed"} if table == "injuries" else set()
                )
                for col in [*spec.required, *spec.optional,
                            *(["games_missed"] if table == "injuries" else [])]:
                    if col not in MEANING:
                        continue
                    tag = "**required**" if col in needed else "optional"
                    rows.append(f"| `{col}` | {tag} | {MEANING[col]} |")
                st.markdown(
                    "| Column | | What it is |\n|---|---|---|\n"
                    + "\n".join(dict.fromkeys(rows))
                )
                st.markdown("")

        st.warning(
            "**Two columns decide whether this study works at all:**\n\n"
            "**`season`** must be the season's END year — the 2023-24 season is `2024`. "
            "Off by one and every contract-year flag lands on the wrong season.\n\n"
            "**`contract_end_season`** must be the last *guaranteed* year of the "
            "contract. Note that a column of **salaries is not enough** — salary tells "
            "us what he was paid, not when his deal ran out.",
            icon="🚨",
        )

        mapped: dict[str, pd.DataFrame] = {}
        mappings: dict[str, dict[str, str]] = {}
        dropped_cols: dict[str, list[str]] = {}

        for table, df in tables_raw.items():
            spec = TABLE_SPECS[table]
            canonical = ["player_name", "player_id", *spec.required, *spec.optional]
            if table == "injuries":
                canonical.append("games_missed")
            options = [IGNORE] + list(dict.fromkeys(canonical))

            with st.expander(
                f"**{table}** — {len(df.columns)} columns to check", expanded=True
            ):
                head = st.columns([2, 2, 3])
                head[0].caption("**YOUR column**")
                head[1].caption("**the analysis calls it**")
                head[2].caption("**example values from your file**")

                guess = suggest_mapping(list(df.columns), table)
                mapping: dict[str, str] = {}
                for col in df.columns:
                    left, right, sample = st.columns([2, 2, 3])
                    left.text(col)
                    default = guess.get(col, IGNORE)
                    choice = right.selectbox(
                        "maps to",
                        options=options,
                        index=options.index(default) if default in options else 0,
                        key=f"map_{st.session_state['upload_round']}_{table}_{col}",
                        label_visibility="collapsed",
                        help=MEANING.get(default) if default in MEANING else None,
                    )
                    preview = ", ".join(str(v) for v in df[col].dropna().head(3))
                    sample.caption(f"{preview}" if preview else "*(empty)*")
                    if choice != IGNORE:
                        mapping[col] = choice

                targets = list(mapping.values())
                clashes = {t for t in targets if targets.count(t) > 1}
                if clashes:
                    st.error(
                        f"**Two of your columns both point at {sorted(clashes)}.** "
                        "Only one column can be each thing — set the other to *ignore*."
                    )
                mapped[table] = apply_mapping(df, mapping)
                mappings[table] = mapping
                dropped_cols[table] = [c for c in df.columns if c not in mapping]

        st.session_state["tables"] = mapped
        st.session_state["mappings"] = mappings
        st.session_state["dropped_cols"] = dropped_cols
        st.success("Matching saved as you go. Now go to **3 · Check**.", icon="✅")

# ------------------------------------------------------------------ 3. check
with tab_check:
    st.subheader("Step 3 — Is anything wrong with the data?")
    tables = st.session_state.get("tables")

    if not tables:
        st.info("Nothing to check yet — do steps 1 and 2 first.")
    else:
        st.markdown(
            "**What's happening here:** before we build anything, the app checks your "
            "data against what the analysis needs. There are two kinds of finding:\n\n"
            "- 🚫 **Problems** — these stop the build. You have to fix them, usually by "
            "going back to step 2 and matching a column you missed, or by correcting "
            "the spreadsheet itself and re-uploading.\n"
            "- ⚠️ **Warnings** — the app is telling you what it did or noticed. Usually "
            "fine. Read them anyway; this is where a silent mistake would show up."
        )

        problems = list(st.session_state.get("concat_warnings", []))
        problems += validate_tables(tables)
        blocking = [p for p in problems if p.blocking]
        advisory = [p for p in problems if not p.blocking]
        st.session_state["all_warnings"] = problems

        st.divider()
        if not blocking:
            st.success(
                "**Nothing blocking. Your data is ready.** Go to "
                "**4 · Clean & download**.",
                icon="✅",
            )
        else:
            st.error(f"**{len(blocking)} problem(s) to fix before we can continue.**")
            for p in blocking:
                st.markdown(f"##### 🚫 {p.table} — {p.message}")
                st.markdown(f"**How to fix it:** {p.fix}")
                st.divider()

        if advisory:
            with st.expander(
                f"⚠️ {len(advisory)} warning(s) — worth a read", expanded=False
            ):
                for p in advisory:
                    st.markdown(f"- **{p.table}** — {p.message}  \n  *{p.fix}*")

        st.session_state["valid"] = not blocking

# ------------------------------------------------------- 4. clean & download
with tab_build:
    st.subheader("Step 4 — Build the file, download it, and share it")
    tables = st.session_state.get("tables")

    if not tables or not st.session_state.get("valid"):
        st.info("Not ready yet — get a clean bill of health in step 3 first.")
    else:
        st.markdown(
            "**What's happening here:** the app merges your three tables into one row "
            "per player per season, works out the contract-year flag, and adds the "
            "controls the model needs.\n\n"
            "**Click all three buttons below, left to right.** They do different "
            "things and you need all three. Buttons 2 and 3 stay switched off until "
            "you've pressed 1."
        )
        st.caption(
            f"While building, seasons with fewer than {MIN_GAMES} games or under "
            f"{MIN_MINUTES_PG} minutes per game are dropped — a handful of minutes "
            "makes a rate stat meaningless. Every row the app drops is written to "
            "**📋 What the app did**, so nothing disappears without an explanation."
        )

        built = st.session_state.get("processed")
        csv = built.to_csv(index=False).encode() if built is not None else b""

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("**1️⃣ Build**")
            st.caption("Make the dataset.")
            if st.button("Build the dataset", type="primary", use_container_width=True):
                report: list[str] = []
                try:
                    merged = merge_tables(
                        tables["stats"], tables["contracts"], tables.get("injuries"),
                        report=report,
                    )
                    st.session_state["processed"] = build_features(merged, report=report)
                    st.session_state["report"] = report
                    st.session_state["saved"] = None
                    st.session_state["crash"] = None
                    st.rerun()
                except Exception as e:
                    st.session_state["crash"] = traceback.format_exc()
                    st.error(f"Build failed: {e}")

        with c2:
            st.markdown("**2️⃣ Download**")
            st.caption("Get the file for Stata.")
            st.download_button(
                "Download player_seasons.csv",
                data=csv,
                file_name="player_seasons.csv",
                mime="text/csv",
                disabled=built is None,
                use_container_width=True,
            )

        with c3:
            st.markdown("**3️⃣ Save**")
            st.caption("Archive it for Kutsi.")
            can_save = built is not None and storage.is_configured()
            if st.button("Save this session", disabled=not can_save,
                         use_container_width=True):
                try:
                    with st.spinner("Saving…"):
                        where = storage.save_session(
                            st.session_state["session_id"],
                            st.session_state.get("uploaded", []),
                            csv,
                            session_log_md(),
                        )
                        st.session_state["saved"] = where
                    st.rerun()
                except Exception as e:
                    st.session_state["crash"] = traceback.format_exc()
                    st.error(f"Save failed: {e}")

        if st.session_state.get("crash"):
            st.error("Something broke. Send Kutsi the text below — it says exactly what.")
            with st.expander("Error details"):
                st.code(st.session_state["crash"], language="text")

        if built is None:
            st.info("Start with **1️⃣ Build**. The other two unlock once it's built.")
        else:
            st.divider()
            st.markdown("#### What you built")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("player-seasons", f"{len(built):,}")
            m2.metric("players", f"{built['player_id'].nunique():,}")
            m3.metric("seasons", f"{built['season'].min()}–{built['season'].max()}")
            share = built["contract_year"].mean()
            m4.metric("contract-year share", f"{share:.1%}")

            if not 0.15 <= share <= 0.45:
                st.warning(
                    f"**{share:.1%} of seasons are contract years, which is outside the "
                    "usual 25–35%.** Players sign 3–4 year deals, so roughly a quarter "
                    "to a third of seasons should be contract years. If this number "
                    "looks wrong, `contract_end_season` is probably wrong — and that "
                    "flag drives the entire study. Check a few players you know against "
                    "Spotrac before trusting anything downstream.",
                    icon="⚠️",
                )

            saved = st.session_state.get("saved")
            if saved:
                st.success(
                    f"**Saved to `{saved}/`** in {storage.repo_name()} — your original "
                    "sheets, the built dataset, and the log of what the app did. "
                    "Earlier sessions are kept, not overwritten.",
                    icon="✅",
                )
            elif not storage.is_configured():
                st.info(
                    "Sharing isn't set up on this deployment, so button 3 is off. "
                    "Downloading with button 2 still works — send Kutsi the file."
                )

            st.markdown("**A first look at the data** — 50 rows picked at random:")
            # A random sample, not the first 50 rows. The file is sorted by player, and
            # player ids are assigned alphabetically, so head(50) would only ever show
            # you the handful of players whose names sort first — useless for spotting
            # whether the data looks right. Fixed seed so it doesn't reshuffle on rerun.
            sample = built.sample(min(50, len(built)), random_state=0)
            st.dataframe(
                sample.sort_values(["player_name", "season"]), use_container_width=True
            )
            st.caption(
                "`contract_year` is the column the whole project is about: 1 if that "
                "season was the last year of his contract, 0 otherwise. Scan a player "
                "you know: does his contract year land where you'd expect? That check "
                "is worth more than any test the app can run for you."
            )

# ------------------------------------------------------- 5. inference preview
with tab_preview:
    st.subheader("Step 5 — A peek at the answer")
    st.markdown(
        "**What's happening here:** this runs the same fixed-effects model as your "
        "`stata/01_main_fe.do`, in Python. It compares **each player to himself** — his "
        "contract years against his other years — while holding age, minutes, injuries "
        "and the season constant.\n\n"
        "**This is a preview, not your result.** It exists so you find out *now* if "
        "something's wrong with the data, instead of after you've written half the "
        "report. The numbers you hand in come from Stata."
    )

    built = st.session_state.get("processed")
    if built is None:
        st.info("Build the dataset in step 4 first.")
    elif st.button("Run the regression", type="primary"):
        try:
            with st.spinner("Estimating…"):
                r = run_inference(built)
        except Exception as e:
            st.session_state["crash"] = traceback.format_exc()
            st.error(f"Estimation failed: {e}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("contract-year effect", f"{r.coef:+.3f} BPM", f"SE {r.se:.3f}")
            c2.metric("95% CI", f"[{r.ci_low:+.2f}, {r.ci_high:+.2f}]")
            c3.metric("p-value (one-tailed)", f"{r.p_one_tailed:.4f}")

            st.session_state["result_summary"] = (
                f"Fixed-effects preview: contract_year = {r.coef:+.3f} BPM "
                f"(SE {r.se:.3f}), 95% CI [{r.ci_low:+.3f}, {r.ci_high:+.3f}], "
                f"one-tailed p = {r.p_one_tailed:.4f}, "
                f"n = {r.n_obs} player-seasons, {r.n_players} players."
            )

            if r.rejects_null:
                st.success(
                    f"At α = 0.05, **reject H₀**: players score {r.coef:+.3f} BPM higher "
                    f"in contract years, holding age, minutes, injuries, player and "
                    f"season fixed. ({r.n_obs:,} player-seasons, {r.n_players:,} players.)"
                )
            else:
                st.info(
                    "**Fail to reject H₀** at α = 0.05 — this data doesn't show a "
                    "significant contract-year effect. **That is a real finding, not a "
                    "failure.** 'We tested it properly and found no effect' is a "
                    "perfectly good result; report it honestly rather than hunting for "
                    "a specification that gives you a star."
                )

            if r.wilcoxon_p is not None:
                st.markdown(
                    f"**Paired Wilcoxon (a robustness check):** {r.n_paired:,} players "
                    f"appear in both states, mean within-player difference "
                    f"{r.wilcoxon_diff:+.3f} BPM, one-tailed p = {r.wilcoxon_p:.4f}. "
                    "This makes no assumption that the effect is normally distributed, "
                    "so it's a useful second opinion."
                )

            st.caption(
                "Note the simple paired difference usually looks bigger than the "
                "fixed-effects estimate. That's because contract years skew older and "
                "towards better players — exactly the confounding the FE model removes. "
                "The FE number is the one you can defend."
            )

# ------------------------------------------------------------------ 6. stata
with tab_stata:
    st.subheader("Step 6 — Now do the actual statistics, in Stata")
    st.markdown(
        "You have `player_seasons.csv`. **This is where the real work starts** — "
        "everything up to now was just getting the data into a shape you can analyse.\n\n"
        "Put the file in your project's `data/processed/` folder, open Stata, and run "
        "the do-files below **in order**. You can download each one from here."
    )

    st.markdown("---")

    st.markdown("### The plan")
    st.markdown(
        "| | do-file | what it does | what you get |\n"
        "|---|---|---|---|\n"
        "| 1 | `01_main_fe.do` | The main fixed-effects regression | **The answer to H₀** "
        "— the contract_year coefficient, its CI, its p-value |\n"
        "| 2 | `02_robustness.do` | Does the finding survive being poked? | Wilcoxon test, "
        "`reghdfe`, alternative outcomes, the shirking check |\n"
        "| 3 | `03_tables_figures.do` | Turns it into things you can hand in | An `esttab` "
        "regression table and a `coefplot` |\n"
    )

    st.markdown("### Your hypotheses, so you don't lose sight of them")
    st.markdown(
        "- **H₀ (null):** a player performs the same in a contract year as in his other "
        "years. The mean within-player difference is zero.\n"
        "- **H₁ (alternative):** he performs *better*. This is **one-tailed** — you have "
        "a directional prediction, so **halve** Stata's two-tailed p-value when you "
        "report it (and only if the coefficient is positive)."
    )

    st.error(
        "**Never report a p-value on its own.** *'+0.6 BPM, 95% CI [0.2, 1.0], p = 0.03'* "
        "is a finding. *'p = 0.03'* is not — it says something is unlikely to be zero "
        "while saying nothing about how big it is or whether anyone should care. "
        "Effect size first, always.",
        icon="🚨",
    )

    st.markdown("### The do-files")
    stata_dir = REPO_ROOT / "stata"
    for path in sorted(stata_dir.glob("*.do")):
        with st.expander(f"`{path.name}`"):
            code = path.read_text()
            st.download_button(
                f"⬇️ Download {path.name}",
                data=code.encode(),
                file_name=path.name,
                mime="text/plain",
                key=f"dl_{path.name}",
            )
            st.code(code, language="stata")

    st.markdown("### Then the writeup")
    st.markdown(
        "Structure it: **Question → Data → Design (why fixed effects) → Results → "
        "Robustness → Limitations.** Professors read the table first, so make the table "
        "good.\n\n"
        "**State the limitations honestly — it's what separates a strong project from an "
        "average one:**\n"
        "- Players don't *randomly* end up in contract years, so this isn't a clean "
        "experiment. Fixed effects control for who a player *is*, not for what's "
        "happening around him that season.\n"
        "- Minutes are partly a coach's decision, and a coach may play a motivated "
        "player more. Controlling for minutes is defensible, but it's arguable — say so.\n"
        "- BPM is one opinion about performance, and it has its own biases.\n"
        "- Whatever rule you chose for option years (guaranteed or not), state it."
    )

# ------------------------------------------------------------- log / method
with tab_log:
    st.subheader("📋 What the app did to your data")
    st.markdown(
        "Every row the pipeline drops is recorded here. If the final file has fewer "
        "player-seasons than you uploaded, **this page tells you exactly where they "
        "went** — and this same log is saved alongside your data, so it can be checked "
        "later. Much of it belongs in your methodology section."
    )

    report = st.session_state.get("report")
    if not report:
        st.info("Build the dataset in step 4 and this fills in.")
    else:
        for line in report:
            if line.startswith("DROPPED"):
                st.warning(line, icon="🗑️")
            else:
                st.markdown(f"- {line}")

    if st.session_state.get("crash"):
        st.divider()
        st.error("The last action failed. Send this to Kutsi.")
        st.code(st.session_state["crash"], language="text")

    st.divider()
    with st.expander("📚 The rules the app always follows — the full method"):
        st.markdown(
            f"""
#### Putting your sheets together
- Files you assign to the same table are **stacked**. Columns are pooled: if a column
  exists in only some files, the other rows get an empty cell there (and you get a
  warning) — silently dropping it would corrupt the panel.
- **stats is the source of truth for who a player is.** Contracts and injuries are
  attached to it by name (or player id). Names are matched ignoring accents and case,
  so `Luka Dončić` and `Luka Doncic` are the same man. Two genuinely different players
  with identical names would be merged — a real, rare risk.
- If a stats sheet has no Season column, the season is read from the **filename**.

#### Rows the app removes, and why
- **Traded players.** A traded player appears once per team plus a `TOT` season-total
  row. We keep the **total** and drop the per-team rows — a partial row would understate
  his games and minutes and make him look worse than he was.
- **Player-seasons with no matching contract.** If we can't find a contract end year,
  we can't say whether it was a contract year, so the row is useless to this study.
- **Tiny samples:** under **{MIN_GAMES} games** or under **{MIN_MINUTES_PG} minutes per
  game**. A per-36 rate built on 40 total minutes is mostly noise; keeping such rows
  would widen your confidence interval and buy nothing.

#### Empty cells — we almost never fill them in
- **`games_missed` → 0** when there's no injury record. This is the *only* value the
  pipeline ever invents, and it's the safe assumption.
- **Performance values are never imputed.** If BPM is missing, the row stays in the file
  but the regression ignores it. Making up an outcome value would be fabricating the
  very thing you're trying to measure — the fastest way to a result that isn't real.

#### Columns the app drops
Anything not matched to a name the analysis uses — `Rk`, `Pos`, `GS`, `Signed Using`,
and so on. The final file keeps only what the model needs, plus names and teams so you
can read it.

#### Columns the app builds
- `minutes_pg` — minutes per game (worked out from totals if that's what you gave it).
- `pts36` / `reb36` / `ast36` — per-36-minute rates. **Rates, not totals**: a player may
  simply be *played more* in a contract year, and the question is whether he played
  *better*.
- `bpm` — if you have no BPM column, a z-scored average of those per-36 rates is used
  instead. Say so in your writeup: it isn't the same metric.
- `contract_year` — **the whole point.** 1 when `season == contract_end_season`.
- `post_contract_year` — the season straight after a contract year. Lets you test
  *shirking*: do players drop off once the new deal is signed?
- `age2` — age squared, because performance rises and then falls with age rather than
  moving in a straight line.
"""
        )

    if st.session_state.get("report"):
        st.download_button(
            "⬇️ Download this session's log",
            data=session_log_md().encode(),
            file_name=f"session_log_{st.session_state['session_id']}.md",
            mime="text/markdown",
        )

# ---------------------------------------------------------------- shared tab
with tab_shared:
    st.subheader("📁 Shared project files")
    if not storage.is_configured():
        st.info("Sharing isn't configured on this deployment. See `app/README.md`.")
    else:
        st.markdown(
            f"Each time you press **Save**, the whole session is filed under its own "
            f"folder in the private repo `{storage.repo_name()}` — your original sheets, "
            "the dataset that was built from them, and the log of what the app did.\n\n"
            "**Nothing is overwritten.** You can upload again tomorrow and still see "
            "exactly what today's numbers came from."
        )

        sessions = storage.list_sessions()
        if not sessions:
            st.caption("_No sessions saved yet._")
        for sid in sessions:
            marker = " ← this session" if sid == st.session_state["session_id"] else ""
            with st.expander(f"**{sid}**{marker}", expanded=(sid == sessions[0])):
                raw = storage.list_dir(f"sessions/{sid}/raw")
                st.markdown(f"**Uploaded sheets** — {len(raw)} file(s)")
                for e in raw:
                    st.markdown(f"- `{Path(e.path).name}` · {e.size / 1024:.0f} KB")

                log = storage.get_file(f"sessions/{sid}/session_log.md")
                if log:
                    with st.popover("📋 view the log"):
                        st.markdown(log.decode())

                data = storage.get_file(f"sessions/{sid}/player_seasons.csv")
                if data:
                    st.download_button(
                        "⬇️ player_seasons.csv from this session",
                        data=data,
                        file_name=f"player_seasons_{sid}.csv",
                        mime="text/csv",
                        key=f"dl_sess_{sid}",
                    )
