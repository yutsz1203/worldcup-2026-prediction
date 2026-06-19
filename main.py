# ruff: noqa: F401 — imports feed the commented-out setup stages below; kept at the
# top so each stage is runnable as-is once uncommented.
#
# This file is the documented runbook for the ONE-TIME data-build / tuning setup
# (Stages 1–6 thread in-memory frames; Stage 9 redeploy is destructive) — uncomment a
# stage and `uv run python main.py`. Every RECURRING stage (the live layer, sim,
# backtests, diagnostics, showcase) has a no-edit-source command in src/cli.py; its
# docstring stays here as documentation with the command to run it.
#     uv run python -m src.cli --help
import pandas as pd

from model.glm import fit_baseline_all, fit_nested_all
from model.rates import get_nested_rates
from src.backtest import redeploy_2026, tune_hyperparameters
from src.const import CLEANED_DATA_PATH, RAW_DATA_PATH, TEAM_LIST
from src.data_preprocess import append_historical_elo, filter_historical_matches
from src.scraper import historical_elo, historical_matches, latest_elo

if __name__ == "__main__":
    """
    Stage 1 — Latest Elo ratings.

    Scrape current Elo for every team in TEAM_LIST from eloratings.net and write it
    to raw/elo_latest.csv. Re-read the cached CSV instead of re-scraping on later runs.
    """
    # elo_ratings = latest_elo()
    # elo_ratings = pd.read_csv(f"{RAW_DATA_PATH}/elo_latest.csv")

    """
    Stage 2 — Historical match results.

    Download the international match results dataset from Kaggle and write it to
    raw/international_football_results.csv.
    """
    # all_matches = historical_matches()

    """
    Stage 3 — Filter historical matches.

    Reduce the raw results to the modelling window / team set and write the cleaned
    frame to cleaned/matches.csv.
    """
    # filtered_matches = filter_historical_matches(all_matches)

    """
    Stage 4 — Historical Elo per team.

    Scrape each team's Elo history from eloratings.net/{country} (from 2019-01-01) to
    raw/elo_historical.csv. Requires cleaned/matches.csv to exist before running.
    """
    # historical_elo_df = historical_elo(filtered_matches)

    """
    Stage 5 — Attach Elo to each match.

    Merge both teams' Elo as of each match date onto matches.csv and write the joined
    frame to cleaned/matches_with_elo.csv.
    """
    # filtered_matches = pd.read_csv(f"{CLEANED_DATA_PATH}/filtered_matches.csv")
    # historical_elo_df = pd.read_csv(f"{RAW_DATA_PATH}/elo_historical.csv")
    # historical_matches_with_elo = append_historical_elo(
    #     filtered_matches, historical_elo_df
    # )

    """
    Stage 6 — Fit the baseline GLM.

    Fit the baseline Poisson regression (attack and defense) for every team and write
    the parameters to cleaned/baseline_params.csv.
    """
    # baseline_params = fit_baseline_all(TEAM_LIST, historical_matches_with_elo)
    # baseline_params.to_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv", index=False)

    """
    Stage 7 — Monte Carlo tournament simulation.  →  uv run python -m src.cli simulate

    Run the full tournament simulation and write per-team stage probabilities. The
    independent model is the default; pass --nested for the nested model. The run also
    writes per-team average goals-for/against (split into group-stage and pooled-knockout
    buckets) to forecast/team_goal_stats.csv — a Fantasy player-selection aid — and the
    per-team probability of finishing the group 1st/2nd/3rd/4th to
    forecast/group_position_probs.csv. The three projection artifacts (r32_slot_occupancy,
    opponent_distribution, eliminations) feed the Stage 12 showcase; they are accumulated
    in the same loop at no extra sim cost.
    """

    """
    Stage 8 — Validation / backtesting.  →  uv run python -m src.cli backtest

    Retrospective Brier/RPS/E1/E2 against the 2018 & 2022 World Cups using the tuned
    adaptive training filter. matches.csv is already rebuilt to 2010+ over the broader
    team set (rebuild_backtest_dataset re-scrapes Elo via Chrome if needed).
    """

    """
    Stage 9 — Hyperparameter tuning + 2026 redeploy (src/backtest.py).

    tune_hyperparameters() grids decay half-life / weight floor / lookback-length on
    pooled match-level RPS and writes data/result/tuning/tuning_grid.csv (the chosen
    params — half-life 8y, floor 0.1, 8-year lookback — are already the module defaults).
    redeploy_2026() refits baseline_params.csv with them and re-runs the sim, preserving
    the pre-tuning params + forecast.
    """
    # tune_hyperparameters()
    # redeploy_2026(n_sims=100000)

    """
    Stage 10 — Model diagnostics.  →  uv run python -m src.cli diagnostics

    Inspect the fitted baseline model. strength_inspection prints each team's attack/
    defense strength; fitted_match_counts and team_strengths write per-team fitted-match
    counts and attack/defense strength (xGF/xGA vs an average WC26 opponent) to
    data/result/forecast/{model_match_counts,team_strengths}.csv.
    """

    """
    Stage 11 — Live WC2026 layer (src/forecast.py, src/bzzoiro.py, src/ledger.py).
      uv run python -m src.cli forecast   # before a round: re-scrape Elo, lock the round
      uv run python -m src.cli results    # after matches finish: refresh actuals
      uv run python -m src.cli ledger     # join locked forecasts onto actuals
      uv run python -m src.cli score      # grade Brier/RPS/accuracy by market

    Rolling round-by-round forecaster: the covariate is live, the GLM is frozen. Run the
    per-round forecast once before each round kicks off — it re-scrapes Elo (reflecting
    every completed match), forecasts the earliest not-yet-locked round, and appends the
    locked probabilities to data/result/live/wc2026_match_probs.csv (written once, never
    recomputed; knockout matchups are read resolved from the bzzoiro feed). Refresh the
    predictions+actuals ledger as matches finish — it left-joins the locked forecasts
    onto ingested results for validation. Once a round's results are in the ledger,
    score_ledger (src/scoring.py) grades every match with match-level Brier/RPS/accuracy
    across the 1X2, O/U 2.5 and O/U 3.5 markets (plus a pooled Overall), prints a table
    per market, and writes data/result/live/wc2026_match_scores.csv.

    write_results (the `results` command) refreshes data/raw/wc26_results.csv from the
    bzzoiro API (the live source of truth) — run it before forecasting a round or
    rebuilding the ledger.

    The Streamlit dashboard (`uv run python -m src.cli dashboard`) is the readable view of
    the live layer: the locked round probabilities with fair odds and a market-comparison
    panel, plus an HKJC HDC EV tab that scrapes the posted lines + odds on demand
    (headless Chrome, src/hkjc.py) and prices each side with the model.
    """

    """
    Stage 12 — Projections + showcase.  →  uv run python -m src.cli showcase

    Render the headline derived deliverables (group-of-death, expected elimination,
    dark-horse index, R32 marginals, marquee matchups, path difficulty, the favorite's
    title path, and a projected bracket) into showcase.md with embedded charts and
    Mermaid diagrams. Reads only the Stage 7 forecast artifacts — no simulation — so it
    is fast and safe to re-run any time after a sim. (project_modal_bracket re-simulates
    each knockout tie with play_match to chain the modal bracket.)
    """

    # ────────────────────────────────────────────────────────────────────────────
    # Nested model — parked. Not part of the current pipeline; the independent model
    # (Stages 6–8) is what we deploy. Kept here at the end for future experimentation.
    # ────────────────────────────────────────────────────────────────────────────

    """
    Stage x — Fit the nested GLM.

    Fit the nested Poisson regression (attack and defense) for every team and write
    the parameters to cleaned/nested_params.csv.
    """
    # historical_matches_with_elo = pd.read_csv(
    #     f"{CLEANED_DATA_PATH}/matches_with_elo.csv"
    # )
    # nested_params = fit_nested_all(TEAM_LIST, historical_matches_with_elo)
    # nested_params.to_csv(f"{CLEANED_DATA_PATH}/nested_params.csv", index=False)

    """
    Stage x — Single-match rates (nested model) - for early debugging.

    Compute the stronger team's rate and the nested goal function for the weaker team.
    """
    # baseline_params = pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv")
    # nested_params = pd.read_csv(f"{CLEANED_DATA_PATH}/nested_params.csv")
    # r1, fn = get_nested_rates(
    #     "Morocco", "Spain", elo_ratings, baseline_params, nested_params
    # )
    # print(r1, fn(r1))
