from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

import kagglehub
import pandas as pd
from kagglehub import KaggleDatasetAdapter
from playwright.async_api import BrowserContext, Page, async_playwright
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from const import _MONTH_MAP, CON, ELO_URL, RAW_DATA_PATH, TODAY

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

opts = Options()
opts.add_argument("--disable-blink-features=AutomationControlled")
opts.add_experimental_option("excludeSwitches", ["enable-automation"])


def latest_elo() -> pd.DataFrame:
    driver = webdriver.Chrome(options=opts)
    driver.get(ELO_URL)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.team-cell"))
    )

    team_cells = driver.find_elements(By.CSS_SELECTOR, "div.team-cell")
    team_names = [cell.text for cell in team_cells]

    rating_cells = driver.find_elements(By.CSS_SELECTOR, "div.l2")
    team_ratings = [float(cell.text) for cell in rating_cells]

    df = pd.DataFrame({"team": team_names, "elo_ratings": team_ratings})
    df["retrieved_date"] = TODAY

    output_path = f"{RAW_DATA_PATH}/elo_latest.csv"

    df.to_csv(output_path, index=False)
    CON.log(f"Latest elo ratings output to {output_path}")
    return df


def historical_matches() -> pd.DataFrame:
    file_path = f"{RAW_DATA_PATH}/international_football_results.csv"
    df = kagglehub.dataset_load(
        KaggleDatasetAdapter.PANDAS,
        "patateriedata/all-international-football-results",
        "all_matches.csv",
    )
    df["retrieved_date"] = TODAY
    CON.log(df.tail())
    df.to_csv(file_path, index=False)
    return df


def historical_elo(
    matches_df: pd.DataFrame, start_date: str = "2016-01-01"
) -> pd.DataFrame:
    # ── Row parsing helpers ─────────────────────────────────────────────────

    def _parse_date(cell_text: str) -> Optional[date]:
        """
        Parse the date cell, which renders as e.g.:
            "May 9\n1917"   →  date(1917, 5, 9)
            "Jan 15\n2023"  →  date(2023, 1, 15)
        """
        lines = cell_text.strip().split("\n")
        if len(lines) < 2:
            return None
        try:
            month_day = lines[0].strip()  # "May 9"
            year = int(lines[1].strip())  # "1917"
            parts = month_day.split()
            month = _MONTH_MAP.get(parts[0])
            day = int(parts[1])
            if month is None:
                return None
            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    def _parse_rating(cell_text: str, line_idx: int = 0) -> Optional[float]:
        """
        Parse the rating cell (.l5.r5). First line is the home team's rating and the
        second line is the away team's rating.
            "1275\n1566"  →  1275.0 (Home), 1566.0 (Away)
        """
        lines = cell_text.strip().split("\n")
        if line_idx >= len(lines):
            return None
        try:
            return float(lines[line_idx].strip())
        except ValueError:
            return None

    def _team_line_index(teams_cell_text: str, team: str) -> int:
        """
        Determine whether the team is home (line 0) or away (line 1)
        from the teams cell (.l1.r1).

            "Japan\nChina", "Japan"  →  0   (home)
            "Japan\nChina", "China"  →  1   (away)

        Uses substring matching to handle cases where the URL slug
        differs slightly from the displayed name (e.g. "Korea_Republic"
        vs "Korea Republic").
        """
        lines = teams_cell_text.strip().split("\n")
        team_normalised = team.replace("_", " ").lower()
        for i, line in enumerate(lines):
            if team_normalised in line.strip().lower():
                return i
        return 0

    async def _scroll_and_collect(page: Page, team: str, start: date) -> list[dict]:
        """
        SlickGrid only renders the rows visible in the viewport.  We scroll the
        grid's viewport container in steps, collecting each batch of materialised
        rows.  We de-duplicate by date+rating (since rows stay in the DOM briefly
        across scrolls).
        """
        records: list[dict] = []
        seen: set[tuple] = set()

        # Identify the SlickGrid viewport — the scrollable container
        viewport_sel = ".slick-viewport"
        await page.wait_for_selector(viewport_sel, timeout=15_000)

        # Get total scrollable height and visible height
        scroll_info = await page.evaluate("""
            () => {
                const vp = document.querySelector('.slick-viewport');
                return {
                    scrollHeight: vp.scrollHeight,
                    clientHeight: vp.clientHeight
                };
            }
        """)
        total_h = scroll_info["scrollHeight"]
        step = scroll_info["clientHeight"]
        position = 0

        while position <= total_h:
            # Scroll the grid viewport to `position`
            await page.evaluate(
                "(pos) => document.querySelector('.slick-viewport').scrollTop = pos",
                position,
            )
            await page.wait_for_timeout(150)  # let SlickGrid render

            # Grab every currently-materialised row
            rows = await page.query_selector_all(".slick-row")
            for row in rows:
                date_el = await row.query_selector(".l0.r0")
                teams_el = await row.query_selector(".l1.r1")
                rating_el = await row.query_selector(".l5.r5")
                if not date_el or not teams_el or not rating_el:
                    continue

                date_text = await date_el.inner_text()
                teams_text = await teams_el.inner_text()
                rating_text = await rating_el.inner_text()

                d = _parse_date(date_text)
                line_idx = _team_line_index(teams_text, team)
                r = _parse_rating(rating_text, line_idx)
                if d is None or r is None:
                    continue
                if d < start:
                    continue

                key = (d, r)
                if key not in seen:
                    seen.add(key)
                    records.append(
                        {
                            "date": d.isoformat(),
                            "team": team.replace("_", " "),
                            "rating": r,
                        }
                    )

            position += step

        return records

    async def scrape_team(
        context: BrowserContext,
        team: str,
        start: date,
        semaphore: asyncio.Semaphore,
    ) -> list[dict]:
        """Scrape a single team's page with concurrency control."""
        team = team.replace(" ", "_")
        async with semaphore:
            page = await context.new_page()
            url = f"{ELO_URL}/{team}"
            logger.info("Scraping %-25s %s", team, url)
            try:
                await page.goto(url, wait_until="networkidle", timeout=30_000)
                records = await _scroll_and_collect(page, team, start)
                logger.info("  %-25s → %d records", team, len(records))
                return records
            except Exception as exc:
                logger.error("  %-25s FAILED: %s", team, exc)
                return []
            finally:
                await page.close()

    async def scrape_all_teams(
        teams: list[str],
        start_date: str = "2016-01-01",
        max_concurrent: int = 4,
    ) -> pd.DataFrame:
        """
        Scrape historical Elo ratings for every team in *teams* from
        eloratings.net, starting from *start_date*.

        Returns
        -------
        pd.DataFrame
            Columns: date (str, yyyy-mm-dd), team (str), rating (float).
            Sorted by (team, date).
        """

        start = date.fromisoformat(start_date)
        semaphore = asyncio.Semaphore(max_concurrent)
        all_records: list[dict] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            )

            tasks = [scrape_team(context, team, start, semaphore) for team in teams]
            results = await asyncio.gather(*tasks)

            for batch in results:
                all_records.extend(batch)

            await context.close()
            await browser.close()

        df = pd.DataFrame(all_records, columns=["date", "team", "rating"])
        df = df.sort_values(["team", "date"]).reset_index(drop=True)
        logger.info("Total records: %d across %d teams", len(df), df["team"].nunique())
        return df

    teams = list(set(matches_df["home_team"]).union(set(matches_df["away_team"])))
    CON.log(f"Scraping historical Elo ratings for {len(teams)} teams...")

    df = asyncio.run(scrape_all_teams(teams, start_date=start_date))
    df.to_csv(f"{RAW_DATA_PATH}/elo_historical.csv", index=False)
    CON.log(df.head())

    return df
