# Roadmap

- [ ] **2 — Market comparison / value-bet discovery.**
  Compare Polymarket (and other) odds against model outputs to surface value opportunities. Capture
  the **opening line** now and track closing-line value (CLV) per market. This is the most perishable
  item: value bets only exist pre-match, and CLV can only be measured if the opening snapshot is taken
  before the line moves. Wire it to the task 1 snapshot.

- [ ] **3 - Match preview** 
  Use the new data source - bzzoiro, to make a match preview that shows
  - h2h results
  - team top xg players
  - team elo

- [ ] **4 — Running scorer.**
  Score the predictions-vs-actuals ledger as results land: `brier_multiclass` / `rps` vs a uniform
  baseline, binary Brier for over/under, with cumulative columns. Must be ready the day MD1 results
  post so the scorecard grows live. (Scoring math already exists in `model/validation.py` — pure
  glue.). Calibration checking as well.

- [ ] **5 — Live tournament re-sim (due before MD2).**
  Wrap `monte_carlo`: seed completed matches + re-scraped Elo, re-sim the remainder, re-snapshot
  reach-probabilities. Reuses `play_match`. First run between MD1 and MD2, then refresh each matchday.

- [ ] **6 - Running biggest surprise log**
  "Biggest surprise log": capture the largest `|model_p − outcome|` matches and tournament-level
    upsets — a compact, memorable story artifact.

## Tier 2 — Whenever, but high portfolio value (any time after the snapshot)

- [ ] **7 — Visualization / dashboard. `(NEW)`**
  Visualising the model's output for the upcoming matches, likely on a web interface.

## Tier 3 — Post-tournament

- [ ] **10 — Final validation wrap-up.**
  Full post-mortem scorecard vs. the locked pre-tournament forecast: final Brier/RPS, calibration,
  champion-prob rank of the actual winner.

- [ ] **11 — Post-tournament data + narrative.**
  - Append finalized WC2026 results → `matches.csv` for the WC2030 build.

