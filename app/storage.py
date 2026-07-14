"""Persist uploads and outputs to a PRIVATE GitHub repo via the Contents API.

Why a second, private repo instead of this one: the analysis repo is public and the
scraped sheets have unclear licensing (see HANDOFF.md), so the data must never land
in it. A private data repo keeps the files versioned and shared between collaborators
while the public repo stays code-only. Arhan never touches GitHub — this module is
the only client, and it authenticates as the app.

Configure in Streamlit secrets (Cloud dashboard, or .streamlit/secrets.toml locally):

    app_password = "..."
    github_token = "github_pat_..."          # fine-grained PAT, Contents: read+write
    data_repo    = "quddusi-t/nba-contract-data"

If these are absent the app still runs — saving is simply disabled, so the whole
upload -> clean -> download flow works before the repo exists.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import requests
import streamlit as st

API = "https://api.github.com"
TIMEOUT = 30


def _secret(name: str) -> str | None:
    """Streamlit secrets first, env var as a fallback (handy for local runs)."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets.toml at all: not an error, just unconfigured
        pass
    return os.environ.get(name.upper())


def is_configured() -> bool:
    return bool(_secret("github_token") and _secret("data_repo"))


def repo_name() -> str:
    return _secret("data_repo") or "(not configured)"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_secret('github_token')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@dataclass(frozen=True)
class SavedFile:
    path: str
    size: int
    updated: str


def _sha(path: str) -> str | None:
    """Current blob sha of a file, or None if it does not exist yet.

    The Contents API needs the sha to overwrite an existing file; omitting it on an
    existing path fails with 422.
    """
    r = requests.get(
        f"{API}/repos/{repo_name()}/contents/{path}", headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def put_file(path: str, content: bytes, message: str) -> None:
    """Create or overwrite one file in the data repo. Raises on failure."""
    body = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
    }
    sha = _sha(path)
    if sha:
        body["sha"] = sha

    r = requests.put(
        f"{API}/repos/{repo_name()}/contents/{path}",
        headers=_headers(),
        json=body,
        timeout=TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"GitHub rejected the upload of {path} ({r.status_code}): "
            f"{r.json().get('message', r.text)}"
        )


def delete_file(path: str, message: str) -> None:
    """Remove one file from the data repo. Silently ignores a file that isn't there."""
    sha = _sha(path)
    if not sha:
        return
    requests.delete(
        f"{API}/repos/{repo_name()}/contents/{path}",
        headers=_headers(),
        json={"message": message, "sha": sha},
        timeout=TIMEOUT,
    )


def save_raw(session_id: str, files: list[tuple[str, bytes]], progress=None) -> str:
    """Archive the uploaded sheets under sessions/<session_id>/raw/, before anything else.

    Deliberately called at UPLOAD time, not at build time. If the pipeline then chokes
    on his data, we already have the exact files that broke it and can debug them
    ourselves — far better than asking him to describe his spreadsheet over chat, or to
    edit it blind. The raw sheets are the one artefact that is never reproducible.

    `progress` is an optional callback(i, total, name): each file is a couple of HTTP
    round-trips, so a dozen sheets takes a noticeable few seconds and the user needs to
    see it moving.
    """
    base = f"sessions/{session_id}"
    for i, (name, blob) in enumerate(files, start=1):
        if progress:
            progress(i, len(files), name)
        put_file(f"{base}/raw/{name}", blob, f"data({session_id}): upload {name}")
    return f"{base}/raw"


def save_build(session_id: str, csv: bytes, log_md: str) -> str:
    """Archive the built dataset and the session log alongside the raw sheets.

    Sessions are kept in their own folder rather than overwriting the last one: uploads
    get iterated on (fix a sheet, re-upload, rebuild), and being able to go back to what
    was uploaded on Tuesday — together with the log of what the pipeline did to it — is
    the difference between "the numbers changed" and "we know why they changed".

    processed/player_seasons.csv is also updated as a pointer to the most recent build,
    so there is always one obvious file to hand to Stata.
    """
    base = f"sessions/{session_id}"
    put_file(f"{base}/player_seasons.csv", csv, f"data({session_id}): built dataset")
    put_file(f"{base}/session_log.md", log_md.encode(), f"data({session_id}): log")
    put_file("processed/player_seasons.csv", csv, f"data: latest build ({session_id})")
    return base


def list_sessions() -> list[str]:
    """Session folder names, newest first (ids are timestamps, so this sorts)."""
    r = requests.get(
        f"{API}/repos/{repo_name()}/contents/sessions", headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code != 200:
        return []
    entries = r.json()
    if not isinstance(entries, list):
        return []
    return sorted(
        (e["name"] for e in entries if e.get("type") == "dir"), reverse=True
    )


def get_file(path: str) -> bytes | None:
    """Download one file from the data repo, or None if it is not there."""
    r = requests.get(
        f"{API}/repos/{repo_name()}/contents/{path}", headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code != 200:
        return None
    return base64.b64decode(r.json()["content"])


def list_dir(path: str) -> list[SavedFile]:
    """List one directory in the data repo (empty list if it does not exist yet)."""
    r = requests.get(
        f"{API}/repos/{repo_name()}/contents/{path}", headers=_headers(), timeout=TIMEOUT
    )
    if r.status_code != 200:
        return []
    entries = r.json()
    if not isinstance(entries, list):
        return []
    return [
        SavedFile(path=e["path"], size=e.get("size", 0), updated="")
        for e in entries
        if e.get("type") == "file"
    ]
