"""Shared-password gate for the console.

Streamlit Community Cloud apps are public URLs, so without this anyone who finds the
link could upload files and burn the free tier's resources. One password, shared
between collaborators, held in Streamlit secrets and never committed.
"""

from __future__ import annotations

import hmac

import streamlit as st

from storage import _secret


def check_password() -> bool:
    """Render the gate. Returns True only once the correct password is entered."""
    if st.session_state.get("authenticated"):
        return True

    expected = _secret("app_password")
    if not expected:
        st.warning(
            "No `app_password` is set in secrets, so this app is **open to anyone "
            "with the link**. Fine for local use; set one before sharing the URL.",
            icon="⚠️",
        )
        st.session_state["authenticated"] = True
        return True

    st.title("Contract-Year Data Console")
    st.caption("Ask Kutsi for the password.")

    with st.form("login"):
        attempt = st.text_input("Password", type="password")
        if st.form_submit_button("Enter"):
            # compare_digest: constant-time, so the check can't be brute-forced by timing
            if hmac.compare_digest(attempt, expected):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Wrong password.")

    return False
