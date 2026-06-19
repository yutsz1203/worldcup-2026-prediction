"""Shared formatting helpers for the dashboard tabs."""

import pandas as pd


def score_cell(h: float, a: float) -> str:
    """``1–0`` for an integer scoreline; ``—`` when either side is missing.

    Missing values are the already-locked rounds predicted before scorelines
    were emitted (Elo has since moved, so they cannot be reconstructed).
    """
    if pd.isna(h) or pd.isna(a):
        return "—"
    return f"{int(h)}–{int(a)}"


def xg_cell(h: float, a: float) -> str:
    """``1.4–0.9`` expected-goals pair; ``—`` when either side is missing."""
    if pd.isna(h) or pd.isna(a):
        return "—"
    return f"{h:.1f}–{a:.1f}"


def prob_cell(p: float) -> str:
    """``66% (1.51)`` — probability with its fair decimal odds (1/p)."""
    return f"{p:.0%} ({1 / p:.2f})" if p > 0 else "0% (—)"


def ev_color(ev: float) -> str:
    """Green for positive edge/EV cells, red for negative."""
    return f"color: {'#137333' if ev > 0 else '#a50e0e'}"
