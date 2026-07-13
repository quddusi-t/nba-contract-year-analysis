"""Contract-Year Data Console — the browser front-end to the same pipeline the CLI runs.

Arhan drops Excel sheets in here; the app merges, maps, validates, cleans, and hands
back player_seasons.csv, then saves everything to the private data repo. No git, no
Python, no terminal.

All the actual logic lives in src/ (ingest, clean, features, quick_inference) — this
file is presentation only. If a rule about the data changes, it changes in src/ and
both the CLI and this page follow.

Run locally:  .venv/bin/streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
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
from common import TABLE_PREFIXES, normalize_columns  # noqa: E402
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


def detect_table(filename: str) -> str:
    """Guess which table a file belongs to from its name, same rule as the CLI.

    The CLI matches on prefix only; here we also accept the table name anywhere in
    the filename, because a scrape often lands as '2019_stats.xlsx'.
    """
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


if not check_password():
    st.stop()

st.title("🏀 Contract-Year Data Console")
st.caption(
    "Upload your scraped sheets → merge → check → get a clean `player_seasons.csv` "
    "ready for Stata. The statistics still happen in Stata; this just gets the data there."
)

tab_upload, tab_map, tab_check, tab_build, tab_preview, tab_shared = st.tabs([
    "1 · Upload",
    "2 · Match columns",
    "3 · Check",
    "4 · Clean & download",
    "5 · Peek at the answer",
    "Shared files",
])

# ---------------------------------------------------------------- 1. upload
with tab_upload:
    st.subheader("Drop in your Excel or CSV files")
    st.markdown(
        "You can upload **many files at once** — one sheet per season is fine "
        "(`stats_2019.xlsx`, `stats_2020.xlsx`, …). They get stacked into one table.\n\n"
        "Three tables are used: **stats** (required), **contracts** (required), "
        "**injuries** (optional). The app guesses which is which from the filename; "
        "correct it below if it guesses wrong."
    )

    files = st.file_uploader(
        "Excel or CSV files",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )

    if files:
        frames: dict[str, list[pd.DataFrame]] = {}
        concat_warnings = []
        st.write("**Assign each file to a table:**")
        for i, f in enumerate(files):
            col_name, col_table, col_info = st.columns([3, 2, 3])
            col_name.text(f.name)
            table = col_table.selectbox(
                "table",
                options=["stats", "contracts", "injuries"],
                index=["stats", "contracts", "injuries"].index(detect_table(f.name)),
                key=f"table_{i}",
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
        cols = st.columns(len(tables))
        for col, (table, df) in zip(cols, tables.items()):
            n_files = len(frames[table])
            col.metric(
                table,
                f"{len(df):,} rows",
                f"from {n_files} file{'s' if n_files > 1 else ''}",
            )

        for p in concat_warnings:
            st.warning(f"**{p.table}** — {p.message}\n\n{p.fix}", icon="⚠️")

        st.success("Files loaded. Go to **2 · Match columns**.")

# ---------------------------------------------------------- 2. column mapping
with tab_map:
    st.subheader("Tell the app what your columns mean")
    tables_raw = st.session_state.get("tables_raw")

    if not tables_raw:
        st.info("Upload files first (step 1).")
    else:
        st.markdown(
            "Your headers on the left, what the analysis calls them on the right. "
            "The app has pre-filled its best guess — **change anything that looks wrong**. "
            "Columns set to *ignore* are dropped.\n\n"
            "`season` must be the season **end year**: 2023-24 → `2024`. "
            "`contract_end_season` is the last **guaranteed** year of the contract."
        )

        mapped: dict[str, pd.DataFrame] = {}
        for table, df in tables_raw.items():
            spec = TABLE_SPECS[table]
            canonical = ["player_name", "player_id", *spec.required, *spec.optional]
            if table == "injuries":
                canonical.append("games_missed")
            options = [IGNORE] + list(dict.fromkeys(canonical))

            with st.expander(f"**{table}** — {len(df.columns)} columns", expanded=True):
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
                        key=f"map_{table}_{col}",
                        label_visibility="collapsed",
                    )
                    preview = ", ".join(str(v) for v in df[col].dropna().head(3))
                    sample.caption(f"e.g. {preview}" if preview else "(empty)")
                    if choice != IGNORE:
                        mapping[col] = choice

                targets = list(mapping.values())
                clashes = {t for t in targets if targets.count(t) > 1}
                if clashes:
                    st.error(
                        f"Two columns are both mapped to {sorted(clashes)}. Pick one."
                    )
                mapped[table] = apply_mapping(df, mapping)

        st.session_state["tables"] = mapped
        st.success("Mapping saved. Go to **3 · Check**.")

# ------------------------------------------------------------------ 3. check
with tab_check:
    st.subheader("Does the data satisfy the contract?")
    tables = st.session_state.get("tables")

    if not tables:
        st.info("Upload and map your columns first (steps 1–2).")
    else:
        problems = list(st.session_state.get("concat_warnings", []))
        problems += validate_tables(tables)
        blocking = [p for p in problems if p.blocking]
        advisory = [p for p in problems if not p.blocking]

        if not blocking:
            st.success(
                "**Everything checks out.** Go to **4 · Clean & download**.", icon="✅"
            )
        else:
            st.error(f"**{len(blocking)} thing(s) to fix before we can continue.**")
            for p in blocking:
                st.markdown(f"- **{p.table}** — {p.message}  \n  *Fix:* {p.fix}")

        if advisory:
            with st.expander(f"{len(advisory)} warning(s) — usually fine, worth a look"):
                for p in advisory:
                    st.markdown(f"- **{p.table}** — {p.message}  \n  *{p.fix}*")

        st.session_state["valid"] = not blocking

# ------------------------------------------------------- 4. clean & download
with tab_build:
    st.subheader("Build the analysis dataset")
    tables = st.session_state.get("tables")

    if not tables or not st.session_state.get("valid"):
        st.info("Get a clean bill of health in step 3 first.")
    else:
        st.caption(
            f"Seasons with fewer than {MIN_GAMES} games or under {MIN_MINUTES_PG} "
            "minutes per game are dropped — rate stats are too noisy on tiny samples."
        )

        if st.button("Build player_seasons.csv", type="primary"):
            try:
                merged = merge_tables(
                    tables["stats"], tables["contracts"], tables.get("injuries")
                )
                built = build_features(merged)
                st.session_state["processed"] = built
            except Exception as e:
                st.error(f"Build failed: {e}")

        built = st.session_state.get("processed")
        if built is not None:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("player-seasons", f"{len(built):,}")
            c2.metric("players", f"{built['player_id'].nunique():,}")
            c3.metric("seasons", f"{built['season'].min()}–{built['season'].max()}")
            share = built["contract_year"].mean()
            c4.metric("contract-year share", f"{share:.1%}")

            if not 0.15 <= share <= 0.45:
                st.warning(
                    f"A {share:.1%} contract-year share is outside the usual 25–35%. "
                    "Check that `contract_end_season` really is the last guaranteed "
                    "year — that flag drives the whole study.",
                    icon="⚠️",
                )

            st.dataframe(built.head(50), use_container_width=True)

            csv = built.to_csv(index=False).encode()
            st.download_button(
                "⬇️ Download player_seasons.csv",
                data=csv,
                file_name="player_seasons.csv",
                mime="text/csv",
                type="primary",
            )
            st.caption("Put this file in `data/processed/` and run the Stata do-files on it.")

            st.divider()
            st.markdown("**Save to the shared project folder** so Kutsi sees the same data.")
            if not storage.is_configured():
                st.info(
                    "Shared storage isn't set up yet — see `app/README.md`. "
                    "Downloading the CSV above works regardless."
                )
            elif st.button(f"Save to {storage.repo_name()}"):
                try:
                    with st.spinner("Saving…"):
                        stamp = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")
                        storage.put_file(
                            "processed/player_seasons.csv", csv, f"data: rebuild {stamp}"
                        )
                        for name, blob in st.session_state.get("uploaded", []):
                            storage.put_file(f"raw/{name}", blob, f"data: upload {name}")
                    st.success(f"Saved to {storage.repo_name()}.")
                except Exception as e:
                    st.error(f"Save failed: {e}")

# ------------------------------------------------------- 5. inference preview
with tab_preview:
    st.subheader("A peek at the answer")
    st.caption(
        "The same fixed-effects model as `stata/01_main_fe.do`, run in Python. "
        "This is a **preview to catch problems early** — Stata stays the tool of "
        "record for the writeup."
    )

    built = st.session_state.get("processed")
    if built is None:
        st.info("Build the dataset in step 4 first.")
    elif st.button("Run the regression"):
        try:
            with st.spinner("Estimating…"):
                r = run_inference(built)
        except Exception as e:
            st.error(f"Estimation failed: {e}")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("contract-year effect", f"{r.coef:+.3f} BPM", f"SE {r.se:.3f}")
            c2.metric("95% CI", f"[{r.ci_low:+.2f}, {r.ci_high:+.2f}]")
            c3.metric("p-value (one-tailed)", f"{r.p_one_tailed:.4f}")

            if r.rejects_null:
                st.success(
                    f"At α = 0.05, **reject H₀**: players score {r.coef:+.3f} BPM higher "
                    f"in contract years, holding age, minutes, injuries, player and "
                    f"season fixed. ({r.n_obs:,} player-seasons, {r.n_players:,} players.)"
                )
            else:
                st.info(
                    "**Fail to reject H₀** at α = 0.05 — this data does not show a "
                    "significant contract-year effect. That is a real finding, not a "
                    "failure; report it honestly."
                )

            if r.wilcoxon_p is not None:
                st.markdown(
                    f"**Paired Wilcoxon (robustness):** {r.n_paired:,} players seen in "
                    f"both states, mean within-player difference "
                    f"{r.wilcoxon_diff:+.3f} BPM, one-tailed p = {r.wilcoxon_p:.4f}."
                )

            st.caption(
                "Careful: the naive paired difference runs bigger than the FE estimate "
                "because contract years skew older and better-selected. The FE number "
                "is the defensible one."
            )

# ---------------------------------------------------------------- shared tab
with tab_shared:
    st.subheader("Shared project files")
    if not storage.is_configured():
        st.info("Shared storage isn't configured. See `app/README.md` to set it up.")
    else:
        st.caption(f"Private repo: `{storage.repo_name()}`")
        for folder in ("raw", "processed"):
            entries = storage.list_dir(folder)
            st.markdown(f"**{folder}/** — {len(entries)} file(s)")
            for e in entries:
                st.markdown(f"- `{e.path}` · {e.size / 1024:.0f} KB")

        latest = storage.get_file("processed/player_seasons.csv")
        if latest:
            st.download_button(
                "⬇️ Download the latest shared player_seasons.csv",
                data=latest,
                file_name="player_seasons.csv",
                mime="text/csv",
            )
