"""Turn a fetched :class:`~jumpcup.fetch.MatchBundle` into the base-rates CSV.

One tidy row per (entity, stat, half): ``rates_{event_id}.csv`` under
``jumpcup/data/cleaned/``. Every full-time λ is split evenly across H1/H2 (v1
simplification — empirically H2 carries ~56% of goals; refinement is on the
roadmap), so the CSV only stores H1/H2 rows and FT is always their sum.

Rate sources, per stat:

- **goal** — the existing GLM (:func:`model.rates.get_independent_rates` on the
  latest Elo + baseline params), the same numbers behind the tournament forecast.
- **shot_on_target / foul / card** — aggregated from the lineup players' pooled
  per-90s over their most recent ``N_RECENT_ROWS`` matches (rows are undated; the
  row count approximates "current season"), scaled by expected minutes and a
  coverage factor that re-inflates for minutes the feed's XI doesn't cover (the
  lineup has no bench, so coverage ≈ 990/880). No opponent adjustment in v1:
  per-90s already average over mixed club/international opposition and Elo is only
  calibrated for goals.
- **corner / offside** — absent from player stats, so a 50/50 blend of the team's
  own past-year per-match mean and the opponent's conceded mean (team-level match
  stats), falling back to own-only when the opponent has thin coverage.
- **penalty_awarded / red_card** — no endpoint carries usable rates; configurable
  match-level priors split evenly per team.

Player rows (goal / assist / shot_on_target) are share-normalized so each team's
player goal λs sum *exactly* to the team GLM λ — player events stay consistent
with the match-level model. The same scale factor is applied to assists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from jumpcup.const import rates_path
from jumpcup.fetch import MatchBundle, SideBundle
from model.rates import get_independent_rates
from src.bzzoiro import make_match_uid
from src.const import CON

ELO_LATEST_PATH = "data/raw/elo_latest.csv"
BASELINE_PARAMS_PATH = "data/cleaned/baseline_params.csv"

MAX_LAMBDA = 15.0  # same clamp as src/forecast.py
N_RECENT_ROWS = 25  # per-player "current season" proxy (rows are undated)
LOW_OBS_ROWS = 5  # below this many rows a player rate is flagged low_obs
STARTER_MIN = 80.0  # expected minutes for a starting-XI player
TEAM_MIN = 990.0  # 11 slots x 90 minutes to cover per team
MIN_OPP_TEAM_MATCHES = 5  # opponent-conceded blend needs at least this coverage

# Match-total priors (no API source); split evenly per team. P(>=1 pen) ~= 0.26,
# P(>=1 red) ~= 0.15 — broadly in line with recent World Cup base rates.
PENALTY_LAMBDA_FT = 0.30
RED_CARD_LAMBDA_FT = 0.16

# Fallbacks when a team has no covered match in the past-year window.
CORNER_LAMBDA_DEFAULT = 5.0
OFFSIDE_LAMBDA_DEFAULT = 2.0

# player-stats row field -> our stat name, for the player-aggregated stats
PLAYER_STAT_FIELDS = {
    "goal": "goals",
    "assist": "goal_assist",
    "shot_on_target": "shots_on_target",
    "foul": "fouls",
}


def _player_per90(rows: list[dict]) -> tuple[dict[str, float], int, float]:
    """Pooled per-90 rates over the most recent N played rows.

    Returns (per90 dict incl. 'card', n_rows_used, minutes_summed). Pooling
    (sum stat / sum minutes) rather than averaging per-match per-90s keeps
    cameo appearances from dominating.
    """
    played = [r for r in rows if (r.get("minutes_played") or 0) > 0][:N_RECENT_ROWS]
    minutes = sum(r["minutes_played"] for r in played)
    per90: dict[str, float] = {}
    if minutes == 0:
        return {s: 0.0 for s in (*PLAYER_STAT_FIELDS, "card")}, 0, 0.0
    for stat, fld in PLAYER_STAT_FIELDS.items():
        per90[stat] = 90.0 * sum(r.get(fld) or 0 for r in played) / minutes
    cards = sum((r.get("yellow_card") or 0) + (r.get("red_card") or 0) for r in played)
    per90["card"] = 90.0 * cards / minutes
    return per90, len(played), minutes


def _team_stat_mean(rows: list[dict], side: str, key: str) -> Optional[float]:
    vals = [r[side].get(key) for r in rows if r[side].get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def _blended_team_rate(
    own_rows: list[dict], opp_rows: list[dict], key: str, default: float
) -> tuple[float, str, int]:
    """50/50 blend of own 'for' mean and opponent 'conceded' mean (corners/offsides)."""
    own = _team_stat_mean(own_rows, "for", key)
    conceded = _team_stat_mean(opp_rows, "against", key)
    if own is None:
        return default, "prior", 0
    if conceded is None or len(opp_rows) < MIN_OPP_TEAM_MATCHES:
        return own, "team_match_for_only", len(own_rows)
    return 0.5 * own + 0.5 * conceded, "team_match_blend", len(own_rows)


def build_rates(
    bundle: MatchBundle, elo: pd.DataFrame, params: pd.DataFrame
) -> pd.DataFrame:
    lam_a, lam_b = get_independent_rates(
        bundle.a.team_name, bundle.b.team_name, elo, params
    )
    lam_a, lam_b = min(lam_a, MAX_LAMBDA), min(lam_b, MAX_LAMBDA)

    is_knockout = bundle.event.get("group_name") is None
    meta = {
        "event_id": bundle.event_id,
        "match_uid": make_match_uid(
            bundle.a.team_name, bundle.b.team_name, is_knockout
        ),
        "elo_retrieved_date": str(elo["retrieved_date"].iloc[0])
        if "retrieved_date" in elo.columns
        else "",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    rows: list[dict] = []

    def emit(
        side: SideBundle,
        entity_type: str,
        stat: str,
        lam_ft: float,
        source: str,
        player_name: str = "",
        n_obs: int = 0,
        minutes_obs: float = 0.0,
        low_obs: bool = False,
    ) -> None:
        for window in ("H1", "H2"):
            rows.append(
                {
                    **meta,
                    "team_key": side.team_key,
                    "team_name": side.team_name,
                    "entity_type": entity_type,
                    "player_name": player_name,
                    "stat": stat,
                    "window": window,
                    "lam": lam_ft / 2.0,
                    "source": source,
                    "n_obs": n_obs,
                    "minutes_obs": minutes_obs,
                    "low_obs": low_obs,
                }
            )

    for side, opp, lam_goal in (
        (bundle.a, bundle.b, lam_a),
        (bundle.b, bundle.a, lam_b),
    ):
        emit(side, "team", "goal", lam_goal, "glm")

        # --- player per-90s, expected minutes, coverage --------------------
        per90s: dict[int, dict[str, float]] = {}
        obs: dict[int, tuple[int, float]] = {}
        for p in side.players:
            per90, n, mins = _player_per90(side.player_rows[p["player_id"]])
            per90s[p["player_id"]] = per90
            obs[p["player_id"]] = (n, mins)
        exp_min = {p["player_id"]: STARTER_MIN for p in side.players}
        covered = sum(exp_min.values())
        coverage = TEAM_MIN / covered if covered else 1.0

        # --- team rates aggregated from the lineup --------------------------
        n_obs_team = sum(n for n, _ in obs.values())
        for stat in ("shot_on_target", "foul", "card"):
            lam_team = coverage * sum(
                per90s[pid][stat] * exp_min[pid] / 90.0 for pid in per90s
            )
            emit(side, "team", stat, lam_team, "player_agg", n_obs=n_obs_team)

        # --- corners / offsides: team match-stats blend ----------------------
        for stat, key, default in (
            ("corner", "corner_kicks", CORNER_LAMBDA_DEFAULT),
            ("offside", "offsides", OFFSIDE_LAMBDA_DEFAULT),
        ):
            lam_stat, source, n = _blended_team_rate(
                side.team_stat_rows, opp.team_stat_rows, key, default
            )
            emit(side, "team", stat, lam_stat, source, n_obs=n)

        # --- priors ----------------------------------------------------------
        emit(side, "team", "penalty_awarded", PENALTY_LAMBDA_FT / 2, "prior")
        emit(side, "team", "red_card", RED_CARD_LAMBDA_FT / 2, "prior")

        # --- player rows: goal shares normalized to the GLM team λ -----------
        raw_goal = {pid: per90s[pid]["goal"] * exp_min[pid] / 90.0 for pid in per90s}
        total_raw = sum(raw_goal.values())
        if total_raw > 0:
            scale = lam_goal / total_raw
            shares = {pid: raw * scale for pid, raw in raw_goal.items()}
        else:
            # degenerate: no lineup player has scored in-window; spread evenly
            # over outfielders so player events stay priceable.
            outfield = [p["player_id"] for p in side.players if p["position"] != "G"]
            shares = {pid: lam_goal / len(outfield) for pid in outfield}
            CON.print(
                f"[yellow]jumpcup:[/] {side.team_name}: no recent goals in the "
                "lineup — uniform outfield goal shares."
            )
        for p in side.players:
            pid = p["player_id"]
            n, mins = obs[pid]
            lam_p_goal = shares.get(pid, 0.0)
            scale = lam_p_goal / raw_goal[pid] if raw_goal.get(pid) else 0.0
            lam_p_assist = (
                scale * per90s[pid]["assist"] * exp_min[pid] / 90.0
                if total_raw > 0
                else 0.0
            )
            lam_p_sot = per90s[pid]["shot_on_target"] * exp_min[pid] / 90.0
            for stat, lam_p in (
                ("goal", lam_p_goal),
                ("assist", lam_p_assist),
                ("shot_on_target", lam_p_sot),
            ):
                emit(
                    side,
                    "player",
                    stat,
                    lam_p,
                    "player_agg",
                    player_name=p["name"],
                    n_obs=n,
                    minutes_obs=mins,
                    low_obs=n < LOW_OBS_ROWS,
                )

        team_goal_sum = sum(shares.values())
        assert abs(team_goal_sum - lam_goal) < 1e-9, (
            f"{side.team_name}: player goal shares ({team_goal_sum}) != GLM λ ({lam_goal})"
        )

    return pd.DataFrame(rows)


def write_rates(bundle: MatchBundle, out: Optional[str] = None) -> pd.DataFrame:
    elo = pd.read_csv(ELO_LATEST_PATH)
    params = pd.read_csv(BASELINE_PARAMS_PATH)
    df = build_rates(bundle, elo, params)
    out = out or rates_path(bundle.event_id)
    df.to_csv(out, index=False)

    ft = (
        df[df["entity_type"] == "team"]
        .groupby(["team_name", "stat"])["lam"]
        .sum()
        .unstack()
        .round(2)
    )
    CON.print(f"[green]jumpcup:[/] wrote {len(df)} rate rows to {out}")
    CON.print(ft)
    return df
