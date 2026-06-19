"""Render the projection deliverables into a single ``showcase.md`` (roadmap step 3).

Pure presentation: assembles the tables from :mod:`src.projections`, the PNG
charts from :mod:`src.charts`, and two GitHub-native Mermaid diagrams (the
favorite's title path and the projected bracket) into one portfolio document.
Reads only the forecast CSV artifacts, so it regenerates instantly after a sim
re-run. Markdown tables are built with a tiny dependency-free helper (no
``tabulate`` needed).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src import charts
from src import projections as P
from src.const import FIGURES_PATH


# ── dependency-free markdown helpers ─────────────────────────────────────────
def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def df_to_md(df: pd.DataFrame, headers: dict[str, str] | None = None) -> str:
    """GitHub-flavoured markdown table from a DataFrame (no external deps)."""
    headers = headers or {}
    cols = list(df.columns)
    head = [headers.get(c, c) for c in cols]
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in df.iterrows():
        lines.append(
            "| " + " | ".join(_fmt(row[c]).replace("|", "\\|") for c in cols) + " |"
        )
    return "\n".join(lines)


def _img(path: str, alt: str) -> str:
    return f"![{alt}]({path})"


# ── Mermaid diagrams ─────────────────────────────────────────────────────────
def _title_path_mermaid(path: pd.DataFrame, team: str) -> str:
    """Linear flowchart of the favorite's modal opponent per stage."""
    nodes = [f'  start(["{team}"])']
    edges = []
    prev = "start"
    for i, r in enumerate(path.itertuples()):
        nid = f"s{i}"
        nodes.append(
            f'  {nid}["{r.stage}: vs {r.modal_opponent}<br/>{r.p_conditional:.0%}"]'
        )
        edges.append(f"  {prev} --> {nid}")
        prev = nid
    return "```mermaid\nflowchart LR\n" + "\n".join(nodes + edges) + "\n```"


def _bracket_mermaid(bracket: pd.DataFrame) -> str:
    """Two-sided bracket converging on the FINAL in the centre, mirroring the
    official bracket layout: the left half flows rightward into the FINAL and the
    right half is mirrored to flow leftward. Arrow-less ``---`` connectors keep
    it neutral like a printed bracket; round order encodes advancement."""
    from src.simulation import load_sim_inputs

    feed = {m["num"]: (m["slot_a"], m["slot_b"]) for m in load_sim_inputs().knockout}
    by_num = {int(r.match_number): r for r in bracket.itertuples()}

    # children map: each match -> the source matches that feed it
    children: dict[int, list[int]] = {}
    for num in by_num:
        children[num] = [
            int(tok[1:])
            for tok in feed.get(num, ())
            if tok.startswith("W") and int(tok[1:]) in by_num
        ]

    def descendants(n: int) -> set[int]:
        out = {n}
        for c in children[n]:
            out |= descendants(c)
        return out

    final_num = next(n for n, r in by_num.items() if r.round == "FINAL")
    # one semifinal subtree is rendered on the right, mirrored
    right_set = descendants(children[final_num][-1]) if children[final_num] else set()

    nodes, edges = [], []
    for num, r in by_num.items():
        if r.round == "R32":
            label = f"{r.team_a} v {r.team_b}<br/><b>{r.projected_winner}</b>"
        else:
            label = f"<b>{r.projected_winner}</b>"
        shape = ("([", "])") if r.round == "FINAL" else ("[", "]")
        nodes.append(f'  m{num}{shape[0]}"{r.round}: {label}"{shape[1]}')
        for child in children[num]:
            # left half: child -> parent (toward the centre); right half mirrored
            if child in right_set:
                edges.append(f"  m{num} --- m{child}")
            else:
                edges.append(f"  m{child} --- m{num}")
    return "```mermaid\nflowchart LR\n" + "\n".join(nodes + edges) + "\n```"


# ── builder ──────────────────────────────────────────────────────────────────
def build_showcase(out: str = "showcase.md", n_match: int = 100000) -> str:
    """Assemble every projection into ``showcase.md`` with tables, charts, diagrams.

    ``n_match`` is the per-tie re-simulation count for the projected bracket
    (:func:`src.projections.project_modal_bracket`). Returns the output path.
    """
    fig = charts.build_all()

    # Reference figures relative to the repo root (where showcase.md lives).
    def rel(key: str) -> str:
        return fig[key]

    parts: list[str] = []
    parts.append("# 🏆 World Cup 2026 — Model Projections\n")
    parts.append(
        "Derived forecasts read straight off a 100k-simulation Monte Carlo of the\n"
        "tournament (weighted-Poisson goal model on Elo covariates). All figures are\n"
        f"**marginals**, not a single most-likely bracket. _Snapshot: {date.today().isoformat()}._\n"
    )

    # Headline
    parts.append("## Title odds\n")
    parts.append(_img(rel("champion_prob_bar"), "Championship probability"))

    # 1 — Group of death + standings
    parts.append("\n## 1 · Group standings & the group of death\n")
    parts.append(
        "`death_index` = expected strength (model net-xG, rebased so the weakest team\n"
        "is 0) of the teams a group is likely to **eliminate** — a high value is a\n"
        "genuine group of death.\n"
    )
    gd = P.group_difficulty_table()
    parts.append(
        df_to_md(
            gd,
            {
                "difficulty_rank": "rank",
                "median_xpoints": "median xPts",
                "strongest": "top seed",
            },
        )
    )
    gs = P.group_standings_table()
    parts.append(
        "\n<details><summary>Full per-group standings (P1/P2/P3-qualify/out, xPts)</summary>\n"
    )
    for g in sorted(gs["group"].unique()):
        sub = gs[gs["group"] == g].drop(columns=["group", "death_index"])
        parts.append(f"\n**Group {g}**\n")
        parts.append(df_to_md(sub))
    parts.append("\n</details>")

    # 2 — Projected bracket
    parts.append("\n## 2 · Projected bracket\n")
    parts.append(
        "Modal R32 occupants chained forward — each tie re-simulated "
        f"{n_match:,}× with the match engine, modal winner advancing. A single\n"
        "self-consistent **chalk** projection conditioned on the modal R32; the honest\n"
        "marginals are in §3 and §6.\n"
    )
    bracket = P.project_modal_bracket(n_match=n_match)
    champ = bracket[bracket["round"] == "FINAL"]["projected_winner"].iloc[0]
    parts.append(f"\n**Projected champion: {champ}**\n")
    parts.append(_bracket_mermaid(bracket))
    parts.append("\n<details><summary>Full projected bracket table</summary>\n")
    parts.append(df_to_md(bracket))
    parts.append("\n</details>")

    # 3 — Favorite's title path
    fav_path = P.favorite_title_path()
    fav = fav_path.attrs.get("team", "favorite")
    parts.append(f"\n## 3 · The favorite's most-likely title path — {fav}\n")
    parts.append(
        "Per-stage modal opponent (a marginal at each round, *not* a joint claim that\n"
        "this exact path happens).\n"
    )
    parts.append(_title_path_mermaid(fav_path, fav))

    # 4 — Expected elimination
    parts.append("\n## 4 · Expected round of elimination\n")
    parts.append(
        "One number per team — the expected stage reached (0 = group … 6 = champion) —\n"
        "linearly ranking all 48.\n"
    )
    parts.append(
        _img(rel("expected_elimination_ranked"), "Expected elimination ranking")
    )

    # 5 — Dark horse
    parts.append("\n## 5 · Dark-horse / overperformance index\n")
    parts.append(
        "Each team's P(reach semis) vs the average of its **seeding pot**. Positive\n"
        "`overperformance` = the model is more bullish than the draw implies.\n"
    )
    parts.append(_img(rel("dark_horse_scatter"), "Dark horse scatter"))
    dh = P.dark_horse_table()
    parts.append("\n**Biggest overperformers (outside Pot 1)**\n")
    dh_out = dh[dh["pot"] != 1].head(8).reset_index(drop=True)
    parts.append(df_to_md(dh_out))

    # 6 — R32 bracket marginals
    parts.append("\n## 6 · Per-slot Round-of-32 marginals\n")
    parts.append(
        "The modal occupant (and runners-up) of each R32 slot — honest where no team\n"
        "owns a slot, especially the third-place-fed `3XXXXX` slots.\n"
    )
    parts.append(df_to_md(P.r32_bracket_marginals()))

    # 7 — Marquee matchups
    parts.append("\n## 7 · Marquee matchup probabilities\n")
    parts.append(
        "Among the six title favorites: P(they meet) by stage, the chance of a given\n"
        "final, and who knocks out whom.\n"
    )
    mm = P.marquee_matchups()
    parts.append(
        df_to_md(
            mm,
            {
                "p_meet_any": "P(meet)",
                "p_final": "P(final)",
                "p_a_elim_b": "P(A out B)",
                "p_b_elim_a": "P(B out A)",
            },
        )
    )

    # 8 — Path difficulty
    parts.append("\n## 8 · Path difficulty — hardest route\n")
    parts.append(
        "For the top contenders: expected aggregate opponent strength on the knockout\n"
        "route (`path_strength_sum`) and the per-match average (`avg_opp_strength`,\n"
        "isolating draw luck from run depth).\n"
    )
    pd_tbl = P.path_difficulty_table()
    contenders = (
        pd_tbl[pd_tbl["champion"] >= pd_tbl["champion"].quantile(0.75)]
        .sort_values("avg_opp_strength", ascending=False)
        .head(12)
        .reset_index(drop=True)
    )
    parts.append(df_to_md(contenders))

    parts.append(
        "\n---\n_Generated by `src/showcase.py` from the forecast artifacts in "
        "`data/result/forecast/`. Re-run the Monte Carlo (main.py Stage 7) to refresh._\n"
    )

    text = "\n".join(parts) + "\n"
    with open(out, "w") as f:
        f.write(text)
    print(f"Showcase written to {out} (figures in {FIGURES_PATH}/)")
    return out


def build_live_showcase(
    out: str | None = None,
    n_match: int = 100000,
    src_dir: str | None = None,
    elo: dict[str, float] | None = None,
) -> str:
    """Render the in-tournament re-sim report into ``updated_simulation_showcase.md``.

    A focused live counterpart to :func:`build_showcase`, reading the re-sim
    artifacts in ``src_dir`` (default :data:`LIVE_PATH`, written by the ``resim``
    CLI command). Sections: updated title odds, group standings, the projected
    bracket, the most common knockout matchups, path difficulty, and the biggest
    title-odds risers vs the locked pre-tournament forecast. ``elo`` (the
    re-scraped ratings) is threaded into the projected-bracket re-sims so they use
    the same ratings as the headline re-sim. Returns the output path.
    """
    from src.const import FORECAST_PATH, LIVE_PATH

    src_dir = src_dir or LIVE_PATH
    out = out or f"{LIVE_PATH}/updated_simulation_showcase.md"
    probs = P._read(P._probs_filename(src_dir), src_dir)

    parts: list[str] = []
    parts.append("# 🏆 World Cup 2026 — Live Re-Simulation\n")
    parts.append(
        "Updated reach-probabilities from a re-run of the Monte Carlo with all\n"
        "**finished group matches seeded** and Elo re-scraped — only the unplayed\n"
        "remainder of the tournament is simulated. The pre-tournament forecast lives\n"
        f"in `showcase.md`. _Snapshot: {date.today().isoformat()} — after Round 1 (Matchday 1)._\n"
    )

    # Updated title odds
    champ_row = probs.sort_values("champion", ascending=False).iloc[0]
    parts.append("## Updated title odds\n")
    parts.append(
        f"Model champion: **{champ_row['team']}** "
        f"({champ_row['champion'] * 100:.1f}%). Top 12 by title probability "
        "(probability of reaching at least each stage, %).\n"
    )
    top = probs.sort_values("champion", ascending=False).head(12).reset_index(drop=True)
    odds = pd.DataFrame(
        {
            "team": top["team"],
            "champion": (top["champion"] * 100).round(1),
            "final": (top["final"] * 100).round(1),
            "sf": (top["sf"] * 100).round(1),
            "qf": (top["qf"] * 100).round(1),
            "r16": (top["r16"] * 100).round(1),
            "r32": (top["r32"] * 100).round(1),
        }
    )
    parts.append(df_to_md(odds))

    # 1 — Projected group standings
    parts.append("\n## 1 · Projected group standings\n")
    parts.append(
        "Per-team group-stage marginals from the re-sim, reflecting the seeded\n"
        "Round-1 results: `p1`/`p2` are the chances of finishing 1st/2nd; "
        "`p3_qualify`/`p3_out` split third place into advancing as a best-third\n"
        "team vs being eliminated; `exp_points` is expected group points; and\n"
        "`qualify_prob` is the overall chance of reaching the Round of 32.\n"
    )
    gs = P.group_standings_table(src_dir)
    for g in sorted(gs["group"].unique()):
        sub = gs[gs["group"] == g].drop(columns=["group", "death_index"])
        parts.append(f"\n**Group {g}**\n")
        parts.append(df_to_md(sub))

    # 2 — Projected bracket
    parts.append("\n## 2 · Projected bracket\n")
    parts.append(
        "Modal occupants chained forward — each tie re-simulated "
        f"{n_match:,}× with the match engine, modal winner advancing. A single\n"
        "self-consistent **chalk** projection conditioned on the seeded results.\n"
    )
    bracket = P.project_modal_bracket(n_match=n_match, src_dir=src_dir, elo=elo)
    champ = bracket[bracket["round"] == "FINAL"]["projected_winner"].iloc[0]
    parts.append(f"\n**Projected champion: {champ}**\n")
    parts.append(_bracket_mermaid(bracket))
    parts.append("\n<details><summary>Full projected bracket table</summary>\n")
    parts.append(df_to_md(bracket))
    parts.append("\n</details>")

    # 3 — Most common knockout matchups
    parts.append("\n## 3 · Most common knockout matchups\n")
    parts.append(
        "The ten most likely knockout ties across the whole bracket: `p_meet` is the\n"
        "probability the pair meets somewhere in the knockouts; `modal_stage` is where\n"
        "they most often do.\n"
    )
    parts.append(df_to_md(P.most_common_matchups(10, src_dir)))

    # 4 — Path difficulty
    parts.append("\n## 4 · Path difficulty — hardest route\n")
    parts.append(
        "For the top contenders: expected aggregate opponent strength on the knockout\n"
        "route (`path_strength_sum`) and the per-match average (`avg_opp_strength`,\n"
        "isolating draw luck from run depth).\n"
    )
    pd_tbl = P.path_difficulty_table(src_dir)
    contenders = (
        pd_tbl[pd_tbl["champion"] >= pd_tbl["champion"].quantile(0.75)]
        .sort_values("avg_opp_strength", ascending=False)
        .head(12)
        .reset_index(drop=True)
    )
    parts.append(df_to_md(contenders))

    # 5 — Biggest title-odds risers
    parts.append("\n## 5 · Biggest title-odds risers vs the pre-tournament forecast\n")
    parts.append(
        "The 16 teams whose champion probability rose the most since the locked\n"
        "pre-tournament forecast (`tournament_probs_initial.csv`) — the seeded\n"
        "Round-1 results' biggest beneficiaries.\n"
    )
    delta = P.champion_prob_delta(
        16, src_dir, initial_path=f"{FORECAST_PATH}/tournament_probs_initial.csv"
    )
    parts.append(df_to_md(delta))

    parts.append(
        "\n---\n_Generated by `src/showcase.py::build_live_showcase` from the re-sim "
        "artifacts in `data/result/live/`. Re-run `uv run python -m src.cli resim` to "
        "refresh after each matchday._\n"
    )

    text = "\n".join(parts) + "\n"
    with open(out, "w") as f:
        f.write(text)
    print(f"Live showcase written to {out}")
    return out
