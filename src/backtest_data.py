"""Static structures for the legacy 32-team World Cups used in backtesting.

For each historical tournament we encode (a) the eight groups of four, (b) the
actual furthest stage each team reached (the scoring target), and (c) the cutoff
date used to anchor the decay and exclude future matches when refitting.

The Round-of-16 → Final bracket wiring is FIFA's standard 32-team template and
is identical across 2018 and 2022, so it lives once in ``LEGACY_KNOCKOUT``.
Slot tokens match :func:`src.simulation._resolve_slot`: ``"1A"``/``"2B"`` are
group winner/runner-up; ``"W49"`` is the winner of match 49. Team names follow
the Kaggle ``international_football_results`` convention so they join cleanly to
the refit baseline params and scraped Elo.
"""

from __future__ import annotations

# Standard 32-team knockout bracket (match numbers follow the FIFA schedule).
# The third-place play-off is intentionally omitted: it cannot raise a team's
# furthest stage above the semi-final it already lost.
LEGACY_KNOCKOUT: list[dict] = [
    # Round of 16
    {"num": 49, "stage_label": "R16", "slot_a": "1A", "slot_b": "2B"},
    {"num": 50, "stage_label": "R16", "slot_a": "1C", "slot_b": "2D"},
    {"num": 51, "stage_label": "R16", "slot_a": "1B", "slot_b": "2A"},
    {"num": 52, "stage_label": "R16", "slot_a": "1D", "slot_b": "2C"},
    {"num": 53, "stage_label": "R16", "slot_a": "1E", "slot_b": "2F"},
    {"num": 54, "stage_label": "R16", "slot_a": "1G", "slot_b": "2H"},
    {"num": 55, "stage_label": "R16", "slot_a": "1F", "slot_b": "2E"},
    {"num": 56, "stage_label": "R16", "slot_a": "1H", "slot_b": "2G"},
    # Quarter-finals
    {"num": 57, "stage_label": "QF", "slot_a": "W53", "slot_b": "W54"},
    {"num": 58, "stage_label": "QF", "slot_a": "W49", "slot_b": "W50"},
    {"num": 59, "stage_label": "QF", "slot_a": "W55", "slot_b": "W56"},
    {"num": 60, "stage_label": "QF", "slot_a": "W51", "slot_b": "W52"},
    # Semi-finals
    {"num": 61, "stage_label": "SF", "slot_a": "W57", "slot_b": "W58"},
    {"num": 62, "stage_label": "SF", "slot_a": "W59", "slot_b": "W60"},
    # Final (match 63 is the third-place play-off, omitted; see module docstring)
    {"num": 64, "stage_label": "FINAL", "slot_a": "W61", "slot_b": "W62"},
]


def _stage_map(
    champion: str,
    final: str,
    sf: list[str],
    qf: list[str],
    r16: list[str],
    groups: dict[str, list[str]],
) -> dict[str, str]:
    """Build {team: furthest stage}. Any team not listed above exited at GROUP."""
    stages = {champion: "CHAMPION", final: "FINAL"}
    stages.update({t: "SF" for t in sf})
    stages.update({t: "QF" for t in qf})
    stages.update({t: "R16" for t in r16})
    for team in (t for teams in groups.values() for t in teams):
        stages.setdefault(team, "GROUP")
    return stages


# ── 2018 World Cup (Russia) ──────────────────────────────────────────────────
WC2018_GROUPS: dict[str, list[str]] = {
    "A": ["Russia", "Saudi Arabia", "Egypt", "Uruguay"],
    "B": ["Portugal", "Spain", "Morocco", "Iran"],
    "C": ["France", "Australia", "Peru", "Denmark"],
    "D": ["Argentina", "Iceland", "Croatia", "Nigeria"],
    "E": ["Brazil", "Switzerland", "Costa Rica", "Serbia"],
    "F": ["Germany", "Mexico", "Sweden", "South Korea"],
    "G": ["Belgium", "Panama", "Tunisia", "England"],
    "H": ["Poland", "Senegal", "Colombia", "Japan"],
}
WC2018_ACTUAL = _stage_map(
    champion="France",
    final="Croatia",
    sf=["Belgium", "England"],
    qf=["Uruguay", "Brazil", "Sweden", "Russia"],
    r16=[
        "Portugal",
        "Argentina",
        "Spain",
        "Denmark",
        "Mexico",
        "Japan",
        "Switzerland",
        "Colombia",
    ],
    groups=WC2018_GROUPS,
)

# ── 2022 World Cup (Qatar) ───────────────────────────────────────────────────
WC2022_GROUPS: dict[str, list[str]] = {
    "A": ["Qatar", "Ecuador", "Senegal", "Netherlands"],
    "B": ["England", "Iran", "United States", "Wales"],
    "C": ["Argentina", "Saudi Arabia", "Mexico", "Poland"],
    "D": ["France", "Australia", "Denmark", "Tunisia"],
    "E": ["Spain", "Costa Rica", "Germany", "Japan"],
    "F": ["Belgium", "Canada", "Morocco", "Croatia"],
    "G": ["Brazil", "Serbia", "Switzerland", "Cameroon"],
    "H": ["Portugal", "Ghana", "Uruguay", "South Korea"],
}
WC2022_ACTUAL = _stage_map(
    champion="Argentina",
    final="France",
    sf=["Croatia", "Morocco"],
    qf=["Netherlands", "Brazil", "Portugal", "England"],
    r16=[
        "United States",
        "Australia",
        "Poland",
        "Senegal",
        "Japan",
        "South Korea",
        "Spain",
        "Switzerland",
    ],
    groups=WC2022_GROUPS,
)


# ── Registry ─────────────────────────────────────────────────────────────────
# cutoff: the day before the tournament's opening match — refits use only matches
# strictly before this date and anchor the time-decay here.
BACKTESTS: dict[int, dict] = {
    2018: {
        "groups": WC2018_GROUPS,
        "actual": WC2018_ACTUAL,
        "cutoff": "2018-06-14",
        "host": "Russia",
    },
    2022: {
        "groups": WC2022_GROUPS,
        "actual": WC2022_ACTUAL,
        "cutoff": "2022-11-20",
        "host": "Qatar",
    },
}
