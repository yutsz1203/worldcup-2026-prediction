# Project Artifacts & Outputs

A showcase-oriented inventory of what this project produces. The system is a probabilistic
forecasting pipeline for the 2026 FIFA World Cup: a weighted Poisson GLM on Elo covariates feeding
a Monte Carlo tournament simulation, validated out-of-sample on the 2018 and 2022 tournaments and
extended with a live, round-by-round forecasting layer for 2026.

All artifacts live under `data/result/`, grouped by purpose:
`validation/` (backtests), `forecast/` (2026 outputs), `tuning/` (hyperparameter sweeps), and
`live/` (rolling in-tournament forecasts).

---

## 1. Out-of-sample validation (the headline credibility result)

The model was back-tested on two complete tournaments it never saw during fitting (2018, 2022),
scored against a uniform baseline using proper scoring rules.

**`validation/validation_scores_latest.csv`** — per-tournament scorecard:

| Year | Match Brier | Brier (uniform) | Match RPS | RPS (uniform) | Accuracy | Tourn. RPS |
|------|-------------|-----------------|-----------|---------------|----------|------------|
| 2018 | 0.537 | 0.667 | 0.184 | 0.244 | 60.9% | 3.41 |
| 2022 | 0.580 | 0.667 | 0.200 | 0.239 | 59.4% | 3.26 |

The model beats the uninformed baseline on every metric in both tournaments — the core evidence
that the forecasts carry real signal. Each row also records the full configuration (half-life,
weight floor, lookback window, home-advantage flag, sparse-team threshold, sim count, seed) so any
result is reproducible.

Supporting files:
- **`validation/validation_2018_probs.csv`, `validation_2022_probs.csv`** — every back-tested match
  with predicted 1X2 / over-under probabilities vs. realized outcome.
- **`validation/validation_2018_matches.csv`, `validation_2022_matches.csv`** — match-level detail.
- **`validation/validation_calibration.csv`** + **`calibration.png`** — reliability diagram
  (predicted vs. observed frequency by probability bin) for calibration analysis.

## 2. The 2026 forecast (the deliverable)

**`forecast/tournament_probs_latest.csv`** — full Monte Carlo tournament projection: each team's
probability of reaching R32 / R16 / QF / SF / Final and of winning the title. Top contenders:

| Team | Champion | Final | SF |
|------|----------|-------|-----|
| Spain | 16.6% | 30.1% | 43.2% |
| Argentina | 16.5% | 25.6% | 38.9% |
| France | 13.8% | 23.2% | 41.2% |
| Portugal | 11.6% | 19.3% | 31.2% |
| Brazil | 7.1% | 13.6% | 25.4% |

**`forecast/group_position_probs.csv`** — per team, the probability of finishing 1st / 2nd / 3rd /
4th in the group, plus the chance of advancing as a best-third-place team.

**`forecast/team_strengths.csv`** — model-derived attack/defense ratings: expected goals for/against
vs. an average opponent, net xG, and attack/defense ranks across all 48 teams.

**`forecast/team_goal_stats.csv`** and **`forecast/model_match_counts.csv`** — supporting
diagnostics (goal distributions, sample sizes per team).

## 3. Hyperparameter tuning & model selection

**`tuning/config_comparison.csv`** + **`tuning/tuning_grid.csv`** — a systematic sweep over modeling
choices (half-life, sparse-team threshold, home-advantage on/off, lookback window), each row scored
on both back-test years with the realized champion's predicted probability and rank recorded. This
is the evidence trail behind the chosen configuration.

**`tuning/threshold_strength_diff.csv`** + **`team_strengths_thr10/20.csv`** — sensitivity of team
strength estimates to the sparse-team data threshold.

## 4. Live, in-tournament forecasting layer

A rolling **round-by-round** forecaster (`src/forecast.py`, `src/bzzoiro.py`,
`src/ledger.py`) that runs *during* the 2026 tournament. Design principle: **the covariate is live,
the structural model is frozen** — Elo is re-scraped before each round (absorbing every completed
match), while the GLM coefficients are never refit mid-tournament. This keeps later scoring and
market comparison honest.

Outputs written to `data/result/live/`:
- **`wc2026_match_probs.csv`** — locked per-round match probabilities (1X2 + over/under), tagged with
  the Elo retrieval date and git model version for full reproducibility. Predictions are written
  **once per round and never recomputed**.
- **`wc2026_match_ledger.csv`** — a single durable predictions-vs-actuals ledger, pairing every
  forecast with its eventual real result for post-hoc validation.

Match results and resolved knockout matchups are ingested from the **bzzoiro API**
(`src/bzzoiro.py`, the single source of truth) into `data/raw/wc26_results.csv` — re-runnable any
time, carrying scores plus extra-time/penalty-shootout splits so knockout winners are read
directly. The forecaster never has to derive standings or bracket logic itself for the live path.

## 5. Data pipeline & engineering

- **Web scraping** (`src/scraper.py`): drives a real browser (Playwright/Selenium) to pull current
  and historical Elo ratings from eloratings.net; pulls international match results via `kagglehub`.
- **Feature engineering** (`src/data_preprocess.py`): filters and joins ~decades of international
  matches, attaches each team's Elo *as of match date* via `merge_asof`, and formats the WC2026
  fixture/group data.
- **Modeling layer** (`model/`): weighted Poisson GLMs with exponential time-decay weighting
  (`glm.py`), Elo → Poisson-rate conversion (`rates.py`), score-matrix → 1X2/over-under probabilities
  (`probabilities.py`), Monte Carlo tournament engine (`src/simulation.py`, `src/brackets.py`), and
  proper-scoring-rule evaluation (`model/validation.py`, `model/evaluation.py`).
- **Reproducibility**: `uv`-managed environment, seeded simulations, configuration captured in every
  output row, and a git model-version stamp on live forecasts.

---

## Quick talking points for a project description

- Probabilistic sports forecasting end-to-end: data scraping → feature engineering → weighted GLM →
  100k-run Monte Carlo simulation → calibrated probabilities.
- **Validated out-of-sample on two World Cups**, beating a uniform baseline on Brier score, RPS, and
  accuracy in both.
- Proper scoring rules (Brier, ranked probability score) and calibration diagrams, not just accuracy.
- A principled live layer that updates the *data* (Elo) without retraining the *model*, with locked,
  versioned, append-only forecast records and a predictions-vs-actuals ledger.
