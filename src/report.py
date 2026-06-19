"""Render the live scorecard markdown (``docs/live_scorecard.md``).

The single pipeline that turns the predictions+actuals ledger into the three-table
report: match-level scoring, biggest model surprises, and biggest underdog wins. It
reads the ledger once and reuses :mod:`src.scoring` (the summary frame) and
:mod:`src.surprises` (the two story tables), so the numbers match ``wc26 score`` and
``wc26 surprises`` exactly — this is just their persistent, readable rendering.

    uv run python -m src.cli report          # regenerate docs/live_scorecard.md
"""

from __future__ import annotations

import pandas as pd

from src.const import CON, FORECAST_PATH, LIVE_PATH, TODAY
from src.scoring import score_summary
from src.surprises import _played, top_model_surprises, top_underdog_wins

LEDGER_PATH = f"{LIVE_PATH}/wc2026_match_ledger.csv"
STRENGTHS_PATH = f"{FORECAST_PATH}/team_strengths.csv"
REPORT_PATH = "docs/live_scorecard.md"


def _scoring_table(summary: pd.DataFrame) -> str:
    """Match-level scoring: model Brier/RPS with the uniform no-skill baseline in
    parentheses (so the table carries the same Model-vs-No-skill context the terminal
    tables print), plus top-pick accuracy."""
    head = (
        "| Market | n | Brier (no-skill) | RPS (no-skill) | Accuracy |\n"
        "|--------|--:|-----------------:|---------------:|---------:|"
    )
    lines = [
        f"| {r['market']} | {int(r['n'])} "
        f"| {r['brier']:.4f} ({r['base_brier']:.4f}) "
        f"| {r['rps']:.4f} ({r['base_rps']:.4f}) "
        f"| {r['accuracy']:.1%} |"
        for _, r in summary.iterrows()
    ]
    return "\n".join([head, *lines])


def _surprises_table(df: pd.DataFrame) -> str:
    head = (
        "| Date | Rd | Match | Result | Model gave | Surprise |\n"
        "|------|----|-------|:------:|-----------:|---------:|"
    )
    if df.empty:
        return head + "\n| _—_ | | | | | |"
    called = {"home": "home_team", "away": "away_team"}
    lines = [
        f"| {r['date']} | {r['round_id']} "
        f"| {r['home_team']} vs {r['away_team']} "
        f"| {int(r['home_score'])}-{int(r['away_score'])} "
        f"| {r[called[r['outcome']]] if r['outcome'] in called else 'draw'} "
        f"{r['p_outcome']:.1%} | {r['surprise']:.3f} |"
        for _, r in df.iterrows()
    ]
    return "\n".join([head, *lines])


def _underdogs_table(df: pd.DataFrame) -> str:
    head = (
        "| Date | Rd | Winner (Elo) | Loser (Elo) | Score | Elo gap |\n"
        "|------|----|--------------|-------------|:-----:|--------:|"
    )
    if df.empty:
        return head + "\n| _—_ | | | | | |"
    lines = [
        f"| {r['date']} | {r['round_id']} "
        f"| {r['winner']} ({r['winner_elo']:.0f}) "
        f"| {r['loser']} ({r['loser_elo']:.0f}) "
        f"| {r['score']} | {r['elo_gap']:.0f} |"
        for _, r in df.iterrows()
    ]
    return "\n".join([head, *lines])


def build_scorecard(
    n: int = 5,
    ledger_path: str = LEDGER_PATH,
    strengths_path: str = STRENGTHS_PATH,
    out_path: str = REPORT_PATH,
) -> str:
    """Render the live scorecard markdown from the ledger and write it to ``out_path``.

    ``n`` caps the rows in each surprise table. Returns the markdown string.
    """
    ledger = pd.read_csv(ledger_path)
    strengths = pd.read_csv(strengths_path)
    n_played = len(_played(ledger))

    markdown = f"""# Live tournament scorecard (match-level) and biggest upsets

## Match-level scoring

Model multiclass Brier and ranked probability score (lower is better) against the
uniform no-skill baseline in parentheses, plus top-pick accuracy. `Overall` pools every
per-match-per-market prediction across the three markets.

{_scoring_table(score_summary(ledger))}

## Biggest upsets

### Biggest model surprises

The matches the model called most wrong, ranked by `surprise = 1 − model_p(actual 1X2
outcome)`. "Model gave" is the probability the model assigned to what actually happened.

{_surprises_table(top_model_surprises(ledger, n=n))}

### Biggest underdog wins

Decisive results the lower-Elo team won, ranked by the Elo gap they overturned
(independent of the model's probability).

{_underdogs_table(top_underdog_wins(ledger, strengths, n=n))}
"""

    with open(out_path, "w") as fh:
        fh.write(markdown)
    CON.log(f"Wrote live scorecard ({n_played} matches played) → {out_path}")
    return markdown
