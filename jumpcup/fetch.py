"""bzzoiro fetch + cache layer for the Jump Probability Cup pipeline.

Everything the rates stage needs for one match is collected by
:func:`fetch_match_bundle`: the WC26 event, both lineups, each lineup player's
per-match stat history, and each team's recent finished-match team stats (the
corners/offsides fallback source). Roughly 65 API calls on a cold cache (~30 s with
the politeness sleep); reruns are free — every response is cached as JSON under
``jumpcup/data/raw/`` and only refetched with ``refresh=True``.

Two API quirks drive the design here:

- The player ids inside ``events/{id}/lineups/`` are a *different namespace* from the
  canonical ``/players/`` ids (e.g. lineup id 990408 for Raúl Rangel 404s on
  ``/players/``; his real id is 10161). Lineup players are therefore joined to the
  ``players/?national_team_id=`` squad by accent-stripped name
  (:func:`resolve_lineup_ids`); ``?search=`` is ignored by the API and cannot help.
- ``players/{id}/stats/`` rows carry no dates (only ``event_id``), so "current
  season" is approximated downstream by taking the most recent N rows.

Auth reuses :func:`src.bzzoiro._load_token` (``Authorization: Token <BZZOIRO_TOKEN>``
from the gitignored ``.env``).
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from jumpcup.const import BZZOIRO_API_BASE, JUMPCUP_RAW_PATH
from src.bzzoiro import TEAM_NAME_MAP, _load_token
from src.const import CON, TEAM_LIST, WC26_LEAGUE_ID, WC26_SEASON_ID

REQUEST_SLEEP_S = 0.4  # politeness between live calls; cache hits skip it
TEAM_STATS_WINDOW_DAYS = 365  # corners/offsides fallback looks back this far


def _get(url: str, params: Optional[dict] = None) -> dict:
    headers = {"Authorization": f"Token {_load_token()}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(REQUEST_SLEEP_S)
    return resp.json()


def _paged(url: str, params: Optional[dict] = None) -> list[dict]:
    """Follow the API's ``next`` cursor until exhausted (same pattern as src/bzzoiro)."""
    results: list[dict] = []
    next_url: Optional[str] = url
    while next_url:
        payload = _get(next_url, params)
        results.extend(payload["results"])
        next_url = payload.get("next")
        params = None  # the ``next`` URL already encodes the query
    return results


def _cached(rel_path: str, fetch: Callable[[], Any], refresh: bool = False) -> Any:
    path = Path(JUMPCUP_RAW_PATH) / rel_path
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


# ---------------------------------------------------------------------------
# Event / lineup / squad fetching
# ---------------------------------------------------------------------------


def fetch_wc26_events(refresh: bool = False) -> list[dict]:
    return _cached(
        "wc26_events.json",
        lambda: _paged(
            f"{BZZOIRO_API_BASE}/events/",
            {"league_id": WC26_LEAGUE_ID, "season_id": WC26_SEASON_ID, "limit": 50},
        ),
        refresh,
    )


def _canon(feed_name: Optional[str]) -> Optional[str]:
    """Feed team name -> our canonical TEAM_LIST name."""
    if not isinstance(feed_name, str):
        return feed_name
    return TEAM_NAME_MAP.get(feed_name, feed_name)


def resolve_wc26_event(
    team_a: Optional[str] = None,
    team_b: Optional[str] = None,
    event_id: Optional[int] = None,
    refresh: bool = False,
) -> dict:
    """Find the WC26 event by id or by (canonical) team pair.

    Team A/B orientation downstream is the feed's home/away. Raises if not found
    (after one forced refresh of the events cache).
    """
    events = fetch_wc26_events(refresh)
    if event_id is not None:
        for e in events:
            if e["id"] == event_id:
                return e
        if not refresh:
            return resolve_wc26_event(event_id=event_id, refresh=True)
        raise ValueError(f"WC26 event {event_id} not found")
    pair = {team_a, team_b}
    hits = [
        e
        for e in events
        if {_canon(e.get("home_team")), _canon(e.get("away_team"))} == pair
    ]
    if not hits:
        if not refresh:
            return resolve_wc26_event(team_a, team_b, refresh=True)
        raise ValueError(f"No WC26 event found for {team_a} vs {team_b}")
    # A pair can meet once in groups and once in the bracket: prefer the unplayed one.
    unplayed = [e for e in hits if e.get("status") != "finished"]
    return sorted(unplayed or hits, key=lambda e: e["event_date"])[0]


def upcoming_matches(n: int = 3, refresh: bool = True) -> list[dict]:
    """The next ``n`` unstarted WC26 matches whose teams are already known.

    Refreshes the events cache by default (3 cheap calls) so finished matches and
    freshly resolved knockout matchups are reflected. Bracket placeholders
    (``W101``/``1A``) are skipped — those matchups aren't forecastable yet.
    """
    events = fetch_wc26_events(refresh)
    known = {*TEAM_LIST}
    fixtures = [
        e
        for e in events
        if e.get("status") == "notstarted"
        and _canon(e.get("home_team")) in known
        and _canon(e.get("away_team")) in known
    ]
    return sorted(fixtures, key=lambda e: e["event_date"])[:n]


def fetch_lineups(event_id: int, refresh: bool = False) -> dict:
    data = _cached(
        f"events/{event_id}/lineups.json",
        lambda: _get(f"{BZZOIRO_API_BASE}/events/{event_id}/lineups/"),
        refresh,
    )
    if data.get("lineup_status") != "confirmed":
        CON.print(
            f"[yellow]jumpcup:[/] lineup for event {event_id} is "
            f"'{data.get('lineup_status')}' (not confirmed) — proceeding anyway. "
            "Re-run with --refresh closer to kickoff."
        )
    return data


def fetch_odds(event_id: int, refresh: bool = False) -> dict:
    return _cached(
        f"events/{event_id}/odds.json",
        lambda: _get(f"{BZZOIRO_API_BASE}/events/{event_id}/odds/"),
        refresh,
    )


def fetch_squad(team_id: int, refresh: bool = False) -> list[dict]:
    return _cached(
        f"teams/{team_id}/squad.json",
        lambda: _paged(
            f"{BZZOIRO_API_BASE}/players/",
            {"national_team_id": team_id, "limit": 100},
        ),
        refresh,
    )


# ---------------------------------------------------------------------------
# Lineup -> squad name resolution
# ---------------------------------------------------------------------------


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def _abbrev_matches(short: str, full: str) -> bool:
    """True when every token of the shorter name prefixes a token of the longer,
    in order ("r rangel" -> "raul rangel")."""
    short_toks, full_toks = short.split(), full.split()
    if len(short_toks) > len(full_toks):
        short_toks, full_toks = full_toks, short_toks
    i = 0
    for tok in short_toks:
        while i < len(full_toks) and not full_toks[i].startswith(tok):
            i += 1
        if i == len(full_toks):
            return False
        i += 1
    return True


def resolve_lineup_ids(
    lineup_players: list[dict], squad: list[dict]
) -> tuple[list[dict], list[str]]:
    """Join lineup players (foreign id namespace) to squad rows by name.

    Returns (resolved, unmatched_names). Each resolved entry keeps the lineup's
    name/position/jersey and gains the canonical ``player_id``.
    """
    by_norm = {_norm_name(p["name"]): p for p in squad}
    resolved, unmatched = [], []
    for lp in lineup_players:
        norm = _norm_name(lp["name"])
        hit = by_norm.get(norm)
        if hit is None:
            cands = [p for p in squad if _abbrev_matches(norm, _norm_name(p["name"]))]
            if len(cands) > 1:
                same_jersey = [
                    p
                    for p in cands
                    if p.get("jersey_number") == lp.get("jersey_number")
                ]
                cands = same_jersey or cands
            if len(cands) > 1:
                same_pos = [p for p in cands if p.get("position") == lp.get("position")]
                cands = same_pos or cands
            if len(cands) != 1:
                last = norm.split()[-1]
                cands = [p for p in squad if _norm_name(p["name"]).split()[-1] == last]
            hit = cands[0] if len(cands) == 1 else None
        if hit is None:
            unmatched.append(lp["name"])
            continue
        resolved.append(
            {
                "name": lp["name"],
                "player_id": hit["id"],
                "position": lp.get("position"),
                "jersey_number": lp.get("jersey_number"),
            }
        )
    return resolved, unmatched


# ---------------------------------------------------------------------------
# Stats fetching
# ---------------------------------------------------------------------------


def fetch_player_match_rows(player_id: int, refresh: bool = False) -> list[dict]:
    """All per-match stat rows for a player (newest first per the API). Undated."""
    return _cached(
        f"players/{player_id}.json",
        lambda: _paged(f"{BZZOIRO_API_BASE}/players/{player_id}/stats/", {"limit": 50}),
        refresh,
    )


def _unwrap_stat(v: Any) -> Optional[float]:
    """Team match stats mix scalars with ``{"value": .., "total": .., "pct": ..}``."""
    if isinstance(v, dict):
        return v.get("value")
    return v


def fetch_team_recent_team_stats(
    team_id: int,
    as_of: date,
    window_days: int = TEAM_STATS_WINDOW_DAYS,
    refresh: bool = False,
) -> list[dict]:
    """Team-level match stats for the team's finished matches in the past year.

    One row per finished match with stats coverage:
    ``{event_id, date, for: {stat: val}, against: {stat: val}}`` where for/against
    are the team's own and the opponent's side of ``events/{id}/stats/``. Matches
    whose stats feed is empty (uncovered friendlies) are skipped.
    """
    events = _cached(
        f"teams/{team_id}/events.json",
        lambda: _paged(
            f"{BZZOIRO_API_BASE}/events/", {"team_id": team_id, "limit": 50}
        ),
        refresh,
    )
    since = (as_of - timedelta(days=window_days)).isoformat()
    rows = []
    for e in events:
        if e.get("status") != "finished":
            continue
        e_date = str(e.get("event_date") or "")[:10]
        if not (since <= e_date <= as_of.isoformat()):
            continue
        stats = _cached(
            f"events/{e['id']}/stats.json",
            lambda eid=e["id"]: _get(f"{BZZOIRO_API_BASE}/events/{eid}/stats/"),
            refresh,
        )
        side = "home" if e.get("home_team_id") == team_id else "away"
        other = "away" if side == "home" else "home"
        own = stats.get("stats", {}).get(side) or {}
        opp = stats.get("stats", {}).get(other) or {}
        if "corner_kicks" not in own:  # no stats coverage for this match
            continue
        rows.append(
            {
                "event_id": e["id"],
                "date": e_date,
                "for": {k: _unwrap_stat(v) for k, v in own.items()},
                "against": {k: _unwrap_stat(v) for k, v in opp.items()},
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass
class SideBundle:
    team_key: str  # "A" (feed home) | "B" (feed away)
    team_name: str  # canonical TEAM_LIST name
    team_id: int
    formation: str
    players: list[dict]  # resolved lineup: name, player_id, position, jersey_number
    unmatched: list[str]
    player_rows: dict[int, list[dict]] = field(default_factory=dict)
    team_stat_rows: list[dict] = field(default_factory=list)


@dataclass
class MatchBundle:
    event: dict
    event_id: int
    lineup_status: str
    a: SideBundle
    b: SideBundle


def fetch_match_bundle(
    team_a: Optional[str] = None,
    team_b: Optional[str] = None,
    event_id: Optional[int] = None,
    refresh: bool = False,
) -> MatchBundle:
    """Fetch everything the rates stage needs for one WC26 match.

    Team A is the feed's home side, team B the away side (regardless of the
    argument order used for lookup).
    """
    event = resolve_wc26_event(team_a, team_b, event_id, refresh)
    eid = event["id"]
    lineups = fetch_lineups(eid, refresh)
    match_date = date.fromisoformat(str(event["event_date"])[:10])

    sides = []
    for key, feed_side in (("A", "home"), ("B", "away")):
        lu = lineups["lineups"][feed_side]
        squad = fetch_squad(lu["team_id"], refresh)
        resolved, unmatched = resolve_lineup_ids(lu["players"], squad)
        if unmatched:
            CON.print(
                f"[yellow]jumpcup:[/] {lu['team_name']}: could not resolve lineup "
                f"player(s) {unmatched} against the squad — excluded from rates "
                "(coverage rescale compensates)."
            )
        side = SideBundle(
            team_key=key,
            team_name=_canon(lu["team_name"]),
            team_id=lu["team_id"],
            formation=lu.get("formation", ""),
            players=resolved,
            unmatched=unmatched,
        )
        for p in resolved:
            side.player_rows[p["player_id"]] = fetch_player_match_rows(
                p["player_id"], refresh
            )
        side.team_stat_rows = fetch_team_recent_team_stats(
            lu["team_id"], as_of=match_date, refresh=refresh
        )
        sides.append(side)

    bundle = MatchBundle(
        event=event,
        event_id=eid,
        lineup_status=lineups.get("lineup_status", "unknown"),
        a=sides[0],
        b=sides[1],
    )
    CON.print(
        f"[green]jumpcup:[/] bundle for event {eid}: "
        f"{bundle.a.team_name} (A/home) vs {bundle.b.team_name} (B/away), "
        f"lineups '{bundle.lineup_status}', "
        f"team-stats matches: {len(bundle.a.team_stat_rows)}/{len(bundle.b.team_stat_rows)}."
    )
    return bundle
