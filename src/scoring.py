"""Match-level scoring of the live WC2026 prediction ledger.

Once a round's results are in the ledger (``data/result/live/wc2026_match_ledger.csv``)
this scores every realised match with the same rules as the historical backtests —
the multiclass Brier score and the ranked probability score (``model/validation.py``)
plus top-pick accuracy — across the three markets we forecast:

* **1X2** — ordered home / draw / away (3 categories).
* **O/U 2.5** — total goals over / under 2.5 (2 categories).
* **O/U 3.5** — total goals over / under 3.5 (2 categories).

Each metric is computed per match and averaged. ``Overall`` pools every
per-match-per-market prediction, so it summarises skill across all three markets at
once. Every market is also scored against its uniform no-skill baseline (1/3 each
for 1X2, 1/2 each for the O/U markets) for context, mirroring the backtest report.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from model.validation import brier_multiclass, rps
from src.const import CON, LIVE_PATH

LEDGER_PATH = f"{LIVE_PATH}/wc2026_match_ledger.csv"
SCORES_PATH = f"{LIVE_PATH}/wc2026_match_scores.csv"

# Each market: its ordered probability columns, the category labels (same order),
# and a row -> realised-outcome-index function aligned with that order.
MARKETS: dict[str, dict] = {
    "1X2": {
        "cols": ["p_home", "p_draw", "p_away"],
        "labels": ["home", "draw", "away"],
        "outcome": lambda row, total: ["home", "draw", "away"].index(row["outcome"]),
    },
    "O/U 2.5": {
        "cols": ["p_over25", "p_under25"],
        "labels": ["over", "under"],
        "outcome": lambda row, total: 0 if total > 2.5 else 1,
    },
    "O/U 3.5": {
        "cols": ["p_over35", "p_under35"],
        "labels": ["over", "under"],
        "outcome": lambda row, total: 0 if total > 3.5 else 1,
    },
}


def _per_match_scores(ledger: pd.DataFrame) -> pd.DataFrame:
    """Long-form per-match, per-market scores: one row per (match, market).

    Carries the model and uniform-baseline Brier/RPS plus a ``correct`` flag (the
    top-probability pick matched the outcome) so both the per-market and pooled
    ``Overall`` aggregates fall out of a single ``groupby``.
    """
    rows = []
    for _, m in ledger.iterrows():
        total = int(m["home_score"]) + int(m["away_score"])
        for market, spec in MARKETS.items():
            probs = np.array([float(m[c]) for c in spec["cols"]])
            # Renormalise: the 1X2 columns are truncated-score-matrix outputs and can
            # drift a hair off 1; the O/U pairs are already complementary.
            probs = probs / probs.sum()
            idx = spec["outcome"](m, total)
            uniform = np.full(len(probs), 1.0 / len(probs))
            rows.append(
                {
                    "match_uid": m["match_uid"],
                    "market": market,
                    "predicted": spec["labels"][int(np.argmax(probs))],
                    "actual": spec["labels"][idx],
                    "brier": brier_multiclass(probs, idx),
                    "rps": rps(probs, idx),
                    "correct": int(np.argmax(probs) == idx),
                    "base_brier": brier_multiclass(uniform, idx),
                    "base_rps": rps(uniform, idx),
                }
            )
    return pd.DataFrame(rows)


def _summarise(label: str, sub: pd.DataFrame) -> dict:
    return {
        "market": label,
        "n": len(sub),
        "brier": float(sub["brier"].mean()),
        "rps": float(sub["rps"].mean()),
        "accuracy": float(sub["correct"].mean()),
        "base_brier": float(sub["base_brier"].mean()),
        "base_rps": float(sub["base_rps"].mean()),
    }


def _aggregate(per_match: pd.DataFrame) -> pd.DataFrame:
    """Summary table: ``Overall`` (all markets pooled) then one row per market."""
    rows = [_summarise("Overall", per_match)]
    rows += [
        _summarise(market, per_match[per_match["market"] == market])
        for market in MARKETS
    ]
    return pd.DataFrame(rows)


def _print_table(row: pd.Series) -> None:
    from rich.table import Table

    table = Table(title=f"{row['market']}  (n={int(row['n'])})")
    table.add_column("Metric")
    table.add_column("Model", justify="right")
    table.add_column("No-skill", justify="right")
    table.add_row("Brier", f"{row['brier']:.4f}", f"{row['base_brier']:.4f}")
    table.add_row("RPS", f"{row['rps']:.4f}", f"{row['base_rps']:.4f}")
    table.add_row("Accuracy", f"{row['accuracy']:.4f}", "—")
    CON.print(table)


def score_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    """Summary frame for a ledger: ``Overall`` + per-market Brier/RPS/accuracy and
    their uniform baselines. Pure (no printing / no I/O) so downstream consumers — the
    ``score`` command and the scorecard report — share one source of truth."""
    return _aggregate(_per_match_scores(ledger))


def score_ledger(
    ledger_path: str = LEDGER_PATH, out_path: str = SCORES_PATH
) -> pd.DataFrame:
    """Score the live ledger, print one table per market, and persist the summary.

    Returns the summary frame (``Overall`` + per-market Brier/RPS/accuracy and their
    uniform baselines); also writes it to ``out_path``.
    """
    ledger = pd.read_csv(ledger_path)
    summary = score_summary(ledger)
    summary.to_csv(out_path, index=False)

    CON.rule("WC2026 live match-level scores")
    for _, row in summary.iterrows():
        _print_table(row)
    CON.log(f"Scored {len(ledger)} matches across {len(MARKETS)} markets → {out_path}")
    return summary
