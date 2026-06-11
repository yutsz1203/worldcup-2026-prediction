import json

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.genmod.generalized_linear_model import GLMResultsWrapper

from src.const import CLEANED_DATA_PATH, TEAM_LIST


def strength_inspection(elo_ratings: pd.DataFrame, params: pd.DataFrame):
    elo_ratings = elo_ratings[elo_ratings["team"].isin(TEAM_LIST)]
    ref_elo = np.mean(elo_ratings["elo_ratings"])

    attack_strength = {
        team: np.exp(
            params.loc[params["team"] == team, "intercept_attack"]
            + params.loc[params["team"] == team, "elo_o_attack"] * ref_elo
        ).values[0]
        for team in TEAM_LIST
    }

    defense_strength = {
        team: np.exp(
            params.loc[params["team"] == team, "intercept_defense"]
            + params.loc[params["team"] == team, "elo_o_defense"] * ref_elo
        ).values[0]
        for team in TEAM_LIST
    }

    sorted_attack_strength = sorted(attack_strength.items(), key=lambda x: -x[1])
    sorted_defense_strength = sorted(defense_strength.items(), key=lambda x: x[1])

    with open(f"{CLEANED_DATA_PATH}/attack_strength.json", "w") as f:
        json.dump(dict(sorted_attack_strength), f, indent=4)

    with open(f"{CLEANED_DATA_PATH}/defense_strength.json", "w") as f:
        json.dump(dict(sorted_defense_strength), f, indent=4)

    # Higher = more goals scored against an average opponent
    print("Attack ranking:")
    for team, val in sorted_attack_strength:
        print(f"  {team}: {val:.2f}")

    # Lower = fewer goals conceded against an average opponent
    print("\ndefense ranking:")
    for team, val in sorted_defense_strength:
        print(f"  {team}: {val:.2f}")


def p_val_inspection(res: GLMResultsWrapper, team: str, cat: str):
    """Inspect deviance and goodness-of-fit p values of the fitted models."""
    # Deviance-based GoF
    dof = res.df_resid
    p_deviance = 1 - stats.chi2.cdf(res.deviance, dof)

    # Pearson chi-squared GoF
    p_pearson = 1 - stats.chi2.cdf(res.pearson_chi2, dof)

    print(p_deviance, p_pearson)

    if p_deviance < 0.05:
        print(f"Poor deviance for {team} {cat}.")

    if p_pearson < 0.05:
        print(f"Poor pearson for {team} {cat}.")
