import numpy as np
from scipy.stats import poisson


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

    proba = [
        [poisson.pmf(i, mean) for i in range(0, 20)] for mean in [lambda_a, lambda_b]
    ]

    score_matrix = np.outer(proba[0], proba[1])
    np.round(score_matrix)

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
