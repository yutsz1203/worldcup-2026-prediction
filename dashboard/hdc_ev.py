"""HKJC HDC EV tab — scrape the posted Handicap lines and price them.

Button-triggered scrape (headless Chrome, ~1 min) held in session state so it
never runs on a plain page load; the table prices each line with the model and
flags the side whose EV clears the betting rule's minimum edge.
"""

import streamlit as st

from dashboard.common import ev_color
from src.hkjc import MIN_EDGE, hdc_ev_table, scrape_hdc


def render_hdc_ev() -> None:
    st.title("HKJC HDC EV")
    st.caption(
        "EV is the expected edge per $1 stake at the offered odds under HKJC "
        f"settlement; Signal marks the side clearing +{MIN_EDGE:.0%}. Lines are "
        "quoted on the home team. Snapshot only — odds move; re-scrape to refresh."
    )
    if st.button("Scrape HKJC odds (headless Chrome, ~1 min)"):
        with st.spinner("Scraping bet.hkjc.com…"):
            st.session_state["hdc_odds"] = scrape_hdc()
    odds = st.session_state.get("hdc_odds")
    if odds is None:
        st.info("Scrape to load the currently posted HDC lines.")
        return

    hdc_round, provenance, table = hdc_ev_table(odds)
    st.caption(f"Round {hdc_round} · {provenance}")
    st.dataframe(
        table.style.format(
            {
                "Home odds": "{:.2f}", "Home fair": "{:.2f}", "Home EV": "{:+.1%}",
                "Away odds": "{:.2f}", "Away fair": "{:.2f}", "Away EV": "{:+.1%}",
            }
        ).map(ev_color, subset=["Home EV", "Away EV"]),
        hide_index=True,
        width="stretch",
        height=38 * (len(table) + 1),
    )
