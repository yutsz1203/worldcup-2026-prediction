from typing import Callable, Mapping

import numpy as np
import pandas as pd

# A param "row" is anything supporting __getitem__ by column name: a pandas
# Series (from .iloc) or a plain dict. The float-based helpers below take these
# directly so callers can pre-extract params into dicts and avoid per-call
# DataFrame lookups in hot loops (e.g. the tournament simulation).
ParamRow = Mapping[str, float]


def independent_rates(
    elo_a: float, elo_b: float, p_a: ParamRow, p_b: ParamRow
) -> tuple[float, float]:
    """Core independent bivariate-Poisson rates from raw Elo floats + param rows.

    Returns (lambda_a_given_b, lambda_b_given_a): expected goals for team A and B.
    """
    mu_a = np.exp(p_a["intercept_attack"] + p_a["elo_o_attack"] * elo_b)
    nu_b = np.exp(p_b["intercept_defense"] + p_b["elo_o_defense"] * elo_a)

    mu_b = np.exp(p_b["intercept_attack"] + p_b["elo_o_attack"] * elo_a)
    nu_a = np.exp(p_a["intercept_defense"] + p_a["elo_o_defense"] * elo_b)

    return (mu_a + nu_b) / 2, (mu_b + nu_a) / 2


def nested_rates(
    elo_strong: float,
    elo_weak: float,
    base_strong: ParamRow,
    base_weak: ParamRow,
    nested_weak: ParamRow,
) -> tuple[float, Callable[[int], float]]:
    """Core nested rates from raw Elo floats + param rows.

    `elo_strong >= elo_weak` must already hold. Returns the stronger team's
    independent rate and a callable g_a -> lambda_weak for the weaker team.
    """
    mu_a = np.exp(
        base_strong["intercept_attack"] + base_strong["elo_o_attack"] * elo_weak
    )
    nu_b = np.exp(
        base_weak["intercept_defense"] + base_weak["elo_o_defense"] * elo_strong
    )
    lambda_strong = (mu_a + nu_b) / 2

    base = nested_weak["intercept"] + nested_weak["e_a"] * elo_strong
    coef_g_a = nested_weak["g_a"]

    def lambda_weak_fn(g_a: int) -> float:
        return np.exp(base + coef_g_a * g_a)

    return lambda_strong, lambda_weak_fn


def get_independent_rates(
    team_a: str, team_b: str, elo: pd.DataFrame, params: pd.DataFrame
) -> tuple[float, float]:
    """Generate the poisson rates of the independent poisson model for goal scores by team a and b."""

    elo_a = elo.loc[elo["team"] == team_a, "elo_ratings"].item()
    elo_b = elo.loc[elo["team"] == team_b, "elo_ratings"].item()

    p_a = params.loc[params["team"] == team_a].iloc[0]
    p_b = params.loc[params["team"] == team_b].iloc[0]

    return independent_rates(elo_a, elo_b, p_a, p_b)


def get_nested_rates(
    team_a: str,
    team_b: str,
    elo: pd.DataFrame,
    base_params: pd.DataFrame,
    nested_params: pd.DataFrame,
) -> tuple[float, Callable[[int], float]]:
    """
    Compute the independent Poisson rate for the stronger team and the nested
    rate for the weaker team as a function of the stronger team's realised goals.

    Teams are reordered internally so the higher-Elo team is the "stronger" side.

    Returns
    -------
    lambda_strong : float
        Independent Poisson rate λ_A|B for the stronger team.
    lambda_weak_fn : Callable[[int], float]
        Function g_a -> λ_B|A. Pass the *realised* goals of the stronger team
        to get the weaker team's rate. Use a single draw for simulation, or
        evaluate over a grid of g_a for analytic probability extraction.
    """
    elo_1 = elo.loc[elo["team"] == team_a, "elo_ratings"].item()
    elo_2 = elo.loc[elo["team"] == team_b, "elo_ratings"].item()

    if elo_1 < elo_2:
        elo_a, elo_b = elo_2, elo_1
        team_a, team_b = team_b, team_a
    else:
        elo_a, elo_b = elo_1, elo_2

    base_p_a = base_params.loc[base_params["team"] == team_a].iloc[0]
    base_p_b = base_params.loc[base_params["team"] == team_b].iloc[0]
    nested_p_b = nested_params.loc[nested_params["team"] == team_b].iloc[0]

    return nested_rates(elo_a, elo_b, base_p_a, base_p_b, nested_p_b)
