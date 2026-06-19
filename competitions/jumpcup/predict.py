from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from rich.syntax import Syntax
from rich.table import Table

from competitions.jumpcup import event_pricer, event_rates
from competitions.jumpcup.const import (
    JUMPCUP_LIVE_PATH,
    probs_path,
    rates_path,
    spec_path,
)
from competitions.jumpcup.fetch import (
    MatchBundle,
    fetch_match_bundle,
    fetch_sportspredict_matches,
    fetch_sportspredict_questions,
    fetch_wc26_events,
    upcoming_matches,
)
from src.const import CON


def _print_upcoming(n: int) -> None:
    for e in upcoming_matches(n):
        when = str(e["event_date"]).replace("T", " ")[:16]
        stage = e.get("group_name") or e.get("round_name") or ""
        CON.print(
            f"  [bold]{e['id']}[/]  {when} UTC  "
            f"{e['home_team']} vs {e['away_team']}  ({stage})"
        )


def _write_spec_stub(bundle: MatchBundle, questions: list[str]) -> bool:
    """Write a spec stub (questions filled, ``spec: null``) for one match.

    Returns False without writing if a spec already exists, so a hand-translated
    spec is never clobbered.
    """
    path = spec_path(bundle.event_id)
    if Path(path).exists():
        CON.print(
            f"[yellow]jumpcup:[/] spec for event {bundle.event_id} already exists "
            f"({path}) — leaving it untouched."
        )
        return False
    stub = {
        "event_id": bundle.event_id,
        "team_A": bundle.a.team_name,
        "team_B": bundle.b.team_name,
        "events": [
            {"id": i, "text": q, "spec": None} for i, q in enumerate(questions, start=1)
        ],
    }
    Path(path).write_text(json.dumps(stub, ensure_ascii=False, indent=2))
    return True


def _sp_name_matches(sp_name: str, home: str, away: str) -> bool:
    """Best-effort check that a SportsPredict ``"HOME vs AWAY"`` label is the same
    fixture as the bzzoiro ``home``/``away`` teams. Tolerant of 3-letter codes and
    full names. Used only to disambiguate *simultaneous* kickoffs, so a miss just
    skips the stub (user fills it manually) — it never causes a silent mispair."""
    parts = re.split(r"\s+vs\.?\s+", str(sp_name).strip(), flags=re.IGNORECASE)
    if len(parts) != 2:
        return False

    def side_ok(token: str, full: str) -> bool:
        t = re.sub(r"[^a-z]", "", token.lower())
        f = re.sub(r"[^a-z]", "", full.lower())
        return bool(t) and bool(f) and (f.startswith(t) or t in f)

    return side_ok(parts[0], home) and side_ok(parts[1], away)


def _match_sp_for_event(event: dict, sp_by_kickoff: dict[str, list[dict]]):
    """The SportsPredict match for a bzzoiro fixture, paired by KICKOFF TIME (not
    list position). The two feeds order/filter differently — SportsPredict keeps
    already-started matches while ``upcoming_matches`` drops them — so positional
    pairing silently attaches the wrong question set. Kickoff-minute is identical
    across both feeds and unique per fixture, except for simultaneous kickoffs,
    which are broken by a team-name check. Returns ``(sp_match, note)`` where a
    ``None`` match means *skip* (note explains why)."""
    kickoff = str(event["event_date"])[:16]
    cands = sp_by_kickoff.get(kickoff, [])
    if not cands:
        return None, f"no SportsPredict match at {kickoff} UTC"
    if len(cands) == 1:
        return cands[0], None
    # simultaneous kickoffs -> require an unambiguous team-name match
    hits = [
        m
        for m in cands
        if _sp_name_matches(m.get("name", ""), event["home_team"], event["away_team"])
    ]
    if len(hits) == 1:
        return hits[0], None
    names = ", ".join(repr(m.get("name", "")) for m in cands)
    return None, (
        f"{len(cands)} SportsPredict matches share kickoff {kickoff} UTC "
        f"({names}) and team-name disambiguation was inconclusive"
    )


def _prep(n: int, refresh: bool) -> None:
    """Fetch ids + rates + questions for the next ``n`` matches and write spec stubs."""
    events = upcoming_matches(n, refresh=True)  # cheap; always fresh fixtures
    # Always fresh, and the *full* list (no [:n] slice): we look matches up by
    # kickoff time, so a different length/order between the feeds is harmless.
    sp_by_kickoff: dict[str, list[dict]] = {}
    for m in fetch_sportspredict_matches(refresh=True):
        sp_by_kickoff.setdefault(str(m.get("opening_time", ""))[:16], []).append(m)

    prepared: list[int] = []
    for event in events:
        eid = event["id"]
        sp_match, skip_note = _match_sp_for_event(event, sp_by_kickoff)
        if sp_match is None:
            CON.print(
                f"[yellow]jumpcup:[/] event {eid} "
                f"({event['home_team']} vs {event['away_team']}): {skip_note} — "
                f"skipping (no question stub written)."
            )
            continue
        CON.print(
            f"[bold]jumpcup:[/] bzzoiro event {eid} "
            f"({event['home_team']} vs {event['away_team']}) "
            f"<-> SportsPredict {sp_match.get('name')!r} @ "
            f"{str(event['event_date'])[:16]} UTC"
        )
        bundle = fetch_match_bundle(event_id=eid, refresh=refresh)
        event_rates.write_rates(bundle)
        questions = fetch_sportspredict_questions(sp_match["id"], refresh)
        if _write_spec_stub(bundle, questions):
            CON.print(
                f"[green]jumpcup:[/] wrote {len(questions)}-question spec stub "
                f"for event {eid}."
            )
        prepared.append(eid)

    CON.print("\n[bold green]jumpcup:[/] prep done. Next:")
    for eid in prepared:
        CON.print(f"  translate the null specs in {spec_path(eid)}")


# ---------------------------------------------------------------------------
# Spec discovery + pricing
# ---------------------------------------------------------------------------
_SPEC_RE = re.compile(r"spec_(\d+)\.json$")


def _spec_event_ids() -> list[int]:
    """Event ids of every spec_{id}.json under the live dir, sorted."""
    return sorted(
        int(m.group(1))
        for p in Path(JUMPCUP_LIVE_PATH).glob("spec_*.json")
        if (m := _SPEC_RE.search(p.name))
    )


def _spec_fill_counts(event_id: int) -> tuple[int, int]:
    """(translated events, total events) for a spec — translated == spec not null."""
    data = json.loads(Path(spec_path(event_id)).read_text())
    events = data.get("events", [])
    return sum(1 for ev in events if ev.get("spec") is not None), len(events)


def _pending_event_ids() -> list[int]:
    """Fully-translated specs that haven't been priced yet."""
    pending = []
    for eid in _spec_event_ids():
        filled, total = _spec_fill_counts(eid)
        if total and filled == total and not Path(probs_path(eid)).exists():
            pending.append(eid)
    return pending


def _price(event_ids, spec, rates, out, n, seed) -> None:
    """Price each event, isolating failures, then print a batch summary."""
    results = []  # (event_id, crosscheck_state, detail)
    for eid in event_ids:
        try:
            df = event_pricer.price(
                eid, spec_file=spec, rates_file=rates, out=out, n=n, seed=seed
            )
        except Exception as exc:  # keep the batch going if one spec isn't ready
            CON.print(f"[red]jumpcup:[/] event {eid} failed to price: {exc}")
            results.append((eid, "fail", str(exc)))
            continue
        total = len(df)
        priced = int(df["probability"].notna().sum())
        detail = f"{priced}/{total}" + (
            f" ({total - priced} blank)" if priced < total else ""
        )
        state = "ok" if df.attrs.get("crosscheck_ok", True) else "mismatch"
        results.append((eid, state, detail))

    if len(results) > 1:
        _print_price_summary(results)


def _print_price_summary(results) -> None:
    table = Table(title="price summary", show_header=True, header_style="bold")
    table.add_column("event")
    table.add_column("cross-check")
    table.add_column("priced")
    render = {
        "ok": "[green]ok[/]",
        "mismatch": "[red]MISMATCH[/]",
        "fail": "[red]error[/]",
    }
    for eid, state, detail in results:
        table.add_row(str(eid), render[state], detail)
    CON.print(table)
    flagged = [eid for eid, state, _ in results if state != "ok"]
    if flagged:
        CON.print(
            f"[yellow]jumpcup:[/] review {flagged} — cross-check mismatch or error; "
            "don't submit those."
        )


def _status(show_all: bool = False) -> None:
    """Show pipeline state (rates / spec / priced) for every prepped match.

    Finished matches are hidden by default (the prepped set only grows over the
    tournament); pass ``show_all=True`` to include them.
    """
    ids = _spec_event_ids()
    if not ids:
        CON.print("[yellow]jumpcup:[/] no prepped matches — run [bold]prep --n N[/].")
        return
    # event status from the (cached) feed; anything not "finished" still shows, so
    # a live/notstarted match is never hidden and an id missing from the feed is
    # shown rather than silently dropped.
    status_by_id = {e["id"]: e.get("status") for e in fetch_wc26_events(refresh=False)}
    hidden = 0
    pending = 0
    if not show_all:
        kept = [eid for eid in ids if status_by_id.get(eid) != "finished"]
        hidden = len(ids) - len(kept)
        ids = kept
    if not ids:
        CON.print(
            f"[yellow]jumpcup:[/] all {hidden} prepped match(es) finished — "
            "run [bold]status --all[/] to see them."
        )
        return
    table = Table(
        title="jumpcup pipeline status", show_header=True, header_style="bold"
    )
    for col in ("event", "match", "rates", "spec", "priced"):
        table.add_column(col)
    for eid in ids:
        data = json.loads(Path(spec_path(eid)).read_text())
        filled, total = _spec_fill_counts(eid)
        spec_state = (
            "[green]ready[/]"
            if total and filled == total
            else f"[yellow]stub {filled}/{total}[/]"
        )
        has_rates = Path(rates_path(eid)).exists()
        has_priced = Path(probs_path(eid)).exists()
        rates = "[green]✓[/]" if has_rates else "—"
        priced = "[green]✓[/]" if has_priced else "—"
        match = f"{data.get('team_A', '?')} vs {data.get('team_B', '?')}"
        table.add_row(str(eid), match, rates, spec_state, priced)
        if has_rates and not has_priced:
            pending += 1
    CON.print(table)
    if hidden:
        CON.print(
            f"[dim]{hidden} finished match(es) hidden — [bold]status --all[/] "
            "to show.[/]"
        )
    if pending > 0:
        CON.print(f"[green]jumpcup:[/] {pending} match(es) ready but unpriced — run:")
        CON.print(
            Syntax(
                "uv run python -m competitions.jumpcup.predict price --pending",
                "bash",
                theme="ansi_dark",
                word_wrap=True,
            )
        )


def _show(event_ids: list[int] | None, show_all: bool = False) -> None:
    """Print already-priced results from ``probs_{id}.csv`` — read-only, no recompute.

    With no ids, shows every priced *upcoming* match (finished matches hidden
    unless ``show_all``). Explicit ids are always shown regardless of status.
    Unpriced ids warn and are skipped rather than recomputing (use ``price``).
    """
    if event_ids:
        ids = event_ids
    else:
        priced = [eid for eid in _spec_event_ids() if Path(probs_path(eid)).exists()]
        if show_all:
            ids = priced
        else:
            status_by_id = {
                e["id"]: e.get("status") for e in fetch_wc26_events(refresh=False)
            }
            ids = [eid for eid in priced if status_by_id.get(eid) != "finished"]
            if priced and not ids:
                CON.print(
                    "[yellow]jumpcup:[/] every priced match has finished — run "
                    "[bold]show --all[/] to see them."
                )
                return
    if not ids:
        CON.print(
            "[yellow]jumpcup:[/] nothing priced yet — run [bold]price --pending[/]."
        )
        return
    for eid in ids:
        path = probs_path(eid)
        if not Path(path).exists():
            CON.print(
                f"[yellow]jumpcup:[/] event {eid} not priced yet — run "
                f"[bold]price --event-id {eid}[/]."
            )
            continue
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        try:
            spec = json.loads(Path(spec_path(eid)).read_text())
            match = f"{spec.get('team_A', '?')} vs {spec.get('team_B', '?')}"
        except FileNotFoundError:
            match = ""
        generated = rows[0].get("generated_at", "") if rows else ""
        table = Table(
            title=f"event {eid}  {match}".strip(),
            caption=f"priced {generated}" if generated else None,
            show_header=True,
            header_style="bold",
        )
        table.add_column("#", justify="right")
        table.add_column("question")
        table.add_column("prob", justify="right")
        for r in rows:
            p = r.get("probability") or ""
            prob = f"{float(p):.2%}" if p else f"[dim]— {r.get('note', '')}[/]"
            table.add_row(r.get("jump_event_id", ""), r.get("text", ""), prob)
        CON.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="competitions.jumpcup.predict", description=__doc__
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upcoming", help="list the next WC26 matches with event ids")
    p_up.add_argument("--n", type=int, default=3, help="how many matches to list")

    p_rates = sub.add_parser("rates", help="fetch match bundle and write base rates")
    p_rates.add_argument("--team-a", help="canonical team name (either side)")
    p_rates.add_argument("--team-b", help="canonical team name (either side)")
    p_rates.add_argument("--event-id", type=int, help="bzzoiro event id")
    p_rates.add_argument(
        "--refresh", action="store_true", help="refetch instead of using cached JSON"
    )

    p_price = sub.add_parser("price", help="simulate and price one or more event specs")
    p_price.add_argument(
        "--event-id",
        type=int,
        nargs="+",
        metavar="EVENT_ID",
        help="one or more bzzoiro event ids to price",
    )
    p_price.add_argument(
        "--pending",
        action="store_true",
        help="price every fully-translated spec that isn't priced yet",
    )
    p_price.add_argument(
        "--spec",
        help="spec JSON path (single event only; default: spec_{event_id}.json)",
    )
    p_price.add_argument(
        "--rates",
        help="rates CSV path (single event only; default: rates_{event_id}.csv)",
    )
    p_price.add_argument(
        "--out",
        help="output CSV path (single event only; default: probs_{event_id}.csv)",
    )
    p_price.add_argument("--n", type=int, default=event_pricer.N_SIMS_DEFAULT)
    p_price.add_argument("--seed", type=int, default=event_pricer.SEED_DEFAULT)

    p_prep = sub.add_parser(
        "prep",
        help="fetch ids+rates+questions and write spec stubs for the next N matches",
    )
    p_prep.add_argument("--n", type=int, default=3)
    p_prep.add_argument(
        "--refresh", action="store_true", help="refetch instead of using cached JSON"
    )

    p_status = sub.add_parser(
        "status", help="show rates/spec/priced state for every prepped match"
    )
    p_status.add_argument(
        "--all",
        action="store_true",
        help="include finished matches (hidden by default)",
    )

    p_show = sub.add_parser(
        "show", help="print already-priced results from probs CSVs (no recompute)"
    )
    p_show.add_argument(
        "--event-id",
        type=int,
        nargs="+",
        metavar="EVENT_ID",
        help="event ids to show (default: every priced upcoming match)",
    )
    p_show.add_argument(
        "--all",
        action="store_true",
        help="include finished matches (hidden by default)",
    )

    args = parser.parse_args()
    if args.cmd == "upcoming":
        _print_upcoming(args.n)
    elif args.cmd == "status":
        _status(args.all)
    elif args.cmd == "show":
        _show(args.event_id, args.all)
    elif args.cmd == "prep":
        _prep(args.n, args.refresh)
    elif args.cmd == "rates":
        if args.event_id is None and not (args.team_a and args.team_b):
            parser.error("rates needs --event-id or both --team-a/--team-b")
        bundle = fetch_match_bundle(
            args.team_a, args.team_b, args.event_id, args.refresh
        )
        event_rates.write_rates(bundle)
    else:  # price
        if args.pending and args.event_id:
            parser.error("use either --event-id or --pending, not both")
        if args.spec or args.rates or args.out:
            if args.pending or (args.event_id and len(args.event_id) > 1):
                parser.error("--spec/--rates/--out apply to a single --event-id only")
        if args.pending:
            event_ids = _pending_event_ids()
            if not event_ids:
                CON.print(
                    "[yellow]jumpcup:[/] nothing pending — every translated spec "
                    "is already priced (see [bold]status[/])."
                )
                return
            CON.print(
                f"[bold]jumpcup:[/] pricing {len(event_ids)} pending event(s): "
                f"{event_ids}"
            )
        elif args.event_id:
            event_ids = args.event_id
        else:
            parser.error("price needs --event-id or --pending")
        _price(event_ids, args.spec, args.rates, args.out, args.n, args.seed)


if __name__ == "__main__":
    main()
