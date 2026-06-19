"""Command-line entry point for the recurring WC2026 operations.

`main.py` is the documented runbook for the **one-time** data-build/tuning setup
(Stages 1–6 thread in-memory frames between each other; Stage 9 redeploy is
destructive) — leave those there. This CLI covers every runnable operation: the
per-round live workflow, the Monte Carlo sim, backtests, the sparse-threshold sweep,
WC26 preprocessing steps, diagnostics, and the showcase — so you never edit source to
run them.

    uv run python -m src.cli <command> [options]
    uv run python -m src.cli --help

Typical per-round routine (see README "Running the pipeline"):

    # before a round kicks off
    uv run python -m src.cli forecast       # re-scrapes Elo, locks the next round
    # after its matches finish
    uv run python -m src.cli results         # refresh actuals from the bzzoiro API
    uv run python -m src.cli ledger          # join locked forecasts onto actuals
    uv run python -m src.cli score           # grade Brier/RPS/accuracy by market

Handlers import their heavy dependencies lazily so unrelated commands (e.g.
`score`) don't pull in Selenium/Chrome.
"""

from __future__ import annotations

import argparse


# ── Stage 11 — live layer ────────────────────────────────────────────────────
def _cmd_results(args: argparse.Namespace) -> None:
    from src.bzzoiro import write_results

    write_results()


def _cmd_forecast(args: argparse.Namespace) -> None:
    from src.forecast import forecast_next_round

    forecast_next_round(rescrape=not args.no_rescrape)


def _cmd_ledger(args: argparse.Namespace) -> None:
    import pandas as pd

    from src.bzzoiro import load_actual_results_csv
    from src.forecast import MATCH_PROBS_PATH
    from src.ledger import build_match_ledger

    build_match_ledger(pd.read_csv(MATCH_PROBS_PATH), load_actual_results_csv())


def _cmd_score(args: argparse.Namespace) -> None:
    from src.scoring import score_ledger

    score_ledger()


def _cmd_surprises(args: argparse.Namespace) -> None:
    from src.surprises import report_surprises

    report_surprises(n=args.n)


def _cmd_report(args: argparse.Namespace) -> None:
    from src.report import build_scorecard

    build_scorecard(n=args.n)


# ── Stage 11 — live tournament re-sim ────────────────────────────────────────
def _cmd_resim(args: argparse.Namespace) -> None:
    """Seed finished group matches + re-scraped Elo, re-simulate the remainder.

    Writes the live artifacts (``tournament_probs_updated.csv`` + the projection
    satellites) into ``data/result/live/`` and renders
    ``updated_simulation_showcase.md``. Re-run after each matchday.
    """
    from src.const import LIVE_PATH
    from src.showcase import build_live_showcase
    from src.simulation import (
        load_completed_group_results,
        load_sim_inputs,
        monte_carlo,
    )

    if not args.no_rescrape:
        from src.scraper import latest_elo  # lazy: heavy deps (Selenium/Chrome)

        latest_elo()  # refresh data/raw/elo_latest.csv with current ratings

    inputs = load_sim_inputs(use_nested=args.nested)
    completed = load_completed_group_results()
    monte_carlo(
        inputs,
        n=args.n,
        completed=completed,
        out=f"{LIVE_PATH}/tournament_probs_updated.csv",
        goals_out=f"{LIVE_PATH}/team_goal_stats.csv",
        group_pos_out=f"{LIVE_PATH}/group_position_probs.csv",
        r32_slots_out=f"{LIVE_PATH}/r32_slot_occupancy.csv",
        opponent_dist_out=f"{LIVE_PATH}/opponent_distribution.csv",
        eliminations_out=f"{LIVE_PATH}/eliminations.csv",
    )
    build_live_showcase(n_match=args.n, src_dir=LIVE_PATH, elo=inputs.elo0)


# ── Stage 7 — Monte Carlo simulation ─────────────────────────────────────────
def _cmd_simulate(args: argparse.Namespace) -> None:
    from src.const import FORECAST_PATH
    from src.simulation import load_sim_inputs, monte_carlo

    monte_carlo(
        load_sim_inputs(use_nested=args.nested),
        n=args.n,
        goals_out=f"{FORECAST_PATH}/team_goal_stats.csv",
        group_pos_out=f"{FORECAST_PATH}/group_position_probs.csv",
        r32_slots_out=f"{FORECAST_PATH}/r32_slot_occupancy.csv",
        opponent_dist_out=f"{FORECAST_PATH}/opponent_distribution.csv",
        eliminations_out=f"{FORECAST_PATH}/eliminations.csv",
    )


# ── Stage 8 — backtests ──────────────────────────────────────────────────────
def _cmd_backtest(args: argparse.Namespace) -> None:
    from src.backtest import run_backtests_scored

    years = (2018, 2022) if args.year == "all" else (int(args.year),)
    run_backtests_scored(years=years, n_sims=args.n, seed=args.seed)


# ── Stage 9 — sparse-threshold sweep ─────────────────────────────────────────
def _cmd_sweep(args: argparse.Namespace) -> None:
    from src.backtest import sweep_sparse_threshold

    sweep_sparse_threshold(n_sims=args.n, seed=args.seed)


# ── Stages 1–6 — WC26 preprocessing steps ────────────────────────────────────
_PREPROCESS_STEPS = ("teams", "groupstage", "knockout", "timezone")


def _cmd_preprocess(args: argparse.Namespace) -> None:
    from src.data_preprocess import (
        change_timezone,
        format_wc26_groupstage_matches_dataset,
        format_wc26_knockout_matches_dataset,
        format_wc26_teams_dataset,
    )

    steps = {
        "teams": format_wc26_teams_dataset,
        "groupstage": format_wc26_groupstage_matches_dataset,
        "knockout": format_wc26_knockout_matches_dataset,
        "timezone": change_timezone,
    }
    for name in args.steps:
        steps[name]()


# ── Stage 10 — model diagnostics ─────────────────────────────────────────────
def _cmd_diagnostics(args: argparse.Namespace) -> None:
    import pandas as pd

    from model.evaluation import strength_inspection
    from src.backtest import fitted_match_counts, team_strengths
    from src.const import CLEANED_DATA_PATH, RAW_DATA_PATH

    strength_inspection(
        pd.read_csv(f"{RAW_DATA_PATH}/elo_latest.csv"),
        pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv"),
    )
    fitted_match_counts()
    team_strengths()


# ── Stage 12 — showcase ──────────────────────────────────────────────────────
def _cmd_showcase(args: argparse.Namespace) -> None:
    from src.showcase import build_showcase

    build_showcase(n_match=args.n)


# ── Streamlit dashboard ──────────────────────────────────────────────────────
def _cmd_dashboard(args: argparse.Namespace) -> None:
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "dashboard/app.py"], check=True
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wc26",
        description="Recurring WC2026 pipeline operations (see main.py for one-time setup).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # Stage 11 — live layer
    sub.add_parser(
        "results", help="refresh actual results from the bzzoiro API (wc26_results.csv)"
    ).set_defaults(func=_cmd_results)

    p_forecast = sub.add_parser(
        "forecast", help="lock the next not-yet-played round's probabilities"
    )
    p_forecast.add_argument(
        "--no-rescrape",
        action="store_true",
        help="reuse cached Elo instead of re-scraping (default: re-scrape)",
    )
    p_forecast.set_defaults(func=_cmd_forecast)

    sub.add_parser(
        "ledger", help="join locked forecasts onto actual results (match ledger)"
    ).set_defaults(func=_cmd_ledger)

    sub.add_parser(
        "score",
        help="grade the ledger: Brier/RPS/accuracy by market + a scores CSV",
    ).set_defaults(func=_cmd_score)

    p_surp = sub.add_parser(
        "surprises",
        help="top model surprises + biggest underdog wins from the live ledger",
    )
    p_surp.add_argument("-n", type=int, default=5, help="rows per table (default 5)")
    p_surp.set_defaults(func=_cmd_surprises)

    p_report = sub.add_parser(
        "report",
        help="render docs/live_scorecard.md (scoring + surprises tables) from the ledger",
    )
    p_report.add_argument(
        "-n", type=int, default=5, help="rows per surprise table (default 5)"
    )
    p_report.set_defaults(func=_cmd_report)

    # Stage 11 — live tournament re-sim
    p_resim = sub.add_parser(
        "resim",
        help="seed finished group matches + re-scraped Elo, re-simulate the remainder",
    )
    p_resim.add_argument(
        "-n", type=int, default=100000, help="number of simulations (default 100000)"
    )
    p_resim.add_argument(
        "--no-rescrape",
        action="store_true",
        help="reuse cached Elo instead of re-scraping (default: re-scrape)",
    )
    p_resim.add_argument(
        "--nested", action="store_true", help="use the nested model instead of independent"
    )
    p_resim.set_defaults(func=_cmd_resim)

    # Stage 7 — simulation
    p_sim = sub.add_parser("simulate", help="run the Monte Carlo tournament sim")
    p_sim.add_argument("-n", type=int, default=100000, help="number of simulations")
    p_sim.add_argument(
        "--nested", action="store_true", help="use the nested model instead of independent"
    )
    p_sim.set_defaults(func=_cmd_simulate)

    # Stage 8 — backtests
    p_bt = sub.add_parser(
        "backtest",
        help="retrospective 2018/2022 validation + consolidated scores CSV",
    )
    p_bt.add_argument(
        "year", nargs="?", default="all", choices=["2018", "2022", "all"]
    )
    p_bt.add_argument("-n", type=int, default=100000, help="number of simulations")
    p_bt.add_argument("--seed", type=int, default=2026, help="RNG seed")
    p_bt.set_defaults(func=_cmd_backtest)

    # Stage 9 — sparse-threshold sweep
    p_sweep = sub.add_parser(
        "sweep",
        help="sweep SPARSE_THRESHOLD (backtest + flip-band strength diff); restores prod fits",
    )
    p_sweep.add_argument("-n", type=int, default=100000, help="number of simulations")
    p_sweep.add_argument("--seed", type=int, default=2026, help="RNG seed")
    p_sweep.set_defaults(func=_cmd_sweep)

    # Stages 1–6 — WC26 preprocessing steps
    p_pre = sub.add_parser(
        "preprocess",
        help="re-run WC26 preprocessing steps (run 'timezone' first if combined)",
    )
    p_pre.add_argument("steps", nargs="+", choices=_PREPROCESS_STEPS)
    p_pre.set_defaults(func=_cmd_preprocess)

    # Stage 10 — diagnostics
    sub.add_parser(
        "diagnostics", help="write fitted-match counts and team attack/defense strengths"
    ).set_defaults(func=_cmd_diagnostics)

    # Stage 12 — showcase
    p_show = sub.add_parser("showcase", help="render showcase.md from the latest sim artifacts")
    p_show.add_argument("-n", type=int, default=100000, help="sims for modal-bracket chaining")
    p_show.set_defaults(func=_cmd_showcase)

    # Dashboard
    sub.add_parser(
        "dashboard", help="launch the Streamlit dashboard (dashboard/app.py)"
    ).set_defaults(func=_cmd_dashboard)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
