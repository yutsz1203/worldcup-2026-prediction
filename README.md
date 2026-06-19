# ⚽ World Cup 2026 Prediction

A probabilistic forecasting system for the 2026 FIFA World Cup: independent Poisson
regressions on Elo-based covariates, feeding a 100,000-run
Monte Carlo simulation of the full 48-team tournament. Backtested against the 2018 and
2022 World Cups, where it beats the no-skill baseline on Brier and RPS in both.

For derived projections (group of death, dark horses, marquee matchups, title paths),
see [showcase.md](showcase.md).

## 2026 Forecast (pre-tournament snapshot)

100,000 Monte Carlo simulations, cutoff **2026-06-11**, before kickoff. Probability (%)
of winning the title and of reaching at least each stage.

My model predicts the 2026 World Champion is **🇪🇸 Spain**, with a probability of 17.1%.

| # | Team | **Champion** | Final | SF | QF | R16 | R32 |
|---|---|---|---|---|---|---|---|
| 1 | 🇪🇸 Spain | **17.10** | 28.6 | 43.1 | 53.9 | 74.6 | 99.7 |
| 2 | 🇦🇷 Argentina | **16.33** | 27.2 | 39.7 | 57.9 | 68.8 | 98.8 |
| 3 | 🇫🇷 France | **14.25** | 25.6 | 44.3 | 60.7 | 82.0 | 98.3 |
| 4 | 🇵🇹 Portugal | **11.33** | 19.1 | 30.4 | 48.6 | 72.4 | 96.1 |
| 5 | 🇧🇷 Brazil | **6.99** | 13.0 | 25.0 | 41.5 | 61.7 | 95.0 |
| 6 | 🇨🇴 Colombia | **6.18** | 12.5 | 22.5 | 39.6 | 66.8 | 95.0 |
| 7 | 🏴󠁧󠁢󠁥󠁮󠁧󠁿 England | **5.84** | 13.2 | 28.5 | 47.3 | 69.6 | 97.2 |
| 8 | 🇳🇱 Netherlands | **4.01** | 8.8 | 19.4 | 38.2 | 53.6 | 92.8 |
| 9 | 🇩🇪 Germany | **2.88** | 7.2 | 17.1 | 30.1 | 65.0 | 97.2 |
| 10 | 🇺🇾 Uruguay | **2.72** | 6.3 | 12.7 | 23.8 | 39.0 | 92.4 |
| 11 | 🇲🇦 Morocco | **1.89** | 4.3 | 10.7 | 23.4 | 42.8 | 86.1 |
| 12 | 🇧🇪 Belgium | **1.88** | 5.2 | 12.3 | 35.4 | 65.3 | 95.2 |
| 13 | 🇭🇷 Croatia | **1.43** | 4.0 | 10.5 | 21.5 | 45.1 | 90.7 |
| 14 | 🇸🇳 Senegal | **1.31** | 3.6 | 9.6 | 20.7 | 42.5 | 79.8 |
| 15 | 🇯🇵 Japan | **1.02** | 2.9 | 7.8 | 18.6 | 33.4 | 80.2 |
| 16 | 🇨🇭 Switzerland | **0.85** | 2.7 | 7.7 | 23.9 | 61.7 | 95.8 |
| 17 | 🇩🇿 Algeria | **0.60** | 1.7 | 4.4 | 10.9 | 23.7 | 70.8 |
| 18 | 🇪🇨 Ecuador | **0.53** | 1.9 | 6.5 | 16.5 | 46.1 | 91.0 |
| 19 | 🇦🇹 Austria | **0.44** | 1.4 | 3.9 | 10.3 | 23.3 | 73.8 |
| 20 | 🇹🇷 Turkey | **0.39** | 1.5 | 4.7 | 17.0 | 43.6 | 76.0 |
| 21 | 🇨🇮 Ivory Coast | **0.31** | 1.0 | 3.4 | 9.6 | 28.4 | 74.9 |
| 22 | 🇺🇸 United States | **0.25** | 1.0 | 3.4 | 13.1 | 37.8 | 70.6 |
| 23 | 🇨🇦 Canada | **0.23** | 0.9 | 3.6 | 15.8 | 49.7 | 93.5 |
| 24 | 🇵🇾 Paraguay | **0.23** | 0.9 | 3.0 | 11.9 | 35.3 | 68.4 |
| 25 | 🇲🇽 Mexico | **0.17** | 1.0 | 5.3 | 20.4 | 58.3 | 92.9 |
| 26 | 🏴󠁧󠁢󠁳󠁣󠁴󠁿 Scotland | **0.14** | 0.6 | 2.7 | 9.4 | 24.9 | 72.4 |
| 27 | 🇨🇿 Czechia | **0.13** | 0.7 | 2.9 | 11.6 | 36.1 | 75.4 |
| 28 | 🇮🇷 Iran | **0.12** | 0.6 | 2.5 | 11.9 | 39.6 | 83.8 |
| 29 | 🇦🇺 Australia | **0.10** | 0.5 | 2.0 | 8.6 | 28.6 | 60.8 |
| 30 | 🇰🇷 South Korea | **0.10** | 0.5 | 2.3 | 10.2 | 32.1 | 70.5 |
| 31 | 🇸🇪 Sweden | **<0.1** | 0.4 | 1.8 | 6.4 | 16.2 | 62.1 |
| 32 | 🇪🇬 Egypt | **<0.1** | 0.3 | 1.1 | 5.0 | 21.5 | 62.3 |
| 33 | 🇹🇳 Tunisia | **<0.1** | 0.1 | 0.6 | 2.4 | 7.8 | 36.5 |
| 34 | 🇳🇴 Norway | **<0.1** | 0.3 | 2.2 | 9.2 | 27.6 | 70.4 |
| 35 | 🇵🇦 Panama | **<0.1** | 0.1 | 0.5 | 2.1 | 9.0 | 48.8 |
| 36 | 🇺🇿 Uzbekistan | **<0.1** | 0.1 | 0.4 | 2.1 | 8.9 | 40.1 |
| 37 | 🇿🇦 South Africa | **<0.1** | 0.1 | 0.4 | 2.1 | 8.9 | 32.4 |
| 38 | 🇸🇦 Saudi Arabia | **<0.1** | <0.1 | 0.2 | 1.0 | 4.7 | 28.3 |
| 39 | 🇧🇦 Bosnia and Herzegovina | **<0.1** | <0.1 | 0.2 | 2.1 | 11.9 | 49.3 |
| 40 | 🇨🇩 DR Congo | **<0.1** | <0.1 | 0.2 | 1.2 | 5.6 | 28.1 |
| 41 | 🇮🇶 Iraq | **<0.1** | <0.1 | 0.1 | 0.6 | 2.9 | 15.8 |
| 42 | 🇬🇭 Ghana | **<0.1** | <0.1 | 0.1 | 0.8 | 4.2 | 29.7 |
| 43 | 🇨🇻 Cape Verde | **0** | <0.1 | 0.1 | 0.7 | 3.9 | 26.8 |
| 44 | 🇳🇿 New Zealand | **0** | <0.1 | <0.1 | 0.4 | 4.4 | 26.6 |
| 45 | 🇯🇴 Jordan | **0** | <0.1 | 0.1 | 0.6 | 3.3 | 22.1 |
| 46 | 🇭🇹 Haiti | **0** | 0 | <0.1 | 0.4 | 2.6 | 19.4 |
| 47 | 🇶🇦 Qatar | **0** | 0 | <0.1 | 0.5 | 3.8 | 25.3 |
| 48 | 🇨🇼 Curaçao | **0** | 0 | <0.1 | 0.1 | 1.0 | 10.7 |

### Projected bracket

A single self-consistent **chalk** projection: modal R32 occupants chained forward, each
tie re-simulated 100,000× with the match engine and the modal winner advancing. The honest
per-stage marginals are in [showcase.md](showcase.md).

**Projected champion: Spain**

```mermaid
flowchart LR
  m73["R32: Czechia v Canada<br/><b>Canada</b>"]
  m74["R32: Germany v Scotland<br/><b>Germany</b>"]
  m75["R32: Netherlands v Morocco<br/><b>Netherlands</b>"]
  m76["R32: Brazil v Japan<br/><b>Brazil</b>"]
  m77["R32: France v Sweden<br/><b>France</b>"]
  m78["R32: Ecuador v Senegal<br/><b>Senegal</b>"]
  m79["R32: Mexico v Ivory Coast<br/><b>Mexico</b>"]
  m80["R32: England v Uzbekistan<br/><b>England</b>"]
  m81["R32: Turkey v Bosnia and Herzegovina<br/><b>Turkey</b>"]
  m82["R32: Belgium v Norway<br/><b>Belgium</b>"]
  m83["R32: Colombia v Croatia<br/><b>Colombia</b>"]
  m84["R32: Spain v Austria<br/><b>Spain</b>"]
  m85["R32: Switzerland v Egypt<br/><b>Switzerland</b>"]
  m86["R32: Argentina v Uruguay<br/><b>Argentina</b>"]
  m87["R32: Portugal v Panama<br/><b>Portugal</b>"]
  m88["R32: United States v Iran<br/><b>United States</b>"]
  m89["R16: <b>Netherlands</b>"]
  m90["R16: <b>France</b>"]
  m91["R16: <b>Brazil</b>"]
  m92["R16: <b>England</b>"]
  m93["R16: <b>Spain</b>"]
  m94["R16: <b>Belgium</b>"]
  m95["R16: <b>Argentina</b>"]
  m96["R16: <b>Portugal</b>"]
  m97["QF: <b>France</b>"]
  m98["QF: <b>Spain</b>"]
  m99["QF: <b>Brazil</b>"]
  m100["QF: <b>Argentina</b>"]
  m101["SF: <b>Spain</b>"]
  m102["SF: <b>Argentina</b>"]
  m104(["FINAL: <b>Spain</b>"])
  m73 --- m89
  m75 --- m89
  m74 --- m90
  m77 --- m90
  m91 --- m76
  m91 --- m78
  m92 --- m79
  m92 --- m80
  m83 --- m93
  m84 --- m93
  m81 --- m94
  m82 --- m94
  m95 --- m86
  m95 --- m88
  m96 --- m85
  m96 --- m87
  m89 --- m97
  m90 --- m97
  m93 --- m98
  m94 --- m98
  m99 --- m91
  m99 --- m92
  m100 --- m95
  m100 --- m96
  m97 --- m101
  m98 --- m101
  m102 --- m99
  m102 --- m100
  m101 --- m104
  m104 --- m102
```

<details><summary>Full projected bracket table</summary>

| match | round | team_a | team_b | projected_winner | p_winner |
| --- | --- | --- | --- | --- | --- |
| 73 | R32 | Czechia | Canada | Canada | 0.5224 |
| 74 | R32 | Germany | Scotland | Germany | 0.742 |
| 75 | R32 | Netherlands | Morocco | Netherlands | 0.6221 |
| 76 | R32 | Brazil | Japan | Brazil | 0.6566 |
| 77 | R32 | France | Sweden | France | 0.8912 |
| 78 | R32 | Ecuador | Senegal | Senegal | 0.5187 |
| 79 | R32 | Mexico | Ivory Coast | Mexico | 0.7039 |
| 80 | R32 | England | Uzbekistan | England | 0.9085 |
| 81 | R32 | Turkey | Bosnia and Herzegovina | Turkey | 0.8132 |
| 82 | R32 | Belgium | Norway | Belgium | 0.6378 |
| 83 | R32 | Colombia | Croatia | Colombia | 0.6419 |
| 84 | R32 | Spain | Austria | Spain | 0.8671 |
| 85 | R32 | Switzerland | Egypt | Switzerland | 0.724 |
| 86 | R32 | Argentina | Uruguay | Argentina | 0.732 |
| 87 | R32 | Portugal | Panama | Portugal | 0.8701 |
| 88 | R32 | United States | Iran | United States | 0.5516 |
| 89 | R16 | Canada | Netherlands | Netherlands | 0.75 |
| 90 | R16 | Germany | France | France | 0.6849 |
| 91 | R16 | Brazil | Senegal | Brazil | 0.6479 |
| 92 | R16 | Mexico | England | England | 0.759 |
| 93 | R16 | Colombia | Spain | Spain | 0.6538 |
| 94 | R16 | Turkey | Belgium | Belgium | 0.6042 |
| 95 | R16 | Argentina | United States | Argentina | 0.8943 |
| 96 | R16 | Switzerland | Portugal | Portugal | 0.7106 |
| 97 | QF | Netherlands | France | France | 0.6493 |
| 98 | QF | Spain | Belgium | Spain | 0.7939 |
| 99 | QF | Brazil | England | Brazil | 0.5051 |
| 100 | QF | Argentina | Portugal | Argentina | 0.5635 |
| 101 | SF | France | Spain | Spain | 0.5695 |
| 102 | SF | Brazil | Argentina | Argentina | 0.614 |
| 104 | FINAL | Spain | Argentina | Spain | 0.5051 |

</details>

## Model Pipeline

Expected goals for each team are modeled as a function of the Elo gap between opponents:

```
log(λ_A) = β₀ + β₁ · (Elo_A - Elo_B)
log(λ_B) = β₂ + β₃ · (Elo_A - Elo_B)
```

```
Historical match results + Elo ratings
        │
        ▼
Poisson regression (fit β coefficients, exponential time decay)
        │
        ▼
Match-level probability engine
  └── Independent Poisson score matrix (1X2, over/under)
        │
        ▼
Tournament simulation engine
  ├── Group stage (round-robin, FIFA tiebreakers)
  ├── Third-place qualification (best 8 of 12, all 495 bracket configurations)
  ├── Knockout bracket (R32 → Final)
  │     ├── Extra time (λ/3 scaled intensity)
  │     └── Penalties (Elo-weighted logistic)
  └── Monte Carlo aggregation (N = 100,000)
        │
        ▼
Team-level advancement probabilities
  └── Brier / RPS evaluation vs. no-skill baselines
```

Elo is used as the sole covariate because international teams play too few matches
(~10–15/year) to estimate stable team-level attack/defense parameters directly — Elo
compresses decades of results into a single prior the regression translates into goal rates.

### Backtest results

Out-of-sample: the model is re-fit at each tournament's start date (no leakage) and scored
against the actual results (`data/result/validation/validation_scores_latest.csv`).

**Match-level (1X2)** — lower is better, vs. a no-skill uniform baseline:

| Tournament | Matches | Brier | Brier (uniform) | RPS | RPS (uniform) | Accuracy |
|---|---|---|---|---|---|---|
| WC 2018 | 64 | **0.537** | 0.667 | **0.184** | 0.244 | 60.9% |
| WC 2022 | 64 | **0.580** | 0.667 | **0.200** | 0.239 | 59.4% |

**Tournament-level (stage reached)** — per-team "how far did they go" predictions, scored
with the four Gilch & Müller (2018) rules as totals summed over all 32 participants:
**E1** = max-likelihood stage error, **E2** = probability-weighted ordinal error, plus
multiclass Brier and RPS. The last two rows are the reference values from their paper
(different tournaments, same 32-team format):

| Tournament | Model | E1 | E2 | Brier | RPS |
|---|---|---|---|---|---|
| WC 2018 | This model | 27.0 | 32.48 | 18.26 | 3.41 |
| WC 2022 | This model | 25.0 | 32.01 | 19.67 | 3.26 |
| WC 2010 | Gilch & Müller (2018) | 24 | 30.50 | 17.51 | 4.93 |
| WC 2014 | Gilch & Müller (2018) | 25 | 34.32 | 21.89 | 5.42 |

## Project Structure

```
├── main.py                   # One-time setup runbook (scrape → fit → tune; commented stages)
├── src/                      # Data & simulation layer
│   ├── cli.py                #   CLI — all runnable ops (`uv run -m src.cli --help`)
│   ├── scraper.py            #   Elo scraping (eloratings.net)
│   ├── data_preprocess.py    #   Cleaning / joining Kaggle datasets
│   ├── simulation.py         #   Match engine + Monte Carlo tournament sim
│   ├── brackets.py           #   48-team bracket & third-place routing
│   ├── forecast.py           #   Live 2026 forecast assembly
│   ├── backtest.py           #   Backtest harness & tuned hyperparameters
│   ├── ledger.py             #   Predictions-vs-actuals ledger
│   ├── scoring.py            #   Match-level ledger scoring (Brier/RPS/accuracy by market)
│   ├── surprises.py          #   Biggest model surprises + underdog wins from the ledger
│   ├── report.py             #   Live scorecard generator (docs/live_scorecard.md)
│   ├── bzzoiro.py            #   Match-stats API client (h2h, player xG)
│   ├── hkjc.py               #   HKJC handicap scraper + EV pricing (dashboard HDC tab)
│   ├── projections.py        #   Derived projections (bracket, paths, indices)
│   ├── charts.py             #   Figure generation
│   └── showcase.py           #   showcase.md generator
├── model/                    # Modeling layer
│   ├── glm.py                #   Weighted Poisson GLM fit
│   ├── rates.py              #   Team goal-rate construction
│   ├── probabilities.py      #   Score matrix → 1X2 / over-under probabilities
│   ├── evaluation.py         #   Brier / RPS scoring
│   └── validation.py         #   Tournament-level scoring (Gilch & Müller rules)
├── dashboard/                # Streamlit dashboard (`streamlit run dashboard/app.py`)
│   ├── app.py                #   Entry point + tab layout
│   ├── match_probs.py        #   Round-by-round match probabilities tab
│   ├── hdc_ev.py             #   HKJC handicap EV tab
│   └── common.py             #   Shared loaders/formatting
├── competitions/             # External competition entries (consume the core model)
│   ├── datacamp/             #   DataCamp forecasting competition
│   ├── drw/                  #   DRW trading challenge (client + fair values)
│   └── jumpcup/              #   Jump Probability Cup (`uv run -m competitions.jumpcup.predict`)
├── data/
│   ├── raw/                  # Kaggle downloads (match results, Elo ratings)
│   ├── cleaned/              # Filtered, joined datasets + fitted params
│   └── result/
│       ├── forecast/         # Live 2026 forecast artifacts + figures
│       ├── live/             # In-tournament ledger & re-sim outputs
│       ├── validation/       # Backtest scores & per-match outputs
│       └── tuning/           # Hyperparameter sweeps
├── docs/                     # Roadmap, scoring methodology, HDC pricing, live scorecard
├── notebooks/                # Exploration
└── showcase.md               # Generated projections report
```

## Data Sources & APIs

| Source | What | Link |
|---|---|---|
| Kaggle (Mart Jürisoo) | 49,000+ international match results (1872–2026) | [Link](https://www.kaggle.com/datasets/martj42/international-football-results-from-1872-to-2017) |
| Kaggle (Elo Ratings) | Historical Elo time series for all national teams | [Link](https://www.kaggle.com/datasets/saifalnimri/international-football-elo-ratings) |
| eloratings.net | Current Elo ratings (scraped) | [Link](https://www.eloratings.net/) |
| bzzoiro sports API | Match stats, h2h, player xG (match previews) | `sports.bzzoiro.com/api/v2` |

## Setup

```bash
uv sync
```

## Running the pipeline

The project has two entry points, split by how often a step runs:

- **`main.py` — one-time setup runbook.** The data-build chain (Stages 1–6: scrape →
  filter → fit) threads in-memory frames between stages, and the tuning/redeploy step
  (Stage 9) is destructive. These are run once when bootstrapping or rebuilding the
  dataset, so they live as commented, numbered, documented stages you uncomment and run
  with `uv run python main.py`. Read the docstrings top-to-bottom — it doubles as the
  pipeline's narrative.

- **`src/cli.py` — every runnable operation.** Everything you re-run (the per-round live
  layer, the sim, backtests, tuning sweeps, preprocessing, diagnostics, the showcase) is a
  subcommand, so you never edit source to run it:

  ```bash
  uv run python -m src.cli --help            # list commands
  uv run python -m src.cli <command> [opts]
  ```

  | Command | Stage | What it does |
  |---|---|---|
  | `forecast` | 11 | Re-scrape Elo and lock the next not-yet-played round's probabilities (`--no-rescrape` to reuse cached Elo) |
  | `results` | 11 | Refresh actual results from the bzzoiro API (`wc26_results.csv`) |
  | `ledger` | 11 | Join locked forecasts onto actuals → the match ledger |
  | `score` | 11 | Grade the ledger: per-market Brier/RPS/accuracy + `wc2026_match_scores.csv` |
  | `surprises` | 11 | Top model surprises + biggest underdog wins from the ledger (`-n`) |
  | `report` | 11 | Render `docs/live_scorecard.md` (scoring + surprise tables) from the ledger (`-n`) |
  | `resim` | 11 | Live re-sim: seed finished group matches + re-scraped Elo, re-simulate the remainder → `data/result/live/tournament_probs_updated.csv` + `updated_simulation_showcase.md` (`-n`, `--no-rescrape`, `--nested`) |
  | `simulate` | 7 | Monte Carlo tournament sim + projection artifacts (`-n`, `--nested`) |
  | `backtest` | 8 | Retrospective 2018/2022 validation → consolidated `validation_scores_latest.csv` (`backtest 2022`, `-n`, `--seed`) |
  | `sweep` | 9 | Sweep `SPARSE_THRESHOLD` (backtest + flip-band strength diff); restores prod fits |
  | `preprocess` | 1–6 | Re-run WC26 preprocessing steps: `teams groupstage knockout timezone` (`timezone` first if combined) |
  | `diagnostics` | 10 | Write fitted-match counts and team attack/defense strengths |
  | `showcase` | 12 | Render `showcase.md` from the latest sim artifacts |
  | `dashboard` | — | Launch the Streamlit dashboard (`dashboard/app.py`) |

  **Per-round routine:**

  ```bash
  # before a round kicks off — lock the predictions
  uv run python -m src.cli forecast

  # after its matches finish — ingest results, then grade
  uv run python -m src.cli results
  uv run python -m src.cli ledger
  uv run python -m src.cli score
  uv run python -m src.cli surprises     # biggest model surprises + underdog wins
  uv run python -m src.cli report        # refresh docs/live_scorecard.md
  uv run python -m src.cli resim         # re-sim the remainder → updated reach-probs + showcase
  ```

### `backtest` vs `sweep` — validate vs tune

They sit on opposite sides of "decide the model" and are easy to confuse:

- **`sweep` is *tuning*** — an experiment to **choose** the `SPARSE_THRESHOLD` knob. It
  runs the backtest across thresholds {10,12,15,20,25}, refits the live model at the two
  finalists, and diffs the teams the knob actually moves (`config_comparison.csv`,
  `threshold_strength_diff.csv` under `data/result/tuning/`). It **snapshots and restores**
  the deployed fits, so it changes nothing in production — you read its CSVs, pick the
  winner, and hardcode it as the module default in `src/backtest.py`. Pair it with
  `tune_hyperparameters()` (main.py Stage 9), which grids the *continuous* knobs (decay
  half-life / weight floor / lookback). Run only when (re)choosing hyperparameters.

- **`backtest` is *validation*** — it scores the **current, already-chosen** params against
  the 2018 & 2022 World Cups (re-fit at each tournament's start, no leakage) and writes the
  consolidated `validation_scores_latest.csv`. It's read-only w.r.t. params. Run it after
  *any* change to params, training data, or model code to confirm the config still beats
  the no-skill baseline and hasn't regressed.

The rule of thumb: **tune (`sweep` + `tune_hyperparameters`) → lock the knobs → `backtest`
to confirm → deploy.**

### Reproducing the full pipeline for a future World Cup

The model is tournament-agnostic; porting it to e.g. WC2030 is a fixed sequence. Steps in
`main.py` are uncommented stages (`uv run python main.py`); steps in `src/cli.py` are
commands. Run top-to-bottom:

| # | Phase | Where | Command / action |
|---|---|---|---|
| 0 | **Tournament constants** | `src/const.py` | Update `TEAM_LIST`, `GROUPPING`, and the fixtures/pots paths for the new field & draw (the start-date cutoff is passed to `redeploy_2026`/`backtest` at steps 5–6, not stored here) |
| 1 | **Fixtures** | CLI | `preprocess timezone groupstage knockout teams` — format the new tournament's teams, group + knockout fixtures (run `timezone` first) |
| 2 | **Training data** | main.py (Stages 1–5) | `latest_elo` → `historical_matches` (Kaggle) → `filter_historical_matches` → `historical_elo` → `append_historical_elo` (builds `matches_with_elo.csv`) |
| 3 | **Backtest dataset** | `src.backtest.rebuild_backtest_dataset()` | One-off: rebuild `matches.csv` over the broader 2010+ team set so the backtests have full coverage |
| 4 | **Tune** | CLI + main.py (Stage 9) | `sweep` (→ pick `SPARSE_THRESHOLD`) and `tune_hyperparameters()` (→ pick half-life/floor/lookback); hardcode the winners as the defaults in `src/backtest.py` |
| 5 | **Validate** | CLI | `backtest` — confirm the tuned config beats the no-skill baseline on 2018/2022 |
| 6 | **Fit & deploy** | main.py (Stage 9) | `redeploy_2026(cutoff="<start-date>")` refits `baseline_params.csv` with the tuned recipe (or Stage 6 `fit_baseline_all` for an untuned fit) |
| 7 | **Simulate** | CLI | `simulate` — Monte Carlo the tournament → per-team stage probabilities + projection artifacts |
| 8 | **Inspect** | CLI | `diagnostics` (fitted-match counts, team strengths) and `showcase` (render `showcase.md`) |
| 9 | **Run live** | CLI | Each round: `forecast` → `results` → `ledger` → `score` → `surprises` → `report` → `resim` (the per-round routine above); `dashboard` to view |

Steps 0–6 are the one-time per-tournament build; steps 7–9 are re-run throughout the
tournament as results land.

## Roadmap

- [ ] **Market comparison / value-bet discovery** — fetch Polymarket odds automatically from its Gamma API / bzzoiro API.
- [ ] **Match preview** — per-match preview from the bzzoiro data source: h2h results,
      team top-xG players, team Elo.
- [ ] **Knockout-stage re-sim** — extend `resim` past the group stage. The current
      `completed` seam (`load_completed_group_results`) is **group-stage only**: seed the
      confirmed bracket + completed knockout matches so reach-probabilities update as each
      knockout round is played.
- [ ] **Final validation wrap-up** — post-mortem scorecard vs. the locked pre-tournament
      forecast: final Brier/RPS, calibration, champion-prob rank of the actual winner.
- [ ] **Post-tournament data + narrative** — append finalized WC2026 results to
      `matches.csv` for the WC2030 build.

## References

- Gilch, L. & Müller, S. (2018). *A Prediction Tournament for the 2018 FIFA World Cup Based on Elo Ratings.* [arXiv:1806.01930](https://arxiv.org/abs/1806.01930).
