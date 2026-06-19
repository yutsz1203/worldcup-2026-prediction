"""Derived tournament projections (roadmap Tier 0, step 3).

Every function here is a **pure read** off the forecast CSV artifacts written by
:func:`src.simulation.monte_carlo` — no simulation is run (the one exception,
:func:`project_modal_bracket`, reuses the lightweight ``play_match`` engine for a
few thousand single-match simulations, not a full tournament). Each returns a
tidy ``pd.DataFrame`` so the showcase layer (:mod:`src.showcase`) can render it as
a markdown table, chart, or Mermaid diagram. Re-run the sim before kickoff to
refresh the artifacts; the projections regenerate from them instantly.

Deliverables (roadmap step 3):
    1. group_standings_table        — P(1st/2nd/3rd-q/3rd-out/4th), xP, group-of-death
    2. expected_elimination_table   — one expected-finish number ranking all 48
    3. dark_horse_table             — deep-run prob vs seeding-pot baseline
    4. r32_bracket_marginals        — modal occupant (+ runners-up) of each R32 slot
    5. marquee_matchups             — P(X meets Y at stage Z), P(final), P(X eliminates Y)
    6. path_difficulty_table        — expected opponent strength on the route
    7. favorite_title_path          — the favorite's modal opponent at each stage
    8. project_modal_bracket        — full chalk bracket, modal R32 chained by re-sim
"""

from __future__ import annotations

from itertools import combinations
from typing import Optional

import pandas as pd

from src.const import CUSTOM_PROGRESS, FORECAST_PATH, WC26_POTS_PATH

# Cumulative reach-probability columns in tournament_probs_initial.csv, weakest to
# strongest stage (the ordinal "stage reached" GROUP=0 … CHAMPION=6 is applied
# inline in expected_elimination_table).
_STAGE_COLS = ["r32", "r16", "qf", "sf", "final", "champion"]
# Knockout stages as labelled in opponent_distribution.csv, ordered.
_KO_STAGES = ["R32", "R16", "QF", "SF", "FINAL"]


# ── artifact loaders ─────────────────────────────────────────────────────────
def _read(name: str, src_dir: str = FORECAST_PATH) -> pd.DataFrame:
    return pd.read_csv(f"{src_dir}/{name}")


def _strength() -> pd.Series:
    """Per-team model strength (net expected goals vs an average WC26 opponent)."""
    s = _read("team_strengths.csv")  # static (result-independent), always in forecast
    return s.set_index("team")["net_xg"]


def _probs_filename(src_dir: str = FORECAST_PATH) -> str:
    """Name of the reach-probability CSV in ``src_dir``.

    The live re-sim writes ``tournament_probs_updated.csv``; the pre-tournament
    forecast writes ``tournament_probs_initial.csv``. Prefer the updated file when
    present so projections transparently pick up a live re-sim.
    """
    import os

    updated = "tournament_probs_updated.csv"
    return updated if os.path.exists(f"{src_dir}/{updated}") else "tournament_probs_initial.csv"


# ── 1. group standings + group-of-death ──────────────────────────────────────
def group_standings_table(src_dir: str = FORECAST_PATH) -> pd.DataFrame:
    """Per-team group-stage marginals, expected points, and a group-of-death index.

    Columns: ``team, group, p1, p2, p3_qualify, p3_out, p4, exp_points,
    qualify_prob, death_index``. ``p3_qualify`` is the chance of finishing third
    *and* advancing as a best-third team (``p_best_third``); ``p3_out`` is
    third-but-eliminated (``p3 - p_best_third``). ``exp_points`` uses the full
    ``p3`` (a third-placed team banks its group points regardless of qualifying).

    ``death_index`` (constant within a group) is the **expected strength of the
    eliminated**: ``Σ_team (1 - qualify_prob) · strength``, where ``strength`` is
    ``net_xg`` rebased so the field's weakest team sits at 0 (keeping the index
    non-negative and readable). A high value means the group is likely to send
    strong teams home — the literal "group of death".
    """
    g = _read("group_position_probs.csv", src_dir)
    strength = _strength()
    strength = strength - strength.min()  # rebase: weakest team -> 0, all >= 0
    g["p3_qualify"] = g["p_best_third"]
    g["p3_out"] = (g["p3"] - g["p_best_third"]).clip(lower=0)
    g["exp_points"] = 3 * g["p1"] + 2 * g["p2"] + 1 * g["p3"]
    g["qualify_prob"] = g["p1"] + g["p2"] + g["p_best_third"]
    g["_elim_strength"] = (1 - g["qualify_prob"]) * g["team"].map(strength)
    death = g.groupby("group")["_elim_strength"].transform("sum")
    g["death_index"] = death
    cols = [
        "team",
        "group",
        "p1",
        "p2",
        "p3_qualify",
        "p3_out",
        "p4",
        "exp_points",
        "qualify_prob",
        "death_index",
    ]
    return (
        g[cols]
        .sort_values(["group", "exp_points"], ascending=[True, False])
        .round(4)
        .reset_index(drop=True)
    )


def group_difficulty_table(src_dir: str = FORECAST_PATH) -> pd.DataFrame:
    """One row per group ranked by ``death_index`` (the group-of-death ranking)."""
    g = group_standings_table(src_dir)
    out = (
        g.groupby("group")
        .agg(
            death_index=("death_index", "first"),
            strongest=("team", "first"),
            median_xpoints=("exp_points", "median"),
        )
        .reset_index()
        .sort_values("death_index", ascending=False)
        .round(4)
        .reset_index(drop=True)
    )
    out.insert(0, "difficulty_rank", out.index + 1)
    return out


# ── 2. expected round of elimination ─────────────────────────────────────────
def expected_elimination_table() -> pd.DataFrame:
    """One expected-finish number per team, linearly ranking all 48.

    Converts the cumulative reach-probabilities to per-stage *exit* probabilities
    (``exit_group = 1 - r32``, ``exit_r32 = r32 - r16``, …, ``win`` = champion),
    then ``expected_finish = Σ p(reach stage S) · ordinal(S)`` with GROUP = 0 …
    CHAMPION = 6. Higher = expected to go further; rank is ascending in finish.
    """
    t = _read("tournament_probs_initial.csv").copy()
    exits = pd.DataFrame({"team": t["team"]})
    exits["exit_group"] = 1 - t["r32"]
    for cur, nxt in zip(_STAGE_COLS[:-1], _STAGE_COLS[1:]):
        exits[f"exit_{cur}"] = t[cur] - t[nxt]
    exits["win"] = t["champion"]
    # expected stage reached = Σ ordinal · P(reach that stage and stop there)
    ordinals = [0, 1, 2, 3, 4, 5, 6]
    cols = [
        "exit_group",
        "exit_r32",
        "exit_r16",
        "exit_qf",
        "exit_sf",
        "exit_final",
        "win",
    ]
    exits["expected_finish"] = sum(o * exits[c] for o, c in zip(ordinals, cols))
    exits = exits.sort_values("expected_finish", ascending=False).reset_index(drop=True)
    exits.insert(1, "rank", exits.index + 1)
    return exits.round(4)


# ── 3. dark-horse / overperformance index ────────────────────────────────────
def dark_horse_table() -> pd.DataFrame:
    """Each team's deep-run probability vs the average of its seeding pot.

    ``deep_run`` = P(reach the semi-finals) (the ``sf`` column). ``pot_baseline``
    is the mean ``deep_run`` of the team's pot peers; ``overperformance`` is the
    gap. Positive = the model is more bullish than the seeding implies — the
    contrarian dark horses. Sorted by ``overperformance`` descending.
    """
    t = _read("tournament_probs_initial.csv")[["team", "sf", "champion"]].copy()
    pots = pd.read_csv(WC26_POTS_PATH)
    df = t.merge(pots, on="team", how="left").rename(columns={"sf": "deep_run"})
    df["pot_baseline"] = df.groupby("pot")["deep_run"].transform("mean")
    df["overperformance"] = df["deep_run"] - df["pot_baseline"]
    return (
        df[["team", "pot", "champion", "deep_run", "pot_baseline", "overperformance"]]
        .sort_values("overperformance", ascending=False)
        .round(4)
        .reset_index(drop=True)
    )


# ── 4. per-slot R32 bracket marginals ────────────────────────────────────────
def r32_bracket_marginals(top_k: int = 3) -> pd.DataFrame:
    """Modal occupant (with probability) of each Round-of-32 slot, plus runners-up.

    Reads ``r32_slot_occupancy.csv``. ``runners_up`` lists the next ``top_k - 1``
    most likely occupants as ``"Team (p)"`` strings — honest where no single team
    owns a slot (the third-place-fed ``"3ABCDF"`` slots especially).
    """
    occ = _read("r32_slot_occupancy.csv")
    rows = []
    for slot, grp in occ.groupby("slot"):
        grp = grp.sort_values("prob", ascending=False)
        top = grp.iloc[0]
        runners = grp.iloc[1:top_k]
        rows.append(
            {
                "match_number": int(top["match_number"]),
                "slot": slot,
                "opponent_slot": top["opponent_slot"],
                "modal_team": top["team"],
                "modal_prob": round(float(top["prob"]), 4),
                "runners_up": ", ".join(
                    f"{r.team} ({r.prob:.2f})" for r in runners.itertuples()
                ),
            }
        )
    return (
        pd.DataFrame(rows).sort_values(["match_number", "slot"]).reset_index(drop=True)
    )


# ── 5. marquee matchup probabilities ─────────────────────────────────────────
def _default_marquee_pairs(top: int = 6) -> list[tuple[str, str]]:
    t = _read("tournament_probs_initial.csv").sort_values("champion", ascending=False)
    return list(combinations(list(t["team"].head(top)), 2))


def marquee_matchups(pairs: Optional[list[tuple[str, str]]] = None) -> pd.DataFrame:
    """P(team X meets team Y) by stage, plus P(final) and P(X eliminates Y).

    For each pair, one row with the meeting probability at each knockout stage
    (``R32``..``FINAL``), the total ``p_meet_any``, and the two directed
    elimination probabilities. Probabilities are unconditional (per the full
    tournament). Defaults to every pairing among the six title favorites.
    """
    if pairs is None:
        pairs = _default_marquee_pairs()
    opp = _read("opponent_distribution.csv")
    elim = _read("eliminations.csv")
    # meet_prob lookup: (team, opponent, stage) -> prob; symmetric in team/opponent.
    meet = {
        (r.team, r.opponent, r.stage): r.meet_prob for r in opp.itertuples(index=False)
    }
    elim_lk = {(r.winner, r.loser): r.prob for r in elim.itertuples(index=False)}
    rows = []
    for a, b in pairs:
        row = {"team_a": a, "team_b": b}
        total = 0.0
        for st in _KO_STAGES:
            p = meet.get((a, b, st), 0.0)
            row[f"p_{st.lower()}"] = round(p, 4)
            total += p
        row["p_meet_any"] = round(total, 4)
        row["p_a_elim_b"] = round(elim_lk.get((a, b), 0.0), 4)
        row["p_b_elim_a"] = round(elim_lk.get((b, a), 0.0), 4)
        rows.append(row)
    return (
        pd.DataFrame(rows)
        .sort_values("p_meet_any", ascending=False)
        .reset_index(drop=True)
    )


# ── 6. path difficulty ───────────────────────────────────────────────────────
def path_difficulty_table(src_dir: str = FORECAST_PATH) -> pd.DataFrame:
    """Expected opponent strength on each team's knockout route ("hardest route").

    From ``opponent_distribution.csv`` weighted by ``net_xg``. ``exp_ko_matches``
    = Σ meet_prob (expected knockout games played); ``path_strength_sum`` =
    Σ meet_prob · net_xg(opponent) (aggregate route toughness, rewards going far);
    ``avg_opp_strength`` = the per-match average (isolates draw difficulty from
    run depth). ``hardest_stage`` is where the toughest expected opponent sits.
    Sorted by ``avg_opp_strength`` — the genuine "hardest route" ranking.
    """
    opp = _read("opponent_distribution.csv", src_dir).copy()
    strength = _strength()
    opp["opp_strength"] = opp["opponent"].map(strength).fillna(0.0)
    opp["weighted"] = opp["meet_prob"] * opp["opp_strength"]
    agg = opp.groupby("team").agg(
        exp_ko_matches=("meet_prob", "sum"),
        path_strength_sum=("weighted", "sum"),
    )
    agg["avg_opp_strength"] = agg["path_strength_sum"] / agg["exp_ko_matches"]
    # Stage contributing the most expected opponent strength.
    by_stage = opp.groupby(["team", "stage"])["weighted"].sum()
    agg["hardest_stage"] = by_stage.groupby(level=0).idxmax().map(lambda x: x[1])
    champ = _read(_probs_filename(src_dir), src_dir).set_index("team")["champion"]
    agg["champion"] = champ
    # Sort by aggregate route toughness (the roadmap's "aggregate opponent
    # strength on the route to the final"); avg_opp_strength isolates draw luck
    # for the contender framing the showcase applies.
    return (
        agg.reset_index()
        .sort_values("path_strength_sum", ascending=False)
        .round(4)
        .reset_index(drop=True)
    )


# ── 7. favorite's most-likely title path ─────────────────────────────────────
def favorite_title_path(team: Optional[str] = None) -> pd.DataFrame:
    """The favorite's modal opponent at each knockout stage (a per-stage marginal).

    If ``team`` is None, picks the top champion-probability team. For each stage
    the modal opponent is ``argmax meet_prob``; ``p_conditional`` divides by the
    team's total meeting mass at that stage, i.e. P(opponent | team reached stage).
    Honest per-stage marginals — not a claim that this exact path occurs jointly.
    """
    t = _read("tournament_probs_initial.csv").sort_values("champion", ascending=False)
    if team is None:
        team = t.iloc[0]["team"]
    opp = _read("opponent_distribution.csv")
    sub = opp[opp["team"] == team]
    rows = []
    for st in _KO_STAGES:
        s = sub[sub["stage"] == st]
        if s.empty:
            continue
        reach_mass = s["meet_prob"].sum()
        top = s.sort_values("meet_prob", ascending=False).iloc[0]
        rows.append(
            {
                "stage": st,
                "modal_opponent": top["opponent"],
                "p_conditional": (
                    round(float(top["meet_prob"] / reach_mass), 4)
                    if reach_mass
                    else 0.0
                ),
            }
        )
    out = pd.DataFrame(rows)
    out.attrs["team"] = team
    return out


# ── 8. projected full bracket (modal R32 chained by re-simulation) ───────────
def project_modal_bracket(
    n_match: int = 10000,
    seed: int = 2026,
    src_dir: str = FORECAST_PATH,
    elo: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """Full chalk bracket: project a consistent group stage, then advance by re-sim.

    Builds one self-consistent group-stage outcome — per group the modal winner
    (argmax ``p1``), runner-up (argmax ``p2`` of the rest) and third (argmax
    ``p3_qualify`` of the rest) — then takes the **eight groups whose projected
    third-placer has the highest ``p3_qualify``** as the best-third qualifiers and
    routes them to their Round-of-32 slots through FIFA's actual Annex-C
    allocation (:func:`src.brackets.assign_third_place_slots`, the same table the
    Monte Carlo uses). Each tie is then **re-simulated ``n_match`` times** with the
    real engine (:func:`src.simulation.play_match`, extra time + shootouts
    included) from pre-tournament Elo, and the modal winner advances.

    Resolving the bracket from a single projected group stage (rather than
    stitching independent per-slot modals) guarantees consistency: every team
    appears once, and exactly eight third-placed teams qualify. This is a "chalk"
    projection — not a most-likely joint outcome (the honest marginals live in
    :func:`r32_bracket_marginals` and :func:`favorite_title_path`).

    Columns: ``match_number, round, team_a, team_b, projected_winner, p_winner``.
    """
    import numpy as np

    from src.brackets import assign_third_place_slots, load_third_place_map
    from src.simulation import _resolve_slot, load_sim_inputs, play_match

    inputs = load_sim_inputs()
    rng = np.random.default_rng(seed)
    # When driven from a live re-sim, use the re-scraped Elo for the per-tie sims
    # so the projected bracket reflects the same ratings as the headline re-sim.
    elo0 = elo if elo is not None else inputs.elo0

    # Project one consistent group stage: within each group fill 1st/2nd/3rd/4th
    # greedily (argmax p1, then argmax p2 of the rest, then argmax p3_qualify of
    # the rest) so no team takes two positions.
    gs = group_standings_table(src_dir)
    group_results: dict[str, dict[int, str]] = {}
    third_p3q: dict[str, float] = {}
    for grp, sub in gs.groupby("group"):
        taken: set[str] = set()
        positions: dict[int, str] = {}
        for pos, col in ((1, "p1"), (2, "p2"), (3, "p3_qualify")):
            rem = sub[~sub["team"].isin(taken)]
            row = rem.loc[rem[col].idxmax()]
            positions[pos] = row["team"]
            taken.add(row["team"])
            if pos == 3:
                third_p3q[grp] = float(row["p3_qualify"])
        positions[4] = sub[~sub["team"].isin(taken)].iloc[0]["team"]
        group_results[grp] = positions

    # The eight best third-placed teams qualify — pick the eight groups whose
    # projected third has the highest p3_qualify, then route them to R32 slots via
    # FIFA's published allocation (the engine's own table).
    qualifying_groups = set(
        sorted(third_p3q, key=lambda g: third_p3q[g], reverse=True)[:8]
    )
    assignment = assign_third_place_slots(qualifying_groups, load_third_place_map())

    def resolve(token: str, m: dict, winners: dict[int, str]) -> Optional[str]:
        if token.startswith("W"):
            return winners.get(int(token[1:]))
        if token.startswith("RU"):  # third-place play-off — not on the title path
            return None
        # Group winner / runner-up / best-third slot — resolved with the engine's
        # own slot logic against the projected group stage (winners/losers unused).
        return _resolve_slot(token, m, group_results, assignment, {}, {})

    winners: dict[int, str] = {}
    rows = []
    for m in sorted(inputs.knockout, key=lambda x: x["num"]):
        a = resolve(m["slot_a"], m, winners)
        b = resolve(m["slot_b"], m, winners)
        if a is None or b is None:  # skip the third-place play-off
            continue
        wins_a = 0
        with CUSTOM_PROGRESS as p:
            for _ in p.track(
                range(n_match), description="Simulating individual matchups..."
            ):
                elo_pair = {a: elo0[a], b: elo0[b]}  # fresh ratings for this tie
                res = play_match(
                    a,
                    b,
                    elo_pair,
                    inputs,
                    rng,
                    knockout=True,
                    host_country=m["host_country"],
                )
                if res["winner"] == a:
                    wins_a += 1
        p_a = wins_a / n_match
        winner = a if p_a >= 0.5 else b
        winners[m["num"]] = winner
        rows.append(
            {
                "match_number": m["num"],
                "round": m["stage_label"],
                "team_a": a,
                "team_b": b,
                "projected_winner": winner,
                "p_winner": round(max(p_a, 1 - p_a), 4),
            }
        )
    return pd.DataFrame(rows)


# ── 9. most common knockout matchups ─────────────────────────────────────────
def most_common_matchups(top_k: int = 10, src_dir: str = FORECAST_PATH) -> pd.DataFrame:
    """The ``top_k`` most likely knockout matchups across the whole bracket.

    From ``opponent_distribution.csv``: two teams meet at most once in the
    knockouts, so summing ``meet_prob`` over all knockout stages for an unordered
    pair gives ``p_meet`` = P(they face each other somewhere in the bracket). The
    distribution is symmetric (each tie is tallied from both perspectives), so a
    single orientation (``team < opponent``) is kept to avoid double counting.
    ``modal_stage`` is the stage at which the pair is most likely to meet.
    Columns: ``team_a, team_b, p_meet, modal_stage``.
    """
    opp = _read("opponent_distribution.csv", src_dir)
    opp = opp[opp["stage"].isin(_KO_STAGES) & (opp["team"] < opp["opponent"])].copy()
    agg = (
        opp.groupby(["team", "opponent"])
        .agg(p_meet=("meet_prob", "sum"))
        .reset_index()
    )
    modal = (
        opp.loc[opp.groupby(["team", "opponent"])["meet_prob"].idxmax()]
        .rename(columns={"stage": "modal_stage"})[["team", "opponent", "modal_stage"]]
    )
    out = agg.merge(modal, on=["team", "opponent"]).rename(
        columns={"team": "team_a", "opponent": "team_b"}
    )
    return (
        out.sort_values("p_meet", ascending=False)
        .head(top_k)
        .round(4)
        .reset_index(drop=True)
    )


# ── 10. biggest title-odds movers vs the pre-tournament forecast ─────────────
def champion_prob_delta(
    top_k: int = 16,
    src_dir: str = FORECAST_PATH,
    initial_path: str = f"{FORECAST_PATH}/tournament_probs_initial.csv",
) -> pd.DataFrame:
    """Largest champion-probability increases since the pre-tournament forecast.

    Joins the re-sim's champion column (``{src_dir}/tournament_probs_updated.csv``)
    onto the locked pre-tournament column (``initial_path``) on ``team`` and ranks
    by the increase. Columns: ``team, champion_initial, champion_updated, delta``;
    returns the ``top_k`` biggest risers.
    """
    updated = _read(_probs_filename(src_dir), src_dir).set_index("team")["champion"]
    initial = pd.read_csv(initial_path).set_index("team")["champion"]
    out = pd.DataFrame(
        {"champion_initial": initial, "champion_updated": updated}
    ).dropna(subset=["champion_updated"])
    out["delta"] = out["champion_updated"] - out["champion_initial"]
    return (
        out.reset_index()
        .sort_values("delta", ascending=False)
        .head(top_k)
        .round(4)
        .reset_index(drop=True)
    )
