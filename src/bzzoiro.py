"""Fetch live WC2026 results from the bzzoiro API into a single ``data/raw`` CSV.

bzzoiro (``https://sports.bzzoiro.com/api/v2/``) is a free, instant football feed and the
single source of truth for the rolling forecaster's results ingestion: it carries resolved
knockout matchups, finalized scorelines, and — crucially — extra-time and penalty-shootout
breakdowns, so knockout winners are fully derivable without us reconstructing the bracket.

``league_id=27`` spans *every* World Cup edition (2014/2018/2022 are mixed in), so we
always pin ``season_id=188`` — WC2026, exactly 104 matches. The list endpoint returns
the identical field set as the per-event detail endpoint (no goalscorer/lineup detail
anywhere), so we page the list once (50/page, 3 calls) rather than hitting 104 ids.

:func:`write_results` is idempotent and overwrite-all: re-run it any time to refresh
``data/raw/wc26_results.csv``. Unplayed matches carry blank scores; played ones fill in.
The CSV is the canonical tidy match table the rest of the pipeline reads:
:func:`load_actual_results_csv` feeds the predictions+actuals ledger (``src/ledger.py``)
and :func:`load_resolved_fixtures_csv` feeds the round forecaster (``src/forecast.py``),
plus audit columns (HT/ET/penalty splits, status, event id) for post-tournament analysis.

The join key shared across the forecast and result sides is the orientation- and
date-independent ``match_uid`` (:func:`make_match_uid`); feed team names are canonicalized
to ``TEAM_LIST`` via :data:`TEAM_NAME_MAP` (:func:`normalize_team_names`).

Auth: the API expects the standard ``Authorization: Token <key>`` header (a header
literally named ``Token`` returns 401). The token is a secret read from the gitignored
``.env`` (``BZZOIRO_TOKEN``); it is never committed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from src.const import (
    BZZOIRO_EVENTS_URL,
    CON,
    TEAM_LIST,
    WC26_LEAGUE_ID,
    WC26_RESULTS_PATH,
    WC26_SEASON_ID,
)

# Feed ``round_name`` -> canonical round id used by the rolling forecaster. Knockout
# labels vary across editions/transcribers, so several spellings map in.
ROUND_ID_MAP: dict[str, str] = {
    "round of 32": "R32",
    "round of 16": "R16",
    "quarterfinals": "QF",
    "quarter-finals": "QF",
    "quarterfinal": "QF",
    "semifinals": "SF",
    "semi-finals": "SF",
    "semifinal": "SF",
    "final": "FINAL",
    "match for 3rd place": "BRONZE",
    "match for third place": "BRONZE",
    "third place play-off": "BRONZE",
}

GROUP_ROUNDS = {"G1", "G2", "G3"}
KNOCKOUT_ROUNDS = {"R32", "R16", "QF", "SF", "BRONZE", "FINAL"}

# Feed (source) team name -> canonical name in ``TEAM_LIST``. Identity names are omitted;
# only the spellings that differ from ours need an entry.
TEAM_NAME_MAP: dict[str, str] = {
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "USA": "United States",
    "Czech Republic": "Czechia",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
    "Curacao": "Curaçao",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}


def make_match_uid(home: str, away: str, is_knockout: bool) -> str:
    """Orientation- and date-independent join key shared by forecasts and results.

    Each unordered pair meets at most once in the group stage and at most once in the
    single-elimination bracket, so a sorted team pair tagged group-vs-knockout is unique.
    """
    a, b = sorted((home, away))
    return f"{'KO' if is_knockout else 'GRP'}|{a}|{b}"


def normalize_team_names(df: pd.DataFrame, assert_known: bool = True) -> pd.DataFrame:
    """Map feed team names to canonical ``TEAM_LIST`` names on a copy.

    Maps ``home_team``/``away_team`` (and ``winner`` if present). When ``assert_known``
    is set, raises listing any names that still fall outside ``TEAM_LIST`` — used for
    *played* matches, which can only involve real teams.
    """
    df = df.copy()
    for col in ("home_team", "away_team", "winner"):
        if col in df.columns:
            df[col] = df[col].map(
                lambda t: TEAM_NAME_MAP.get(t, t) if isinstance(t, str) else t
            )
    if assert_known:
        seen = set(df["home_team"]).union(df["away_team"])
        bad = sorted(t for t in seen if t not in TEAM_LIST)
        if bad:
            raise ValueError(f"Unmapped team names from results feed: {bad}")
    return df


# Columns written to the CSV. The leading block is the canonical tidy schema the
# ledger/validation code consumes; the trailing block is audit detail for
# post-tournament analysis.
RESULTS_COLUMNS = [
    "round",
    "round_id",
    "group",
    "date",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "winner",
    "is_knockout",
    "played",
    "match_uid",
    # audit / raw detail
    "event_id",
    "status",
    "home_score_ht",
    "away_score_ht",
    "et_home",
    "et_away",
    "pens_home",
    "pens_away",
    "is_neutral_ground",
]


def _load_token(key: str = "BZZOIRO_TOKEN") -> str:
    """Return ``key`` from the environment, loading the project-root ``.env`` first."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    token = os.environ.get(key)
    if token:
        return token.strip()
    raise RuntimeError(
        f"{key} not set. Add it to a project-root .env (see .env.example) "
        "or export it in your environment."
    )


def fetch_events(
    season_id: int = WC26_SEASON_ID, league_id: int = WC26_LEAGUE_ID
) -> list[dict]:
    """Page the events list for one season and return every raw event dict.

    Follows the API's ``next`` cursor until exhausted. Sends the token on every request
    (the ``next`` URL carries no auth of its own).
    """
    headers = {"Authorization": f"Token {_load_token()}"}
    params = {"league_id": league_id, "season_id": season_id, "limit": 50}
    url: Optional[str] = BZZOIRO_EVENTS_URL
    events: list[dict] = []
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        events.extend(payload["results"])
        url = payload.get("next")
        params = None  # the ``next`` URL already encodes league/season/limit/offset
    return events


def _pair(obj: Optional[dict]) -> tuple[Optional[int], Optional[int]]:
    """Flatten a ``{"home": int, "away": int}`` API object into a scalar pair."""
    if not obj:
        return None, None
    return obj.get("home"), obj.get("away")


def _resolve_winner(
    hs, as_, home: str, away: str, pens: Optional[dict], is_knockout: bool
) -> Optional[str]:
    """Advancing team name, decided on penalties when the scoreline is level.

    ``home_score``/``away_score`` from the feed are the decisive scoreline (after extra
    time). A level knockout is settled by ``penalty_shootout``; a level group match is a
    genuine draw (``None``). ``None`` for an unplayed match (no score).
    """
    if hs is None or as_ is None:
        return None
    if hs > as_:
        return home
    if as_ > hs:
        return away
    if is_knockout and pens:
        return home if (pens.get("home", 0) > pens.get("away", 0)) else away
    return None


def parse_events(raw: list[dict]) -> pd.DataFrame:
    """Flatten raw events into the canonical tidy schema (:data:`RESULTS_COLUMNS`).

    Team names are canonicalized to ``TEAM_LIST`` (unresolved bracket placeholders such
    as ``W73``/``1A``/``3A/3B/...`` are left as-is — they're dropped by
    :func:`load_resolved_fixtures_csv`). Group stage uses ``round_number`` as the
    matchday (``G1``/``G2``/``G3``); knockout uses ``round_name`` via :data:`BZ_ROUND_MAP`.
    """
    rows = []
    for e in raw:
        group_name = e.get("group_name")
        is_knockout = group_name is None
        group = group_name.replace("Group ", "") if group_name else None
        if is_knockout:
            round_id = ROUND_ID_MAP.get(str(e.get("round_name", "")).strip().lower())
        else:
            round_id = f"G{e.get('round_number')}"
        home, away = e.get("home_team"), e.get("away_team")
        hs, as_ = e.get("home_score"), e.get("away_score")
        et_home, et_away = _pair(e.get("extra_time_score"))
        pens_home, pens_away = _pair(e.get("penalty_shootout"))
        played = e.get("status") == "finished" and hs is not None
        rows.append(
            {
                "round": str(e.get("round_name") or "").strip(),
                "round_id": round_id,
                "group": group,
                "date": str(e.get("event_date") or "")[:10],
                "home_team": home,
                "away_team": away,
                "home_score": hs,
                "away_score": as_,
                "winner": _resolve_winner(
                    hs, as_, home, away, e.get("penalty_shootout"), is_knockout
                ),
                "is_knockout": is_knockout,
                "played": played,
                "event_id": e.get("id"),
                "status": e.get("status"),
                "home_score_ht": e.get("home_score_ht"),
                "away_score_ht": e.get("away_score_ht"),
                "et_home": et_home,
                "et_away": et_away,
                "pens_home": pens_home,
                "pens_away": pens_away,
                "is_neutral_ground": e.get("is_neutral_ground"),
            }
        )
    df = pd.DataFrame(rows)
    # Canonicalize names (placeholders pass through); a played match can only involve
    # real teams, so any unmapped *played* name is a mapping gap worth surfacing.
    df = normalize_team_names(df, assert_known=False)
    if not df.empty and df["played"].any():
        normalize_team_names(df[df["played"]], assert_known=True)
    df["match_uid"] = [
        make_match_uid(h, a, ko)
        for h, a, ko in zip(df["home_team"], df["away_team"], df["is_knockout"])
    ]
    return df[RESULTS_COLUMNS]


def write_results(out: str = WC26_RESULTS_PATH) -> pd.DataFrame:
    """Fetch + parse the full WC26 season and overwrite ``out``. Returns the frame."""
    df = parse_events(fetch_events())
    df = df.sort_values(by="date")
    df.to_csv(out, index=False)
    n_played = int(df["played"].sum())
    unresolved = int(
        (
            (df["played"])
            & (df["home_score"] == df["away_score"])
            & df["winner"].isna()
        ).sum()
    )
    CON.print(
        f"[green]bzzoiro:[/] wrote {len(df)} WC26 matches to {out} "
        f"({n_played} played)."
        + (
            f" [yellow]{unresolved} level result(s) with no winner.[/]"
            if unresolved
            else ""
        )
    )
    return df


def load_actual_results_csv(path: str = WC26_RESULTS_PATH) -> pd.DataFrame:
    """Finalized matches only — the actual-results side of the ledger.

    Played rows with integer scores, canonical names, and a ``match_uid`` join key. An
    empty result yields an empty frame carrying ``match_uid`` so the ledger's left-join
    still works.
    """
    df = pd.read_csv(path)
    df = df[df["played"].astype(bool)].copy()
    if df.empty:
        df["match_uid"] = pd.Series(dtype=str)
        return df.reset_index(drop=True)
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    return df.reset_index(drop=True)


def load_resolved_fixtures_csv(path: str = WC26_RESULTS_PATH) -> pd.DataFrame:
    """All matches whose two teams are already known (played or not).

    Rows with an unresolved bracket placeholder on either side are dropped (the natural
    "not forecastable yet" signal). Used by ``src/forecast.py`` to read upcoming
    knockout matchups.
    """
    df = pd.read_csv(path)
    teams = set(TEAM_LIST)
    df = df[df["home_team"].isin(teams) & df["away_team"].isin(teams)].copy()
    df["played"] = df["played"].astype(bool)
    return df.reset_index(drop=True)
