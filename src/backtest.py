"""Retrospective validation against the 2018 & 2022 World Cups.

For a given tournament we (1) refit the baseline params on matches strictly
before the tournament, anchoring the time-decay at its start; (2) score the 64
actual matches' 1X2 predictions (Brier/RPS/accuracy + calibration); and (3) run
the Monte Carlo engine in its legacy 32-team mode and score the per-team
stage-reached predictions (E1/E2/Brier/RPS).

Training data is built per-team by an adaptive neutral-ground filter
(``_team_training_df``): ≥``SPARSE_THRESHOLD`` neutral matches → neutral-only, else broaden to
majors + Nations League; France adds its EURO 2016 host games. ``matches.csv`` is
the rebuilt 2010–2026, 58-team, NL-complete dataset (``rebuild_backtest_dataset``
re-scrapes it via Chrome if needed). ``tune_hyperparameters`` grids the decay /
floor / window on pooled match-level RPS; ``redeploy_2026`` applies the tuned
params to the live model, preserving the pre-tuning params + forecast.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from model.glm import fit_baseline_all
from model.validation import calibration_table, score_matches, score_tournament
from src.backtest_data import BACKTESTS, LEGACY_KNOCKOUT
from src.const import (
    CLEANED_DATA_PATH,
    CON,
    FORECAST_PATH,
    GROUPPING,
    RAW_DATA_PATH,
    TUNING_PATH,
    VALIDATION_PATH,
    TEAM_LIST,
)
from src.simulation import LEGACY_FORMAT, build_legacy_sim_inputs, monte_carlo

HALF_LIFE_YEAR = 12
DECAY_LAM = np.log(2) / (
    HALF_LIFE_YEAR * 365
)  # tuned: ~half-weight at 12 years (matches model/glm.py)
WEIGHT_FLOOR = 0.1  # min match weight (non-identified by the RPS objective; kept as a mild regularizer, matches model/glm.py default)
# Training window is a *lookback length* (years before the tournament), so the
# tuned value transfers across tournaments with different dates. DATA_FLOOR is the
# earliest scraped data; lookbacks reaching past it are clamped there.
LOOKBACK_YEARS = 7.0  # tuned on pooled match-level RPS (best unclamped combo)
DATA_FLOOR = "2010-01-01"
SPARSE_THRESHOLD = (
    20  # < this many neutral matches → broaden to majors + Nations League
)
# Home-advantage covariate disabled: the 2×2 backtest sweep (data/result/
# config_comparison.csv) found home_adv=OFF gave a small, consistent match-level
# RPS gain (~0.1924 vs 0.1946) and the best tournament E2/RPS at thr=20.
USE_HOME_ADV = False  # include the home_adv covariate in sparse teams' baseline fits


def _window_start(cutoff: str, lookback_years: float) -> str:
    """Training-window start = Jan 1 of (cutoff − lookback)'s year, clamped to the floor."""
    start = pd.Timestamp(cutoff) - pd.DateOffset(years=int(lookback_years))
    # Handle fractional years (e.g. 7.5) on top of the integer offset.
    start -= pd.Timedelta(days=round((lookback_years % 1) * 365))
    # Snap to Jan 1 of that year so the window aligns to calendar-year boundaries.
    start = pd.Timestamp(year=start.year, month=1, day=1)
    return max(start, pd.Timestamp(DATA_FLOOR)).strftime("%Y-%m-%d")


# Major tournaments whose (possibly non-neutral) matches are added for sparse teams.
MAJORS = [
    "World Cup",
    "European Championship",
    "Copa América",
    "African Nations Cup",
    "Asian Cup",
    "CONCACAF Championship",
    "Oceania Nations Cup",
]
# Teams that host a major and whose decisive home (non-neutral) matches we keep
# regardless of the window: {team: (tournament_label, year)}. France hosted EURO 2016.
NEUTRAL_HOST_EXCEPTIONS = {"France": ("European Championship", 2016)}


def backtest_team_list() -> list[str]:
    """Union of the WC2026 teams and every 2018/2022 participant."""
    teams = set(TEAM_LIST)
    for cfg in BACKTESTS.values():
        teams.update(t for grp in cfg["groups"].values() for t in grp)
    return sorted(teams)


def _load_matches() -> pd.DataFrame:
    # utc=True keeps dates tz-aware so create_baseline_model_data's unconditional
    # .dt.tz_localize(None) succeeds (it errors on already-naive series).
    df = pd.read_csv(f"{CLEANED_DATA_PATH}/matches.csv")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    # Guard against the bool column round-tripping as "True"/"False" strings
    # (non-empty strings are all truthy, which would silently break filters).
    if df["neutral"].dtype == object:
        df["neutral"] = df["neutral"].map({"True": True, "False": False}).astype(bool)
    return df


def _load_elo_history() -> pd.DataFrame:
    df = pd.read_csv(f"{RAW_DATA_PATH}/elo_historical.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def _asof_elo(
    elo_hist: pd.DataFrame, teams: list[str], cutoff: str
) -> dict[str, float]:
    """Each team's most recent Elo on or before ``cutoff``."""
    sub = elo_hist[elo_hist["date"] <= pd.Timestamp(cutoff)]
    out: dict[str, float] = {}
    for t in teams:
        rows = sub[sub["team"] == t]
        if not rows.empty:
            out[t] = float(rows["rating"].iloc[-1])
    return out


def _tournament_matches(
    year: int, elo_hist: pd.DataFrame, teams: list[str]
) -> pd.DataFrame:
    """The 64 actual WC matches for ``year``, enriched with as-of-match Elo."""
    raw = pd.read_csv(f"{RAW_DATA_PATH}/international_football_results.csv")
    raw["date"] = pd.to_datetime(raw["date"])
    wc = raw[(raw["tournament"] == "World Cup") & (raw["date"].dt.year == year)].copy()
    wc = wc[wc["home_team"].isin(teams) & wc["away_team"].isin(teams)]
    wc = wc.sort_values("date")

    elo = elo_hist.sort_values("date")
    wc = pd.merge_asof(
        wc,
        elo.rename(columns={"team": "home_team", "rating": "home_elo"}),
        on="date",
        by="home_team",
    )
    wc = pd.merge_asof(
        wc,
        elo.rename(columns={"team": "away_team", "rating": "away_elo"}),
        on="date",
        by="away_team",
    )
    return wc


def _team_training_df(
    matches: pd.DataFrame,
    team: str,
    cutoff: str,
    window_start: str,
    sparse_threshold: int = SPARSE_THRESHOLD,
) -> pd.DataFrame:
    """The training matches for one team under the adaptive neutral-ground rule.

    Within ``[window_start, cutoff)``: if the team has ≥ ``SPARSE_THRESHOLD``
    neutral-ground matches, train on **neutral-only**; otherwise (sparse) broaden
    to neutral + major tournaments + Nations League. A host exception
    (``NEUTRAL_HOST_EXCEPTIONS``, e.g. France/EURO 2016) re-adds a team's decisive
    non-neutral home-tournament matches even if before ``window_start``.
    """
    cutoff_ts = pd.Timestamp(cutoff, tz="UTC")
    start_ts = pd.Timestamp(window_start, tz="UTC")
    is_team = (matches["home_team"] == team) | (matches["away_team"] == team)
    win = matches[
        is_team & (matches["date"] >= start_ts) & (matches["date"] < cutoff_ts)
    ]

    neutral = win[win["neutral"]]
    if len(neutral) >= sparse_threshold:
        df_t = neutral
    else:
        is_nl = win["tournament"].str.startswith("European Nations League")
        df_t = win[win["neutral"] | win["tournament"].isin(MAJORS) | is_nl]

    if team in NEUTRAL_HOST_EXCEPTIONS:
        tour, yr = NEUTRAL_HOST_EXCEPTIONS[team]
        extra = matches[
            is_team
            & (matches["tournament"] == tour)
            & (matches["date"].dt.year == yr)
            & (matches["date"] < cutoff_ts)
        ]
        df_t = pd.concat([df_t, extra]).drop_duplicates()
    return df_t


def _training_groups(
    matches: pd.DataFrame,
    teams: list[str],
    cutoff: str,
    window_start: str,
    sparse_threshold: int = SPARSE_THRESHOLD,
) -> list[tuple[list[str], pd.DataFrame]]:
    """One (single-team, training-df) group per team under the adaptive rule.

    Per-team groups are required because a sparse team's non-neutral fallback
    match must enter *its* fit but not its stronger opponent's (which stays
    neutral-only). The `run_backtest` fitting loop consumes these unchanged.
    """
    return [
        ([t], _team_training_df(matches, t, cutoff, window_start, sparse_threshold))
        for t in teams
    ]


def _fit_base_params(
    matches: pd.DataFrame,
    teams: list[str],
    cutoff: str,
    lam: float,
    floor: float,
    window_start: str,
    verbose: bool = True,
    use_home_adv: bool = USE_HOME_ADV,
    sparse_threshold: int = SPARSE_THRESHOLD,
) -> dict[str, dict]:
    """Refit baseline params for every team under the adaptive training filter."""
    fit_groups = _training_groups(
        matches, teams, cutoff, window_start, sparse_threshold
    )
    counts = {t: len(df) for (g, df) in fit_groups for t in g}
    missing = [t for t in teams if counts.get(t, 0) == 0]
    if missing:
        raise ValueError(f"No training data for {missing} (window {window_start}).")
    base: dict[str, dict] = {}
    for subset, df in fit_groups:
        bdf = fit_baseline_all(
            subset,
            df,
            T=pd.Timestamp(cutoff),
            lam=lam,
            floor=floor,
            verbose=verbose,
            use_home_adv=use_home_adv,
        )
        base.update(bdf.set_index("team").to_dict("index"))
    return base


def run_backtest(
    year: int,
    n_sims: int = 20000,
    seed: int = 2026,
    lam: float = DECAY_LAM,
    floor: float = WEIGHT_FLOOR,
    lookback_years: float = LOOKBACK_YEARS,
    use_home_adv: bool = USE_HOME_ADV,
    sparse_threshold: int = SPARSE_THRESHOLD,
) -> dict:
    """Run the full backtest for one tournament; print and persist the scores."""
    cfg = BACKTESTS[year]
    cutoff = cfg["cutoff"]
    groups, actual = cfg["groups"], cfg["actual"]
    teams = sorted({t for grp in groups.values() for t in grp})

    matches = _load_matches()
    window_start = _window_start(cutoff, lookback_years)
    CON.log(
        f"Refitting {len(teams)} teams (cutoff {cutoff}, "
        f"{lookback_years}y lookback → window {window_start})..."
    )
    base = _fit_base_params(
        matches,
        teams,
        cutoff,
        lam,
        floor,
        window_start,
        use_home_adv=use_home_adv,
        sparse_threshold=sparse_threshold,
    )

    elo_hist = _load_elo_history()
    elo0 = _asof_elo(elo_hist, teams, cutoff)

    # ── Match-level ──
    tmatches = _tournament_matches(year, elo_hist, teams)
    m_metrics, per_match = score_matches(tmatches, base)
    calib = calibration_table(per_match)

    # ── Tournament-level ──
    inputs = build_legacy_sim_inputs(
        groups, LEGACY_KNOCKOUT, base, elo0, host_country=cfg.get("host")
    )
    probs = monte_carlo(inputs, n=n_sims, seed=seed, out=None)
    t_metrics = score_tournament(probs, actual, LEGACY_FORMAT.stage_order)

    # ── Report + persist ──
    CON.rule(f"WC{year} validation")
    CON.print(
        f"[bold]Match level[/bold] ({m_metrics['n_matches']} matches): "
        f"Brier {m_metrics['brier']:.3f} (uniform {m_metrics['baseline_brier']:.3f}), "
        f"RPS {m_metrics['rps']:.3f} (uniform {m_metrics['baseline_rps']:.3f}), "
        f"accuracy {m_metrics['accuracy']:.3f}"
    )
    CON.print(
        f"[bold]Tournament level[/bold] (totals over {t_metrics['n_teams']} teams): "
        f"E1 {t_metrics['E1']:.3f}, E2 {t_metrics['E2']:.3f}, "
        f"Brier {t_metrics['brier']:.3f}, RPS {t_metrics['rps']:.3f}"
    )
    per_match.to_csv(f"{VALIDATION_PATH}/validation_{year}_matches.csv", index=False)
    probs.to_csv(f"{VALIDATION_PATH}/validation_{year}_probs.csv", index=False)
    calib.to_csv(f"{VALIDATION_PATH}/validation_{year}_calibration.csv", index=False)

    return {
        "year": year,
        "match": m_metrics,
        "tournament": t_metrics,
        "probs": probs,
        "actual": actual,
    }


def _champion_diagnostics(probs: pd.DataFrame, actual: dict[str, str]) -> dict:
    """Champion-overconfidence diagnostics from a Monte Carlo probs table.

    ``probs`` is the :func:`monte_carlo` output (a ``team`` column plus a
    cumulative ``champion`` column, sorted descending by ``champion``). ``actual``
    maps team → reached stage; exactly one team is mapped to ``"CHAMPION"``.

    Returns the actual champion's predicted win-prob and its rank in the field
    (1 = model favorite), plus the field's top favorite and its prob — so a
    config that crowns a non-winner (low actual-champ prob, large rank, high
    top-favorite prob) is visible at a glance.
    """
    champ = next(t for t, s in actual.items() if s == "CHAMPION")
    d = probs.copy()
    d["rank"] = d["champion"].rank(ascending=False, method="min").astype(int)
    top = d.sort_values("champion", ascending=False).iloc[0]
    crow = d[d["team"] == champ]
    return {
        "actual_champion": champ,
        "actual_champ_prob": (
            float(crow["champion"].iloc[0]) if not crow.empty else float("nan")
        ),
        "actual_champ_rank": int(crow["rank"].iloc[0]) if not crow.empty else -1,
        "top_favorite": str(top["team"]),
        "top_favorite_prob": float(top["champion"]),
    }


def compare_configs(
    years: tuple[int, ...] = (2018, 2022),
    n_sims: int = 100000,
    seed: int = 2026,
    lam: float = DECAY_LAM,
    floor: float = WEIGHT_FLOOR,
    lookback_years: float = LOOKBACK_YEARS,
    home_adv_options: tuple[bool, ...] = (True, False),
    threshold_options: tuple[int, ...] = (15, 20),
) -> pd.DataFrame:
    """Full backtest (match + tournament Monte Carlo) over the 2×2 knob grid.

    Runs every ``{use_home_adv} × {sparse_threshold}`` config at the **same**
    continuous hyperparameters (``lam``/``floor``/``lookback_years``) so the only
    varying factor is the two sparse-team knobs. For each (config, year) it records
    the match-level scores, the tournament-level totals, and the
    champion-overconfidence diagnostics (:func:`_champion_diagnostics`). Writes
    `data/result/tuning/config_comparison.csv` and returns the tidy frame.
    """
    half_life = np.log(2) / (lam * 365)
    rows = []
    for ha in home_adv_options:
        for th in threshold_options:
            for year in years:
                CON.rule(f"compare home_adv={ha} thr={th} — WC{year}")
                res = run_backtest(
                    year,
                    n_sims=n_sims,
                    seed=seed,
                    lam=lam,
                    floor=floor,
                    lookback_years=lookback_years,
                    use_home_adv=ha,
                    sparse_threshold=th,
                )
                m, t = res["match"], res["tournament"]
                diag = _champion_diagnostics(res["probs"], res["actual"])
                rows.append(
                    {
                        "use_home_adv": ha,
                        "sparse_threshold": th,
                        "year": year,
                        "half_life_years": round(half_life, 1),
                        "floor": floor,
                        "lookback_years": lookback_years,
                        "n_sims": n_sims,
                        "seed": seed,
                        "match_n": m["n_matches"],
                        "match_brier": round(m["brier"], 4),
                        "match_rps": round(m["rps"], 4),
                        "match_accuracy": round(m["accuracy"], 4),
                        "tourn_n_teams": t["n_teams"],
                        "tourn_E1": round(t["E1"], 3),
                        "tourn_E2": round(t["E2"], 3),
                        "tourn_brier": round(t["brier"], 3),
                        "tourn_rps": round(t["rps"], 3),
                        "actual_champion": diag["actual_champion"],
                        "actual_champ_prob": round(diag["actual_champ_prob"], 4),
                        "actual_champ_rank": diag["actual_champ_rank"],
                        "top_favorite": diag["top_favorite"],
                        "top_favorite_prob": round(diag["top_favorite_prob"], 4),
                    }
                )

    df = pd.DataFrame(rows)
    out = f"{TUNING_PATH}/config_comparison.csv"
    df.to_csv(out, index=False)
    CON.rule("Config comparison (2×2 sparse-team knobs)")
    CON.log(f"Comparison ({len(df)} rows) → {out}")
    CON.print(df.to_string(index=False))
    return df


def tune_hyperparameters(
    years: tuple[int, ...] = (2018, 2022),
    half_lives: tuple[float, ...] = (3.0, 5.0, 8.0, 12.0),
    floors: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2),
    lookbacks: tuple[float, ...] = (3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
    home_adv_options: tuple[bool, ...] = (True, False),
    threshold_options: tuple[int, ...] = (15, 20),
) -> pd.DataFrame:
    """Grid-search decay half-life, weight floor and lookback on match-level RPS.

    Also sweeps the two sparse-team knobs — the ``home_adv`` covariate
    (``home_adv_options``) and the sparse threshold (``threshold_options``) — as
    outer loops so every (config × continuous) combination is scored on the same
    objective.

    The window is a **lookback length in years before each tournament's cutoff**
    (not a fixed date), so the tuned value transfers to 2026. The objective is the
    **pooled** (match-count-weighted) mean 1X2 RPS over every match of the given
    tournaments — match-level scoring needs only refit params + as-of Elo (no Monte
    Carlo), so each grid point is just GLM refits. A `clamped` flag marks combos
    where a lookback reaches past the 2010 data floor (so the longer lookback isn't
    truly tested for the earlier tournament). Writes `data/result/tuning/tuning_grid.csv`.
    """
    matches = _load_matches()
    elo_hist = _load_elo_history()
    tdata = {}
    for y in years:
        cfg = BACKTESTS[y]
        teams = sorted({t for grp in cfg["groups"].values() for t in grp})
        tdata[y] = (cfg["cutoff"], teams, _tournament_matches(y, elo_hist, teams))

    combos = [
        (ha, th, lb, h, f)
        for ha in home_adv_options
        for th in threshold_options
        for lb in lookbacks
        for h in half_lives
        for f in floors
    ]
    rows = []
    with CON.status("Tuning…") as status:
        for i, (ha, th, lb, h, floor) in enumerate(combos, 1):
            status.update(
                f"Tuning {i}/{len(combos)}  (home_adv={ha}, thr={th}, "
                f"lookback {lb}y, H={h})"
            )
            lam = np.log(2) / (h * 365)
            per_year, tot_n, sum_rps, sum_brier, clamped = {}, 0, 0.0, 0.0, False
            for y in years:
                cutoff, teams, tmatches = tdata[y]
                ws = _window_start(cutoff, lb)
                clamped = clamped or ws == DATA_FLOOR
                base = _fit_base_params(
                    matches,
                    teams,
                    cutoff,
                    lam,
                    floor,
                    ws,
                    verbose=False,
                    use_home_adv=ha,
                    sparse_threshold=th,
                )
                m, _ = score_matches(tmatches, base)
                per_year[y] = m["rps"]
                tot_n += m["n_matches"]
                sum_rps += m["rps"] * m["n_matches"]
                sum_brier += m["brier"] * m["n_matches"]
            rows.append(
                {
                    "use_home_adv": ha,
                    "sparse_threshold": th,
                    "lookback_years": lb,
                    "half_life": h,
                    "floor": floor,
                    "lam": lam,
                    "clamped": clamped,
                    "pooled_rps": sum_rps / tot_n,
                    "pooled_brier": sum_brier / tot_n,
                    **{f"rps_{y}": per_year[y] for y in years},
                }
            )

    df = pd.DataFrame(rows).sort_values("pooled_rps").reset_index(drop=True)
    out = f"{TUNING_PATH}/tuning_grid.csv"
    df.to_csv(out, index=False)

    # Best among *cleanly testable* combos (no lookback clamped past the data floor).
    clean = df[~df["clamped"]]
    best = (clean if not clean.empty else df).iloc[0]
    CON.rule("Hyperparameter tuning (pooled match-level RPS)")
    CON.log(f"Full grid ({len(df)} combos) → {out}")
    CON.print(
        f"[bold green]Best (unclamped)[/bold green]  home_adv={best['use_home_adv']} "
        f"thr={best['sparse_threshold']} H={best['half_life']} "
        f"floor={best['floor']:.2f} lookback={best['lookback_years']}y → "
        f"pooled RPS {best['pooled_rps']:.4f}, Brier {best['pooled_brier']:.4f}"
    )
    return df


def redeploy_2026(
    n_sims: int = 100000,
    lam: float = DECAY_LAM,
    floor: float = WEIGHT_FLOOR,
    lookback_years: float = LOOKBACK_YEARS,
    cutoff: str = "2026-06-11",
    use_home_adv: bool = USE_HOME_ADV,
    sparse_threshold: int = SPARSE_THRESHOLD,
) -> pd.DataFrame:
    """Refit the live 2026 baseline params with the tuned recipe and re-run the sim.

    Uses the same adaptive per-team training filter as the backtests, with the
    tuned **lookback** measured back from the tournament start. **Originals are
    preserved:** the current `baseline_params.csv` is copied to
    `baseline_params_pretuning.csv` and `tournament_probs_before_tuning.csv` is left
    untouched; the new forecast is written to `tournament_probs_after_tuning.csv`.
    """
    import os
    import shutil

    from src.simulation import load_sim_inputs

    window_start = _window_start(cutoff, lookback_years)
    matches = _load_matches()
    base = _fit_base_params(
        matches,
        list(TEAM_LIST),
        cutoff,
        lam,
        floor,
        window_start,
        verbose=False,
        use_home_adv=use_home_adv,
        sparse_threshold=sparse_threshold,
    )
    params_df = pd.DataFrame([{"team": t, **base[t]} for t in TEAM_LIST])

    params_path = f"{CLEANED_DATA_PATH}/baseline_params.csv"
    # Snapshot the genuine pre-tuning params ONCE — repeated redeploys must not
    # overwrite it with an already-tuned version.
    pretuning_path = f"{CLEANED_DATA_PATH}/baseline_params_pretuning.csv"
    if not os.path.exists(pretuning_path):
        shutil.copy(params_path, pretuning_path)
    params_df.to_csv(params_path, index=False)
    CON.log(
        f"Refit 2026 baseline params (H≈{np.log(2) / (lam * 365):.0f}y, "
        f"{lookback_years}y lookback → window {window_start}); "
        f"original saved to baseline_params_pretuning.csv"
    )

    inputs = load_sim_inputs()  # reads the freshly-written baseline_params.csv
    out = f"{FORECAST_PATH}/tournament_probs_latest.csv"
    return monte_carlo(inputs, n=n_sims, out=out)


# ── Model diagnostics (introspect the live 2026 fit) ─────────────────────────
_GROUP_OF = {t: g for g, members in GROUPPING.items() for t in members}


def _wc26_field_elo() -> tuple[dict[str, float], float]:
    """Current Elo per team and the mean Elo of the 48-team WC2026 field."""
    elo_df = pd.read_csv(f"{RAW_DATA_PATH}/elo_latest.csv")
    elo = dict(zip(elo_df["team"], elo_df["elo_ratings"].astype(float)))
    field_mean = float(np.mean([elo[t] for t in TEAM_LIST if t in elo]))
    return elo, field_mean


def fitted_match_counts(
    cutoff: str = "2026-06-11", lookback_years: float = LOOKBACK_YEARS
) -> pd.DataFrame:
    """How many matches the live 2026 model fitted for each team.

    Mirrors the production training filter (adaptive neutral-ground rule, tuned
    lookback). Writes `data/result/forecast/model_match_counts.csv` with the match count,
    how many were neutral, whether the team hit the sparse fallback, and the
    team's mean goals for/against in its training sample. Sorted thinnest-first.
    """
    matches = _load_matches()
    window_start = _window_start(cutoff, lookback_years)
    elo, _ = _wc26_field_elo()
    rows = []
    for t in TEAM_LIST:
        d = _team_training_df(matches, t, cutoff, window_start)
        is_home = d["home_team"] == t
        gf = np.where(is_home, d["home_score"], d["away_score"])
        ga = np.where(is_home, d["away_score"], d["home_score"])
        n_neutral = int(d["neutral"].sum())
        rows.append(
            {
                "team": t,
                "group": _GROUP_OF.get(t),
                "elo": round(elo.get(t, float("nan")), 1),
                "n_fitted_matches": len(d),
                "n_neutral": n_neutral,
                "sparse": n_neutral < SPARSE_THRESHOLD,
                "mean_gf": round(float(np.mean(gf)), 2) if len(d) else float("nan"),
                "mean_ga": round(float(np.mean(ga)), 2) if len(d) else float("nan"),
            }
        )
    df = pd.DataFrame(rows).sort_values("n_fitted_matches").reset_index(drop=True)
    out = f"{FORECAST_PATH}/model_match_counts.csv"
    df.to_csv(out, index=False)
    CON.log(f"Fitted match counts (window {window_start}) → {out}")
    return df


def team_strengths() -> pd.DataFrame:
    """Per-team attack/defense strength from the live 2026 baseline params.

    ``xgf_vs_avg`` is the expected goals a team *scores* against a typical WC2026
    opponent (Elo = the 48-team field mean); ``xga_vs_avg`` is the expected goals
    it *concedes* to that opponent. Both evaluate every team against the same
    reference, so they are directly comparable — handy for Fantasy: high
    ``xgf_vs_avg`` (low ``attack_rank``) = attacking returns, low ``xga_vs_avg``
    (low ``defense_rank``) = clean-sheet potential. Writes
    `data/result/forecast/team_strengths.csv`, sorted by net expected-goal margin.
    """
    base = pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv").set_index("team")
    elo, ref = _wc26_field_elo()
    rows = []
    for t in TEAM_LIST:
        p = base.loc[t]
        xgf = float(np.exp(p["intercept_attack"] + p["elo_o_attack"] * ref))
        xga = float(np.exp(p["intercept_defense"] + p["elo_o_defense"] * ref))
        rows.append(
            {
                "team": t,
                "group": _GROUP_OF.get(t),
                "elo": round(elo.get(t, float("nan")), 1),
                "xgf_vs_avg": round(xgf, 3),
                "xga_vs_avg": round(xga, 3),
                "net_xg": round(xgf - xga, 3),
            }
        )
    df = pd.DataFrame(rows)
    df["attack_rank"] = df["xgf_vs_avg"].rank(ascending=False).astype(int)
    df["defense_rank"] = (
        df["xga_vs_avg"].rank(ascending=True).astype(int)
    )  # lower=better
    df = df.sort_values("net_xg", ascending=False).reset_index(drop=True)
    out = f"{FORECAST_PATH}/team_strengths.csv"
    df.to_csv(out, index=False)
    CON.log(f"Team strengths (vs avg WC26 opponent, Elo {ref:.0f}) → {out}")
    return df


def rebuild_backtest_dataset(start_date: str = "2014-01-01") -> None:
    """Rebuild matches.csv over the broader backtest team set and wider window.

    This re-scrapes historical Elo (browser-driven, needs Chrome) and re-downloads
    the Kaggle results, so it is a deliberate, manually-invoked step rather than
    part of run_backtest. After it finishes, run_backtest(2018)/(2022) will have
    full team coverage.
    """
    from src.data_preprocess import append_historical_elo, filter_historical_matches
    from src.scraper import historical_elo, historical_matches

    teams = backtest_team_list()
    raw = historical_matches()
    filtered = filter_historical_matches(raw, team_list=teams, start_date=start_date)
    elo_hist = historical_elo(filtered, start_date=start_date)
    append_historical_elo(filtered, elo_hist)
    CON.log("Rebuilt matches.csv for backtesting.")


if __name__ == "__main__":
    run_backtest(2022)
