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


def replace_raw(files: list[tuple[str, bytes]], message: str) -> tuple[int, int]:
    """Make raw/ mirror exactly this upload: write the new files, delete stragglers.

    Deliberately NOT additive. If saves piled up, a later collaborator pulling the repo
    would find one upload's sheets mixed with another's and no way to tell which is
    which. Nothing is lost by replacing: git keeps every previous version in history.

    Returns (written, deleted).
    """
    keep = {name for name, _ in files}
    for name, blob in files:
        put_file(f"raw/{name}", blob, message)

    stale = [f for f in list_dir("raw") if Path(f.path).name not in keep | {".gitkeep"}]
    for f in stale:
        delete_file(f.path, f"data: drop {Path(f.path).name} (not in the latest upload)")

    return len(files), len(stale)


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
