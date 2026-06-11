"""Rolling round-by-round match forecaster for the live WC2026.

One round is forecast at a time, against **freshly re-scraped Elo** that already
reflects every completed match (the covariate is live; the GLM is frozen). Group
matchups come from the local fixture file; knockout matchups are read resolved from
the bzzoiro feed (``src/bzzoiro.py``) once the bracket settles upstream.

Predictions are *locked*: a round's probabilities are written once to
``wc2026_match_probs.csv`` and never recomputed (the guard in :func:`forecast_round`).
Scoring is deferred — :func:`src.ledger.build_match_ledger` pairs each locked
prediction with its eventual actual result for later validation.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

import numpy as np
import pandas as pd

from model.probabilities import generate_probabilities
from model.rates import get_independent_rates
from src.bzzoiro import GROUP_ROUNDS, load_resolved_fixtures_csv, make_match_uid
from src.const import (
    CLEANED_DATA_PATH,
    CON,
    LIVE_PATH,
    RAW_DATA_PATH,
    WC26_RESULTS_PATH,
)

ROUND_ORDER = ["G1", "G2", "G3", "R32", "R16", "QF", "SF", "BRONZE", "FINAL"]
MATCH_PROBS_PATH = f"{LIVE_PATH}/wc2026_match_probs.csv"
# Mirror the simulation / validation cap: degenerate sparse-team params can blow a
# rate up far enough that the truncated score-matrix underflows to all zeros.
MAX_LAMBDA = 15.0

PROBS_COLUMNS = [
    "match_uid",
    "round_id",
    "stage",
    "date",
    "home_team",
    "away_team",
    "p_home",
    "p_draw",
    "p_away",
    "p_over25",
    "p_under25",
    "p_over35",
    "p_under35",
    "elo_retrieved_date",
    "model_version",
]


def _model_version() -> str:
    """Short git SHA for reproducibility; empty string outside a git checkout."""
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return ""


def _load_elo(elo: Optional[pd.DataFrame], rescrape: bool) -> pd.DataFrame:
    """Resolve the Elo frame: explicit arg > fresh scrape > cached CSV.

    The scraper is imported lazily so forecasting (and tests passing an Elo frame)
    never pulls in Playwright/Selenium or hits the bare-import ``src/`` path.
    """
    if elo is not None:
        return elo
    if rescrape:
        from src.scraper import latest_elo  # lazy: heavy deps + bare imports

        return latest_elo()
    return pd.read_csv(f"{RAW_DATA_PATH}/elo_latest.csv")


def _group_round_fixtures(round_id: str) -> pd.DataFrame:
    """Concrete matchups for a group matchday from the local fixture file.

    Within each group the six fixtures are ordered by kickoff into three matchdays
    (rows 0-1 -> G1, 2-3 -> G2, 4-5 -> G3).
    """
    df = pd.read_csv(f"{CLEANED_DATA_PATH}/wc26_groupstage_matches.csv")
    md = {"G1": 0, "G2": 1, "G3": 2}[round_id]
    rows = []
    for label, g in df.groupby("match_label"):
        g = g.sort_values("kickoff_at").reset_index(drop=True)
        for _, r in g.iloc[md * 2 : md * 2 + 2].iterrows():
            home, away = r["home_team"], r["away_team"]
            rows.append(
                {
                    "match_uid": make_match_uid(home, away, is_knockout=False),
                    "round_id": round_id,
                    "stage": label,
                    "date": str(r["kickoff_at"])[:10],
                    "home_team": home,
                    "away_team": away,
                }
            )
    return pd.DataFrame(rows)


def load_round_fixtures(
    round_id: str, results_path: Optional[str] = None
) -> pd.DataFrame:
    """Concrete (home, away) matchups for ``round_id``.

    Group rounds come from the local fixture file; knockout rounds from the
    resolved-fixtures feed, restricted to **unplayed** matches. Raises if a
    knockout round has no resolved fixtures yet (bracket not settled upstream).
    Columns: ``match_uid, round_id, stage, date, home_team, away_team``.
    """
    if round_id in GROUP_ROUNDS:
        return _group_round_fixtures(round_id)

    fixtures = load_resolved_fixtures_csv(results_path or WC26_RESULTS_PATH)
    ko = fixtures[(fixtures["round_id"] == round_id) & (~fixtures["played"])].copy()
    if ko.empty:
        raise ValueError(
            f"No resolved unplayed fixtures for round {round_id} yet — the knockout "
            "bracket has not settled upstream in the results feed."
        )
    return pd.DataFrame(
        {
            "match_uid": ko["match_uid"].to_numpy(),
            "round_id": round_id,
            "stage": ko["round"].to_numpy(),
            "date": ko["date"].to_numpy(),
            "home_team": ko["home_team"].to_numpy(),
            "away_team": ko["away_team"].to_numpy(),
        }
    )


def _predict_fixture(
    home: str, away: str, elo: pd.DataFrame, base: pd.DataFrame
) -> dict:
    """1X2 + over/under probabilities for one matchup (no home-advantage bonus)."""
    lam_h, lam_a = get_independent_rates(home, away, elo, base)
    lam_h, lam_a = min(lam_h, MAX_LAMBDA), min(lam_a, MAX_LAMBDA)
    long_info, _ = generate_probabilities(home, lam_h, away, lam_a)
    probs = np.array(
        [
            float(long_info["Home Probability"]),
            float(long_info["Draw Probability"]),
            float(long_info["Away Probability"]),
        ]
    )
    probs = probs / probs.sum()  # truncated score-matrix can fall a hair short of 1
    return {
        "p_home": probs[0],
        "p_draw": probs[1],
        "p_away": probs[2],
        "p_over25": float(long_info["Over 2.5"]),
        "p_under25": float(long_info["Under 2.5"]),
        "p_over35": float(long_info["Over 3.5"]),
        "p_under35": float(long_info["Under 3.5"]),
    }


def forecast_round(
    round_id: str,
    elo: Optional[pd.DataFrame] = None,
    rescrape: bool = True,
    force: bool = False,
    results_path: Optional[str] = None,
    out: str = MATCH_PROBS_PATH,
) -> pd.DataFrame:
    """Forecast and lock one round's matches; append to the probs CSV.

    Re-scrapes Elo by default (``elo``/``rescrape`` override for tests). Already-locked
    matches for this round are skipped unless ``force``; the file is the durable record
    of what was predicted before each round was played. Returns the full probs frame.
    """
    if round_id not in ROUND_ORDER:
        raise ValueError(
            f"Unknown round_id {round_id!r}; expected one of {ROUND_ORDER}"
        )

    elo_df = _load_elo(elo, rescrape)
    base_df = pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv")
    fixtures = load_round_fixtures(round_id, results_path)

    existing = (
        pd.read_csv(out) if os.path.exists(out) else pd.DataFrame(columns=PROBS_COLUMNS)
    )
    if not force and not existing.empty:
        locked = set(existing["match_uid"])
        fixtures = fixtures[~fixtures["match_uid"].isin(locked)]
    if fixtures.empty:
        CON.print(f"[yellow]Round {round_id} already locked — nothing to forecast.[/]")
        return existing

    retrieved = (
        str(elo_df["retrieved_date"].iloc[0])
        if "retrieved_date" in elo_df.columns and len(elo_df)
        else ""
    )
    version = _model_version()

    rows = []
    for _, fx in fixtures.iterrows():
        pred = _predict_fixture(fx["home_team"], fx["away_team"], elo_df, base_df)
        rows.append(
            {
                "match_uid": fx["match_uid"],
                "round_id": fx["round_id"],
                "stage": fx["stage"],
                "date": fx["date"],
                "home_team": fx["home_team"],
                "away_team": fx["away_team"],
                **pred,
                "elo_retrieved_date": retrieved,
                "model_version": version,
            }
        )

    new_df = pd.DataFrame(rows, columns=PROBS_COLUMNS)
    combined = (
        pd.concat([existing, new_df], ignore_index=True)
        if not existing.empty
        else new_df
    )
    combined.to_csv(out, index=False)
    CON.print(f"[green]Locked {len(new_df)} match(es) for round {round_id}[/] → {out}")
    return combined


def forecast_next_round(
    rescrape: bool = True,
    results_path: Optional[str] = None,
    out: str = MATCH_PROBS_PATH,
) -> pd.DataFrame:
    """Forecast the earliest round not yet locked whose fixtures are resolvable.

    Walks ``ROUND_ORDER`` and forecasts the first round with no locked probabilities;
    for knockout rounds this naturally waits until the feed has resolved its matchups
    (otherwise :func:`load_round_fixtures` raises and we surface it).
    """
    locked_rounds: set[str] = set()
    if os.path.exists(out):
        prev = pd.read_csv(out)
        locked_rounds = set(prev["round_id"].unique())

    for round_id in ROUND_ORDER:
        if round_id in locked_rounds:
            continue
        return forecast_round(
            round_id, rescrape=rescrape, results_path=results_path, out=out
        )

    CON.print("[green]All rounds already locked.[/]")
    return pd.read_csv(out)
