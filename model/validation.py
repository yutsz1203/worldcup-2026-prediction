"""Scoring rules for validating the model against historical tournaments.

Two layers:

* **Match level** — for every historical match, turn the refit baseline params
  plus the teams' as-of Elo into a 1X2 probability and score the realised
  outcome with the multiclass Brier score and the ranked probability score
  (RPS). Compared against a uniform (1/3, 1/3, 1/3) no-skill baseline scored on
  the same matches. A calibration table bins predicted win-probabilities into
  deciles and reports observed vs predicted.

* **Tournament level** — convert the Monte Carlo cumulative reach-probabilities
  into an exact per-stage distribution and score it against the stage each team
  actually reached with the paper's four rules: E1 (max-likelihood error),
  E2 (weighted ordinal error), Brier, and RPS.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from model.probabilities import generate_probabilities
from model.rates import independent_rates
from src.const import VALIDATION_PATH

# 1X2 outcomes are ordered home-win < draw < away-win for the RPS.
OUTCOME_LABELS = ["home", "draw", "away"]


# ── Pure scoring rules ───────────────────────────────────────────────────────
def brier_multiclass(probs: np.ndarray, outcome_idx: int) -> float:
    """Multiclass Brier score: sum_k (p_k - o_k)^2 (0 best, 2 worst)."""
    onehot = np.zeros(len(probs))
    onehot[outcome_idx] = 1.0
    return float(np.sum((np.asarray(probs) - onehot) ** 2))


def rps(probs: np.ndarray, outcome_idx: int) -> float:
    """Ranked probability score over ordered categories (0 best, 1 worst)."""
    probs = np.asarray(probs, dtype=float)
    onehot = np.zeros(len(probs))
    onehot[outcome_idx] = 1.0
    cum_p = np.cumsum(probs)
    cum_o = np.cumsum(onehot)
    return float(np.sum((cum_p - cum_o) ** 2) / (len(probs) - 1))


def _outcome_index(home_score: int, away_score: int) -> int:
    if home_score > away_score:
        return 0
    if home_score == away_score:
        return 1
    return 2


# ── Match-level validation ───────────────────────────────────────────────────
def score_matches(
    matches: pd.DataFrame, base_params: dict[str, dict]
) -> tuple[dict, pd.DataFrame]:
    """Score 1X2 predictions for a set of matches.

    ``matches`` needs columns ``home_team, away_team, home_score, away_score,
    home_elo, away_elo``. ``base_params`` maps team -> baseline param row (keys
    ``intercept_attack``/``elo_o_attack``/``intercept_defense``/``elo_o_defense``).

    Returns a metrics dict (mean Brier/RPS, accuracy, and the uniform-guess
    baselines) and a per-match DataFrame carrying the predicted probabilities,
    realised outcome, and per-match scores (the latter feeds calibration).
    """
    rows = []
    uniform = np.array([1 / 3, 1 / 3, 1 / 3])
    for _, m in matches.iterrows():
        home, away = m["home_team"], m["away_team"]
        if home not in base_params or away not in base_params:
            continue
        if pd.isna(m["home_elo"]) or pd.isna(m["away_elo"]):
            continue
        lam_home, lam_away = independent_rates(
            float(m["home_elo"]),
            float(m["away_elo"]),
            base_params[home],
            base_params[away],
        )
        # Clamp to a sane max: degenerate params (e.g. perfectly-separated sparse
        # fits) can blow a rate up so far the truncated score-matrix underflows to
        # all-zero probabilities. 15 goals mirrors the simulation's MAX_LAMBDA.
        lam_home, lam_away = min(lam_home, 15.0), min(lam_away, 15.0)
        long_info, _ = generate_probabilities(home, lam_home, away, lam_away)
        probs = np.array(
            [
                float(long_info["Home Probability"]),
                float(long_info["Draw Probability"]),
                float(long_info["Away Probability"]),
            ]
        )
        # Renormalise: the score-matrix is truncated at 20 goals so the three
        # outcome probabilities can fall a hair short of 1.
        probs = probs / probs.sum()
        outcome = _outcome_index(int(m["home_score"]), int(m["away_score"]))
        rows.append(
            {
                "home_team": home,
                "away_team": away,
                "p_home": probs[0],
                "p_draw": probs[1],
                "p_away": probs[2],
                "outcome": OUTCOME_LABELS[outcome],
                "predicted": OUTCOME_LABELS[int(np.argmax(probs))],
                "correct": int(np.argmax(probs) == outcome),
                "brier": brier_multiclass(probs, outcome),
                "rps": rps(probs, outcome),
            }
        )

    per_match = pd.DataFrame(rows)
    if per_match.empty:
        raise ValueError("No scorable matches (check team-name / Elo coverage).")

    base_brier = np.mean(
        [
            brier_multiclass(uniform, OUTCOME_LABELS.index(o))
            for o in per_match["outcome"]
        ]
    )
    base_rps = np.mean(
        [rps(uniform, OUTCOME_LABELS.index(o)) for o in per_match["outcome"]]
    )
    metrics = {
        "n_matches": len(per_match),
        "brier": float(per_match["brier"].mean()),
        "rps": float(per_match["rps"].mean()),
        "accuracy": float(per_match["correct"].mean()),
        "baseline_brier": float(base_brier),
        "baseline_rps": float(base_rps),
    }
    return metrics, per_match


def calibration_table(per_match: pd.DataFrame, bins: int = 10) -> pd.DataFrame:
    """Decile calibration of the home-win probability vs observed home-win rate."""
    df = per_match.copy()
    df["home_win"] = (df["outcome"] == "home").astype(int)
    edges = np.linspace(0, 1, bins + 1)
    df["bin"] = pd.cut(df["p_home"], edges, include_lowest=True)
    out = (
        df.groupby("bin", observed=True)
        .agg(
            n=("home_win", "size"),
            predicted=("p_home", "mean"),
            observed=("home_win", "mean"),
        )
        .reset_index()
    )
    return out


# ── Tournament-level validation ──────────────────────────────────────────────
def exact_stage_distribution(
    probs_table: pd.DataFrame, stage_order: dict[str, int]
) -> pd.DataFrame:
    """Convert cumulative reach-probabilities to an exact per-stage distribution.

    ``probs_table`` is the :func:`monte_carlo` output (a ``team`` column plus one
    cumulative column per non-GROUP stage, e.g. ``r16, qf, sf, final, champion``).
    Returns a frame with one exact-probability column per stage including
    ``group`` (P(exactly stage) = P(reach stage) - P(reach next stage)).
    """
    stages = sorted(stage_order, key=lambda s: stage_order[s])  # GROUP..CHAMPION
    out = {"team": probs_table["team"].tolist()}
    reach = {s: probs_table[s.lower()].to_numpy() for s in stages if s != "GROUP"}
    reach["GROUP"] = np.ones(len(probs_table))  # everyone "reaches" the group stage
    for i, s in enumerate(stages):
        nxt = stages[i + 1] if i + 1 < len(stages) else None
        out[s.lower()] = reach[s] - (reach[nxt] if nxt else 0.0)
    return pd.DataFrame(out)


def score_tournament(
    probs_table: pd.DataFrame,
    actual: dict[str, str],
    stage_order: dict[str, int],
) -> dict:
    """Score per-team stage predictions with E1, E2, Brier and RPS.

    Returns the tournament **totals** (each error summed over all participating
    teams, per Gilch & Müller — cf. their Table 7: 2014 32-team totals were
    E1≈26-28, E2≈34, Brier≈22, RPS≈5.5), not per-team means. ``actual`` maps team
    -> the stage label it reached; teams missing from either side are skipped.

    The paper encodes ``result(T)`` descending (1=winner … 6=group exit) whereas
    we keep the project's ascending GROUP=0 … CHAMPION order (the simulation's
    furthest-stage bookkeeping needs "higher = further"). All four scores are
    invariant to a consistent reversal of the ordinal index — E1/E2 use absolute
    distance, Brier is order-free, and RPS is symmetric under category reversal —
    so the totals are directly comparable to the paper's.
    """
    stages = sorted(stage_order, key=lambda s: stage_order[s])
    exact = exact_stage_distribution(probs_table, stage_order)
    cols = [s.lower() for s in stages]

    e1 = e2 = brier = rps_total = 0.0
    counted = 0
    for _, r in exact.iterrows():
        team = r["team"]
        if team not in actual:
            continue
        p = r[cols].to_numpy(dtype=float)
        actual_idx = stage_order[actual[team]]
        idxs = np.arange(len(stages))
        e1 += abs(int(np.argmax(p)) - actual_idx)
        e2 += float(np.sum(p * np.abs(idxs - actual_idx)))
        brier += brier_multiclass(p, actual_idx)
        rps_total += rps(p, actual_idx)
        counted += 1

    # Totals summed over all participating teams (Gilch & Müller): E1, E2, BS, RPS.
    return {
        "n_teams": counted,
        "E1": e1,
        "E2": e2,
        "brier": brier,
        "rps": rps_total,
    }


# ── Calibration plot ─────────────────────────────────────────────────────────
def plot_calibration(
    years: tuple[int, ...] = (2018, 2022),
    out_path: str | None = None,
) -> str:
    """Plot decile calibration (predicted vs observed home-win rate), years pooled.

    Pools the per-match predictions across all ``years`` (each
    ``validation_{year}_matches.csv``, carrying ``p_home``/``outcome``) and re-bins
    them with :func:`calibration_table` so every decile is weighted by its true
    match count — statistically sounder than averaging the per-year binned tables.
    The pooled binned table is also written to
    ``data/result/validation/validation_calibration.csv``. Points sit on the
    diagonal when predictions are perfectly calibrated; marker area scales with the
    bin count ``n``. Returns the saved PNG path (default
    ``data/result/validation/calibration.png``).
    """
    if out_path is None:
        out_path = f"{VALIDATION_PATH}/calibration.png"

    per_match = pd.concat(
        [
            pd.read_csv(f"{VALIDATION_PATH}/validation_{year}_matches.csv")
            for year in years
        ],
        ignore_index=True,
    )
    tbl = calibration_table(per_match)
    tbl.to_csv(f"{VALIDATION_PATH}/validation_calibration.csv", index=False)

    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot([0, 1], [0, 1], ls="--", c="grey", lw=1, label="perfect calibration")
    ax.scatter(
        tbl["predicted"],
        tbl["observed"],
        s=tbl["n"] * 18,
        c="tab:blue",
        alpha=0.7,
        edgecolors="white",
        linewidths=0.8,
        zorder=3,
        label="decile bin (area ∝ count)",
    )
    span = "+".join(str(y) for y in years)
    ax.set_title(f"Match-level calibration — WC {span} pooled (n = {len(per_match)})")
    ax.set_xlabel("Predicted home-win probability")
    ax.set_ylabel("Observed home-win rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal")
    ax.grid(True, ls=":", alpha=0.4)
    ax.legend(loc="upper left", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    saved = plot_calibration()
    print(f"Calibration plot → {saved}")
