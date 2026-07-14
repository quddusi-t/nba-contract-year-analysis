# The web console

**Live: https://nba-contract-console.streamlit.app** (password-gated — ask Kutsi.)
Data lands in the private repo **quddusi-t/nba-contract-data**.

A browser front-end to the same pipeline `src/` runs, so a collaborator can do the
data work **without git, Python, or a terminal**. They open a URL, drag in Excel
sheets, and get a validated `player_seasons.csv` back.

```
upload many sheets  →  merge  →  match columns  →  validate  →  clean  →  download
                                                                    ↓
                                                  private data repo (shared state)
```

The page is presentation only. Every rule about the data lives in `src/ingest.py`,
`src/clean.py`, and `src/features.py` — the CLI and the website import the same
functions, so they cannot disagree about what valid data is. **Change the rules in
`src/`, never here.**

## What it does *not* do

**It does not run Stata.** Stata is licensed and won't run on free hosting, so the
estimation stays on your machine and the do-files in `stata/` remain the deliverable.
Tab 5 runs the same fixed-effects model in Python as an early warning — a preview, not
the result of record. See `docs/METHODOLOGY.md`.

---

## Deploying it (one-time, ~10 minutes)

### 1. Create the private data repo

Scraped sheets have unclear licensing and the analysis repo is public, so data goes in
a **separate private repo** (`.gitignore` keeps it out of this one — keep it that way).

```bash
gh repo create quddusi-t/nba-contract-data --private \
  --description "Raw + processed data for the contract-year study"
```

### 2. Create a scoped access token

github.com → Settings → Developer settings → **Fine-grained tokens** → Generate new token.

| Setting | Value |
|---|---|
| Repository access | **Only select repositories** → `nba-contract-data` |
| Permissions | **Contents: Read and write** (nothing else) |
| Expiration | Past the end of the project |

Fine-grained and scoped to one repo matters: the app holds this token, so if it leaks,
the blast radius is one private data repo — not your whole account.

### 3. Deploy to Streamlit Community Cloud (free)

Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, **New app**:

| Field | Value |
|---|---|
| Repository | `quddusi-t/nba-contract-year-analysis` |
| Branch | `main` |
| Main file path | `app/streamlit_app.py` |

Under **Advanced settings → Secrets**, paste:

```toml
app_password = "pick-something-and-text-it-to-arhan"
github_token = "github_pat_..."
data_repo    = "quddusi-t/nba-contract-data"
```

Deploy. You get a public URL; the password gate keeps strangers out.

### 4. Send the collaborator two things

The URL and the password. That's the whole onboarding.

---

## Running it locally

```bash
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/streamlit run app/streamlit_app.py
```

Secrets are optional locally. Without them the app runs open (it warns you) and the
save-to-shared-repo step is disabled — the upload → clean → download flow still works.
To test with secrets, create `.streamlit/secrets.toml` with the block from step 3;
it is gitignored.

## After you merge a change: REBOOT, don't just refresh

Streamlit Cloud picks up a new commit by re-running the **main script**. Modules already
imported into the Python process — everything in `src/` (`ingest`, `clean`, `features`) —
stay cached in `sys.modules` from before. So the page updates while the pipeline
underneath it does not, and you get errors like:

    TypeError: merge_tables() got an unexpected keyword argument 'report'

which look like a code bug but are a stale import. A browser hard-refresh cannot fix it;
the stale module is on the server.

**Any change to `src/` needs a reboot:** share.streamlit.io → your app → **⋮** →
**Reboot app**. That restarts the process and re-imports everything. Changes confined to
`app/` hot-reload fine — but since almost all real changes touch `src/`, just reboot by
default after merging.

## Notes on the free tier

- The app **sleeps after ~7 days idle** and wakes on the next visit (slow first load).
- ~1 GB RAM. Fine for NBA panel data — a few thousand player-seasons is nothing.
- The repo it deploys from is public, but **no data is committed to it**. Uploads live
  in memory during a session and are written only to the private data repo.
