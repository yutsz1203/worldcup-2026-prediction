"""The single durable predictions+actuals ledger for future validation.

:func:`build_match_ledger` left-joins the locked per-round forecasts
(``wc2026_match_probs.csv``) onto the ingested actual results, one row per forecast.
Every prediction is kept; the actual columns stay blank until the match is played.
It performs **no scoring** — that is deferred (see the plan roadmap); this file just
pairs each locked prediction with the outcome it was trying to call.

Orientation note: the forecast's ``home_team``/``away_team`` may differ from the feed's
``team1``/``team2`` order. Outcome is derived from the feed's canonical ``winner`` (so
penalty-decided knockouts resolve correctly, not as draws), and the actual scoreline is
re-oriented to the forecast's home/away so ``home_score`` lines up with ``p_home``.
"""

from __future__ import annotations

import pandas as pd

from src.const import LIVE_PATH
from src.forecast import PROBS_COLUMNS

LEDGER_PATH = f"{LIVE_PATH}/wc2026_match_ledger.csv"

LEDGER_COLUMNS = PROBS_COLUMNS + [
    "home_score",
    "away_score",
    "outcome",
    "actual_winner",
]

_RES_COLS = [
    "match_uid",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "winner",
]


def build_match_ledger(
    match_probs: pd.DataFrame,
    actual_results: pd.DataFrame,
    out: str = LEDGER_PATH,
) -> pd.DataFrame:
    """Left-join locked forecasts onto actual results on ``match_uid``.

    Returns (and writes) one row per forecast: prediction columns plus
    ``home_score``/``away_score`` (re-oriented to the forecast's home/away),
    ``outcome`` ∈ {home, draw, away} from the canonical winner, and ``actual_winner``.
    Unplayed matches have blank actual fields.
    """
    probs = match_probs.copy()

    has_results = actual_results is not None and not actual_results.empty
    if has_results:
        res = actual_results[_RES_COLS].rename(
            columns={
                "home_team": "_res_home",
                "away_team": "_res_away",
                "home_score": "_res_hs",
                "away_score": "_res_as",
                "winner": "_res_winner",
            }
        )
        merged = probs.merge(res, on="match_uid", how="left")
    else:
        merged = probs.assign(
            _res_home=pd.NA,
            _res_away=pd.NA,
            _res_hs=pd.NA,
            _res_as=pd.NA,
            _res_winner=pd.NA,
        )

    home_score, away_score, outcome, winner_out = [], [], [], []
    for _, r in merged.iterrows():
        if pd.isna(r["_res_home"]):
            home_score.append(pd.NA)
            away_score.append(pd.NA)
            outcome.append("")
            winner_out.append("")
            continue
        # Re-orient the feed scoreline to the forecast's home/away designation.
        if r["_res_home"] == r["home_team"]:
            hs, as_ = r["_res_hs"], r["_res_as"]
        else:
            hs, as_ = r["_res_as"], r["_res_hs"]
        home_score.append(int(hs))
        away_score.append(int(as_))
        w = r["_res_winner"]
        if pd.isna(w):
            outcome.append("draw")
            winner_out.append("")
        else:
            outcome.append("home" if w == r["home_team"] else "away")
            winner_out.append(w)

    merged["home_score"] = pd.array(home_score, dtype="Int64")
    merged["away_score"] = pd.array(away_score, dtype="Int64")
    merged["outcome"] = outcome
    merged["actual_winner"] = winner_out

    ledger = merged[LEDGER_COLUMNS].sort_values("date").reset_index(drop=True)
    ledger.to_csv(out, index=False)
    return ledger
