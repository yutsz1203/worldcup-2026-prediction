"""Monte Carlo stat-line simulator + event pricer.

Loads a base-rates CSV (:mod:`jumpcup.event_rates`) and a hand-written event spec
JSON (grammar in ``competitions/jumpcup/jump-probability-cup.md``), simulates ``n`` per-match
stat lines, and prices every event as the mean of its indicator.

What gets drawn, per team per half (H1/H2 atomic; FT = sum):

- independent Poissons for goal, corner, shot_on_target, foul, penalty_awarded,
  offside, red_card; yellow = Poisson(λ_card − λ_red) so ``card = yellow + red``
  contains reds by construction.
- **player counts by conditional multinomial thinning** of the team count
  (sequential binomials — exact multinomial marginals, guarantees player ≤ team and
  shares that sum to the rates CSV's λs). Only players referenced in the spec are
  materialized. Player assists: ``Binom(team_goals − own_goals, q)`` with
  ``q = λ_assist / λ_team_goal``; ``goal_contribution = goals + assists``.
- **FIRST** by exchangeability: the first occurrence falls in H1 iff H1 total > 0;
  within the deciding half with counts (a, b), P(A first) = a/(a+b).

v1 dependence simplifications (documented, deliberate): stats are mutually
independent except player↔team coupling, FIRST↔counts, and red ⊂ card. No
score–cards / score–corners coupling.

Every run also cross-checks {A wins, draw, total ≥ 3} against the closed-form
score-matrix (:func:`model.probabilities.generate_probabilities`) and warns if the
Monte Carlo deviates by more than ``CROSSCHECK_TOL``.
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from competitions.jumpcup.const import probs_path, rates_path, spec_path
from competitions.jumpcup.fetch import _abbrev_matches, _norm_name
from model.probabilities import generate_probabilities
from src.const import CON

N_SIMS_DEFAULT = 100_000
SEED_DEFAULT = 26
CROSSCHECK_TOL = 0.01  # MC s.e. ~0.0016 at 100k sims
MIN_YELLOW_LAMBDA = 0.05  # per-half floor when λ_card barely exceeds λ_red
MAX_ASSIST_Q = 0.9  # a goal can't be assisted by its own scorer

STATS = {
    "goal",
    "corner",
    "shot_on_target",
    "foul",
    "card",
    "red_card",
    "penalty_awarded",
    "offside",
    "goal_contribution",
    "assist",
}
PLAYER_STATS = {"goal", "assist", "shot_on_target", "goal_contribution"}
WINDOWS = {"H1", "H2", "FT"}
OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
}


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


@dataclass
class Rates:
    event_id: int
    match_uid: str
    team_names: dict[str, str]  # "A"/"B" -> canonical name
    team: dict[tuple[str, str, str], float]  # (key, stat, half) -> λ
    players: dict[str, dict[str, dict]]  # key -> norm_name -> {name, (stat,half): λ}


def load_rates(path: str) -> Rates:
    df = pd.read_csv(path)
    team_names = (
        df[["team_key", "team_name"]]
        .drop_duplicates()
        .set_index("team_key")["team_name"]
        .to_dict()
    )
    team, players = {}, {"A": {}, "B": {}}
    for r in df.itertuples():
        if r.entity_type == "team":
            team[(r.team_key, r.stat, r.window)] = r.lam
        else:
            entry = players[r.team_key].setdefault(
                _norm_name(r.player_name), {"name": r.player_name}
            )
            entry[(r.stat, r.window)] = r.lam
    return Rates(
        event_id=int(df["event_id"].iloc[0]),
        match_uid=str(df["match_uid"].iloc[0]),
        team_names=team_names,
        team=team,
        players=players,
    )


# ---------------------------------------------------------------------------
# Spec loading / validation
# ---------------------------------------------------------------------------


def _walk_atoms(node: dict):
    if "and" in node or "or" in node:
        for child in node.get("and", node.get("or")):
            yield from _walk_atoms(child)
    else:
        yield node


def _entity_refs(atom: dict) -> list[Any]:
    if atom["atom"] == "compare":
        return [atom["left"], atom["right"]]
    return [atom["entity"]]


def load_spec(path: str, rates: Rates) -> dict:
    """Load + validate a spec file; resolves player refs against the rates CSV.

    Player entities gain a ``_key``/``_norm`` annotation used by the simulator.
    Fails loudly on unknown stats/windows/ops and on *ambiguous* player names. A
    player who simply isn't in the lineup (e.g. dropped to the bench on a refresh)
    is not an error: the event is tagged ``_unresolved`` and skipped at pricing,
    so the rest of the slate still prices.
    """
    spec = json.loads(open(path).read())
    for ev in spec["events"]:
        ev.pop("_unresolved", None)
        for atom in _walk_atoms(ev["spec"]):
            kind = atom.get("atom")
            if kind not in {"threshold", "compare", "first"}:
                raise ValueError(f"event {ev['id']}: unknown atom {kind!r}")
            if atom["stat"] not in STATS:
                raise ValueError(f"event {ev['id']}: unknown stat {atom['stat']!r}")
            if kind != "first" and atom["window"] not in WINDOWS:
                raise ValueError(f"event {ev['id']}: bad window {atom['window']!r}")
            if kind == "compare":
                for wk in ("left_window", "right_window"):
                    if wk in atom and atom[wk] not in WINDOWS:
                        raise ValueError(
                            f"event {ev['id']}: bad {wk} {atom[wk]!r}"
                        )
            if kind == "first" and atom.get("window", "FT") not in WINDOWS:
                raise ValueError(f"event {ev['id']}: bad window {atom['window']!r}")
            if kind == "threshold" and atom["op"] not in OPS:
                raise ValueError(f"event {ev['id']}: bad op {atom['op']!r}")
            if kind == "compare" and atom["op"] not in OPS:
                raise ValueError(f"event {ev['id']}: bad op {atom['op']!r}")
            for ent in _entity_refs(atom):
                if isinstance(ent, dict):  # player
                    if atom["stat"] not in PLAYER_STATS:
                        raise ValueError(
                            f"event {ev['id']}: stat {atom['stat']!r} has no "
                            "player-level rates"
                        )
                    norm = _norm_name(ent["player"])
                    keys = [ent["team"][-1]] if "team" in ent else ["A", "B"]
                    # exact normalized match first, then abbreviation fallback: the
                    # feed's name format varies (confirmed lineups abbreviate, e.g.
                    # "Scott McTominay" -> "S. McTominay"), so a spec written with
                    # full names must still resolve after a lineup refresh.
                    hits = [(k, norm) for k in keys if norm in rates.players[k]]
                    if not hits:
                        hits = [
                            (k, pn)
                            for k in keys
                            for pn in rates.players[k]
                            if _abbrev_matches(norm, pn)
                            or _abbrev_matches(pn, norm)
                        ]
                    if len(hits) == 0:  # not in lineup -> skip, don't crash
                        ev["_unresolved"] = (
                            f"player {ent['player']!r} not in lineup"
                        )
                        break
                    if len(hits) > 1:  # genuinely ambiguous -> author must fix
                        known = sorted(
                            rates.players["A"][n]["name"] for n in rates.players["A"]
                        ) + sorted(
                            rates.players["B"][n]["name"] for n in rates.players["B"]
                        )
                        raise ValueError(
                            f"event {ev['id']}: player {ent['player']!r} ambiguous "
                            f"(hits={hits}). Lineup players: {known}"
                        )
                    ent["_key"], ent["_norm"] = hits[0]
                elif ent not in {"team_A", "team_B", "match_total"}:
                    raise ValueError(f"event {ev['id']}: bad entity {ent!r}")
                if kind == "first" and not (
                    isinstance(ent, str) and ent.startswith("team_")
                ):
                    raise ValueError(
                        f"event {ev['id']}: FIRST entity must be team_A/team_B"
                    )
            if ev.get("_unresolved"):
                break
    return spec


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@dataclass
class SimState:
    n: int
    team: dict[tuple[str, str, str], np.ndarray]  # (key, stat, half) -> counts
    player: dict[tuple[str, str, str, str], np.ndarray]  # (key, norm, stat, half)


def _thin_players(
    team_counts: dict[str, np.ndarray],
    shares: list[tuple[str, float]],
    rng: np.random.Generator,
) -> dict[tuple[str, str], np.ndarray]:
    """Sequential-binomial multinomial thinning per half. ``shares`` must sum <= 1
    (the remainder is unreferenced players)."""
    out = {}
    for half, counts in team_counts.items():
        remaining = counts.copy()
        used = 0.0
        for norm, s in shares:
            denom = 1.0 - used
            p = min(s / denom, 1.0) if denom > 1e-12 else 0.0
            draw = rng.binomial(remaining, p)
            out[(norm, half)] = draw
            remaining = remaining - draw
            used += s
    return out


def simulate(
    rates: Rates, spec: dict, n: int = N_SIMS_DEFAULT, seed: int = SEED_DEFAULT
) -> SimState:
    rng = np.random.default_rng(seed)
    team: dict[tuple[str, str, str], np.ndarray] = {}

    for key in ("A", "B"):
        for half in ("H1", "H2"):
            lam_red = rates.team[(key, "red_card", half)]
            lam_yellow = max(
                rates.team[(key, "card", half)] - lam_red, MIN_YELLOW_LAMBDA
            )
            red = rng.poisson(lam_red, n)
            team[(key, "red_card", half)] = red
            team[(key, "card", half)] = red + rng.poisson(lam_yellow, n)
            for stat in (
                "goal",
                "corner",
                "shot_on_target",
                "foul",
                "penalty_awarded",
                "offside",
            ):
                team[(key, stat, half)] = rng.poisson(rates.team[(key, stat, half)], n)

    # Which players does the spec reference, and with which stats?
    refs: dict[str, dict[str, set]] = {"A": {}, "B": {}}
    for ev in spec["events"]:
        if ev.get("_unresolved"):
            continue
        for atom in _walk_atoms(ev["spec"]):
            for ent in _entity_refs(atom):
                if isinstance(ent, dict):
                    refs[ent["_key"]].setdefault(ent["_norm"], set()).add(atom["stat"])

    player: dict[tuple[str, str, str, str], np.ndarray] = {}
    for key in ("A", "B"):
        if not refs[key]:
            continue
        needs_goal = [
            norm
            for norm, stats in refs[key].items()
            if stats & {"goal", "goal_contribution", "assist"}
        ]
        needs_sot = [n_ for n_, st in refs[key].items() if "shot_on_target" in st]

        lam_team_goal_ft = sum(rates.team[(key, "goal", h)] for h in ("H1", "H2"))
        if needs_goal:
            shares = [
                (
                    norm,
                    sum(rates.players[key][norm][("goal", h)] for h in ("H1", "H2"))
                    / lam_team_goal_ft,
                )
                for norm in needs_goal
            ]
            goals = _thin_players(
                {h: team[(key, "goal", h)] for h in ("H1", "H2")}, shares, rng
            )
            for (norm, half), arr in goals.items():
                player[(key, norm, "goal", half)] = arr
            # assists: of the team's other goals, each is assisted by this player
            # with probability q = λ_assist / λ_team_goal.
            for norm in needs_goal:
                lam_assist_ft = sum(
                    rates.players[key][norm][("assist", h)] for h in ("H1", "H2")
                )
                q = min(lam_assist_ft / lam_team_goal_ft, MAX_ASSIST_Q)
                for half in ("H1", "H2"):
                    others = (
                        team[(key, "goal", half)] - player[(key, norm, "goal", half)]
                    )
                    assists = rng.binomial(others, q)
                    player[(key, norm, "assist", half)] = assists
                    player[(key, norm, "goal_contribution", half)] = (
                        player[(key, norm, "goal", half)] + assists
                    )
        if needs_sot:
            lam_team_sot_ft = sum(
                rates.team[(key, "shot_on_target", h)] for h in ("H1", "H2")
            )
            shares = [
                (
                    norm,
                    sum(
                        rates.players[key][norm][("shot_on_target", h)]
                        for h in ("H1", "H2")
                    )
                    / lam_team_sot_ft,
                )
                for norm in needs_sot
            ]
            sots = _thin_players(
                {h: team[(key, "shot_on_target", h)] for h in ("H1", "H2")},
                shares,
                rng,
            )
            for (norm, half), arr in sots.items():
                player[(key, norm, "shot_on_target", half)] = arr

    return SimState(n=n, team=team, player=player)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _count(sim: SimState, stat: str, entity: Any, window: str) -> np.ndarray:
    halves = ("H1", "H2") if window == "FT" else (window,)
    if isinstance(entity, dict):
        return sum(
            sim.player[(entity["_key"], entity["_norm"], stat, h)] for h in halves
        )
    if entity == "match_total":
        return sum(sim.team[(k, stat, h)] for k in ("A", "B") for h in halves)
    key = entity[-1]  # "team_A" -> "A"
    return sum(sim.team[(key, stat, h)] for h in halves)


def _eval_first(
    sim: SimState, stat: str, entity: str, window: str, rng: np.random.Generator
) -> np.ndarray:
    """P(entity records the first occurrence within ``window``): the deciding half
    is the first (in the window) with any occurrence; within it, exchangeable
    arrivals give P = own/(own+opp). ``window`` H1/H2 scope to a single half."""
    key = entity[-1]
    opp = "B" if key == "A" else "A"
    own_h1, opp_h1 = sim.team[(key, stat, "H1")], sim.team[(opp, stat, "H1")]
    own_h2, opp_h2 = sim.team[(key, stat, "H2")], sim.team[(opp, stat, "H2")]
    if window == "H1":
        own, tot = own_h1, own_h1 + opp_h1
    elif window == "H2":
        own, tot = own_h2, own_h2 + opp_h2
    else:  # FT: first occurrence falls in H1 iff H1 has any, else H2
        h1_any = (own_h1 + opp_h1) > 0
        own = np.where(h1_any, own_h1, own_h2)
        tot = np.where(h1_any, own_h1 + opp_h1, own_h2 + opp_h2)
    p = np.divide(own, tot, out=np.zeros(sim.n), where=tot > 0)
    return (tot > 0) & (rng.random(sim.n) < p)


def eval_node(node: dict, sim: SimState, rng: np.random.Generator) -> np.ndarray:
    if "and" in node:
        out = np.ones(sim.n, dtype=bool)
        for child in node["and"]:
            out &= eval_node(child, sim, rng)
        return out
    if "or" in node:
        out = np.zeros(sim.n, dtype=bool)
        for child in node["or"]:
            out |= eval_node(child, sim, rng)
        return out
    kind = node["atom"]
    if kind == "threshold":
        return OPS[node["op"]](
            _count(sim, node["stat"], node["entity"], node["window"]), node["k"]
        )
    if kind == "compare":
        # optional per-side window overrides let a compare span two windows
        # (e.g. "2nd-half goals > 1st-half goals"); both default to `window`.
        lw = node.get("left_window", node["window"])
        rw = node.get("right_window", node["window"])
        return OPS[node["op"]](
            _count(sim, node["stat"], node["left"], lw),
            _count(sim, node["stat"], node["right"], rw),
        )
    return _eval_first(
        sim, node["stat"], node["entity"], node.get("window", "FT"), rng
    )


# ---------------------------------------------------------------------------
# Cross-check + pricing
# ---------------------------------------------------------------------------


def crosscheck(rates: Rates, sim: SimState) -> bool:
    """Print the MC-vs-closed-form comparison; return False if any line mismatches."""
    lam_a = sum(rates.team[("A", "goal", h)] for h in ("H1", "H2"))
    lam_b = sum(rates.team[("B", "goal", h)] for h in ("H1", "H2"))
    long_info, _ = generate_probabilities(
        rates.team_names["A"], lam_a, rates.team_names["B"], lam_b
    )
    ga = sim.team[("A", "goal", "H1")] + sim.team[("A", "goal", "H2")]
    gb = sim.team[("B", "goal", "H1")] + sim.team[("B", "goal", "H2")]
    mc = {
        "A wins": (ga > gb).mean(),
        "Draw": (ga == gb).mean(),
        "Total >= 3": ((ga + gb) >= 3).mean(),
    }
    cf = {
        "A wins": long_info["Home Probability"],
        "Draw": long_info["Draw Probability"],
        "Total >= 3": long_info["Over 2.5"],
    }
    assert abs((ga > gb).mean() + (ga == gb).mean() + (ga < gb).mean() - 1.0) < 1e-12
    CON.print("[bold]Cross-check (MC vs closed-form score matrix):[/]")
    ok_all = True
    for k in mc:
        diff = abs(mc[k] - cf[k])
        mismatch = diff > CROSSCHECK_TOL
        ok_all = ok_all and not mismatch
        flag = "[red]MISMATCH[/]" if mismatch else "ok"
        CON.print(f"  {k:11s}  MC {mc[k]:.4f}  CF {cf[k]:.4f}  |Δ| {diff:.4f}  {flag}")
    return ok_all


def _model_version() -> str:
    """Short git SHA for reproducibility; empty string outside a git checkout."""
    import subprocess

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


def price(
    event_id: int,
    spec_file: Optional[str] = None,
    rates_file: Optional[str] = None,
    out: Optional[str] = None,
    n: int = N_SIMS_DEFAULT,
    seed: int = SEED_DEFAULT,
) -> pd.DataFrame:
    rates = load_rates(rates_file or rates_path(event_id))
    spec = load_spec(spec_file or spec_path(event_id), rates)
    sim = simulate(rates, spec, n, seed)
    # FIRST atoms and the evaluator share one auxiliary stream, separate from the
    # simulation draws so adding events never perturbs the stat line itself.
    rng = np.random.default_rng(seed + 1)

    crosscheck_ok = crosscheck(rates, sim)

    version = _model_version()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    skipped = []
    for ev in spec["events"]:
        reason = ev.get("_unresolved")
        p = None if reason else round(float(eval_node(ev["spec"], sim, rng).mean()), 4)
        if reason:
            skipped.append((ev["id"], reason))
        rows.append(
            {
                "event_id": event_id,
                "match_uid": rates.match_uid,
                "jump_event_id": ev["id"],
                "text": ev["text"],
                "canonical_spec": json.dumps(
                    ev["spec"], ensure_ascii=False, separators=(",", ":")
                ),
                "probability": p,
                "note": reason or "",
                "n_sims": n,
                "seed": seed,
                "model_version": version,
                "generated_at": now,
            }
        )
    df = pd.DataFrame(rows)
    df.attrs["crosscheck_ok"] = crosscheck_ok
    out = out or probs_path(event_id)
    df.to_csv(out, index=False)
    if skipped:
        CON.print(
            f"[yellow]jumpcup: {len(skipped)} event(s) not priced "
            f"(blank probability):[/]"
        )
        for eid, reason in skipped:
            CON.print(f"  [yellow]event {eid}: {reason}[/]")
    CON.print(f"[green]jumpcup:[/] wrote {len(df)} event probabilities to {out}")
    CON.print(
        df[["jump_event_id", "text", "probability"]].to_string(
            index=False, na_rep="—"
        )
    )
    return df
