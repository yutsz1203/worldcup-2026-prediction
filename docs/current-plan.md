# Task 3 — Live WC2026 results pipeline + accuracy/loss

## Context

The prediction model (independent Poisson on Elo covariates), the Monte Carlo tournament
engine (`src/simulation.py`: `play_match`/`monte_carlo`, fully built), parameter tuning, and
2018/2022 backtesting (`src/backtest.py`) are **done and validated**. WC2026 kicks off
**11–12 June 2026** (today is 2026-06-08), so the time-critical gap is the *live* layer: lock
pre-tournament predictions, ingest real results, and score them as matches finish.

A larger plan was drafted with Claude AI Chat (betting/Polymarket, a SQLite prediction-locking
DB, projections, dashboard, live re-sim). That plan made several **wrong assumptions about this
codebase** — corrected below — and is far broader than `future-plan.md` Task 3. The
recommendation is to ship Task 3 (Phase A) **before first kickoff**, then layer the rest as
independent phases. This file details Phase A concretely and sketches B–F as a roadmap.

### Corrections to the Claude-AI draft (so we don't build against ghosts)

- **No `simulate_match(team_a, team_b, elo_a, elo_b)` and no `PoissonParams`/`predict_rate()`.**
  Real engine: `play_match(...)` (mutates an Elo dict). Per-match probabilities come from
  `model/rates.py::get_independent_rates()` → `model/probabilities.py::generate_probabilities()`.
- **No `tournament_probs_before_validation.csv`.** The locked pre-tournament per-team stage file
  is `data/result/forecast/tournament_probs_initial.csv` (cols `team,r32,r16,qf,sf,final,champion`).
- **`generate_probabilities()` has no BTTS** — emits 1X2 + O/U 2.5/3.5 only. Needs a small add.
- **Knockout fixtures use slot tokens** (`wc26_knockout_matches.csv` `match_label` = `"2A vs 2B"`),
  so per-match probs can only be precomputed for the **48 group matches**; knockout teams are
  unknown pre-tournament.
- **Scoring already exists** — `model/validation.py`: `brier_multiclass`, `rps`, `_outcome_index`,
  `score_matches`, `calibration_table`. No new scoring math needed. **Drop the SQLite/parquet DB**;
  the repo's discipline is CSV artifacts under `data/result/<subdir>/`. "Prediction locking" is
  satisfied by writing the per-match probs CSV **once before kickoff and never recomputing at
  score time**.
- Keep the two correct principles from the draft: **never refit the GLMs mid-tournament** (Elo
  updating carries the live signal) and **no nested-model code paths**.

---


## Recommended workflow (where every idea goes)

Engine is done, so each phase below is *orchestration glue* over existing functions. Ship in
this order; each phase is independently committable.

- **Phase A — Lock predictions + ingest + match scoring** *(this file, do now, before 11 Jun)*.
  The foundation: no CLV/calibration/retrospective is honest without locked pre-tournament
  predictions. = `future-plan.md` Task 3.
- **Phase B — Live re-simulation** *(before matchday 2)*. Wrap the existing `monte_carlo` to
  seed completed matches at their real scorelines + updated Elo and re-sim only remaining
  fixtures; re-snapshot `tournament_probs_initial`-style table per matchday. Reuses `play_match`.
- **Phase C — Error tracking / benchmark ladder / calibration** *(from match 1, ongoing)*.
  Extend the Phase-A scorer with benchmarks: uniform (already in `score_matches`), then an
  Elo-only logistic baseline, then market closing prices. Reuse `calibration_table`.
- **Phase D — Market comparison (Polymarket) + CLV** *(can lag days)*. Read-only public REST;
  log entry prices early so CLV works later. Fully independent module.
- **Phase E — Projections + dashboard** *(incremental)*. Group standings, modal bracket, path
  difficulty, survival curves — all aggregations over sim output. Dashboard is most visible.
- **Phase F — Retrospective + append WC2026 to historical dataset** *(end)*. Credibility piece;
  feed finalized results back into `matches.csv` for a future WC2030 build.
- **Explicitly dropped:** nested model, mid-tournament GLM refit, golden-boot/top-scorer
  (no player data), SQLite/parquet store, real-money trading.

---

## Phase A — concrete, task-by-task

All new `src/` modules follow the **`src/backtest.py` convention**: package-qualified imports
(`from src.const import ...`, `from model.validation import ...`) and run from the project root
(via `main.py`) — *not* the bare-import style of `scraper.py`/`data_preprocess.py`.

### Task A2 — `LIVE_PATH` + seed result dir (`src/const.py`, `data/result/live/`)
- Add `LIVE_PATH = f"{RESULT_DATA_PATH}/live"`.
- Create `data/result/live/wc2026_actual_results.csv` with header **only**:
  `match_number,stage,date,home_team,away_team,home_score,away_score` (works day one — populate
  rows manually as matches finish, or via the future fetcher).
- **Accept:** `from src.const import LIVE_PATH` works; header file exists, zero rows.

### Task A3 — results ingestion (`src/bzzoiro.py`)

> **Realized (2026-06-10):** shipped as `src/bzzoiro.py` (not a stub). The recommended source
> below was openfootball; it was instead built against the **bzzoiro API** (free, instant,
> exposes ET/penalty splits), and the join key became `match_uid` (sorted team pair tagged
> GRP/KO), not `match_number`. The interim `src/results_ingest.py` was deleted, its shared
> helpers folded into `bzzoiro.py`.

- `load_actual_results(path=f"{LIVE_PATH}/wc2026_actual_results.csv") -> pd.DataFrame`: read CSV;
  **gate on score present** (drop rows with NaN `home_score`/`away_score` → only finalized
  matches flow downstream); coerce scores to int; run team-name normalization + assert.
- `RESULTS_TEAM_NAME_MAP: dict[str, str]` + `normalize_team_names(df, source) -> df`: map source
  names → canonical `TEAM_LIST` names (e.g. openfootball "Côte d'Ivoire"→"Ivory Coast",
  "DR Congo"/"Curaçao" forms); **assert no unmapped team names** (raise listing offenders).
- `fetch_latest_results()`: `TODO` stub raising `NotImplementedError`, with a docstring
  documenting the recommended source — openfootball
  `https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json`,
  gate on the `score.ft` field, freshness ~day-by-day (volunteer-maintained, **not** real-time),
  detect changes via GitHub ETag/commit. Plugging a source in = filling this one function.
- **Accept:** empty results file → empty frame, no crash; a hand-added row → normalized 1-row frame.

### Task A4 — pre-tournament per-match prob sweep (`src/forecast.py`)
Locks predictions for the 48 group matches once, before kickoff.
- `forecast_match_probs(out=f"{LIVE_PATH}/wc2026_match_probs.csv") -> pd.DataFrame`:
  load `data/raw/elo_latest.csv` (`team,elo_ratings`), `data/cleaned/baseline_params.csv`, and
  `data/cleaned/wc26_groupstage_matches.csv`; for each of the 48 fixtures call
  `get_independent_rates(home, away, elo, base)` then `generate_probabilities(home, λh, away, λa)`.
- Mirror `score_matches` numerics: clamp each λ to `15.0`; renormalize the 1X2 triple (truncated
  grid falls a hair short of 1).
- Columns: `match_number, stage, date, home_team, away_team, p_home, p_draw, p_away,
  p_over25, p_under25, p_over35, p_under35, p_btts_yes, p_btts_no` (+ optional `model_version` =
  `git rev-parse --short HEAD` for reproducibility). `stage="Group"`, `date` from `kickoff_at`.
- **Accept:** 48 rows; all probs in [0,1]; `p_home+p_draw+p_away ≈ 1`.

### Task A5 — running scorer (`model/validation.py`)
Scores finished matches against the **locked** A4 probs (not recomputed) — honors prediction
locking and reuses the existing pure scorers.
- Make `_outcome_index` reusable (it already exists) and add
  `score_running(match_probs, actual_results, out=f"{LIVE_PATH}/wc2026_running_scores.csv") -> pd.DataFrame`:
  inner-join locked probs + actual results on `match_number`; per row compute `outcome_idx`,
  then 1X2 `brier_multiclass`/`rps`, the uniform `(1/3,1/3,1/3)` baseline Brier/RPS (as
  `score_matches` does), and cheap binary Brier for O/U-2.5 and BTTS (probs already in the file).
- Emit per-match + cumulative columns: `match_number, date, home_team, away_team, home_score,
  away_score, outcome, predicted, correct, brier, rps, baseline_brier, baseline_rps,
  cum_brier, cum_rps, cum_baseline_brier, cum_baseline_rps`.
- **Accept:** N finished group matches → N rows; empty results → empty frame (no crash);
  cumulative means match a manual recompute.

### Task A6 — wire `main.py` stages
Add two commented blocks in the staged-pipeline style (run from root):
- one-off pre-kickoff: `from src.forecast import forecast_match_probs; forecast_match_probs()`.
- live loop: `load_actual_results()` → `score_running(pd.read_csv(match_probs), results)`.
- **Accept:** uncommenting each block runs end-to-end from the project root.

---

## Verification (Phase A, end-to-end)

1. `uv run python -c "from src.forecast import forecast_match_probs; forecast_match_probs()"`
   → inspect `data/result/live/wc2026_match_probs.csv` (48 rows, 1X2 sums ≈ 1, BTTS present).
2. Hand-add 2–3 real/sample finished group results to
   `data/result/live/wc2026_actual_results.csv` (e.g. match 1 Mexico–South Africa).
3. `uv run python` → `from src.bzzoiro import load_actual_results_csv`,
   `from model.validation import score_running` → run the scorer; eyeball
   `wc2026_running_scores.csv` (per-match Brier/RPS below the uniform baseline for confident
   correct calls; cumulative columns monotone in count).
4. Edge cases: empty results file → empty scorer frame, no exception; an unmapped team name in
   results → ingestion raises listing the offender.
5. `uvx ruff check .` and `uvx ruff format .` clean.

## Phase A acceptance criteria
- Per-match probs are written **once** before kickoff and scored as-is (never recomputed) —
  the locking discipline, without a DB.
- Every team-name mapping asserts on unmapped names.
- GLMs are never refit; no nested-model code paths added.
- All new artifacts live under `data/result/live/`.
