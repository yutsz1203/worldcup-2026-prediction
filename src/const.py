import calendar
from datetime import date
from pathlib import Path

from rich import console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
)

RAW_DATA_PATH = "data/raw"
CLEANED_DATA_PATH = "data/cleaned"
RESULT_DATA_PATH = "data/result"
# Result artifacts are grouped by purpose: the live 2026 forecast, out-of-sample
# validation/backtests, and hyperparameter sweeps. See README "Project Structure".
FORECAST_PATH = f"{RESULT_DATA_PATH}/forecast"
VALIDATION_PATH = f"{RESULT_DATA_PATH}/validation"
TUNING_PATH = f"{RESULT_DATA_PATH}/tuning"
# Showcase figures (matplotlib PNGs embedded in showcase.md; see src/charts.py).
FIGURES_PATH = f"{FORECAST_PATH}/figures"
# Live 2026 layer: locked per-round forecasts, ingested results, and the
# predictions+actuals ledger (see src/forecast.py, src/bzzoiro.py, src/ledger.py).
LIVE_PATH = f"{RESULT_DATA_PATH}/live"
for _p in (FORECAST_PATH, VALIDATION_PATH, TUNING_PATH, FIGURES_PATH, LIVE_PATH):
    Path(_p).mkdir(parents=True, exist_ok=True)
# FIFA WC2026 seeding pots (1-4, 12 teams each); used by the dark-horse index to
# baseline each team against its pot peers (src/projections.py).
WC26_POTS_PATH = f"{RAW_DATA_PATH}/wc26_pots.csv"
TODAY = date.today().isoformat()
CON = console.Console()

GROUPPING = {
    "A": ["Mexico", "South Africa", "South Korea", "Czechia"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

TEAM_LIST = [team for group in GROUPPING.values() for team in group]
ELO_URL = "https://www.eloratings.net"
# bzzoiro live results API (free, instant). The live forecaster reads WC26 fixtures and
# finalized scores from here (src/bzzoiro.py) — the single source of truth for results
# ingestion. league_id 27 spans every World Cup edition, so season_id 188 (WC2026,
# exactly 104 matches) must always be filtered in. The token is a secret — read from the
# gitignored .env (BZZOIRO_TOKEN), never committed.
BZZOIRO_EVENTS_URL = "https://sports.bzzoiro.com/api/v2/events/"
WC26_LEAGUE_ID = 27
WC26_SEASON_ID = 188
WC26_RESULTS_PATH = f"{RAW_DATA_PATH}/wc26_results.csv"
_MONTH_MAP: dict[str, int] = {
    name: num
    for num in range(1, 13)
    for name in (calendar.month_abbr[num], calendar.month_name[num])
}
CUSTOM_PROGRESS = Progress(
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    MofNCompleteColumn(),
    TaskProgressColumn(),
)
