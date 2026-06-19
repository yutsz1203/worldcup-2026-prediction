import numpy as np
from scipy.stats import poisson


def build_score_matrix(lambda_a: float, lambda_b: float) -> np.ndarray:
    """Joint scoreline pmf P(goals_a = i, goals_b = j) for independent Poissons.

    Truncated at 19 goals per team, so the matrix can sum a hair short of 1.
    """
    proba = [
        [poisson.pmf(i, mean) for i in range(0, 20)] for mean in [lambda_a, lambda_b]
    ]
    return np.outer(proba[0], proba[1])


def _rnd(x: float) -> int:
    """Round half up, matching datacamp_predictions.rnd."""
    return int(np.floor(x + 0.5))


def predicted_scoreline(
    lambda_a: float,
    lambda_b: float,
    p_home: float,
    p_draw: float,
    p_away: float,
) -> tuple[int, int]:
    """Most-representative integer scoreline for (team_a, team_b).

    Rounded expected goals, adjusted to agree with the modal 1X2 pick: if the
    rounded score implies a different outcome than the most-probable one, fall
    back to the modal scoreline within the picked outcome's region. Ports the
    consistency logic from ``competitions/datacamp/datacamp_predictions.py`` to
    the analytic score matrix.
    """
    score_matrix = build_score_matrix(lambda_a, lambda_b)
    rh, ra = _rnd(lambda_a), _rnd(lambda_b)
    pick = ("home", "draw", "away")[int(np.argmax([p_home, p_draw, p_away]))]
    rounded = "home" if rh > ra else "away" if rh < ra else "draw"
    if rounded != pick:
        if pick == "home":
            region = np.tril(score_matrix, -1)  # i > j
        elif pick == "away":
            region = np.triu(score_matrix, 1)  # i < j
        else:
            region = np.diag(np.diag(score_matrix))  # i == j
        rh, ra = np.unravel_index(int(np.argmax(region)), region.shape)
    return int(rh), int(ra)


def _settle_line(diff_grid: np.ndarray, score_matrix: np.ndarray, line: float) -> dict:
    """Settlement probabilities for the favorite at a whole or half-goal line.

    ``line`` is from the favorite's perspective (0 or negative); a push is only
    possible on whole-goal lines.
    """
    adjusted = diff_grid + line
    return {
        "p_win": float(score_matrix[adjusted > 0].sum()),
        "p_push": float(score_matrix[adjusted == 0].sum()),
        "p_lose": float(score_matrix[adjusted < 0].sum()),
    }


def fair_odds(outcome: dict) -> float:
    """Fair decimal odds for a side given its HDC settlement probabilities.

    Solves EV = stake under HKJC settlement: win -> o, half-win -> (o+1)/2,
    push -> 1, half-lose -> 1/2, lose -> 0.
    """
    p_hw = outcome.get("p_half_win", 0.0)
    p_hl = outcome.get("p_half_lose", 0.0)
    return (1 - outcome["p_push"] - (p_hw + p_hl) / 2) / (outcome["p_win"] + p_hw / 2)


def settlement_ev(outcome: dict, odds: float) -> float:
    """Expected edge per unit stake at offered ``odds`` (0 = break-even).

    Same settlement model as :func:`fair_odds`: win -> odds, half-win ->
    (odds+1)/2, push -> 1, half-lose -> 1/2, lose -> 0.
    """
    p_hw = outcome.get("p_half_win", 0.0)
    p_hl = outcome.get("p_half_lose", 0.0)
    return (
        odds * outcome["p_win"]
        + (odds + 1) / 2 * p_hw
        + outcome["p_push"]
        + p_hl / 2
        - 1
    )


def min_odds(outcome: dict, edge: float = 0.05) -> float:
    """Lowest offered decimal odds at which the bet clears ``edge`` EV per stake.

    Same settlement model as :func:`fair_odds`, solved for EV = 1 + edge instead
    of EV = 1.
    """
    p_hw = outcome.get("p_half_win", 0.0)
    p_hl = outcome.get("p_half_lose", 0.0)
    return (1 + edge - outcome["p_push"] - (p_hw + p_hl) / 2) / (
        outcome["p_win"] + p_hw / 2
    )


def generate_handicap_probabilities(
    lambda_fav: float, lambda_dog: float, lines: list[float]
) -> dict[float, dict]:
    """HKJC HDC settlement probabilities for the favorite at each handicap line.

    ``lines`` are from the favorite's perspective (0 or negative, in 0.25 steps).
    Each line maps to ``p_win / p_half_win / p_push / p_half_lose / p_lose`` for
    the favorite; the underdog's outcomes at the mirrored ``+line`` are the same
    dict read in reverse (win <-> lose, half-win <-> half-lose). Quarter lines
    settle as half the stake on each adjacent whole/half line.
    """
    score_matrix = build_score_matrix(lambda_fav, lambda_dog)
    score_matrix /= score_matrix.sum()  # renormalise the truncation shortfall

    rows, cols = np.indices(score_matrix.shape)
    diff_grid = rows - cols

    results = {}
    for line in lines:
        if (line * 4) % 1 != 0:
            raise ValueError(f"Handicap line {line} is not a multiple of 0.25")
        if (line * 2) % 1 == 0:  # whole or half-goal line: single settlement
            s = _settle_line(diff_grid, score_matrix, line)
            results[line] = {
                "p_win": s["p_win"],
                "p_half_win": 0.0,
                "p_push": s["p_push"],
                "p_half_lose": 0.0,
                "p_lose": s["p_lose"],
            }
        else:  # quarter line: half stake on each adjacent line
            lo = _settle_line(diff_grid, score_matrix, line - 0.25)
            hi = _settle_line(diff_grid, score_matrix, line + 0.25)
            # The adjusted diffs differ by 0.5, so at most one component pushes.
            results[line] = {
                "p_win": min(lo["p_win"], hi["p_win"]),
                "p_half_win": abs(hi["p_win"] - lo["p_win"]),
                "p_push": 0.0,
                "p_half_lose": abs(hi["p_lose"] - lo["p_lose"]),
                "p_lose": min(lo["p_lose"], hi["p_lose"]),
            }
    return results


def generate_probabilities(
    team_a: str, lambda_a: np.float64, team_b: str, lambda_b: np.float64
) -> tuple[dict, dict]:
    """
    Return
    long_info:
    {'Predicted Outcome': 'England',
     'Home Probability': np.float64(0.5165),
     'Away Probability': np.float64(0.2122),
     'Draw Probability': np.float64(0.2672),
     'Over 2.5': np.float64(0.3942),
     'Under 2.5': np.float64(0.6058),
     'Over 3.5': np.float64(0.1922),
     'Under 3.5': np.float64(0.8078)}

    short_info:
    {'Outcome': 'England (0.5165)', 2.5: 'Under (0.6058)', 3.5: 'Under (0.8078)'}
    """

    long_info, short_info = {}, {}

    score_matrix = build_score_matrix(lambda_a, lambda_b)

    home_prob = np.round(np.sum(np.tril(score_matrix, -1)), 4)
    draw_prob = np.round(np.trace(score_matrix), 4)
    away_prob = np.round(np.sum(np.triu(score_matrix, 1)), 4)

    outcomes = np.array([home_prob, draw_prob, away_prob])
    labels = np.array([team_a, "Draw", team_b])
    prediction = labels[np.argmax(outcomes)]

    long_info["Predicted Outcome"] = str(prediction)

    short_info["Outcome"] = f"{prediction} ({np.max(outcomes)})"

    long_info["Home Probability"] = home_prob
    long_info["Away Probability"] = away_prob
    long_info["Draw Probability"] = draw_prob

    rows, cols = np.indices(score_matrix.shape)
    total_goals_grid = rows + cols

    thresholds = [2.5, 3.5]

    for t in thresholds:
        over_prob = score_matrix[total_goals_grid > t].sum()
        under_prob = 1 - over_prob

        long_info[f"Over {t}"] = np.round(over_prob, 4)
        long_info[f"Under {t}"] = np.round(under_prob, 4)

        if over_prob > under_prob:
            short_info[t] = f"Over ({over_prob:.4f})"
        else:
            short_info[t] = f"Under ({under_prob:.4f})"

    return long_info, short_info
