"""Monte Carlo simulation of the 2026 FIFA World Cup.

The engine is layered so each piece is independently testable:

    match  -> group  -> third-place ranking + bracket  -> knockout  -> tournament

`run_tournament` plays one full tournament (48 teams) and returns the furthest
stage each team reached; `monte_carlo` repeats it N times and aggregates
stage-by-stage advancement probabilities. Per the development plan, Elo ratings
are updated after every simulated match within an iteration.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from typing import Optional

import numpy as np
import pandas as pd

from model.rates import independent_rates, nested_rates
from src.brackets import (
    assign_third_place_slots,
    load_third_place_map,
    rank_third_placed,
)
from src.const import (
    CLEANED_DATA_PATH,
    CON,
    CUSTOM_PROGRESS,
    FORECAST_PATH,
    GROUPPING,
    RAW_DATA_PATH,
    TEAM_LIST,
)

# ── Tunable constants ───────────────────────────────────────────────────────
ELO_GAP_THRESHOLD = (
    50.0  # below this Elo gap, use the independent model (changelog note)
)
K_FACTOR = 60.0  # Elo update K for World Cup matches (eloratings.net convention)
HOME_ADVANTAGE = 100.0  # Elo points added to a host playing at home (eloratings.net)
PEN_SLOPE = (
    600.0  # flattened logistic slope for penalty shootouts (README: /600 not /400)
)
ET_SCALE = 1.0 / 3.0  # extra time is 30 min ~= 1/3 of regulation
MAX_LAMBDA = 15.0  # cap on per-team expected goals; the nested model can otherwise
# blow up (exp of a large exponent) for sparse teams. A rate above ~15 is nonsensical.

# Maps a wc26_knockout_matches.csv stage_id to a stage label. stage_id 6 is the
# third-place play-off; it is labelled "SF" so reaching it never bumps a team's
# furthest stage above the semi-final it lost.
STAGE_LABEL = {2: "R32", 3: "R16", 4: "QF", 5: "SF", 6: "SF", 7: "FINAL"}


@dataclass(frozen=True)
class TournamentFormat:
    """Stage bookkeeping for a tournament shape (48-team WC2026 vs legacy 32-team).

    ``stage_order`` ranks the furthest-stage labels; ``cum_stages`` are the
    stages reported as cumulative reach-probabilities; ``final_match`` is the
    match number whose winner is champion; ``has_third_place`` toggles the
    best-third-placed-team qualification path (absent in the 32-team format).
    """

    stage_order: dict[str, int]
    cum_stages: list[str]
    final_match: int
    has_third_place: bool


WC2026_FORMAT = TournamentFormat(
    stage_order={
        "GROUP": 0,
        "R32": 1,
        "R16": 2,
        "QF": 3,
        "SF": 4,
        "FINAL": 5,
        "CHAMPION": 6,
    },
    cum_stages=["R32", "R16", "QF", "SF", "FINAL", "CHAMPION"],
    final_match=104,  # match_number of the final in wc26_knockout_matches.csv
    has_third_place=True,
)

# Legacy 32-team World Cup (2018, 2022): eight groups of four, top two advance
# straight to the Round of 16, no third-placed qualifiers.
LEGACY_FORMAT = TournamentFormat(
    stage_order={
        "GROUP": 0,
        "R16": 1,
        "QF": 2,
        "SF": 3,
        "FINAL": 4,
        "CHAMPION": 5,
    },
    cum_stages=["R16", "QF", "SF", "FINAL", "CHAMPION"],
    final_match=64,  # match_number of the final in the legacy bracket
    has_third_place=False,
)


def _draw(lam: float, rng: np.random.Generator) -> int:
    """Poisson draw with the expected-goals rate clamped to a sane maximum."""
    return int(rng.poisson(min(max(lam, 0.0), MAX_LAMBDA)))


# ── Inputs bundle ───────────────────────────────────────────────────────────
@dataclass
class SimInputs:
    elo0: dict[str, float]  # pre-tournament Elo per team
    base: dict[str, dict]  # baseline (attack/defense) params per team
    nested: dict[str, Optional[dict]]  # nested params per team (None if unfit)
    # group letter -> [(home, away, host_country)]; host_country is None at a
    # neutral venue (no host nation playing there).
    group_fixtures: dict[str, list[tuple[str, str, Optional[str]]]]
    knockout: list[dict]  # ordered: {num, stage_label, slot_a, slot_b, host_country}
    third_place_table: Optional[dict[frozenset[str], dict[str, str]]]
    teams: list[str]
    fmt: TournamentFormat = WC2026_FORMAT
    use_nested: bool = False  # default to the independent model (see load_sim_inputs)


def load_sim_inputs(use_nested: bool = False) -> SimInputs:
    """Load all simulation inputs.

    The nested model is **off by default**: it is fit on very small samples for
    strong teams (who are rarely the weaker side), and ~1/3 of teams have an
    implausible opponent-Elo sign (`e_a >= 0`, i.e. the weaker team modelled as
    scoring *more* against stronger opponents). Those teams are dropped from the
    nested model regardless, so that `use_nested=True` only applies it where the
    fit is sane. The independent bivariate-Poisson model is the safe default.
    """
    elo_df = pd.read_csv(f"{RAW_DATA_PATH}/elo_latest.csv")
    elo0 = dict(zip(elo_df["team"], elo_df["elo_ratings"].astype(float)))

    base_df = pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv")
    base = base_df.set_index("team").to_dict("index")

    nested_df = pd.read_csv(f"{CLEANED_DATA_PATH}/nested_params.csv")
    nested: dict[str, Optional[dict]] = {}
    for team, row in nested_df.set_index("team").to_dict("index").items():
        unfit = pd.isna(row.get("intercept")) or not row.get("samples")
        implausible = pd.isna(row.get("e_a")) or row["e_a"] >= 0
        nested[team] = None if (unfit or implausible) else row

    group_df = pd.read_csv(f"{CLEANED_DATA_PATH}/wc26_groupstage_matches.csv")
    group_fixtures: dict[str, list[tuple[str, str, Optional[str]]]] = {}
    for _, r in group_df.iterrows():
        letter = r["match_label"].replace("Group ", "").strip()
        host = r["host_country"] if pd.notna(r["host_country"]) else None
        group_fixtures.setdefault(letter, []).append(
            (r["home_team"], r["away_team"], host)
        )

    ko_df = pd.read_csv(f"{CLEANED_DATA_PATH}/wc26_knockout_matches.csv")
    knockout = []
    for _, r in ko_df.iterrows():
        slot_a, slot_b = (s.strip() for s in r["match_label"].split(" vs "))
        knockout.append(
            {
                "num": int(r["match_number"]),
                "stage_label": STAGE_LABEL[int(r["stage_id"])],
                "slot_a": slot_a,
                "slot_b": slot_b,
                "host_country": (
                    r["host_country"] if pd.notna(r["host_country"]) else None
                ),
            }
        )
    knockout.sort(key=lambda m: m["num"])

    missing = [t for t in TEAM_LIST if t not in elo0 or t not in base]
    if missing:
        raise ValueError(f"Missing Elo/baseline params for: {missing}")

    return SimInputs(
        elo0=elo0,
        base=base,
        nested=nested,
        group_fixtures=group_fixtures,
        knockout=knockout,
        third_place_table=load_third_place_map(),
        teams=list(TEAM_LIST),
        fmt=WC2026_FORMAT,
        use_nested=use_nested,
    )


def build_legacy_sim_inputs(
    groups: dict[str, list[str]],
    knockout: list[dict],
    base: dict[str, dict],
    elo0: dict[str, float],
    nested: Optional[dict[str, Optional[dict]]] = None,
    host_country: Optional[str] = None,
) -> SimInputs:
    """Assemble :class:`SimInputs` for a legacy 32-team World Cup (2018/2022).

    ``groups`` maps a group letter to its four teams; round-robin fixtures are
    generated from each group (the legacy bracket only cares about final
    standings, not match order). ``knockout`` is the ordered R16→Final slot list
    (``{num, stage_label, slot_a, slot_b}``). ``base``/``elo0`` are the
    cutoff-refit baseline params and pre-tournament Elo. The nested model is off
    for backtests unless ``nested`` is supplied. No third-place table is used.
    ``host_country`` (e.g. "Russia" 2018, "Qatar" 2022) plays every match at home,
    so it is stamped on all fixtures and knockout ties.
    """
    group_fixtures = {
        letter: [(h, a, host_country) for h, a in combinations(teams, 2)]
        for letter, teams in groups.items()
    }
    knockout = [{**m, "host_country": host_country} for m in knockout]
    teams = [t for group in groups.values() for t in group]
    missing = [t for t in teams if t not in elo0 or t not in base]
    if missing:
        raise ValueError(f"Missing Elo/baseline params for: {missing}")

    return SimInputs(
        elo0=dict(elo0),
        base=base,
        nested=nested or {t: None for t in teams},
        group_fixtures=group_fixtures,
        knockout=knockout,
        third_place_table=None,
        teams=teams,
        fmt=LEGACY_FORMAT,
        use_nested=nested is not None,
    )


# ── Layer 1: match ──────────────────────────────────────────────────────────
def _home_bonus(
    team_a: str, team_b: str, host_country: Optional[str]
) -> tuple[float, float]:
    """Home-advantage Elo bonus (points_a, points_b) for the team playing at home.

    ``host_country`` is the nation the match venue sits in (from the fixture data
    for WC2026, or the single host of a legacy backtest). Whichever side *is* that
    nation gets the bonus; if neither does — or there is no host — it is a neutral
    venue and both bonuses are zero.
    """
    if host_country is None:
        return 0.0, 0.0
    if team_a == host_country:
        return HOME_ADVANTAGE, 0.0
    if team_b == host_country:
        return 0.0, HOME_ADVANTAGE
    return 0.0, 0.0


def _update_elo(
    a: str,
    b: str,
    ga: int,
    gb: int,
    elo: dict[str, float],
    ba: float = 0.0,
    bb: float = 0.0,
) -> None:
    """Standard (World Football Elo) update with a goal-difference multiplier.

    Mutates `elo` in place. `ba`/`bb` are home-advantage bonuses folded into the
    rating difference for the win expectancy `w_e` only — the stored ratings are
    the real (pre-match) values, so the bonus never persists. A shootout-decided
    knockout is passed here as the drawn aggregate scoreline, so penalties do not
    move the ratings.
    """
    ra, rb = elo[a], elo[b]
    w = 1.0 if ga > gb else 0.0 if ga < gb else 0.5
    dr = (ra + ba) - (rb + bb)  # rating diff incl. home advantage
    w_e = 1.0 / (1.0 + 10 ** (-dr / 400.0))
    margin = abs(ga - gb)
    g = 1.0 if margin <= 1 else 1.5 if margin == 2 else 1 + (0.75 + (margin - 3) / 8)
    delta = K_FACTOR * g * (w - w_e)
    elo[a] = ra + delta
    elo[b] = rb - delta


def _sample_regulation(
    team_a: str,
    team_b: str,
    elo: dict,
    inputs: SimInputs,
    rng: np.random.Generator,
    ba: float = 0.0,
    bb: float = 0.0,
) -> tuple[int, int]:
    """Sample a regulation scoreline (goals for team_a, team_b).

    `ba`/`bb` are home-advantage Elo bonuses added to each side's rating before
    deriving the Poisson rates, so a host scores more / concedes less at home.
    Uses the nested model for clearly mismatched sides (and when the weaker team
    has fitted nested params), otherwise the independent bivariate-Poisson model.
    """
    eff = {team_a: elo[team_a] + ba, team_b: elo[team_b] + bb}
    ea, eb = eff[team_a], eff[team_b]
    strong, weak = (team_a, team_b) if ea >= eb else (team_b, team_a)
    nested_weak = inputs.nested.get(weak) if inputs.use_nested else None

    if abs(ea - eb) < ELO_GAP_THRESHOLD or nested_weak is None:
        lam_a, lam_b = independent_rates(
            ea, eb, inputs.base[team_a], inputs.base[team_b]
        )
        return _draw(lam_a, rng), _draw(lam_b, rng)

    lam_strong, lam_weak_fn = nested_rates(
        eff[strong], eff[weak], inputs.base[strong], inputs.base[weak], nested_weak
    )
    g_strong = _draw(lam_strong, rng)
    g_weak = _draw(lam_weak_fn(g_strong), rng)
    return (g_strong, g_weak) if strong == team_a else (g_weak, g_strong)


def _sample_extra_time(
    team_a: str,
    team_b: str,
    elo: dict,
    inputs: SimInputs,
    rng: np.random.Generator,
    ba: float = 0.0,
    bb: float = 0.0,
) -> tuple[int, int]:
    """Extra time: independent Poisson at 1/3 of regulation intensity."""
    lam_a, lam_b = independent_rates(
        elo[team_a] + ba, elo[team_b] + bb, inputs.base[team_a], inputs.base[team_b]
    )
    return _draw(lam_a * ET_SCALE, rng), _draw(lam_b * ET_SCALE, rng)


def play_match(
    team_a: str,
    team_b: str,
    elo: dict,
    inputs: SimInputs,
    rng: np.random.Generator,
    *,
    knockout: bool = False,
    host_country: Optional[str] = None,
) -> dict:
    """Play one match, updating `elo` in place. Returns goals + winner/loser.

    For group matches a draw is a valid result (winner/loser are None). For
    knockout matches a draw goes to extra time, then a penalty shootout decided
    by an Elo-tilted coin flip with a flattened slope. ``host_country`` (the
    nation the venue is in) grants the home side a one-match Elo bonus.
    """
    ba, bb = _home_bonus(team_a, team_b, host_country)
    ga, gb = _sample_regulation(team_a, team_b, elo, inputs, rng, ba, bb)

    if knockout and ga == gb:
        eta, etb = _sample_extra_time(team_a, team_b, elo, inputs, rng, ba, bb)
        ga, gb = ga + eta, gb + etb

    # Effective (home-adjusted) pre-update ratings, for the shootout tilt.
    ea_pre, eb_pre = elo[team_a] + ba, elo[team_b] + bb
    _update_elo(team_a, team_b, ga, gb, elo, ba, bb)

    winner = loser = None
    if ga > gb:
        winner, loser = team_a, team_b
    elif gb > ga:
        winner, loser = team_b, team_a
    elif knockout:
        p_a = 1.0 / (1.0 + 10 ** (-(ea_pre - eb_pre) / PEN_SLOPE))
        winner, loser = (team_a, team_b) if rng.random() < p_a else (team_b, team_a)

    return {
        "a": team_a,
        "b": team_b,
        "ga": ga,
        "gb": gb,
        "winner": winner,
        "loser": loser,
    }


# ── Layer 2: group ──────────────────────────────────────────────────────────
def _h2h_key(team: str, subset: set[str], results: list[dict]) -> tuple[int, int, int]:
    """Head-to-head (points, gd, gf) for `team` restricted to matches among `subset`."""
    pts = gd = gf = 0
    for m in results:
        if m["a"] in subset and m["b"] in subset:
            if m["a"] == team:
                gf += m["ga"]
                gd += m["ga"] - m["gb"]
                pts += 3 if m["ga"] > m["gb"] else 1 if m["ga"] == m["gb"] else 0
            elif m["b"] == team:
                gf += m["gb"]
                gd += m["gb"] - m["ga"]
                pts += 3 if m["gb"] > m["ga"] else 1 if m["gb"] == m["ga"] else 0
    return (pts, gd, gf)


def simulate_group(
    letter: str, inputs: SimInputs, elo: dict, rng: np.random.Generator
) -> tuple[list[str], dict[str, dict]]:
    """Play a group's 6 fixtures and rank the 4 teams. Returns (ranked_teams, stats)."""
    stats: dict[str, dict] = {}
    for home, away, _ in inputs.group_fixtures[letter]:
        for t in (home, away):
            stats.setdefault(t, {"pts": 0, "gf": 0, "ga": 0, "gd": 0})

    results: list[dict] = []
    for home, away, host in inputs.group_fixtures[letter]:
        m = play_match(home, away, elo, inputs, rng, knockout=False, host_country=host)
        results.append(m)
        hs, as_ = stats[home], stats[away]
        hs["gf"] += m["ga"]
        hs["ga"] += m["gb"]
        as_["gf"] += m["gb"]
        as_["ga"] += m["ga"]
        if m["ga"] > m["gb"]:
            hs["pts"] += 3
        elif m["gb"] > m["ga"]:
            as_["pts"] += 3
        else:
            hs["pts"] += 1
            as_["pts"] += 1
    for s in stats.values():
        s["gd"] = s["gf"] - s["ga"]

    # FIFA order: points -> GD -> GF -> head-to-head -> (Elo/random fallback).
    teams = list(stats)

    def primary(t):
        return (stats[t]["pts"], stats[t]["gd"], stats[t]["gf"])

    teams.sort(key=lambda t: (primary(t), elo[t], rng.random()), reverse=True)

    ranked: list[str] = []
    i = 0
    while i < len(teams):
        j = i
        while j + 1 < len(teams) and primary(teams[j + 1]) == primary(teams[i]):
            j += 1
        cluster = teams[i : j + 1]
        if len(cluster) > 1:
            subset = set(cluster)
            cluster.sort(
                key=lambda t: (_h2h_key(t, subset, results), elo[t], rng.random()),
                reverse=True,
            )
        ranked.extend(cluster)
        i = j + 1

    return ranked, stats


# ── Layer 4: knockout ───────────────────────────────────────────────────────
def _resolve_slot(
    token: str,
    match: dict,
    group_results: dict[str, dict[int, str]],
    assignment: dict[str, str],
    winners: dict[int, str],
    losers: dict[int, str],
) -> str:
    """Resolve a knockout slot token to a concrete team."""
    if token.startswith("W"):
        return winners[int(token[1:])]
    if token.startswith("RU"):
        return losers[int(token[2:])]
    if token[0] == "3":  # third-place slot: opponent is the paired group winner
        other = match["slot_b"] if token == match["slot_a"] else match["slot_a"]
        winner_group = other[1:]  # e.g. "1E" -> "E"
        third_group = assignment[winner_group]
        return group_results[third_group][3]
    # "1A" / "2B": position then group letter
    return group_results[token[1:]][int(token[0])]


def simulate_knockout(
    inputs: SimInputs,
    group_results: dict[str, dict[int, str]],
    assignment: dict[str, str],
    elo: dict,
    rng: np.random.Generator,
    stage_reached: dict[str, str],
    goals: Optional[dict[str, dict]] = None,
    r32_slots: Optional[dict[str, Counter]] = None,
    opponent_at_stage: Optional[dict[str, dict[str, Counter]]] = None,
    eliminations: Optional[Counter] = None,
) -> str:
    """Play all knockout matches in order. Returns the champion.

    When ``goals`` is supplied, each side's goals-for/against and a match count
    are accumulated into the pooled knockout bucket (``k_gf``/``k_ga``/``k_n``).
    Extra-time goals are already folded into the scoreline; shootout wins leave
    it drawn, so penalties contribute no goals. The third-place play-off counts
    as a knockout match (a small share of all knockout ties).

    Three optional projection accumulators (caller-owned, so they persist across
    simulations) capture per-sim bracket detail the headline reach-probabilities
    discard:

    - ``r32_slots[slot_token] -> Counter(team)`` tallies which team filled each
      Round-of-32 slot (e.g. ``"1A"``, ``"3ABCDF"``).
    - ``opponent_at_stage[team][stage] -> Counter(opponent)`` tallies who each
      team faced at each knockout stage.
    - ``eliminations[(winner, loser)]`` tallies knockout eliminations.

    The third-place play-off (its slots are the two semi-final losers, ``RU*``)
    is excluded from ``opponent_at_stage``/``eliminations`` so it never pollutes
    semi-final opponents or title paths; it shares the ``"SF"`` label otherwise.
    """
    winners: dict[int, str] = {}
    losers: dict[int, str] = {}
    for m in inputs.knockout:
        a = _resolve_slot(m["slot_a"], m, group_results, assignment, winners, losers)
        b = _resolve_slot(m["slot_b"], m, group_results, assignment, winners, losers)
        res = play_match(
            a, b, elo, inputs, rng, knockout=True, host_country=m["host_country"]
        )
        winners[m["num"]] = res["winner"]
        losers[m["num"]] = res["loser"]
        if goals is not None:
            for t, gf, ga in ((a, res["ga"], res["gb"]), (b, res["gb"], res["ga"])):
                g = goals[t]
                g["k_gf"] += gf
                g["k_ga"] += ga
                g["k_n"] += 1
        if r32_slots is not None and m["stage_label"] == "R32":
            r32_slots[m["slot_a"]][a] += 1
            r32_slots[m["slot_b"]][b] += 1
        # Exclude the third-place play-off (loser-fed, RU* slots) from matchup/
        # elimination tracking; every other knockout tie is winner/group fed.
        if not m["slot_a"].startswith("RU"):
            if opponent_at_stage is not None:
                opponent_at_stage[a][m["stage_label"]][b] += 1
                opponent_at_stage[b][m["stage_label"]][a] += 1
            if eliminations is not None and res["loser"] is not None:
                eliminations[(res["winner"], res["loser"])] += 1
        for t in (a, b):
            _bump_stage(stage_reached, t, m["stage_label"], inputs.fmt)
    return winners[inputs.fmt.final_match]


def _bump_stage(
    stage_reached: dict[str, str], team: str, label: str, fmt: TournamentFormat
) -> None:
    if fmt.stage_order[label] > fmt.stage_order[stage_reached[team]]:
        stage_reached[team] = label


# ── Layer 5: orchestration ──────────────────────────────────────────────────
def run_tournament(
    inputs: SimInputs,
    rng: np.random.Generator,
    goals: Optional[dict[str, dict]] = None,
    group_pos: Optional[dict[str, Counter]] = None,
    r32_slots: Optional[dict[str, Counter]] = None,
    opponent_at_stage: Optional[dict[str, dict[str, Counter]]] = None,
    eliminations: Optional[Counter] = None,
) -> dict[str, str]:
    """Simulate one full tournament; return {team: furthest stage reached}.

    When ``goals`` is supplied, per-team goals-for/against are accumulated into
    it, split into a group-stage bucket (``g_gf``/``g_ga``/``g_n``) and a pooled
    knockout bucket (``k_gf``/``k_ga``/``k_n``). When ``group_pos`` is supplied,
    each team's final group-finishing position (1-based) is tallied into
    ``group_pos[team]``. The ``r32_slots``/``opponent_at_stage``/``eliminations``
    accumulators capture per-sim bracket detail for the projection layer (see
    :func:`simulate_knockout`). The caller owns the accumulators so they persist
    across many simulations.
    """
    elo = dict(inputs.elo0)
    stage_reached = {team: "GROUP" for team in inputs.teams}

    group_results: dict[str, dict[int, str]] = {}
    third_rows: list[dict] = []
    for letter in inputs.group_fixtures:
        ranked, stats = simulate_group(letter, inputs, elo, rng)
        group_results[letter] = {pos + 1: t for pos, t in enumerate(ranked)}
        if group_pos is not None:
            for pos, t in enumerate(ranked):
                group_pos[t][pos + 1] += 1
        if goals is not None:
            # Each team's matches played in this group = group size - 1.
            n_matches = len(stats) - 1
            for t, s in stats.items():
                g = goals[t]
                g["g_gf"] += s["gf"]
                g["g_ga"] += s["ga"]
                g["g_n"] += n_matches
        if inputs.fmt.has_third_place:
            third = ranked[2]
            third_rows.append(
                {
                    "group": letter,
                    "team": third,
                    "points": stats[third]["pts"],
                    "gd": stats[third]["gd"],
                    "gf": stats[third]["gf"],
                    "elo": elo[third],
                }
            )

    # Best-third-placed qualification only exists in the 48-team format; in the
    # legacy 32-team bracket the Round of 16 is fed purely by positional slots.
    assignment: dict[str, str] = {}
    if inputs.fmt.has_third_place:
        qualifiers = rank_third_placed(third_rows)[:8]
        qualifying_groups = {r["group"] for r in qualifiers}
        assignment = assign_third_place_slots(
            qualifying_groups, inputs.third_place_table
        )
        if group_pos is not None:
            for r in qualifiers:
                group_pos[r["team"]]["q3"] += 1

    champion = simulate_knockout(
        inputs,
        group_results,
        assignment,
        elo,
        rng,
        stage_reached,
        goals,
        r32_slots,
        opponent_at_stage,
        eliminations,
    )
    stage_reached[champion] = "CHAMPION"
    return stage_reached


def monte_carlo(
    inputs: SimInputs,
    n: int = 10000,
    seed: int = 2026,
    out: str | None = f"{FORECAST_PATH}/tournament_probs_latest.csv",
    goals_out: str | None = None,
    group_pos_out: str | None = None,
    r32_slots_out: str | None = None,
    opponent_dist_out: str | None = None,
    eliminations_out: str | None = None,
) -> pd.DataFrame:
    """Run N tournaments; return a per-team cumulative stage-probability table.

    The reported columns follow ``inputs.fmt.cum_stages`` (so the legacy 32-team
    format omits ``r32``). Pass ``out=None`` to skip writing the CSV (useful for
    backtests that score the table in memory).

    When ``goals_out`` is a path, per-team average goals-for/against — split into
    a group-stage and a pooled knockout bucket — are accumulated over the same
    simulation loop and written there as a second artifact (see
    :func:`_write_goal_stats`). When ``group_pos_out`` is a path, the per-team
    probability of finishing the group 1st/2nd/3rd/4th is written there (see
    :func:`_write_group_position_probs`).

    Three further opt-in paths drive the projection/showcase layer
    (:mod:`src.projections`), each populated from the same loop:
    ``r32_slots_out`` → per-slot Round-of-32 occupancy, ``opponent_dist_out`` →
    the (team, stage, opponent) meeting distribution, ``eliminations_out`` →
    head-to-head knockout eliminations. The returned DataFrame is unchanged by
    any of these.
    """
    rng = np.random.default_rng(seed)
    fmt = inputs.fmt
    counts: dict[str, Counter] = {team: Counter() for team in inputs.teams}
    goals: dict[str, dict] | None = None
    if goals_out is not None:
        goals = {
            team: {"g_gf": 0, "g_ga": 0, "g_n": 0, "k_gf": 0, "k_ga": 0, "k_n": 0}
            for team in inputs.teams
        }
    group_pos: dict[str, Counter] | None = None
    if group_pos_out is not None:
        group_pos = {team: Counter() for team in inputs.teams}
    r32_slots: dict[str, Counter] | None = None
    if r32_slots_out is not None:
        r32_slots = {
            tok: Counter()
            for m in inputs.knockout
            if m["stage_label"] == "R32"
            for tok in (m["slot_a"], m["slot_b"])
        }
    opponent_at_stage: dict[str, dict[str, Counter]] | None = None
    if opponent_dist_out is not None:
        ko_stages = [s for s in fmt.cum_stages if s not in ("CHAMPION",)]
        opponent_at_stage = {
            team: {s: Counter() for s in ko_stages} for team in inputs.teams
        }
    eliminations: Counter | None = None
    if eliminations_out is not None:
        eliminations = Counter()
    with CUSTOM_PROGRESS as p:
        for _ in p.track(range(n), description="Simulating tournaments"):
            stage_reached = run_tournament(
                inputs,
                rng,
                goals,
                group_pos,
                r32_slots,
                opponent_at_stage,
                eliminations,
            )
            for team, stage in stage_reached.items():
                counts[team][stage] += 1

    if goals is not None:
        _write_goal_stats(goals, n, goals_out)
    if group_pos is not None:
        _write_group_position_probs(group_pos, n, inputs, group_pos_out)
    if r32_slots is not None:
        _write_r32_slots(r32_slots, inputs, n, r32_slots_out)
    if opponent_at_stage is not None:
        _write_opponent_distribution(opponent_at_stage, n, opponent_dist_out)
    if eliminations is not None:
        _write_eliminations(eliminations, n, eliminations_out)

    rows = []
    for team in inputs.teams:
        c = counts[team]
        row = {"team": team}
        for st in fmt.cum_stages:
            reached = sum(
                v for s, v in c.items() if fmt.stage_order[s] >= fmt.stage_order[st]
            )
            row[st.lower()] = reached / n
        rows.append(row)

    df = (
        pd.DataFrame(rows)
        .sort_values(fmt.cum_stages[-1].lower(), ascending=False)
        .reset_index(drop=True)
    )
    if out is not None:
        df.to_csv(out, index=False)
        CON.log(f"Tournament probabilities ({n} sims) written to {out}")
    _print_table(df)
    return df


def _write_goal_stats(goals: dict[str, dict], n: int, out: str) -> pd.DataFrame:
    """Build and write the per-team average goals-for/against table.

    Averages are **per match**: group buckets divide by group matches played
    (always 3 in WC2026), knockout buckets divide by knockout matches actually
    played (so ``ko_gf``/``ko_ga`` are conditional on reaching the knockouts and
    blank for a team that never did). ``ko_match_rate`` is the average number of
    knockout matches a team plays per tournament — a qualification-depth signal.
    """
    team_group = {team: letter for letter, teams in GROUPPING.items() for team in teams}
    rows = []
    for team, g in goals.items():
        k_n = g["k_n"]
        rows.append(
            {
                "team": team,
                "group": team_group.get(team),
                "group_gf": round(g["g_gf"] / g["g_n"], 3) if g["g_n"] else None,
                "group_ga": round(g["g_ga"] / g["g_n"], 3) if g["g_n"] else None,
                "ko_gf": round(g["k_gf"] / k_n, 3) if k_n else None,
                "ko_ga": round(g["k_ga"] / k_n, 3) if k_n else None,
                "ko_match_rate": round(k_n / n, 3),
            }
        )
    df = (
        pd.DataFrame(rows)
        .sort_values("group_gf", ascending=False)
        .reset_index(drop=True)
    )
    df.to_csv(out, index=False)
    CON.log(f"Per-team goal stats ({n} sims) written to {out}")
    return df


def _write_group_position_probs(
    group_pos: dict[str, Counter], n: int, inputs: SimInputs, out: str
) -> pd.DataFrame:
    """Build and write the per-team group-finishing-position probability table.

    One row per team with its group letter and ``p1``..``pK`` columns giving the
    probability of finishing the group in each position (K = group size, 4 for
    both the WC2026 and legacy formats). In the 48-team format an extra
    ``p_best_third`` column gives the probability of qualifying as one of the
    eight best third-placed teams (so ``p_best_third`` <= ``p3``). Rows sort by
    group, then by ``p1``.
    """
    team_group = {
        t: letter
        for letter, fixtures in inputs.group_fixtures.items()
        for home, away, _ in fixtures
        for t in (home, away)
    }
    # Position keys are ints; "q3" (best-third qualification) is tallied separately.
    max_pos = max(
        (p for c in group_pos.values() for p in c if isinstance(p, int)), default=0
    )
    rows = []
    for team in inputs.teams:
        c = group_pos[team]
        row = {"team": team, "group": team_group.get(team)}
        for i in range(1, max_pos + 1):
            row[f"p{i}"] = round(c[i] / n, 4)
        if inputs.fmt.has_third_place:
            row["p_best_third"] = round(c["q3"] / n, 4)
        rows.append(row)
    df = (
        pd.DataFrame(rows)
        .sort_values(["group", "p1"], ascending=[True, False])
        .reset_index(drop=True)
    )
    df.to_csv(out, index=False)
    CON.log(f"Group-position probabilities ({n} sims) written to {out}")
    return df


def _write_r32_slots(
    r32_slots: dict[str, Counter], inputs: SimInputs, n: int, out: str
) -> pd.DataFrame:
    """Write the per-slot Round-of-32 occupancy distribution.

    One row per (slot, team) the team ever filled, with ``prob`` = count / n (so
    a slot's rows sum to 1). ``match_number`` and ``opponent_slot`` locate the
    slot in the bracket (the R32 tie it belongs to and the token it faces), read
    from ``inputs.knockout``. Rows sort by slot, then by descending prob — so the
    modal occupant of each slot is its first row. The third-place-style slots
    (``"3ABCDF"`` etc.) are where this is most informative.
    """
    slot_meta = {
        tok: {"match_number": m["num"], "opponent_slot": other}
        for m in inputs.knockout
        if m["stage_label"] == "R32"
        for tok, other in ((m["slot_a"], m["slot_b"]), (m["slot_b"], m["slot_a"]))
    }
    rows = []
    for slot, counter in r32_slots.items():
        meta = slot_meta.get(slot, {})
        for team, c in counter.items():
            rows.append(
                {
                    "slot": slot,
                    "match_number": meta.get("match_number"),
                    "opponent_slot": meta.get("opponent_slot"),
                    "team": team,
                    "prob": round(c / n, 5),
                }
            )
    df = (
        pd.DataFrame(rows)
        .sort_values(["match_number", "slot", "prob"], ascending=[True, True, False])
        .reset_index(drop=True)
    )
    df.to_csv(out, index=False)
    CON.log(f"R32 slot occupancy ({n} sims) written to {out}")
    return df


def _write_opponent_distribution(
    opponent_at_stage: dict[str, dict[str, Counter]], n: int, out: str
) -> pd.DataFrame:
    """Write the (team, stage, opponent) meeting distribution.

    Long format, one row per (team, stage, opponent) pair actually observed.
    ``meet_prob`` = count / n is the **unconditional** probability that ``team``
    faces ``opponent`` at ``stage`` (i.e. not divided by the chance the team
    reaches that stage). To get the conditional modal opponent given the team
    reached a stage, divide by ``P(reach stage)`` from
    ``tournament_probs_latest.csv`` — but the argmax (modal opponent) is the same
    either way, since the divisor is constant within a (team, stage). The
    third-place play-off is excluded upstream (see :func:`simulate_knockout`).
    """
    rows = [
        {"team": team, "stage": stage, "opponent": opp, "meet_prob": round(c / n, 6)}
        for team, by_stage in opponent_at_stage.items()
        for stage, counter in by_stage.items()
        for opp, c in counter.items()
    ]
    df = (
        pd.DataFrame(rows)
        .sort_values(["team", "stage", "meet_prob"], ascending=[True, True, False])
        .reset_index(drop=True)
    )
    df.to_csv(out, index=False)
    CON.log(f"Opponent distribution ({n} sims) written to {out}")
    return df


def _write_eliminations(eliminations: Counter, n: int, out: str) -> pd.DataFrame:
    """Write head-to-head knockout eliminations.

    One row per ordered (winner, loser) pair observed, ``prob`` = count / n is the
    unconditional probability that ``winner`` knocks ``loser`` out at some
    knockout stage. The third-place play-off is excluded upstream.
    """
    rows = [
        {"winner": w, "loser": loser_team, "prob": round(c / n, 6)}
        for (w, loser_team), c in eliminations.items()
    ]
    df = pd.DataFrame(rows).sort_values("prob", ascending=False).reset_index(drop=True)
    df.to_csv(out, index=False)
    CON.log(f"Knockout eliminations ({n} sims) written to {out}")
    return df


def _print_table(df: pd.DataFrame, top: int = 16) -> None:
    from rich.table import Table

    # Stage columns present in the table (strongest first), excluding "team".
    cols = [c for c in df.columns if c != "team"][::-1]
    table = Table(title="Advancement probabilities (P reach stage)")
    table.add_column("Team")
    for col in cols:
        table.add_column(col.upper(), justify="right")
    for _, r in df.head(top).iterrows():
        table.add_row(r["team"], *[f"{r[c]:.3f}" for c in cols])
    CON.print(table)
