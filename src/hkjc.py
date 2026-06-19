"""HKJC HDC odds scraper + model EV pricing for the live WC2026.

Scrapes the posted Handicap (HDC) line and odds for every WC2026 match on the
HKJC betting site and prices each line with the frozen GLM (cached Elo by
default, consistent with the locked round forecasts). :func:`hdc_ev_table`
returns one round's EV per side at the offered odds as a frame for the
Streamlit dashboard (``dashboard/app.py``, HDC EV tab). Decision support, not a
locked record — odds move; re-scrape for current prices.

Scrape notes (recon 2026-06-12): the page is a React SPA; rows are
``div.match-row`` with ``data-testid`` hooks (``FBxxxx_homeTeam`` etc.), and
``.hdcOddsItem`` elements come in home/away pairs — one pair per posted line
(condition "[-0.5/-1]" + odds). Matches can carry several lines; the extra ones
only render after clicking each date section's "Expand All" toggle
(``#expandAll_HDC_<yyyymmdd>``). The list scrolls inside ``#scrollView``; the
header ``#fb_top_pagination`` reads "Matches 24 out of 54", where the total
counts the whole coupon (HKJC only posts HDC odds ~a week ahead).
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd

from model.probabilities import (
    fair_odds,
    generate_handicap_probabilities,
    settlement_ev,
)
from model.rates import get_independent_rates
from src.bzzoiro import GROUP_ROUNDS, make_match_uid
from src.const import CLEANED_DATA_PATH, CON, TEAM_LIST
from src.forecast import (
    MAX_LAMBDA,
    ROUND_ORDER,
    _load_elo,
    _model_version,
    load_round_fixtures,
)

WC26_HKJC_TOURN_ID = "50000118"
HKJC_HDC_URL = "https://bet.hkjc.com/en/football/hdc?tournid={tourn_id}"
# Betting rule: flag a side once its EV at the offered odds clears this edge.
MIN_EDGE = 0.05

# HKJC display names -> our canonical TEAM_LIST names (rest match verbatim).
HKJC_TEAM_NAME_MAP: dict[str, str] = {
    "Korea Republic": "South Korea",
    "Turkiye": "Turkey",
    "USA": "United States",
    "D R Congo": "DR Congo",
    "Cote d'Ivoire": "Ivory Coast",
    "Cape Verde Islands": "Cape Verde",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Curacao": "Curaçao",
}


def parse_condition(cond: str) -> float:
    """HKJC condition string to a single handicap line: "[-0.5/-1]" -> -0.75."""
    parts = cond.strip().strip("[]").split("/")
    values = [float(p) for p in parts]
    return sum(values) / len(values)


def _canonical_team(name: str) -> str:
    team = HKJC_TEAM_NAME_MAP.get(name, name)
    if team not in TEAM_LIST:
        raise ValueError(f"Unknown HKJC team name {name!r} (mapped to {team!r})")
    return team


def scrape_hdc(tourn_id: str = WC26_HKJC_TOURN_ID) -> pd.DataFrame:
    """Scrape every posted HDC line + odds for every match of one tournament.

    Columns: ``front_id, kickoff, home_team, away_team, line_no, home_cond,
    home_line, odds_home, odds_away, scraped_at`` — one row per (match, line);
    matches can carry several lines once the date sections are expanded.
    Suspended/odds-less rows are skipped with a warning.
    """
    # Lazy: selenium only needed when actually scraping.
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(HKJC_HDC_URL.format(tourn_id=tourn_id))
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.match-row"))
        )

        pagination = driver.find_element(By.ID, "fb_top_pagination").text
        m = re.search(r"out of (\d+)", pagination)
        total = int(m.group(1)) if m else None

        # Scroll #scrollView to the bottom until the row count stops growing.
        # The "out of N" total counts every coupon match; HKJC only posts HDC
        # odds ~a week ahead, so fewer rendered rows than N is normal — the
        # remainder have no HDC market yet.
        rows = driver.find_elements(By.CSS_SELECTOR, "div.match-row")
        stalls = 0
        while total and len(rows) < total and stalls < 3:
            driver.execute_script(
                "const v = document.getElementById('scrollView');"
                "v.scrollTop = v.scrollHeight;"
            )
            time.sleep(1.5)
            new_rows = driver.find_elements(By.CSS_SELECTOR, "div.match-row")
            stalls = stalls + 1 if len(new_rows) == len(rows) else 0
            rows = new_rows
        if total and len(rows) < total:
            CON.print(
                f"[cyan]HDC odds posted for {len(rows)} of {total} coupon "
                "match(es); the rest have no HDC market yet.[/]"
            )

        # Reveal the extra lines: click each date section's "Expand All" toggle
        # (JS click — the headless viewport may not have them scrolled in).
        toggles = driver.find_elements(By.CSS_SELECTOR, 'div[id^="expandAll_HDC_"]')
        for toggle in toggles:
            driver.execute_script("arguments[0].click();", toggle)
        if toggles:
            time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, "div.match-row")

        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        records = []
        for row in rows:
            fid = row.find_element(By.CSS_SELECTOR, "div.fb-id").text.strip()
            try:
                home = row.find_element(
                    By.CSS_SELECTOR, f'[data-testid="{fid}_homeTeam"]'
                ).text.strip()
                away = row.find_element(
                    By.CSS_SELECTOR, f'[data-testid="{fid}_awayTeam"]'
                ).text.strip()
                kickoff = row.find_element(
                    By.CSS_SELECTOR, f'[data-testid="{fid}_matchTime"]'
                ).text.strip()
                items = row.find_elements(By.CSS_SELECTOR, ".hdcOddsItem")
                if not items or len(items) % 2:
                    raise ValueError(f"expected H/A odds-item pairs, got {len(items)}")
                pairs = []
                for h_item, a_item in zip(items[::2], items[1::2]):
                    cond = h_item.find_element(By.CSS_SELECTOR, ".cond").text.strip()
                    pair_odds = [
                        float(
                            item.find_element(
                                By.CSS_SELECTOR, 'span[data-testid$="_odds"]'
                            ).text.strip()
                        )
                        for item in (h_item, a_item)
                    ]
                    pairs.append((cond, *pair_odds))
            except Exception as exc:
                CON.print(f"[yellow]Skipping {fid}: no usable HDC odds ({exc}).[/]")
                continue
            for line_no, (cond, odd_h, odd_a) in enumerate(pairs, start=1):
                records.append(
                    {
                        "front_id": fid,
                        "kickoff": pd.to_datetime(kickoff, format="%d/%m/%Y %H:%M"),
                        "home_team": _canonical_team(home),
                        "away_team": _canonical_team(away),
                        "line_no": line_no,
                        "home_cond": cond,
                        "home_line": parse_condition(cond),
                        "odds_home": odd_h,
                        "odds_away": odd_a,
                        "scraped_at": scraped_at,
                    }
                )
    finally:
        driver.quit()

    df = (
        pd.DataFrame(records)
        .sort_values(["kickoff", "front_id", "line_no"])
        .reset_index(drop=True)
    )
    CON.print(
        f"[green]Scraped {len(df)} HDC line(s) across "
        f"{df['front_id'].nunique() if len(df) else 0} match(es)[/]"
    )
    return df


def _mirror(outcome: dict) -> dict:
    return {
        "p_win": outcome["p_lose"],
        "p_half_win": outcome["p_half_lose"],
        "p_push": outcome["p_push"],
        "p_half_lose": outcome["p_half_win"],
        "p_lose": outcome["p_win"],
    }


def _filter_round(
    odds_df: pd.DataFrame, round_id: str | None
) -> tuple[str, pd.DataFrame]:
    """Restrict scraped odds to one round's fixtures (match by ``match_uid``).

    With ``round_id=None``, picks the earliest round in ``ROUND_ORDER`` that has
    at least one scraped match — the next round HKJC is pricing.
    """
    rounds = [round_id] if round_id else ROUND_ORDER
    for rid in rounds:
        try:
            fixtures = load_round_fixtures(rid)
        except ValueError:  # knockout bracket not resolved upstream yet
            continue
        uids = {
            make_match_uid(h, a, is_knockout=rid not in GROUP_ROUNDS)
            for h, a in zip(fixtures["home_team"], fixtures["away_team"])
        }
        scraped_uids = odds_df.apply(
            lambda r: make_match_uid(
                r["home_team"], r["away_team"], is_knockout=rid not in GROUP_ROUNDS
            ),
            axis=1,
        )
        subset = odds_df[scraped_uids.isin(uids)]
        if not subset.empty:
            return rid, subset.reset_index(drop=True)
    raise ValueError(
        f"No scraped HKJC match belongs to round {round_id or '(any)'} — "
        "nothing to report."
    )


def hdc_ev_table(
    odds_df: pd.DataFrame | None = None,
    round_id: str | None = None,
    rescrape_elo: bool = False,
) -> tuple[str, str, pd.DataFrame]:
    """Price one round's scraped HDC lines with the model.

    Pass ``odds_df`` from :func:`scrape_hdc` (scrapes fresh when omitted); only
    the given round's matches are included (default: the earliest round with
    scraped odds). Uses the cached Elo snapshot by default (consistent with the
    locked round forecasts); ``rescrape_elo=True`` refreshes it first. Returns
    ``(round_id, provenance, table)`` where ``table`` has one row per
    (match, line): offered odds, fair odds and EV per side (EVs as fractions),
    and the Signal side clearing ``MIN_EDGE``.
    """
    round_id, odds_df = _filter_round(
        scrape_hdc() if odds_df is None else odds_df, round_id
    )
    elo = _load_elo(None, rescrape_elo)
    base = pd.read_csv(f"{CLEANED_DATA_PATH}/baseline_params.csv")
    retrieved = (
        str(elo["retrieved_date"].iloc[0])
        if "retrieved_date" in elo.columns and len(elo)
        else ""
    )
    provenance = (
        f"Scraped {odds_df['scraped_at'].iloc[0] if len(odds_df) else '—'} · "
        f"Elo retrieved {retrieved} · model {_model_version()}"
    )

    rows = []
    for _, r in odds_df.iterrows():
        lam_h, lam_a = get_independent_rates(r["home_team"], r["away_team"], elo, base)
        lam_h, lam_a = min(lam_h, MAX_LAMBDA), min(lam_a, MAX_LAMBDA)
        home = generate_handicap_probabilities(lam_h, lam_a, [r["home_line"]])[
            r["home_line"]
        ]
        away = _mirror(home)
        ev_h = settlement_ev(home, r["odds_home"])
        ev_a = settlement_ev(away, r["odds_away"])
        rows.append(
            {
                "Kickoff": f"{r['kickoff']:%d/%m %H:%M}",
                "Match": f"{r['home_team']} vs {r['away_team']}",
                "Line (home)": r["home_cond"],
                "Home odds": r["odds_home"],
                "Home fair": fair_odds(home),
                "Home EV": ev_h,
                "Away odds": r["odds_away"],
                "Away fair": fair_odds(away),
                "Away EV": ev_a,
                "Signal": "Home"
                if ev_h >= MIN_EDGE
                else "Away"
                if ev_a >= MIN_EDGE
                else "",
            }
        )
    return round_id, provenance, pd.DataFrame(rows)
