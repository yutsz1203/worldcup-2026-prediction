"""Run the 2018 & 2022 backtests on the current (tuned) params and persist scores.

`run_backtest` already writes per-match / per-team / calibration CSVs but only
*prints* the summary score-function metrics. This runner collects those summaries
for both tournaments and writes a single tidy table to
`data/result/validation/validation_scores_latest.csv` for future reference.
"""

import pandas as pd

from src.backtest import (
    HALF_LIFE_YEAR,
    LOOKBACK_YEARS,
    SPARSE_THRESHOLD,
    USE_HOME_ADV,
    WEIGHT_FLOOR,
    run_backtest,
)
from src.const import CON, VALIDATION_PATH

N_SIMS = 100000
SEED = 2026

if __name__ == "__main__":
    rows = []
    for year in (2018, 2022):
        res = run_backtest(year, n_sims=N_SIMS, seed=SEED)
        m, t = res["match"], res["tournament"]
        rows.append(
            {
                "year": year,
                # provenance: which params produced these scores
                "half_life_years": HALF_LIFE_YEAR,
                "weight_floor": WEIGHT_FLOOR,
                "lookback_years": LOOKBACK_YEARS,
                "use_home_adv": USE_HOME_ADV,
                "sparse_threshold": SPARSE_THRESHOLD,
                "n_sims": N_SIMS,
                "seed": SEED,
                # match-level 1X2 score functions
                "match_n": m["n_matches"],
                "match_brier": round(m["brier"], 4),
                "match_brier_uniform": round(m["baseline_brier"], 4),
                "match_rps": round(m["rps"], 4),
                "match_rps_uniform": round(m["baseline_rps"], 4),
                "match_accuracy": round(m["accuracy"], 4),
                # tournament-level stage-reached score functions (totals over teams)
                "tourn_n_teams": t["n_teams"],
                "tourn_E1": round(t["E1"], 3),
                "tourn_E2": round(t["E2"], 3),
                "tourn_brier": round(t["brier"], 3),
                "tourn_rps": round(t["rps"], 3),
            }
        )

    scores = pd.DataFrame(rows)
    out = f"{VALIDATION_PATH}/validation_scores_latest.csv"
    scores.to_csv(out, index=False)
    CON.rule("Saved score functions")
    CON.log(f"Consolidated score functions → {out}")
    CON.print(scores.to_string(index=False))
