"""Paths and API constants for the Jump Probability Cup pipeline.

Jump Cup artifacts are self-contained under ``competitions/jumpcup/data/`` (not the
project-wide ``data/`` tree): ``raw/`` cached API JSON, ``cleaned/`` rates CSVs,
``live/`` hand-written specs + priced probabilities.
"""

from pathlib import Path

BZZOIRO_API_BASE = "https://sports.bzzoiro.com/api/v2"
SPORTSPREDICT_API_BASE = "https://api.sportspredict.com/api/v1"
JUMPCUP_EVENT_ID = "aa5572ec-5930-4d99-b06b-f8966333d172"
JUMPCUP_LOBBY_ID = "8df8038c-fd2c-4a5f-be4e-0e11d5966c05"

_DATA_ROOT = Path(__file__).resolve().parent / "data"
JUMPCUP_RAW_PATH = str(_DATA_ROOT / "raw")  # cached raw JSON, one dir per object
JUMPCUP_CLEANED_PATH = str(_DATA_ROOT / "cleaned")  # rates_{event_id}.csv
JUMPCUP_LIVE_PATH = str(_DATA_ROOT / "live")  # spec/probs per event

for _p in (JUMPCUP_RAW_PATH, JUMPCUP_CLEANED_PATH, JUMPCUP_LIVE_PATH):
    Path(_p).mkdir(parents=True, exist_ok=True)


def rates_path(event_id: int) -> str:
    return f"{JUMPCUP_CLEANED_PATH}/rates_{event_id}.csv"


def spec_path(event_id: int) -> str:
    return f"{JUMPCUP_LIVE_PATH}/spec_{event_id}.json"


def probs_path(event_id: int) -> str:
    return f"{JUMPCUP_LIVE_PATH}/probs_{event_id}.csv"
