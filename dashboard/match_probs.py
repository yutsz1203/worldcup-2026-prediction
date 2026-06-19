"""Match probs tab — the locked round forecasts from ``wc2026_match_probs.csv``.

Pick a round, scan the color-graded probability table, then type a market's
prices (Polymarket ¢ = probability in %) into the comparison panel to get the
model's edge per outcome.
"""

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common import ev_color, prob_cell, score_cell, xg_cell
from src.forecast import MATCH_PROBS_PATH, ROUND_ORDER

PROB_COLS = {
    "Home": "p_home",
    "Draw": "p_draw",
    "Away": "p_away",
    "O2.5": "p_over25",
    "U2.5": "p_under25",
    "O3.5": "p_over35",
    "U3.5": "p_under35",
}


@st.cache_data(ttl=300)
def load_probs() -> pd.DataFrame:
    return pd.read_csv(MATCH_PROBS_PATH)


@st.cache_data(ttl=300)
def load_concluded() -> set[str]:
    """``match_uid``s of matches the results feed marks as already played."""
    from src.bzzoiro import load_resolved_fixtures_csv

    res = load_resolved_fixtures_csv()
    return set(res.loc[res["played"], "match_uid"])


def render_match_probs() -> None:
    probs = load_probs()
    concluded = load_concluded()
    rounds = sorted(probs["round_id"].unique(), key=ROUND_ORDER.index)
    round_id = st.sidebar.selectbox("Round", rounds, index=len(rounds) - 1)
    hide_concluded = st.sidebar.checkbox("Hide concluded matches", value=True)
    rows = (
        probs[probs["round_id"] == round_id]
        .sort_values(["date", "stage"])
        .reset_index(drop=True)
    )
    if hide_concluded:
        rows = rows[~rows["match_uid"].isin(concluded)].reset_index(drop=True)
    if rows.empty:
        st.title(f"Match probabilities — Round {round_id}")
        st.info("Every match in this round has concluded — untick to show them.")
        return

    st.title(f"Match probabilities — Round {round_id}")
    st.caption(
        f"Elo retrieved {rows['elo_retrieved_date'].iloc[0]} · "
        f"model {rows['model_version'].iloc[0]} · locked, never recomputed. "
        "Cells are model probability (fair decimal odds); darker = more likely."
    )

    view = pd.DataFrame(
        {
            "Date": rows["date"].str[8:10] + "/" + rows["date"].str[5:7],
            "Stage": rows["stage"],
            "Match": rows["home_team"] + " vs " + rows["away_team"],
            "Score": [
                score_cell(h, a)
                for h, a in zip(rows["pred_home"], rows["pred_away"])
            ],
            "xG": [
                xg_cell(h, a) for h, a in zip(rows["xg_home"], rows["xg_away"])
            ],
            **{label: rows[col] for label, col in PROB_COLS.items()},
        }
    )
    styler = (
        view.style.format(prob_cell, subset=list(PROB_COLS))
        .background_gradient(cmap="Blues", subset=list(PROB_COLS), vmin=0.0, vmax=1.0)
    )
    st.dataframe(styler, hide_index=True, width="stretch", height=38 * (len(view) + 1))

    st.subheader("Compare vs market")
    st.caption(
        "Type the market's prices for one match (Polymarket ¢ = probability in %). "
        "Edge = model − market in percentage points; EV is the return per $1 buying "
        "the outcome at that price, if the model is right."
    )
    match = st.selectbox("Match", view["Match"])
    r = rows.iloc[view.index[view["Match"] == match][0]]

    panel = pd.DataFrame(
        {
            "Outcome": list(PROB_COLS),
            "Model %": [round(r[col] * 100, 1) for col in PROB_COLS.values()],
            "Market ¢": [np.nan] * len(PROB_COLS),
        }
    )
    left, right = st.columns(2)
    with left:
        edited = st.data_editor(
            panel,
            hide_index=True,
            disabled=["Outcome", "Model %"],
            column_config={
                "Market ¢": st.column_config.NumberColumn(
                    min_value=0.1, max_value=99.9, step=0.1, format="%.1f ¢"
                )
            },
            key=f"market_{round_id}_{match}",
        )
    with right:
        result = edited.dropna(subset=["Market ¢"]).copy()
        if result.empty:
            st.info("Enter a market price on the left to see the edge.")
        else:
            result["Edge (pp)"] = result["Model %"] - result["Market ¢"]
            result["EV %"] = (result["Model %"] / result["Market ¢"] - 1) * 100
            st.dataframe(
                result.style.format(
                    {"Model %": "{:.1f}", "Market ¢": "{:.1f}",
                     "Edge (pp)": "{:+.1f}", "EV %": "{:+.1f}"}
                ).map(ev_color, subset=["Edge (pp)", "EV %"]),
                hide_index=True,
                width="stretch",
            )
