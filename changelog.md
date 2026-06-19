## Changelog

### Jun 18
- Fetched all round 1 results, built the match ledger, and scored model predictions.
- Built running-scorers pipeline, calculating Brier, RPS, and Accuracy for Overall, 1X2, 2.5/3.5 O/U markets.
- Cleaned `main.py`, moved modules calling to a standardised `cli.py`
- Added the biggest-surprise log (`src/surprises.py`, `cli surprises`): top model surprises by `1 − model_p` of the actual result, plus biggest underdog wins by Elo gap.
- Reported the running-scorers, biggest-surprise log in `docs/live_scorecard.md`

### Jun 10
- Added `src/bzzoiro.py`: pulls all 104 WC26 matches (`league_id=27`, `season_id=188`) from the
  free bzzoiro API into `data/raw/wc26_results.csv` — re-runnable anytime, carrying scores,
  ET/penalty splits, and resolved knockout winners for continuous error scoring and final
  validation. bzzoiro is now the live source of truth: `forecast.py` and `main.py` read it via
  `load_resolved_fixtures_csv` / `load_actual_results_csv`, superseding the openfootball feed.
  Token lives in a gitignored `.env` (`BZZOIRO_TOKEN`).

### Jun 9
- Worked on Tier 0 Section 3 (Projections & Deliverables) in the Roadmap. Produced the following deliverables. All displayed in showcase.md.
  1. Group standings 
      - Probability of finishing the group at each position, Expected points, Probability of qualifying to the knockout stage
      - Group of death indicator (expected strength of eliminated team)
  2. Expected round of elimination
  3. Dark horse indicator - P(reach semis) vs the average of its **seeding pot**.
  4. R32 modal occupant - The most likely occupant of each slot in the R32 bracket
  5. Matchup probabilities
  6. Path difficulty
  7. Favourites most likely route
  8. Projected Bracket

- Updated match numbers in `data/raw/wc_matches` to match official match numbers.
- 

### Jun 6

Added two Fantasy-oriented forecast artifacts off the existing Monte Carlo run — no new
simulation, both accumulated over the same `monte_carlo` loop that produces the stage
probabilities.

- **simulation.py** — threaded two optional accumulators through `run_tournament`
  (→ `simulate_knockout`): `goals` (per-team goals-for/against) and `group_pos` (per-team
  group-finishing position). Group goals/positions are free from `simulate_group`'s existing
  per-team `stats` + `ranked` order; knockout goals come from each `play_match` result.
  Extra-time goals are already in the scoreline and shootout wins stay drawn, so penalties
  correctly contribute no goals.
- **simulation.py** — `monte_carlo` gained `goals_out` and `group_pos_out` path params
  (both default `None`, so the existing `tournament_probs_*.csv` output and return value are
  unchanged when omitted). New writers:
  - `_write_goal_stats` → `forecast/team_goal_stats.csv`: per-match average GF/GA split into
    a **group-stage** and a **pooled knockout** bucket (`group_gf/ga`, `ko_gf/ga`), plus
    `ko_match_rate` (avg knockout matches played per tournament). Knockout averages are
    conditional on reaching the knockouts.
  - `_write_group_position_probs` → `forecast/group_position_probs.csv`: per-team probability
    of finishing the group **1st/2nd/3rd/4th** (`p1..p4`), with a `group` column, plus
    `p_best_third` — the probability of qualifying as one of the **8 best third-placed teams**
    (tallied from `run_tournament`'s existing `rank_third_placed(...)[:8]`; `p_best_third <= p3`,
    and the column sums to ~8 across teams). Group letter derived from `inputs.group_fixtures`
    so it's correct for the legacy 32-team format too (which omits `p_best_third`).
- **main.py** — active sim stage now passes both `goals_out` and `group_pos_out`.

### Jun 5

Tested lowering `SPARSE_THRESHOLD` 20→10 (prompted by ~17/48 WC26 teams carrying the
`sparse` flag in `model_match_counts.csv`). **Decision: keep 20 — 10 rejected.** The flag
is not a contradiction of the paper's neutral-only rule: it's the adaptive fallback in
`_team_training_df` (neutral-only when a team has ≥threshold neutral matches; otherwise
broaden to neutral + majors + Nations League — *not* home/away qualifiers). Lowering the
threshold *reduces* the broadened set, flipping the 10–19-neutral band (mostly strong
sides) onto thin neutral-only fits.

- **sweep_thresholds.py** (new throwaway runner) — extended `compare_configs` to
  `threshold ∈ {10,12,15,20,25}` at the production knob (`home_adv=OFF`) →
  `data/result/config_comparison_threshold_sweep.csv`; and refit (`redeploy_2026`) +
  recomputed `team_strengths` at thr=10 vs thr=20, diffing the flip-band teams →
  `data/result/threshold_strength_diff.csv` (+ `team_strengths_thr10/20.csv`). Restores
  production fits and the canonical 2×2 `config_comparison.csv` on exit.
- **Backtest evidence** — thr=10 is the *worst* match-level RPS in both years (2018
  0.1862, 2022 0.2015) vs the thr=15/20 best (~0.1842/0.2003); tournament E2/RPS noisy and
  not consistently favoring 10. No support for lowering.
- **Rate-stability evidence (decisive)** — at thr=10 the flip-band strong teams get
  unstable small-sample neutral-only fits: Belgium xGF collapses 1.55→0.93, Sweden inflates
  1.38→1.96, Portugal 2.09→1.70 — clearly artifacts, not signal. Confirms the bias↓/
  variance↑ risk of thin neutral-only data. **`SPARSE_THRESHOLD` unchanged at 20**;
  production artifacts untouched.

Earlier the same day — investigated the two sparse-team knobs against the backtests, then
re-tuned and redeployed.

- **glm.py / backtest.py** — made the `home_adv` covariate (`use_home_adv`) and the
  sparse threshold (`sparse_threshold`) tunable parameters, threaded from the entry
  points (`run_backtest`, `tune_hyperparameters`, `redeploy_2026`, new `compare_configs`)
  down through `_fit_base_params` → `_training_groups` → `_team_training_df` and
  `fit_baseline_all` → `fit_baseline`. Added module constant `USE_HOME_ADV` next to
  `SPARSE_THRESHOLD` as the single flip-point.
- **backtest.py** — `tune_hyperparameters` now also sweeps `home_adv ∈ {on,off}` ×
  `threshold ∈ {15,20}` (384 GLM-only points → `tuning_grid.csv`). New `compare_configs`
  + `_champion_diagnostics` run the full match+tournament Monte Carlo over the 2×2 grid
  with champion-overconfidence diagnostics (actual-winner prob/rank vs top-favorite prob)
  → `data/result/config_comparison.csv`. `run_backtest` now also returns the MC probs +
  actuals.
- **Findings** (see `config_comparison.csv`): `home_adv=OFF` gave a small, *consistent*
  match-level RPS gain (~0.1924 vs 0.1946 across both years); on tournament E2/RPS and
  actual-champion probability the winner was **home_adv=OFF, threshold=20**. The two knobs
  do **not** resolve favorite-overconfidence (Germany ~32% in 2018, Netherlands ~20% in
  2022) — those teams aren't sparse at the backtest cutoffs, so the knobs never touch them;
  the overconfidence is generated by the Elo-driven simulation, not the GLM fit. The
  France-vs-Peru concern *did* improve (France now 4th / 5.6%, above Peru) — mostly from the
  lookback 8→7y change.
- **Tuned defaults updated** (`src/backtest.py`): `USE_HOME_ADV` True→**False**,
  `SPARSE_THRESHOLD` 15→**20**, `LOOKBACK_YEARS` 8.0→**7.0** (half-life 12y, floor 0.1
  unchanged). Re-ran `run_backtests.py`, `redeploy_2026()`, `team_strengths()`. Prior-round
  outputs frozen as `*_prev_round.csv`.

### Jun 4

Big day. Built the Monte Carlo engine, a backtesting harness against WC2018/2022,
tuned the model against it, and refined sparse-team fitting. Grouped by theme below.

#### Monte Carlo engine & brackets
- **brackets.py** — encoded FIFA's full 495-combination third-place → R32 allocation
  table (Annex C of `FWC26_regulations_EN.pdf` → `data/cleaned/third_place_bracket_map.csv`,
  validated against the fixture eligibility sets). Added `rank_third_placed()`,
  `assign_third_place_slots()`.
- **simulation.py** — layered engine: match → group → knockout → tournament, with
  per-match Elo updates, extra time (rates/3), and Elo-tilted penalty shootouts.
  `monte_carlo()` writes per-team stage probabilities to `cleaned/tournament_probs.csv`.
  10k sims ≈ 4s; Spain/Argentina/France/England top the table (face-valid).
- **rates.py** — refactored into float-in/float-out `independent_rates()` /
  `nested_rates()` cores (DataFrame wrappers delegate) for the simulation hot loop.
- Fixed `wc26_knockout_matches.csv` (match 100 referenced `W100` → `W96`).
- Nested model is **off by default** in the sim: fit on tiny samples for strong teams,
  and ~1/3 of teams have an implausible opponent-Elo sign — those are dropped.

#### Backtesting & validation harness
- **simulation.py** — generalised for the legacy 32-team format: `TournamentFormat`
  (carried on `SimInputs`), conditional third-place path in `run_tournament`,
  format-driven stage maps, `build_legacy_sim_inputs()`. WC2026 behaviour
  regression-checked.
- **glm.py** — `fit_baseline_all` / `fit_nested_all` now take `T` / `lam` so backtests
  can anchor decay at a historical cutoff and exclude future matches.
- **backtest_data.py** — 2018/2022 groups, the standard R16→Final bracket, and the
  actual stage each team reached (the scoring target).
- **validation.py** — E1, E2, Brier, RPS (Gilch & Müller), decile calibration, and
  match-level 1X2 scoring (`score_matches`, `score_tournament`,
  `exact_stage_distribution`). Tournament scores are **totals summed over teams**
  (not means), direction-invariant to the paper's descending `result(T)` encoding.
  Cross-checked vs their Table 7 (2014 32-team totals: E1≈26–28, E2≈34, Brier≈22, RPS≈5.5).
- **backtest.py** — `run_backtest(year)` (cutoff refit → as-of Elo → match-level +
  legacy-sim scoring); `rebuild_backtest_dataset()` re-scrapes Elo via Chrome and rebuilds
  `matches.csv` over the 58-team backtest set back to 2010 so the 2018 window is fair.
  2018 uses a bespoke recipe: neutral matches since 2010 for all teams **except France**,
  which adds its (non-neutral, host) EURO 2016 games. Pre-rebuild backups in
  `data/_backup_pre_rebuild/`.
- **run_backtests.py** — runs `run_backtest(2018)` + `run_backtest(2022)` on the tuned
  defaults and writes a consolidated summary to `data/result/validation_scores.csv`
  (param provenance + all score functions); per-match/probs/calibration CSVs are still
  written by `run_backtest` itself.

#### Parameter tuning
- Objective: pooled match-level RPS over the 2018+2022 matches (no Monte Carlo needed,
  so the grid is cheap).
- **data_preprocess.py** — made `matches.csv` **NL-complete**: keep all UEFA Nations
  League games (every tier) for every team, so the adaptive filter has the data under
  any window. Re-filtered existing raw results (no scrape); 2654→2942 rows. Side benefit:
  Scotland 17→40 and Bosnia 18→38 training matches.
- **backtest.py** — **adaptive per-team training filter** (`_team_training_df`) used by
  all backtests + the 2026 refit: ≥20 neutral matches → neutral-only; sparse → neutral +
  majors + Nations League; France → + EURO 2016. Per-team so a sparse team's non-neutral
  games don't leak into a strong opponent's neutral fit.
- **glm.py** — threaded a `floor` (min weight) param and a `verbose` flag through the fitters.
- `tune_hyperparameters()` grids half-life × floor × **lookback length** on pooled match RPS
  → `data/result/tuning_grid.csv`. The window is a *lookback in years before the cutoff*
  (not a fixed date) so the tuned value transfers to 2026; a `clamped` flag marks lookbacks
  reaching past the 2010 data floor. Findings: slower decay helps but plateaus by ~8y (floor
  inert there); the clean lookback optimum is **~8 years**.
- **Chosen params: half-life 8y (λ=ln2/(8·365)), floor 0.1, lookback 8y** (H=12 was within
  0.0005 RPS — noise). Set as defaults in `glm.py` / `backtest.py`.
- **2026 redeploy** (`redeploy_2026`) — refit `baseline_params.csv` with the tuned recipe +
  8y lookback (window 2018-06-11) + 100k sims. New forecast: Spain 0.184 / France 0.156 /
  Argentina 0.116 / Portugal 0.108. **Originals preserved:** `baseline_params_pretuning.csv`
  (snapshot once) + `tournament_probs_before_tuning.csv`; new run in
  `tournament_probs_after_tuning.csv`.
- **Deferred:** `K_FACTOR` / `PEN_SLOPE` / `ET_SCALE` (2-tournament objective too noisy);
  `ELO_GAP_THRESHOLD` (no effect until nested is on); Dixon–Coles τ (advertised in README
  but **not implemented** — open gap).

#### Sparse-team fitting
- **backtest.py** — lowered `SPARSE_THRESHOLD` 20→15. Only Sweden (17 neutral) and Portugal
  (19 neutral) cross it: they switch from the broadened fallback to neutral-only fits,
  dropping their non-neutral contamination. Sparse-team count 11→9; regenerated
  `data/result/model_match_counts.csv`.
- **glm.py** — added a `home_adv` covariate to the baseline attack/defense fits, coded from
  the team's perspective (+1 home / -1 away on non-neutral pitches, 0 neutral). `fit_baseline`
  includes it only when it varies, so neutral-only teams are unchanged and only sparse teams —
  whose broadened sets pull in non-neutral matches — get the term. It absorbs the venue effect
  instead of letting it leak into the Elo slope/intercept. WC26 predictions are neutral
  (home_adv=0), so the term drops out at predict time and `rates.py` is untouched.
  (e.g. Germany: home_adv≈0.35, ~1.4× attack at home.)

#### Results
Match Brier/RPS are 3-way 1X2 multiclass (uniform no-skill ≈ 0.667 / 0.24); tournament
columns are totals summed over teams. Pre-tuning at 20k sims; tuned/final from the persisted
`validation_scores.csv` (20k sims, seed 2026).

| Run        | Year | Match Brier | Match RPS | Acc   | E1   | E2   | Brier | RPS  |
|------------|------|-------------|-----------|-------|------|------|-------|------|
| Pre-tuning | 2018 | 0.543       | 0.187     | 0.578 | 28.0 | 33.6 | 19.4  | 3.63 |
| Pre-tuning | 2022 | 0.581       | 0.201     | 0.578 | 26.0 | 31.8 | 19.9  | 3.25 |
| Tuned      | 2018 | 0.536       | 0.185     | —     | 30.0 | 33.4 | 19.0  | 3.60 |
| Tuned      | 2022 | 0.586       | 0.203     | —     | 25.0 | 32.4 | 19.8  | 3.31 |

Both years beat the uniform no-skill match baselines and sit in the paper's Table-7 range.
2022: Argentina/France rank 2nd/3rd (the actual finalists). 2018's higher E1 reflects
Germany — the pre-tournament favourite and the model's top pick — crashing out in the group
stage (a genuine upset, not a model error).

### May 30
- **rates.py** — attempted `get_nested_rates()`, blocked by sparse datasets for high-Elo teams.
- **probabilities.py** — `generate_probabilities()`: match-level probabilities from the
  Poisson goal rates of both teams.
- Downloaded WC2026 match data from Kaggle (areezvisram12/fifa-world-cup-2026-match-data)
  and preprocessed into `wc26_matches.csv`, `wc26_groupstage_matches.csv`,
  `wc26_knockout_matches.csv`.
- Tournament rules: downloaded bracket graphics.

### May 28
- **rates.py** — `get_independent_rates()`: independent Poisson rates for both teams.

## Current status
- Built baseline independent Poisson model (goodness-of-fit + deviance analysis).
- Built nested Poisson model for the weaker sides (still off by default — sparsity blocker).
- Monte Carlo tournament engine + 495-combo bracket logic working.
- Backtesting harness validates on WC2018/2022; parameters tuned and redeployed for 2026.

## Notes
- Fall back to the independent model when the Elo difference between teams is small (~50).

## TODO
- ~~Encode bracket combinations~~ (done: full FIFA 495-combo table).
- ~~Perform simulation of the whole tournament~~ (done: Monte Carlo engine).
- ~~Validation on past tournaments (Brier/RPS vs WC2018/2022)~~ (done: `src/backtest.py`;
  both 2018 and 2022 now run on the rebuilt dataset).
- ~~Rebuild matches.csv over the broader backtest team set + pre-2016~~ (done:
  `rebuild_backtest_dataset()` rebuilt to 2010–2026 over 58 teams; 2018 backtest re-run).
- ~~Fine-tune decay ξ, weight floor, and training window on match-level RPS~~ (done:
  half-life 8y / floor 0.1 / 8y lookback). Still open: `K_FACTOR`, `ELO_GAP_THRESHOLD`,
  `PEN_SLOPE` on tournament-level RPS (deferred — 2-tournament objective too noisy).
- Handle sparse teams well enough to **re-enable the nested model** — `home_adv` + the
  lowered sparse threshold help the baseline, but the nested layer is still the blocker
  (tiny samples / implausible Elo signs for strong teams). Refit with pooled/regularised
  params, then re-enable `load_sim_inputs(use_nested=True)` in the simulation.
- Implement Dixon–Coles τ (advertised in the README but not yet implemented).
- Live WC2026 results pipeline + running accuracy/loss (reuse `model/validation.py` metrics).
- ~~Investigate effect of "having home advantage vs no home advantage on spare teams" and
  "spare threshold = 15 vs 20". After that, tune the parameters again.~~ (done Jun 5:
  `compare_configs` → `config_comparison.csv`; adopted home_adv=OFF / threshold=20 / lookback=7y,
  re-tuned + redeployed + team strengths regenerated.)
    - **Favorite overconfidence is unresolved by these knobs** (Ger ~32% in 2018, Net ~20% in
      2022): Germany/Netherlands aren't sparse at the backtest cutoffs, so the sparse-team knobs
      don't touch them — the overconfidence comes from the Elo-driven simulation. Next lever:
      simulation params (K_FACTOR / Elo→rate slope) or a champion-probability shrinkage.
    - France-vs-Peru fixed: France now 4th (5.6%), above Peru (4.4%).
