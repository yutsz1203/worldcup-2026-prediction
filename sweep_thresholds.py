"""Empirically decide SPARSE_THRESHOLD (sparse-team neutral-match cutoff).

Two parts, matching the experiment plan:

  Step 1 — sweep the backtest over thresholds {10,12,15,20,25} at the production
  default (use_home_adv=False) and write `data/result/tuning/config_comparison.csv`.

  Step 2 — for the two candidate thresholds {10, 20}, refit the live 2026 model
  (`redeploy_2026`) and recompute `team_strengths`, saving each to a scratch file
  (`team_strengths_thr10.csv` / `team_strengths_thr20.csv`) so we can diff the
  fitted attack/defense rates of the teams the threshold actually moves.

Production `baseline_params.csv` / `team_strengths.csv` are restored at the end —
this runner is read-only with respect to deployed artifacts.
"""

import shutil

import pandas as pd

from src.backtest import compare_configs, redeploy_2026, team_strengths
from src.const import CLEANED_DATA_PATH, CON, FORECAST_PATH, TUNING_PATH

N_SIMS = 100000
SEED = 2026
THRESHOLDS = (10, 12, 15, 20, 25)
SANITY_THRESHOLDS = (10, 20)

# Teams in the 10–19 neutral band — the ones that flip between neutral-only and
# the broadened fallback as the threshold crosses them (for focused diffing).
FLIP_BAND = [
    "Spain", "Croatia", "England", "Belgium", "Switzerland",
    "Portugal", "Netherlands", "Sweden", "Czechia", "Turkey",
    "Norway", "Austria", "Germany", "France", "Scotland",
]

if __name__ == "__main__":
    base_csv = f"{CLEANED_DATA_PATH}/baseline_params.csv"
    strengths_csv = f"{FORECAST_PATH}/team_strengths.csv"
    prod_base_backup = f"{CLEANED_DATA_PATH}/baseline_params_prod_backup.csv"
    prod_strengths_backup = f"{FORECAST_PATH}/team_strengths_prod_backup.csv"

    # --- Step 1: threshold sweep (production knob: home_adv=False) ---------------
    CON.rule("Step 1 — threshold sweep")
    compare_configs(
        threshold_options=THRESHOLDS,
        home_adv_options=(False,),
        n_sims=N_SIMS,
        seed=SEED,
    )

    # --- Step 2: refit + strengths at each candidate threshold -------------------
    strengths = {}
    for th in SANITY_THRESHOLDS:
        CON.rule(f"Step 2 — redeploy + strengths at thr={th}")
        redeploy_2026(n_sims=N_SIMS, sparse_threshold=th)
        df = team_strengths()
        scratch = f"{TUNING_PATH}/team_strengths_thr{th}.csv"
        shutil.copy(strengths_csv, scratch)
        strengths[th] = df.set_index("team")
        CON.log(f"thr={th} strengths → {scratch}")

    # --- Diff the flip-band teams between the two thresholds ---------------------
    lo, hi = SANITY_THRESHOLDS
    a, b = strengths[lo], strengths[hi]
    rows = []
    for t in FLIP_BAND:
        if t not in a.index or t not in b.index:
            continue
        rows.append(
            {
                "team": t,
                f"xgf_thr{lo}": a.loc[t, "xgf_vs_avg"],
                f"xgf_thr{hi}": b.loc[t, "xgf_vs_avg"],
                "d_xgf": round(a.loc[t, "xgf_vs_avg"] - b.loc[t, "xgf_vs_avg"], 3),
                f"xga_thr{lo}": a.loc[t, "xga_vs_avg"],
                f"xga_thr{hi}": b.loc[t, "xga_vs_avg"],
                "d_xga": round(a.loc[t, "xga_vs_avg"] - b.loc[t, "xga_vs_avg"], 3),
            }
        )
    diff = pd.DataFrame(rows).sort_values(
        "d_xgf", key=lambda s: s.abs(), ascending=False
    )
    diff_out = f"{TUNING_PATH}/threshold_strength_diff.csv"
    diff.to_csv(diff_out, index=False)
    CON.rule(f"Flip-band rate diff (thr={lo} vs thr={hi})")
    CON.print(diff.to_string(index=False))
    CON.log(f"Diff → {diff_out}")

    # --- Restore production fits -------------------------------------------------
    shutil.copy(prod_base_backup, base_csv)
    shutil.copy(prod_strengths_backup, strengths_csv)
    CON.rule("Restored production baseline_params.csv / team_strengths.csv")
