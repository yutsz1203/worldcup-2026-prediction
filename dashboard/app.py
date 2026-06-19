# ruff: noqa: E402 — the sys.path bootstrap must precede the repo-root imports.
"""Streamlit dashboard for the live WC2026 model — entrypoint.

One module per tab (``match_probs``, ``hdc_ev``); shared formatting in ``common``.

Run:  streamlit run dashboard/app.py
"""

import sys
from pathlib import Path

# Repo-root imports (src/, model/, dashboard/) regardless of the launch directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboard.hdc_ev import render_hdc_ev
from dashboard.match_probs import render_match_probs

st.set_page_config(page_title="WC2026 forecasts", layout="wide", page_icon="🏆")

tab_probs, tab_hdc = st.tabs(["Match probs", "HKJC HDC EV"])
with tab_probs:
    render_match_probs()
with tab_hdc:
    render_hdc_ev()
