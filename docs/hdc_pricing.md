# HKJC Handicap (HDC) Pricing — Calculation Methods

How the live layer prices Asian-handicap markets against HKJC's posted odds: the settlement
model, the probability machinery, and the derived quantities (fair odds, min odds, EV) shown
in the Streamlit dashboard's HKJC HDC EV tab (`streamlit run dashboard/app.py`).

Code: `model/probabilities.py` (`build_score_matrix`, `generate_handicap_probabilities`,
`fair_odds`, `min_odds`, `settlement_ev`) and `src/hkjc.py` (scraper + pricing,
`hdc_ev_table(round_id=...)`).

---

## 1. The market being priced

HKJC HDC is a **two-outcome** Asian handicap settled on the full-time score adjusted by the
handicap line (no extra time). There is no draw selection; instead, whole-goal and split
("quarter") lines can refund part or all of the stake:

- **Half-ball line** (−0.5, −1.5, …): wins or loses outright. Canada −0.5 wins iff Canada wins.
- **Whole-ball line** (0, −1, −2, …): adds a *push* — if the adjusted score lands exactly level
  (e.g. Canada −1 and Canada wins by exactly 1), the stake is refunded.
- **Quarter / split line** (`[-0.5/-1]`, `[0/+0.5]`, …): half the stake on each adjacent line.
  Outcomes become win / **half-win** / push / **half-lose** / lose. Example — $100 on Canada
  `[-0.5/-1]` is $50 on −0.5 plus $50 on −1: Canada by 2+ → both win; by exactly 1 → the −0.5
  half wins, the −1 half refunds ("half win"); draw or loss → all lost.

Lines are quoted on the **home team** as HKJC lists it; the away side holds the mirrored + line.

**Payout per $1 stake at decimal odds `o`** (this settlement vector drives every formula below):

| Outcome   | Return |
|-----------|--------|
| win       | `o` |
| half-win  | `(o + 1) / 2` (half the stake at `o`, half refunded) |
| push      | `1` |
| half-lose | `1/2` |
| lose      | `0` |

---

## 2. Settlement probabilities from the score matrix

The frozen GLM maps the two teams' current Elo ratings to expected goals
(λ_home, λ_away) via `get_independent_rates` (capped at `MAX_LAMBDA = 15`). Goals are modelled
as **independent Poissons**, giving the joint scoreline pmf as an outer product, truncated at
19 goals per team and renormalised (`build_score_matrix`):

```
P(home = i, away = j) = Pois(i; λ_home) · Pois(j; λ_away)
```

Everything below is a sum over cells of this 20×20 grid, bucketed by goal difference
`D = i − j`. For a line `ℓ` (home perspective, any sign, multiple of 0.25):

- **Whole/half line**: `p_win = P(D + ℓ > 0)`, `p_push = P(D + ℓ = 0)` (zero for half lines),
  `p_lose` the remainder.
- **Quarter line**: settle the two component lines `ℓ ± 0.25` separately and combine. Because
  the components differ by half a goal, at most one can push at any `D`, so:
  `p_win = min` of the component win probs, `p_half_win = |difference|` of them, and
  symmetrically for the lose side; `p_push = 0`.

The away side never needs its own computation — its outcome vector is the home vector read in
reverse (win ↔ lose, half-win ↔ half-lose, same push).

Worked example (Canada λ = 1.63 vs Bosnia λ = 0.79, line `[-0.5/-1]`, i.e. ℓ = −0.75):

| Outcome | Event | Probability |
|---|---|---|
| win | Canada by 2+ | 0.3148 |
| half-win | Canada by exactly 1 | 0.2607 |
| lose | draw or Bosnia win | 0.4245 |

---

## 3. Fair odds

The break-even price: the decimal odds `o` at which expected return equals the stake. Setting
E[return] = 1 with the settlement vector from §1:

```
o · p_win + (o+1)/2 · p_half_win + p_push + 1/2 · p_half_lose = 1

         1 − p_push − (p_half_win + p_half_lose) / 2
o_fair = ─────────────────────────────────────────────        (fair_odds)
                   p_win + p_half_win / 2
```

Example: `(1 − 0.2607/2) / (0.3148 + 0.2607/2) = 0.8697 / 0.4452 = 1.95` for Canada;
the mirrored vector gives 2.05 for Bosnia. Fair odds carry no margin: for half-ball lines
`1/o_home + 1/o_away = 1` exactly (push/half outcomes make the identity approximate otherwise).

## 4. EV at the offered odds

Plug the bookmaker's price into the same expected return and subtract the stake
(`settlement_ev`):

```
EV = o_offered · p_win + (o_offered+1)/2 · p_half_win + p_push + p_half_lose/2 − 1
```

Example at HKJC's 2.07: `2.07·0.3148 + 1.535·0.2607 − 1 = +5.2%`. The away side at 1.77 gives
−11.8%. Both sides cannot be positive: HKJC's implied probabilities sum to ~1.048 (≈4.8%
overround — their margin).

## 5. Min odds (the betting rule)

The offered price at which a side first clears the required edge (`min_odds`; default
`MIN_EDGE = +5%` EV). Same equation as §3 solved for E[return] = 1 + edge:

```
o_min = (1 + edge − p_push − (p_half_win + p_half_lose)/2) / (p_win + p_half_win/2)
```

Decision rule: **bet a side only if the posted odds ≥ its min odds.** Equivalent mental
shortcut: o_min/o_fair ≈ ×1.05 for half-ball lines, ×1.06 for quarter lines, ×1.07 for whole
lines — push/half-refund outcomes dilute a price gap, so push-capable lines need a larger
markup for the same edge.

---

## 6. Known limitations

- **No Dixon–Coles correction** (deliberately deferred). Independent Poissons slightly misprice
  the low-score cells (0-0, 1-0, 0-1, 1-1) — exactly the goal differences (0, ±1) that decide
  pushes and half outcomes. Lines near level for evenly matched teams are the most exposed;
  consider demanding ~7–8% EV there instead of 5%.
- **Lambdas are frozen-GLM + Elo only** — no lineup, injury, or team-news information. A large
  EV (15%+) usually means the market knows something the model doesn't, not free money; trust
  modest 5–10% edges more than spectacular ones.
- Fair/EV numbers use the **cached Elo snapshot** by default
  (`hdc_ev_table(rescrape_elo=True)` to refresh), and the scraped odds are a moving snapshot —
  re-scrape for current prices.
