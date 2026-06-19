"""The running biggest-surprise log for the live WC2026 ledger.

Two compact, memorable story tables drawn from the predictions+actuals ledger
(``data/result/live/wc2026_match_ledger.csv``):

* **Biggest model surprises** — the matches the model called most wrong, ranked by
  ``surprise = 1 − model_p(actual 1X2 outcome)``. A 0.92 means the model gave the
  thing that actually happened only an 8% chance.
* **Biggest underdog wins** — decisive results where the lower-Elo team won, ranked by
  the Elo gap they overturned (independent of the model's probability).

Both look only at realised matches, so the picture grows round by round. This is a
read-only view — it scores nothing and persists nothing.
"""

from __future__ import annotations

import pandas as pd

from src.const import CON, FORECAST_PATH, LIVE_PATH

LEDGER_PATH = f"{LIVE_PATH}/wc2026_match_ledger.csv"
STRENGTHS_PATH = f"{FORECAST_PATH}/team_strengths.csv"

# outcome label -> the model-probability column that called it.
_OUTCOME_COL = {"home": "p_home", "draw": "p_draw", "away": "p_away"}


def _played(ledger: pd.DataFrame) -> pd.DataFrame:
    """Rows with a realised 1X2 result (unplayed forecasts have a blank outcome)."""
    return ledger[ledger["outcome"].isin(_OUTCOME_COL)].copy()


def top_model_surprises(ledger: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Played matches ranked by ``1 − model_p(actual outcome)``, biggest first."""
    played = _played(ledger)
    played["p_outcome"] = [
        float(r[_OUTCOME_COL[r["outcome"]]]) for _, r in played.iterrows()
    ]
    played["surprise"] = 1.0 - played["p_outcome"]
    cols = [
        "date",
        "round_id",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "outcome",
        "p_outcome",
        "surprise",
    ]
    return played.sort_values("surprise", ascending=False).head(n)[cols]


def top_underdog_wins(
    ledger: pd.DataFrame, strengths: pd.DataFrame, n: int = 5
) -> pd.DataFrame:
    """Decisive matches the lower-Elo team won, ranked by the Elo gap overturned."""
    elo = dict(zip(strengths["team"], strengths["elo"]))
    decisive = ledger[ledger["outcome"].isin(["home", "away"])].copy()

    rows = []
    for _, r in decisive.iterrows():
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        if r["outcome"] == "home":
            winner, loser, w_goals, l_goals = r["home_team"], r["away_team"], hs, as_
        else:
            winner, loser, w_goals, l_goals = r["away_team"], r["home_team"], as_, hs
        if winner not in elo or loser not in elo:
            continue
        gap = elo[loser] - elo[winner]
        if gap <= 0:  # winner was the favourite (or level) — not an upset
            continue
        rows.append(
            {
                "date": r["date"],
                "round_id": r["round_id"],
                "winner": winner,
                "loser": loser,
                "score": f"{w_goals}-{l_goals}",
                "winner_elo": float(elo[winner]),
                "loser_elo": float(elo[loser]),
                "elo_gap": float(gap),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values("elo_gap", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )


def _print_surprises(df: pd.DataFrame) -> None:
    from rich.table import Table

    table = Table(title="Biggest model surprises  (1 − model_p of the actual result)")
    table.add_column("Date")
    table.add_column("Rd")
    table.add_column("Match")
    table.add_column("Result", justify="center")
    table.add_column("Model gave", justify="right")
    table.add_column("Surprise", justify="right")
    for _, r in df.iterrows():
        called = {"home": r["home_team"], "away": r["away_team"], "draw": "draw"}[
            r["outcome"]
        ]
        table.add_row(
            str(r["date"]),
            str(r["round_id"]),
            f"{r['home_team']} vs {r['away_team']}",
            f"{int(r['home_score'])}-{int(r['away_score'])}",
            f"{called} {r['p_outcome']:.1%}",
            f"{r['surprise']:.3f}",
        )
    CON.print(table)


def _print_underdogs(df: pd.DataFrame) -> None:
    from rich.table import Table

    table = Table(title="Biggest underdog wins  (Elo gap overturned)")
    table.add_column("Date")
    table.add_column("Rd")
    table.add_column("Winner (Elo)")
    table.add_column("Loser (Elo)")
    table.add_column("Score", justify="center")
    table.add_column("Elo gap", justify="right")
    for _, r in df.iterrows():
        table.add_row(
            str(r["date"]),
            str(r["round_id"]),
            f"{r['winner']} ({r['winner_elo']:.0f})",
            f"{r['loser']} ({r['loser_elo']:.0f})",
            str(r["score"]),
            f"{r['elo_gap']:.0f}",
        )
    CON.print(table)


def report_surprises(
    n: int = 5,
    ledger_path: str = LEDGER_PATH,
    strengths_path: str = STRENGTHS_PATH,
) -> None:
    """Print the two surprise tables from the live ledger (top ``n`` rows each)."""
    ledger = pd.read_csv(ledger_path)
    if _played(ledger).empty:
        CON.log("No played matches in the ledger yet — nothing to surprise us.")
        return

    strengths = pd.read_csv(strengths_path)
    CON.rule("WC2026 biggest-surprise log")
    _print_surprises(top_model_surprises(ledger, n=n))
    _print_underdogs(top_underdog_wins(ledger, strengths, n=n))
