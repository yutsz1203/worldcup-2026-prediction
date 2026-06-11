# Jump Trading Probability Cup — Events

## Generalised event taxonomy

Every event is a **boolean predicate over count statistics**, built from three
atomic predicate types combined with AND/OR. An event is fully specified by:

```
Event      := Atom | Event AND Event | Event OR Event
Atom       := THRESHOLD(stat, entity, window, op, k)     # count(stat, entity, window) op k
            | COMPARE(stat, entity1, entity2, window, op) # count(e1) op count(e2)
            | FIRST(stat, entity)                         # entity records the first
                                                          # occurrence of stat in the match
op         := >, >=, <, <=, =
```

### Dimensions

| Dimension | Values seen in the event list |
|---|---|
| `stat` | goal, corner, shot_on_target, foul, card, red_card, penalty_awarded, offside, goal_contribution (goal or assist, excl. own goals) |
| `entity` | team_A, team_B, match_total (A+B), player_p |
| `window` | FT (full match), H1 (first half / "at halftime"), H2 (second half) |
| `k` | event-specific threshold (often 1, i.e. "at least one occurrence") |

Notes:
- "Match outcome" events are not a separate type: *team A wins* =
  `COMPARE(goal, A, B, FT, >)`; *tied at halftime* = `COMPARE(goal, A, B, H1, =)`.
- "Both teams …" is the AND of two per-team thresholds, not its own entity.
- `FIRST` is the only atom that needs *within-match ordering*, not just end-of-window counts.

### Mapping of every listed event

| Event | Canonical form |
|---|---|
| Team A wins | `COMPARE(goal, A, B, FT, >)` |
| Tied at halftime | `COMPARE(goal, A, B, H1, =)` |
| Total goals over/under X | `THRESHOLD(goal, total, FT, >=/<, X)` |
| Team A scores in 2nd half | `THRESHOLD(goal, A, H2, >=, 1)` |
| BTTS and X+ total goals | `THRESHOLD(goal, A, FT, >=, 1) AND THRESHOLD(goal, B, FT, >=, 1) AND THRESHOLD(goal, total, FT, >=, X)` |
| 2nd half has X+ goals | `THRESHOLD(goal, total, H2, >=, X)` |
| A scores first, B scores in H2 | `FIRST(goal, A) AND THRESHOLD(goal, B, H2, >=, 1)` |
| Team A scores X+ goals | `THRESHOLD(goal, A, FT, >=, X)` |
| More corners at HT / in H2 / FT | `COMPARE(corner, A, B, H1/H2/FT, >)` |
| Team A X+ corners | `THRESHOLD(corner, A, FT, >=, X)` |
| More SOT in 2nd half | `COMPARE(shot_on_target, A, B, H2, >)` |
| X+ total SOT in 2nd half | `THRESHOLD(shot_on_target, total, H2, >=, X)` |
| Both teams 1+ SOT at HT | `THRESHOLD(sot, A, H1, >=, 1) AND THRESHOLD(sot, B, H1, >=, 1)` |
| Team A X+ SOT in 2nd half | `THRESHOLD(shot_on_target, A, H2, >=, X)` |
| A more fouls than B | `COMPARE(foul, A, B, FT, >)` |
| A more cards than B | `COMPARE(card, A, B, FT, >)` |
| Penalty OR red card | `THRESHOLD(penalty_awarded, total, FT, >=, 1) OR THRESHOLD(red_card, total, FT, >=, 1)` |
| Penalty awarded | `THRESHOLD(penalty_awarded, total, FT, >=, 1)` |
| X+ cards in 2nd half / total | `THRESHOLD(card, total, H2/FT, >=, X)` |
| Team 1+ card in 2nd half | `THRESHOLD(card, team, H2, >=, 1)` |
| Team A/B X+ offsides | `THRESHOLD(offside, A/B, FT, >=, X)` |
| Player X scores | `THRESHOLD(goal, player_p, FT, >=, 1)` |
| Player X scores or assists | `THRESHOLD(goal_contribution, player_p, FT, >=, 1)` |
| Player X k+ SOT (FT / H2) | `THRESHOLD(shot_on_target, player_p, FT/H2, >=, k)` |

## Implications for the prediction pipeline

The taxonomy reduces the pipeline to one design: **model the joint distribution of a
per-match "stat line", then evaluate each event as an indicator function on it.**

A simulated stat line per match needs:

1. **Per-window, per-team counts** for each `stat` — goals, corners, SOT, fouls, cards,
   red cards, penalties, offsides — split into H1 and H2 (FT is the sum, so H1/H2 is the
   atomic granularity; "at halftime" = H1).
2. **Joint dependence between team A and team B counts** — required by every `COMPARE`
   atom (especially ties, which are sensitive to the dependence structure) — and across
   stats/windows for AND/OR compositions (e.g. BTTS ∧ over-X couples three margins).
3. **Within-match goal ordering** for `FIRST` — either simulate goal times (competing
   Poisson processes: P(A scores first | a goal occurs) = λ_A / (λ_A + λ_B)), or draw an
   ordering conditional on the simulated half-by-half goal counts.
4. **Player-level allocation** for player-specific events — distribute team goals /
   goal contributions / SOT over players (e.g. multinomial shares per player, conditioned
   on expected minutes).

With that, every event — current and future, as long as it stays within this grammar —
is priced the same way: simulate N stat lines, compute the mean of the event's indicator.
Closed-form shortcuts (e.g. Poisson CDF for simple thresholds, Skellam for goal
comparisons) remain available as fast paths / sanity checks, but the Monte Carlo
evaluator is the general engine and matches the existing tournament-simulation
architecture.

## Hand-written event spec format

The pipeline (see `jumpcup/`) prices a per-match JSON spec at
`jumpcup/data/live/spec_{event_id}.json`. Jump's 10 free-text events are
translated by hand (in a Claude chat) into this format — there is deliberately no
natural-language parser.

```
uv run python -m jumpcup.predict rates --team-a Mexico --team-b "South Africa"   # or --event-id
uv run python -m jumpcup.predict price --event-id 8287
```

Top level:

```json
{
  "event_id": 8287,
  "team_A": "Mexico",
  "team_B": "South Africa",
  "events": [ {"id": 1, "text": "<Jump's wording>", "spec": <node>}, ... ]
}
```

`team_A` is always the feed's **home** side (the rates CSV records the mapping).
A `<node>` is one of:

- `{"and": [<node>, ...]}` / `{"or": [<node>, ...]}` — boolean composition
- `{"atom": "threshold", "stat": S, "entity": E, "window": W, "op": OP, "k": K}`
- `{"atom": "compare", "stat": S, "left": E, "right": E, "window": W, "op": OP}`
- `{"atom": "first", "stat": S, "entity": "team_A" | "team_B"}`

with `S` ∈ goal, corner, shot_on_target, foul, card, red_card, penalty_awarded,
offside, assist, goal_contribution; `W` ∈ H1, H2, FT; `OP` ∈ `>`, `>=`, `<`, `<=`, `=`;
`E` ∈ `"team_A"`, `"team_B"`, `"match_total"`, or
`{"player": "<name as in lineup>", "team": "team_A"}` (`team` optional — the pricer
resolves accent-insensitively against the rates CSV and fails loudly if ambiguous).
Player entities only support goal, assist, goal_contribution, shot_on_target.

Example covering all atom types:

```json
{
  "event_id": 8287,
  "team_A": "Mexico",
  "team_B": "South Africa",
  "events": [
    {"id": 1, "text": "Will Mexico win?",
     "spec": {"atom": "compare", "stat": "goal", "left": "team_A", "right": "team_B",
              "window": "FT", "op": ">"}},
    {"id": 2, "text": "Will Raul Jimenez have 2+ shots on target in the 2nd half?",
     "spec": {"atom": "threshold", "stat": "shot_on_target",
              "entity": {"player": "Raúl Jiménez", "team": "team_A"},
              "window": "H2", "op": ">=", "k": 2}},
    {"id": 3, "text": "Will a penalty be awarded or a red card shown?",
     "spec": {"or": [
        {"atom": "threshold", "stat": "penalty_awarded", "entity": "match_total",
         "window": "FT", "op": ">=", "k": 1},
        {"atom": "threshold", "stat": "red_card", "entity": "match_total",
         "window": "FT", "op": ">=", "k": 1}]}},
    {"id": 4, "text": "Will Mexico score first and South Africa score in the 2nd half?",
     "spec": {"and": [
        {"atom": "first", "stat": "goal", "entity": "team_A"},
        {"atom": "threshold", "stat": "goal", "entity": "team_B",
         "window": "H2", "op": ">=", "k": 1}]}}
  ]
}
```
