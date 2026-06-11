"""Round-of-32 third-placed-team bracket logic for the 48-team WC2026 format.

Twenty-four teams advance from the group stage as group winners and runners-up;
the eight best of the twelve third-placed teams join them. *Which* group winner
plays *which* third-placed team depends on the exact set of eight groups whose
third-placed teams qualify (12C8 = 495 possibilities). FIFA publishes the full
allocation in Annex C of the tournament regulations; it is transcribed (and
validated against the fixture eligibility sets) into
`data/cleaned/third_place_bracket_map.csv` by the project's data pipeline.
"""

from __future__ import annotations

import pandas as pd

from src.const import CLEANED_DATA_PATH

# The eight group winners (by group letter) that face a third-placed team in the
# Round of 32, taken from the `3XXXXX` slots in wc26_knockout_matches.csv.
THIRD_PLACE_WINNERS = ["A", "B", "D", "E", "G", "I", "K", "L"]


def load_third_place_map() -> dict[frozenset[str], dict[str, str]]:
    """Load FIFA's allocation table.

    Returns a mapping from the (frozen) set of the eight qualifying third-place
    group letters to ``{winner_group_letter: third_place_group_letter}`` — i.e.
    for each of the eight group winners, which group's third-placed team it faces.
    """
    df = pd.read_csv(f"{CLEANED_DATA_PATH}/third_place_bracket_map.csv")
    table: dict[frozenset[str], dict[str, str]] = {}
    for _, row in df.iterrows():
        key = frozenset(row["qualifying_thirds"])
        table[key] = {w: row[f"winner_{w}"] for w in THIRD_PLACE_WINNERS}
    return table


def rank_third_placed(third_rows: list[dict]) -> list[dict]:
    """Rank the twelve third-placed teams; the best eight qualify.

    Each row must carry ``group``, ``points``, ``gd``, ``gf`` and ``elo``.
    FIFA orders by points -> goal difference -> goals for -> (fair play / FIFA
    ranking, which we don't have, so we fall back to current Elo). The caller
    is responsible for any random tiebreak applied upstream.
    """
    return sorted(
        third_rows,
        key=lambda r: (r["points"], r["gd"], r["gf"], r["elo"]),
        reverse=True,
    )


def assign_third_place_slots(
    qualifying_groups: set[str], table: dict[frozenset[str], dict[str, str]]
) -> dict[str, str]:
    """Map each group winner to the third-place group it faces.

    ``qualifying_groups`` is the set of eight group letters whose third-placed
    teams advanced. Returns ``{winner_group_letter: third_place_group_letter}``.
    """
    key = frozenset(qualifying_groups)
    if key not in table:
        raise KeyError(
            f"No FIFA allocation for qualifying third-place groups {sorted(qualifying_groups)}"
        )
    return table[key]
