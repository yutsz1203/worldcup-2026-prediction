# Live tournament scorecard (match-level) and biggest upsets

## Match-level scoring

Model multiclass Brier and ranked probability score (lower is better) against the
uniform no-skill baseline in parentheses, plus top-pick accuracy. `Overall` pools every
per-match-per-market prediction across the three markets.

| Market | n | Brier (no-skill) | RPS (no-skill) | Accuracy |
|--------|--:|-----------------:|---------------:|---------:|
| Overall | 72 | 0.5821 (0.5556) | 0.2452 (0.2384) | 48.6% |
| 1X2 | 24 | 0.6629 (0.6667) | 0.1940 (0.2153) | 41.7% |
| O/U 2.5 | 24 | 0.5194 (0.5000) | 0.2597 (0.2500) | 50.0% |
| O/U 3.5 | 24 | 0.5640 (0.5000) | 0.2820 (0.2500) | 54.2% |

## Biggest upsets

### Biggest model surprises

The matches the model called most wrong, ranked by `surprise = 1 − model_p(actual 1X2
outcome)`. "Model gave" is the probability the model assigned to what actually happened.

| Date | Rd | Match | Result | Model gave | Surprise |
|------|----|-------|:------:|-----------:|---------:|
| 2026-06-16 | G1 | Spain vs Cape Verde | 0-0 | draw 4.0% | 0.960 |
| 2026-06-14 | G1 | Qatar vs Switzerland | 1-1 | draw 13.0% | 0.870 |
| 2026-06-18 | G1 | Portugal vs DR Congo | 1-1 | draw 17.4% | 0.826 |
| 2026-06-16 | G1 | Saudi Arabia vs Uruguay | 1-1 | draw 22.2% | 0.778 |
| 2026-06-16 | G1 | Iran vs New Zealand | 2-2 | draw 22.9% | 0.771 |

### Biggest underdog wins

Decisive results the lower-Elo team won, ranked by the Elo gap they overturned
(independent of the model's probability).

| Date | Rd | Winner (Elo) | Loser (Elo) | Score | Elo gap |
|------|----|--------------|-------------|:-----:|--------:|
| 2026-06-15 | G1 | Ivory Coast (1695) | Ecuador (1938) | 1-0 | 243 |
| 2026-06-18 | G1 | Ghana (1510) | Panama (1730) | 1-0 | 220 |
| 2026-06-14 | G1 | Australia (1777) | Turkey (1911) | 2-0 | 134 |
| 2026-06-13 | G1 | United States (1726) | Paraguay (1834) | 4-1 | 108 |
