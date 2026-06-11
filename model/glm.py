from typing import Tuple

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.genmod.generalized_linear_model import GLMResultsWrapper


def create_baseline_model_data(
    df: pd.DataFrame, team: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    home_df = df[df["home_team"] == team].copy()
    away_df = df[df["away_team"] == team].copy()

    # Home-advantage covariate from the team's perspective: +1 when it plays at
    # home on a non-neutral pitch, -1 when away on a non-neutral pitch, 0 on
    # neutral ground. Sparse teams' training sets are broadened to include
    # non-neutral major/Nations-League matches, so this term lets the fit absorb
    # the venue effect instead of leaking it into the Elo slope/intercept. It is
    # 0 for neutral-only (non-sparse) teams, so fit_baseline drops it; WC26
    # predictions are neutral (home_adv = 0), so the term vanishes at predict time.
    home_adv_home = (~home_df["neutral"].astype(bool)).astype(int)
    home_adv_away = -(~away_df["neutral"].astype(bool)).astype(int)

    attack_home_df = pd.DataFrame(
        {
            "date": home_df["date"].dt.tz_localize(None),
            "goals": home_df["home_score"],
            "elo_o": home_df["away_elo"],
            "home_adv": home_adv_home,
        }
    )

    attack_away_df = pd.DataFrame(
        {
            "date": away_df["date"].dt.tz_localize(None),
            "goals": away_df["away_score"],
            "elo_o": away_df["home_elo"],
            "home_adv": home_adv_away,
        }
    )

    defense_home_df = pd.DataFrame(
        {
            "date": home_df["date"].dt.tz_localize(None),
            "goals": home_df["away_score"],
            "elo_o": home_df["away_elo"],
            "home_adv": home_adv_home,
        }
    )

    defense_away_df = pd.DataFrame(
        {
            "date": away_df["date"].dt.tz_localize(None),
            "goals": away_df["home_score"],
            "elo_o": away_df["home_elo"],
            "home_adv": home_adv_away,
        }
    )

    attack_df = pd.concat([attack_home_df, attack_away_df], ignore_index=True)
    defense_df = pd.concat([defense_home_df, defense_away_df], ignore_index=True)

    return attack_df, defense_df


def fit_baseline(
    df: pd.DataFrame,
    team: str,
    cat: str,
    T: pd.Timestamp = pd.Timestamp("2026-06-11"),
    lam: float = np.log(2) / (12 * 365),  # tuned: ~half-weight at 12 years
    floor: float = 0.1,
    use_home_adv: bool = True,
) -> GLMResultsWrapper:
    model_df = df.copy()
    model_df["days_ago"] = (T - model_df["date"]).dt.days
    model_df["weight"] = np.maximum(np.exp(-lam * model_df["days_ago"]), floor)

    # Add the home-advantage term only when enabled AND the training set actually
    # contains non-neutral matches (sparse teams). For neutral-only teams home_adv
    # is all zeros — a degenerate column that would break the GLM — so the formula
    # stays exactly "goals ~ elo_o" and their fits are unchanged. Passing
    # use_home_adv=False drops the term even for sparse teams (the ablation knob).
    formula = "goals ~ elo_o"
    if use_home_adv and "home_adv" in model_df and model_df["home_adv"].nunique() > 1:
        formula += " + home_adv"

    model = smf.glm(
        formula=formula,
        data=model_df,
        family=sm.families.Poisson(),
        freq_weights=model_df["weight"],
    )

    res = model.fit()

    return res


def fit_baseline_all(
    TEAM_LIST: list[str],
    df: pd.DataFrame,
    T: pd.Timestamp = pd.Timestamp("2026-06-11"),
    lam: float = np.log(2) / (12 * 365),  # tuned: ~half-weight at 12 years
    floor: float = 0.1,
    verbose: bool = True,
    use_home_adv: bool = True,
) -> pd.DataFrame:
    """Fit the baseline attack/defense models for every team.

    ``T`` is the decay anchor (tournament start), ``lam`` the exponential decay
    rate, and ``floor`` the minimum match weight. All three are threaded through
    to ``fit_baseline`` so a backtest / tuning sweep can re-anchor at a historical
    start date and vary the decay. Callers should pre-filter ``df`` to matches
    before that date to avoid leaking future results. Pass ``verbose=False`` to
    silence the per-team progress print (e.g. in the tuning grid).
    """
    rows = []
    for team in TEAM_LIST:
        if verbose:
            print(f"Fitting baseline models for {team}")
        attack_df, defense_df = create_baseline_model_data(df, team)
        attack_params = fit_baseline(
            attack_df,
            team,
            "attack",
            T=T,
            lam=lam,
            floor=floor,
            use_home_adv=use_home_adv,
        ).params
        defense_params = fit_baseline(
            defense_df,
            team,
            "defense",
            T=T,
            lam=lam,
            floor=floor,
            use_home_adv=use_home_adv,
        ).params
        rows.append(
            {
                "team": team,
                "intercept_attack": attack_params["Intercept"],
                "elo_o_attack": attack_params["elo_o"],
                "intercept_defense": defense_params["Intercept"],
                "elo_o_defense": defense_params["elo_o"],
            }
        )

    return pd.DataFrame(rows)


def create_nested_model_data(df: pd.DataFrame, team: str) -> pd.DataFrame:
    home_df_raw = df[
        (df["home_team"] == team) & (df["home_elo"] <= df["away_elo"])
    ].copy()
    away_df_raw = df[
        (df["away_team"] == team) & (df["away_elo"] <= df["home_elo"])
    ].copy()

    home_df = pd.DataFrame(
        {
            "date": home_df_raw["date"].dt.tz_localize(None),
            "g_b": home_df_raw["home_score"],
            "e_a": home_df_raw["away_elo"],
            "g_a": home_df_raw["away_score"],
        }
    )

    away_df = pd.DataFrame(
        {
            "date": away_df_raw["date"].dt.tz_localize(None),
            "g_b": away_df_raw["away_score"],
            "e_a": away_df_raw["home_elo"],
            "g_a": away_df_raw["home_score"],
        }
    )

    return pd.concat([home_df, away_df])


def fit_nested(
    df: pd.DataFrame,
    team: str,
    cat: str,
    T: pd.Timestamp = pd.Timestamp("2026-06-11"),
    lam: float = np.log(2) / (12 * 365),  # tuned: ~half-weight at 12 years
) -> GLMResultsWrapper:
    model_df = df.copy()
    model_df["days_ago"] = (T - model_df["date"]).dt.days
    model_df["weight"] = np.maximum(np.exp(-lam * model_df["days_ago"]), 0.1)

    model = smf.glm(
        formula="g_b ~ e_a + g_a",
        data=model_df,
        family=sm.families.Poisson(),
        freq_weights=model_df["weight"],
    )

    res = model.fit()

    return res


def fit_nested_all(
    TEAM_LIST: list[str],
    df: pd.DataFrame,
    T: pd.Timestamp = pd.Timestamp("2026-06-11"),
    lam: float = np.log(2) / (12 * 365),  # tuned: ~half-weight at 12 years
) -> pd.DataFrame:
    """
    Fitting the nested poisson model for the weaker side.
    Assume E_A > E_B.
    It is trying to model the number of goals G_B scored by B: log lambda_B(E_A, G_A) = gamma_0 + gamma_1 * E_A + gamma_2 * G_A
    where E_A is the elo of team A, G_A is the goal scored by A.
    G_B has the poisson rate of lambda_B

    ``T`` (decay anchor) and ``lam`` (decay rate) are threaded through to
    ``fit_nested`` so a backtest can re-anchor at a historical tournament start.
    """
    rows = []
    for team in TEAM_LIST:
        print(f"Fitting nested models for {team}")
        b_df = create_nested_model_data(df, team)
        if b_df.empty:
            rows.append(
                {
                    "team": team,
                    "intercept": None,
                    "e_a": None,
                    "g_a": None,
                    "samples": 0,
                }
            )
        else:
            params = fit_nested(b_df, team, "attack", T=T, lam=lam).params
            rows.append(
                {
                    "team": team,
                    "intercept": params["Intercept"],
                    "e_a": params["e_a"],
                    "g_a": params["g_a"],
                    "samples": len(b_df),
                }
            )

    return pd.DataFrame(rows)
