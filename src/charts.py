"""Matplotlib charts for the showcase (roadmap Tier 0, step 3).

Each function renders one projection (:mod:`src.projections`) to a PNG under
``FIGURES_PATH`` and returns the file path for embedding in ``showcase.md``. The
non-interactive ``Agg`` backend is forced so this runs headless. Charts are
regenerated from the forecast CSV artifacts only — no simulation.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: write PNGs, never open a window
import matplotlib.pyplot as plt

from src import projections as P
from src.const import FIGURES_PATH

_BAR = "#2b6cb0"


def _save(fig, name: str) -> str:
    path = f"{FIGURES_PATH}/{name}"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def champion_prob_bar(top: int = 20) -> str:
    """Horizontal bar of the ``top`` teams by championship probability."""
    df = (
        P._read("tournament_probs_initial.csv")
        .sort_values("champion", ascending=False)
        .head(top)
        .iloc[::-1]
    )
    fig, ax = plt.subplots(figsize=(8, 0.38 * len(df) + 1))
    ax.barh(df["team"], df["champion"] * 100, color=_BAR)
    for y, v in enumerate(df["champion"] * 100):
        ax.text(v + 0.15, y, f"{v:.1f}%", va="center", fontsize=8)
    ax.set_xlabel("Championship probability (%)")
    ax.set_title(f"WC2026 — title odds (top {top})")
    ax.margins(x=0.08)
    return _save(fig, "champion_prob_bar.png")


def expected_elimination_ranked() -> str:
    """All 48 teams ranked by expected stage reached (GROUP 0 → CHAMPION 6)."""
    df = P.expected_elimination_table().sort_values("expected_finish").reset_index()
    fig, ax = plt.subplots(figsize=(8, 0.22 * len(df) + 1))
    colors = plt.cm.viridis(df["expected_finish"] / df["expected_finish"].max())
    ax.barh(df["team"], df["expected_finish"], color=colors)
    ax.set_xlabel("Expected stage reached (0=group … 4=SF, 5=final, 6=champion)")
    ax.set_title("WC2026 — expected round of elimination (all 48)")
    ax.tick_params(axis="y", labelsize=7)
    ax.margins(y=0.01)
    return _save(fig, "expected_elimination_ranked.png")


def dark_horse_scatter() -> str:
    """Pot baseline (x) vs deep-run probability (y); above the line = overperforming."""
    df = P.dark_horse_table()
    fig, ax = plt.subplots(figsize=(7.5, 6))
    pot_colors = {1: "#2b6cb0", 2: "#38a169", 3: "#dd6b20", 4: "#805ad5"}
    for pot, grp in df.groupby("pot"):
        ax.scatter(
            grp["pot_baseline"] * 100,
            grp["deep_run"] * 100,
            label=f"Pot {int(pot)}",
            color=pot_colors.get(int(pot), "#555"),
            s=45,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.5,
        )
    lim = max(df["deep_run"].max(), df["pot_baseline"].max()) * 100 * 1.1
    ax.plot([0, lim], [0, lim], "--", color="#999", lw=1, label="par (= pot avg)")
    # Label the biggest overperformers and underperformers.
    flagged = list(df.head(6).itertuples()) + list(df.tail(3).itertuples())
    for r in flagged:
        ax.annotate(
            r.team,
            (r.pot_baseline * 100, r.deep_run * 100),
            fontsize=7,
            xytext=(4, 3),
            textcoords="offset points",
        )
    ax.set_xlabel("Seeding-pot baseline: avg P(reach SF) of pot peers (%)")
    ax.set_ylabel("Model P(reach SF) (%)")
    ax.set_title("WC2026 — dark-horse index (above line = beats its pot)")
    ax.legend(fontsize=8)
    return _save(fig, "dark_horse_scatter.png")


def build_all() -> dict[str, str]:
    """Render every showcase chart; return {key: path}."""
    return {
        "champion_prob_bar": champion_prob_bar(),
        "expected_elimination_ranked": expected_elimination_ranked(),
        "dark_horse_scatter": dark_horse_scatter(),
    }
