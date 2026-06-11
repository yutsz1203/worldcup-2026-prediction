# WC2026 Prediction Model — Development Plan

**Model:** Nested Poisson regression with Elo covariates (Gilch & Müller, 2018)
**Timeline:** 15 May → 11 June 2026 (4 weeks)
**Target outputs:** Match-level win/draw/loss probabilities, over/under goal probabilities, tournament stage probabilities for all 48 teams


## Tournament Structure

48 teams in 12 groups of 4. Each team plays 3 group matches. Top 2 per group (24 teams) plus 8 best third-placed teams advance to a Round of 32, then single elimination through R16 → QF → SF → Final. Extra time (30 min) and penalties apply in knockouts. All matches on neutral ground (USA/Canada/Mexico).

**Groups:**

| Group | Teams |
|-------|-------|
| A | Mexico, South Africa, South Korea, Czechia |
| B | Canada, Bosnia-Herzegovina, Qatar, Switzerland |
| C | Brazil, Morocco, Haiti, Scotland |
| D | United States, Paraguay, Australia, Türkiye |
| E | Germany, Curaçao, Ivory Coast, Ecuador |
| F | Netherlands, Japan, Sweden, Tunisia |
| G | Belgium, Egypt, Iran, New Zealand |
| H | Spain, Cape Verde, Saudi Arabia, Uruguay |
| I | France, Senegal, Iraq, Norway |
| J | Argentina, Algeria, Austria, Jordan |
| K | Portugal, DR Congo, Uzbekistan, Colombia |
| L | England, Croatia, Ghana, Panama |

**Knockout bracket:** Two separate pathways to the semis. Spain/Argentina and France/England are on opposite sides, so they can't meet before the SF (if they win their groups). All possible combinations for the round of 32 can be viewed at: https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage#Combinations_of_matches_in_the_round_of_32



## Phase 1: Data Sourcing (Days 1–4)

### 1a. Elo ratings

**Source:** eloratings.net — scrape or manually extract current Elo ratings for all 48 teams.

These are your static input covariates at the start of the simulation. You'll update them dynamically during each Monte Carlo run (see Phase 4).

**Deliverable:** `elo_ratings.csv` — columns: `team`, `elo_rating`, `date_retrieved`

### 1b. Historical match data

**Source:** Pick one primary source and stick with it:
- **International football results (Kaggle/GitHub):** Mart Jürisoo's dataset (`international_football_results.csv`) covers every international match since 1872 with dates, scores, tournament type, and venue. This is the fastest route.
- **FBref** as a secondary source if you want xG-level data (not strictly necessary for this model).

**Scope:** All international matches of all 48 participating teams from **1 Jan 2018** to present. The paper used ~8 years of data; 2018–2026 gives you the same window.

**Filter to neutral-ground matches only.** The paper showed that including home/away qualifiers with a home-advantage covariate flattened all win probabilities to ~2–6%. Tournament-style matches on neutral ground are the target population. Exception: include major tournament matches played in the host country (e.g., Germany at Euro 2024, Qatar at WC 2022) since these behave more like neutral matches than home qualifiers.


- build historical_elo.csv by web scraping of all teams (appears in the data) asynchrously
- concat elo of both teams to each of the matches

**Deliverable:** `matches.csv` — columns: `date`, `team_a`, `team_b`, `goals_a`, `goals_b`, `elo_a`, `elo_b` (Elo at date of match)

### 1c. Historical Elo ratings

You need each team's Elo at the date of each historical match, not just today's values. Options:
- eloratings.net has historical data
- Compute Elo yourself from match results (more work but gives you full control over the K-factor and weighting)

For a 4-week build, scraping historical Elo from eloratings.net is the pragmatic choice.

-- Do the following section before monte-carlo-simulation. Skip for now. --
### 1d. Tournament rules & bracket logic

Encode the full WC2026 rules:
- Group tiebreakers: points → GD → GF → head-to-head → fair play → FIFA ranking
- Best third-place ranking: points → GD → GF → fair play → FIFA ranking
- R32 bracket structure: group winners vs third-placed teams, runners-up vs other group winners/runners-up (the exact bracket mapping depends on which third-placed teams qualify — there are multiple possible combinations)
- Extra time: simulate with Poisson rates scaled to 30/90 = 1/3 of normal rates
- Penalties: model as a coin flip (50/50) or use a simple calibrated probability

**Key complexity:** The R32 bracket assignment depends on which 8 of the 12 third-placed teams qualify. FIFA has published the possible bracket combinations. Source these from FIFA's official knockout stage documentation and hard-code them.


## Phase 2: Model Building (Days 4–10) — ✅ DONE

Independent baseline (2a) and nested extension (2b) fitted for all teams; sparse-data
handling (2c) addressed via the `home_adv` covariate and the adaptive per-team training
filter. The nested layer is built but stays off by default in the simulation until the
sparsity blocker is resolved (see `changelog.md` TODO).

### 2a. Independent Poisson baseline (build first) — ✅

For each team T, fit two Poisson regressions on their neutral-ground match history:

**Attack regression (goals scored by T):**
```
log μ_T(Elo_O) = α₀ + α₁ · Elo_O
```

**Defence regression (goals conceded by T):**
```
log ν_T(Elo_O) = β₀ + β₁ · Elo_O
```

**Model for sparse teams**
```
log μ_T(Elo_O) = α₀ + α₁ · Elo_O + α₂ · home_adv
```

Where `Elo_O` is the opponent's Elo at match date.


For a match between A and B:
```
λ_A|B = (μ_A(Elo_B) + ν_B(Elo_A)) / 2
λ_B|A = (μ_B(Elo_A) + ν_A(Elo_B)) / 2
```

**Modification from paper — use your exponential decay weighting.** Rather than the paper's hard cutoff of "all matches since 2010", weight each match with `w = exp(-ξ · Δt)` where `Δt` is time in days from the match to the tournament start. This is better than a hard cutoff and you already have experience with it. Choose ξ so that matches from ~3 years ago have roughly half-weight. Fit the regressions as weighted Poisson GLMs.

**Implementation:** Python with `statsmodels` (weighted GLM with Poisson family) or R with `glm()`. Python is probably faster given your existing codebase.

**Validation checkpoint:** For each team, run a goodness-of-fit χ² test as in the paper. Check that top teams have acceptable p-values (>0.05). If a team has a terrible fit (like France in the paper), investigate and adjust the data window.

**Deliverable:** Fitted `(α₀, α₁, β₀, β₁)` per team. A function `predict_rates(team_a, team_b, elo_a, elo_b) → (λ_A|B, λ_B|A)`.

### 2b. Nested extension — ✅ (built; off by default pending sparsity fix)

Add the nested conditioning layer. For each team B (the weaker team in any matchup), fit an additional regression:

```
log λ_B(Elo_A, G_A) = γ₀ + γ₁ · Elo_A + γ₂ · G_A
```

Where `G_A` is the number of goals actually scored by the stronger team.

**Training data:** For each match where team B was the weaker side (lower Elo), use `(Elo_opponent, goals_opponent, goals_B)` as the training row.

**Simulation changes:** Instead of drawing `G_A` and `G_B` independently:
1. Draw `G_A ~ Poisson(λ_A|B)` using the independent model's rate
2. Compute `λ_B|A = exp(γ₀ + γ₁ · Elo_A + γ₂ · G_A)`
3. Draw `G_B ~ Poisson(λ_B|A)`

Always assign the higher-Elo team as "team A" for this step.

**Deliverable:** Fitted `(γ₀, γ₁, γ₂)` per team. Updated `simulate_match()` function.

### 2c. Sparse data handling — ✅ (home_adv covariate + adaptive per-team filter)

Some teams (Norway, Bosnia, Austria, Scotland) have very few neutral-ground matches in your dataset. 

Approach: 
- **Include home/away matches** for these teams only, with a home-advantage covariate — the paper showed this doesn't work for strong teams, but for weak teams with tiny sample sizes it may be the lesser evil.

## Phase 3: Match Probability Extraction (Days 10–12)

### 3a. Match outcome probabilities

Given `(λ_A|B, λ_B|A)`, compute:

**For the independent model:**
```
P(G_A = i, G_B = j) = Poisson(i; λ_A|B) × Poisson(j; λ_B|A)
```

Sum over the grid `(i, j)` for `i, j ∈ {0, ..., 10}` to get:
- `P(win_A)`, `P(draw)`, `P(win_B)` — moneyline market
- `P(total > 2.5)`, `P(total > 3.5)` — over/under markets
- `P(BTTS)` — both teams to score

**For the nested model:** You can't get closed-form joint probabilities. Instead, enumerate: for each `g_a ∈ {0,...,10}`, compute `P(G_A = g_a)` from the Poisson, then compute `λ_B|A(g_a)` and get `P(G_B = j | G_A = g_a)`. The joint probability is:
```
P(G_A = i, G_B = j) = Poisson(i; λ_A|B) × Poisson(j; λ_B|A(i))
```

This is still tractable analytically — no simulation needed for single-match probabilities.

### 3b. Brier score validation

Before running tournament simulations, validate single-match predictions on a holdout. Use all neutral-ground matches from 2024–2025 as your test set (or the 2022 World Cup). Compute Brier scores for the moneyline market and compare against the 0.25 no-skill baseline.

**Target:** If your model can't beat 0.25 on single matches, the tournament simulation won't be meaningful.


## Phase 4: Monte Carlo Tournament Simulation (Days 12–18)

### 4a. Group stage simulation

For each of the 100,000 iterations:
1. Start with current Elo ratings for all 48 teams
2. Simulate all 3 matches per group (36 total group matches per iteration)
3. After each simulated match, update Elo ratings for both teams using the standard Elo update formula with an appropriate K-factor (the paper showed this matters — up to 5pp difference in final probabilities)
4. Rank teams within each group by points → GD → GF → head-to-head
5. Determine which 8 third-placed teams advance
6. Assign R32 bracket positions based on the FIFA-published combinations

### 4b. Knockout stage simulation

For each knockout match:
1. Simulate 90 minutes using the nested model with current (updated) Elo ratings
2. If drawn, simulate extra time: same Poisson model but with rates divided by 3
3. If still drawn after extra time, decide by penalty shootout (coin flip or calibrated probability — historical data suggests ~55/45 in favour of the team that shoots first, but this is marginal)
4. Update Elo ratings after each knockout match

### 4c. Output collection

For each iteration, record:
- Final group standings (all 12 groups)
- Which stage each team reached (group exit, R32, R16, QF, SF, final, champion)
- All match scores

Aggregate over 100,000 iterations to get:
- `P(team reaches stage X)` for each team and each stage
- Group-stage qualification probabilities
- Head-to-head probabilities for key matchups (e.g., Spain vs Argentina in the final)

### 4d. Performance

100,000 iterations × ~68 matches per iteration = ~6.8M match simulations. Each match simulation is a couple of Poisson draws — this is trivial computationally. In Python with numpy vectorisation, expect this to run in under a minute. Don't over-engineer the parallelism.


## Phase 5: Validation (Days 18–22)

### 5a. Retrospective validation on WC2022

Refit the model using only data available before the 2022 World Cup (matches up to Nov 2022, Elo ratings as of Nov 2022). Run 100,000 tournament simulations with the WC2022 bracket and format. Compare:

- Team-level stage probabilities vs actual outcomes using Brier score and RPS (as in the paper)
- Single-match moneyline Brier scores across all 64 matches

### 5b. Score functions

Use the paper's four scoring rules:
- **E1 (Max-likelihood error):** |actual_stage - predicted_most_likely_stage| summed over all teams
- **E2 (Weighted differences):** Σ p_j × |j - actual_stage| summed over all teams
- **Brier score:** Standard Brier over the 6-category stage distribution per team
- **RPS:** Ranked probability score over the ordinal stage variable

Compare the nested model vs the independent baseline on all four metrics.

### 5c. Calibration check

Bin your predicted match probabilities into deciles (0–10%, 10–20%, etc.) and check whether the observed win rate within each bin matches the predicted probability. Plot a calibration curve.


## Phase 6: Production Run & Output (Days 22–26)

### 6a. Final model run

With the validated model, run the WC2026 simulation:
- Current Elo ratings (scraped fresh)
- Full 48-team bracket
- 100,000+ iterations

### 6b. Outputs to generate

1. **Team probability table:** P(champion), P(final), P(SF), P(QF), P(R16), P(R32), P(group exit) for all 48 teams
2. **Match-level probabilities:** For every group-stage match, produce P(win/draw/loss), P(O/U 2.5), P(O/U 3.5), P(BTTS) — these are your betting market outputs
3. **Group qualification probabilities:** P(1st), P(2nd), P(3rd qualifying), P(3rd non-qualifying), P(4th) per team per group
4. **Sankey diagram:** As in the paper, a flow visualisation from groups through to the final (optional but impressive)

### 6c. Brier score reporting

For each betting market you produce probabilities for, state the expected Brier score from your validation. This is your credibility metric — anyone can produce probabilities, the Brier score relative to 0.25 is what shows whether there's genuine skill.


## Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Sparse data for debutant teams (Curaçao, Cape Verde, Haiti, etc.) | Bad regression fits, meaningless probabilities | Pooled regression fallback for teams with <10 neutral matches |
| R32 bracket combinations are complex | Wrong bracket logic invalidates simulations | Source bracket rules directly from FIFA, write unit tests for every combination |
| Elo source goes down or has stale data | No covariates | Have a backup plan to compute Elo from scratch using match results |
| Model overfits to historical data | Poor out-of-sample performance | Validate on WC2022 before trusting WC2026 predictions |
| Time pressure | Incomplete model | The independent model (Phase 2a) is a working fallback — ship that if the nested extension doesn't come together |


## Daily Targets

| Days | Phase | Milestone |
|------|-------|-----------|
| 1–2 | Data | Elo ratings scraped, match dataset downloaded and filtered |
| 3–4 | Data | Historical Elo joined to matches, tournament rules encoded |
| 4–7 | Model | Independent Poisson regressions fitted for all 48 teams, GoF tests pass |
| 7–10 | Model | Nested extension fitted, sparse-data fallbacks in place |
| 10–12 | Probabilities | Match probability functions working, holdout Brier scores computed |
| 12–16 | Simulation | Group stage simulation working end-to-end |
| 16–18 | Simulation | Full tournament simulation (group + knockout) running |
| 18–22 | Validation | WC2022 retrospective validation complete, score functions computed |
| 22–24 | Production | Final WC2026 simulation run, all outputs generated |
| 25–26 | Buffer | Bug fixes, additional markets, visualisation |
| 27–28 | Buffer | Contingency |

