"""Generate predictions for the DataCamp WC2026 competition.

Maps DataCamp's fixture files (datacamp/data) onto our model:
- group matches: 100k vectorized regulation sims per fixture (independent
  bivariate-Poisson model, pre-tournament Elo, host bonus) -> mean goals +
  modal outcome.
- knockouts: our chalk R32 lineup (showcase §8) routed through the *official
  FIFA* bracket (per the published schedule / Wikipedia knockout-stage page),
  each tie re-simulated 100k times with regulation + ET (1/3 intensity) +
  Elo-tilted shootout, modal winner advancing. DataCamp's knockout_slots.csv
  renumbered the R32 chronologically but kept "Winner Match N" tokens in
  official numbering, so their routing is internally inconsistent; we simulate
  in official-id space and map to DataCamp ids by venue/date (OFF_TO_DC).

Run from project root: uv run python notebooks/datacamp_predictions.py
"""

from collections import Counter

import numpy as np
import pandas as pd

from model.rates import independent_rates
from src.simulation import HOME_ADVANTAGE, MAX_LAMBDA, PEN_SLOPE, load_sim_inputs

N = 100_000
SEED = 2026

# "datacamp": resolve knockout ties with DataCamp's own slot tokens and match
# ids taken at face value (safer if their scorer resolves its own bracket).
# "official": simulate the official FIFA routing and map to DataCamp ids by
# venue/date (correct if they transcribe real results; see module docstring).
ROUTING = "datacamp"

# Flip the top-K ties by P(shootout) to penalties=True, but only in rounds with
# multiplier <= 2 (R32/R16): ~25-30% of WC knockout ties historically go to
# pens (5/16 in 2022, 4/16 in 2018), while a wrong call at QF+ costs 5 x >=4
# points against a <=16% model probability.
PENS_FLIPS = 6
PENS_ROUNDS = {"Round of 32", "Round of 16"}

# DataCamp name -> our name
NAME_MAP = {
    "USA": "United States",
    "Côte d'Ivoire": "Ivory Coast",
    "Cabo Verde": "Cape Verde",
    "UEFA Playoff A": "Bosnia and Herzegovina",  # Group B slot
    "UEFA Playoff B": "Sweden",  # Group F slot
    "UEFA Playoff C": "Turkey",  # Group D slot
    "UEFA Playoff D": "Czechia",  # Group A slot
    "FIFA Playoff 1": "DR Congo",  # Group K slot
    "FIFA Playoff 2": "Iraq",  # Group I slot
}
# our name -> DataCamp name (for knockout team strings)
BACK_MAP = {
    "United States": "USA",
    "Ivory Coast": "Côte d'Ivoire",
    "Cape Verde": "Cabo Verde",
}

# Chalk group stage from showcase §8 (project_modal_bracket's projected groups).
WINNERS = {
    "A": "Mexico",
    "B": "Switzerland",
    "C": "Brazil",
    "D": "Turkey",
    "E": "Germany",
    "F": "Netherlands",
    "G": "Belgium",
    "H": "Spain",
    "I": "France",
    "J": "Argentina",
    "K": "Portugal",
    "L": "England",
}
RUNNERS = {
    "A": "Czechia",
    "B": "Canada",
    "C": "Morocco",
    "D": "United States",
    "E": "Ecuador",
    "F": "Japan",
    "G": "Iran",
    "H": "Uruguay",
    "I": "Senegal",
    "J": "Austria",
    "K": "Colombia",
    "L": "Croatia",
}
# Official FIFA knockout bracket (match number, round, slot_a, slot_b, host).
# Source: 2026 FIFA World Cup knockout stage, Wikipedia / FIFA schedule.
# Note: matches official numbering; our wc26_knockout_matches.csv has the
# 89/90 labels swapped (cosmetic — both feed QF 97 — but flips 97's home side).
OFFICIAL_KO = [
    (73, "Round of 32", "2A", "2B", "United States"),
    (74, "Round of 32", "1E", "3ABCDF", "United States"),
    (75, "Round of 32", "1F", "2C", "Mexico"),
    (76, "Round of 32", "1C", "2F", "United States"),
    (77, "Round of 32", "1I", "3CDFGH", "United States"),
    (78, "Round of 32", "2E", "2I", "United States"),
    (79, "Round of 32", "1A", "3CEFHI", "Mexico"),
    (80, "Round of 32", "1L", "3EHIJK", "United States"),
    (81, "Round of 32", "1D", "3BEFIJ", "United States"),
    (82, "Round of 32", "1G", "3AEHIJ", "United States"),
    (83, "Round of 32", "2K", "2L", "Canada"),
    (84, "Round of 32", "1H", "2J", "United States"),
    (85, "Round of 32", "1B", "3EFGIJ", "Canada"),
    (86, "Round of 32", "1J", "2H", "United States"),
    (87, "Round of 32", "1K", "3DEIJL", "United States"),
    (88, "Round of 32", "2D", "2G", "United States"),
    (89, "Round of 16", "W74", "W77", "United States"),
    (90, "Round of 16", "W73", "W75", "United States"),
    (91, "Round of 16", "W76", "W78", "United States"),
    (92, "Round of 16", "W79", "W80", "Mexico"),
    (93, "Round of 16", "W83", "W84", "United States"),
    (94, "Round of 16", "W81", "W82", "United States"),
    (95, "Round of 16", "W86", "W88", "United States"),
    (96, "Round of 16", "W85", "W87", "Canada"),
    (97, "Quarter-final", "W89", "W90", "United States"),
    (98, "Quarter-final", "W93", "W94", "United States"),
    (99, "Quarter-final", "W91", "W92", "United States"),
    (100, "Quarter-final", "W95", "W96", "United States"),
    (101, "Semi-final", "W97", "W98", "United States"),
    (102, "Semi-final", "W99", "W100", "United States"),
    (103, "Third-place playoff", "L101", "L102", "United States"),
    (104, "Final", "W101", "W102", "United States"),
]

# Official match number -> DataCamp match_id (matched by venue/date; DataCamp
# renumbered the R32 and R16 chronologically by kickoff).
OFF_TO_DC = {
    73: 73,
    74: 75,
    75: 76,
    76: 74,
    77: 78,
    78: 77,
    79: 79,
    80: 80,
    81: 82,
    82: 81,
    83: 83,
    84: 84,
    85: 85,
    86: 87,
    87: 88,
    88: 86,
    89: 90,
    90: 89,
    91: 91,
    92: 92,
    93: 93,
    94: 94,
    95: 95,
    96: 96,
    **{i: i for i in range(97, 105)},
}

# Best-third allocation from showcase §8, keyed by the slot's group-letter set.
THIRDS = {
    frozenset("ABCDF"): "Scotland",
    frozenset("CDFGH"): "Sweden",
    frozenset("CEFHI"): "Ivory Coast",
    frozenset("EHIJK"): "Uzbekistan",
    frozenset("BEFIJ"): "Bosnia and Herzegovina",
    frozenset("AEHIJ"): "Norway",
    frozenset("EFGIJ"): "Egypt",
    frozenset("DEIJL"): "Panama",
}


def host_from_venue(venue: str) -> str:
    if any(c in venue for c in ("Mexico City", "Guadalajara", "Monterrey")):
        return "Mexico"
    if any(c in venue for c in ("Toronto", "Vancouver")):
        return "Canada"
    return "United States"


def bonuses(home: str, away: str, host: str | None) -> tuple[float, float]:
    if host is None:
        return 0.0, 0.0
    if home == host:
        return HOME_ADVANTAGE, 0.0
    if away == host:
        return 0.0, HOME_ADVANTAGE
    return 0.0, 0.0


def rates(home, away, host, inputs):
    ba, bb = bonuses(home, away, host)
    ea, eb = inputs.elo0[home] + ba, inputs.elo0[away] + bb
    la, lb = independent_rates(ea, eb, inputs.base[home], inputs.base[away])
    return (
        min(max(la, 0.0), MAX_LAMBDA),
        min(max(lb, 0.0), MAX_LAMBDA),
        ea,
        eb,
    )


def modal_score(gh, ga, mask):
    return Counter(zip(gh[mask].tolist(), ga[mask].tolist())).most_common(1)[0][0]


def rnd(x):
    return int(np.floor(x + 0.5))


def sim_group_match(home, away, host, inputs, rng):
    la, lb, _, _ = rates(home, away, host, inputs)
    gh = rng.poisson(la, N)
    ga = rng.poisson(lb, N)
    p_h, p_d, p_a = (gh > ga).mean(), (gh == ga).mean(), (gh < ga).mean()
    outcome = {"home": p_h, "draw": p_d, "away": p_a}
    pick = max(outcome, key=outcome.get)
    rh, ra = rnd(gh.mean()), rnd(ga.mean())
    rounded_outcome = "home" if rh > ra else "away" if rh < ra else "draw"
    adjusted = False
    if rounded_outcome != pick:
        mask = (
            (gh > ga) if pick == "home" else (gh < ga) if pick == "away" else (gh == ga)
        )
        rh, ra = modal_score(gh, ga, mask)
        adjusted = True
    return {
        "home": home,
        "away": away,
        "mean_h": gh.mean(),
        "mean_a": ga.mean(),
        "p_home": p_h,
        "p_draw": p_d,
        "p_away": p_a,
        "pred_h": rh,
        "pred_a": ra,
        "winning_team": pick,
        "adjusted": adjusted,
    }


def sim_ko_match(home, away, host, inputs, rng):
    la, lb, ea, eb = rates(home, away, host, inputs)
    gh = rng.poisson(la, N)
    ga = rng.poisson(lb, N)
    tied = gh == ga
    n_t = int(tied.sum())
    gh = gh.astype(float)
    ga = ga.astype(float)
    gh[tied] += rng.poisson(la / 3.0, n_t)
    ga[tied] += rng.poisson(lb / 3.0, n_t)
    pens = gh == ga
    p_pen_h = 1.0 / (1.0 + 10 ** (-(ea - eb) / PEN_SLOPE))
    pen_home_win = rng.random(int(pens.sum())) < p_pen_h
    win_h = (gh > ga).astype(float)
    win_h[pens] = pen_home_win.astype(float)
    p_h = win_h.mean()
    p_pens = pens.mean()
    winner = "home" if p_h >= 0.5 else "away"
    pred_pens = bool(p_pens > 0.5)
    rh, ra = rnd(gh.mean()), rnd(ga.mean())
    adjusted = False
    if pred_pens:
        if rh != ra:
            rh, ra = modal_score(gh.astype(int), ga.astype(int), pens)
            adjusted = True
    else:
        need = (gh > ga) if winner == "home" else (gh < ga)
        ok = (rh > ra) if winner == "home" else (rh < ra)
        if not ok:
            rh, ra = modal_score(gh.astype(int), ga.astype(int), need)
            adjusted = True
    draw_h, draw_a = modal_score(gh.astype(int), ga.astype(int), pens)
    return {
        "home": home,
        "away": away,
        "mean_h": gh.mean(),
        "mean_a": ga.mean(),
        "p_home_win": p_h,
        "p_pens": p_pens,
        "pred_h": rh,
        "pred_a": ra,
        "winner": winner,
        "penalties": pred_pens,
        "draw_h": draw_h,
        "draw_a": draw_a,
        "adjusted": adjusted,
    }


def main():
    inputs = load_sim_inputs()  # independent model, like the forecast
    rng = np.random.default_rng(SEED)

    # ── group stage ─────────────────────────────────────────────────────────
    dc = pd.read_csv("datacamp/data/group_fixtures.csv")
    ours = pd.read_csv("data/cleaned/wc26_groupstage_matches.csv")
    host_lookup = {}
    for _, r in ours.iterrows():
        host = r["host_country"] if pd.notna(r["host_country"]) else None
        host_lookup[(r["home_team"], r["away_team"])] = host

    group_rows = []
    for _, r in dc.iterrows():
        home = NAME_MAP.get(r["home_team"], r["home_team"])
        away = NAME_MAP.get(r["away_team"], r["away_team"])
        if (home, away) in host_lookup:
            host = host_lookup[(home, away)]
        elif (away, home) in host_lookup:
            host = host_lookup[(away, home)]
            print(f"  NOTE: match {r['match_id']} orientation flipped vs our fixtures")
        else:
            raise ValueError(f"fixture not found: {home} v {away}")
        res = sim_group_match(home, away, host, inputs, rng)
        res["match_id"] = int(r["match_id"])
        group_rows.append(res)
    gdf = pd.DataFrame(group_rows).set_index("match_id").sort_index()

    # ── knockout ────────────────────────────────────────────────────────────
    winners: dict[int, str] = {}
    losers: dict[int, str] = {}
    ko_rows = []

    if ROUTING == "official":

        def resolve(token: str) -> str:
            if token.startswith("W") and token[1:].isdigit():
                return winners[int(token[1:])]
            if token.startswith("L") and token[1:].isdigit():
                return losers[int(token[1:])]
            if token[0] == "1":
                return WINNERS[token[1]]
            if token[0] == "2":
                return RUNNERS[token[1]]
            if token[0] == "3":
                return THIRDS[frozenset(token[1:])]
            raise ValueError(token)

        for off_id, rnd_label, slot_a, slot_b, host in OFFICIAL_KO:
            home, away = resolve(slot_a), resolve(slot_b)
            res = sim_ko_match(home, away, host, inputs, rng)
            winners[off_id] = home if res["winner"] == "home" else away
            losers[off_id] = away if res["winner"] == "home" else home
            res["official_id"] = off_id
            res["match_id"] = OFF_TO_DC[off_id]
            res["round"] = rnd_label
            ko_rows.append(res)
    else:  # DataCamp's own tokens/ids taken at face value

        def resolve(token: str) -> str:
            token = token.strip()
            if token.startswith("Winner Group"):
                return WINNERS[token.split()[-1]]
            if token.startswith("Runner-up Group"):
                return RUNNERS[token.split()[-1]]
            if token.startswith("Best 3rd"):
                letters = frozenset(token.split("(Groups ")[1].rstrip(")").split("/"))
                return THIRDS[letters]
            if token.startswith("Winner Match"):
                return winners[int(token.split()[-1])]
            if token.startswith("Loser Match"):
                return losers[int(token.split()[-1])]
            raise ValueError(token)

        for _, r in pd.read_csv("datacamp/data/knockout_slots.csv").iterrows():
            home, away = resolve(r["slot_home"]), resolve(r["slot_away"])
            res = sim_ko_match(home, away, host_from_venue(r["venue"]), inputs, rng)
            mid = int(r["match_id"])
            winners[mid] = home if res["winner"] == "home" else away
            losers[mid] = away if res["winner"] == "home" else home
            res["match_id"] = mid
            res["round"] = r["round"]
            ko_rows.append(res)

    kdf = pd.DataFrame(ko_rows).set_index("match_id").sort_index()

    # Flip the most shootout-prone cheap-round ties to penalties=True with their
    # modal drawn (post-ET) scoreline; the match winner stays the modal winner.
    flips = kdf[kdf["round"].isin(PENS_ROUNDS)]["p_pens"].nlargest(PENS_FLIPS).index
    kdf.loc[flips, "penalties"] = True
    kdf.loc[flips, "pred_h"] = kdf.loc[flips, "draw_h"]
    kdf.loc[flips, "pred_a"] = kdf.loc[flips, "draw_a"]

    # ── report ──────────────────────────────────────────────────────────────
    pd.set_option("display.width", 200)
    print("\nGROUP PREDICTIONS\n")
    print(gdf.round(3).to_string())
    print("\nKNOCKOUT PREDICTIONS\n")
    print(kdf.round(3).to_string())

    # ── pasteable output ────────────────────────────────────────────────────
    print("\n" + "=" * 70 + "\nPASTE BLOCK 1 (group)\n" + "=" * 70)
    lines = ["_g = {"]
    for mid, r in gdf.iterrows():
        lines.append(
            f"    {mid}: ({r['pred_h']}, {r['pred_a']}, '{r['winning_team']}'),"
        )
    lines.append("}")
    print("\n".join(lines))

    print("\n" + "=" * 70 + "\nPASTE BLOCK 2 (knockout)\n" + "=" * 70)
    lines = ["_k = {"]
    for mid, r in kdf.iterrows():
        h = BACK_MAP.get(r["home"], r["home"])
        a = BACK_MAP.get(r["away"], r["away"])
        lines.append(
            f"    {mid}: (\"{h}\", \"{a}\", {r['pred_h']}, {r['pred_a']}, "
            f"'{r['winner']}', {r['penalties']}),"
        )
    lines.append("}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
