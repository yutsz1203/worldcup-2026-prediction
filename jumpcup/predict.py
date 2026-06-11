"""CLI for the Jump Probability Cup pipeline. Run from the project root:

    uv run python -m jumpcup.predict upcoming [--n 3]
    uv run python -m jumpcup.predict rates --team-a Mexico --team-b "South Africa"
    uv run python -m jumpcup.predict rates --event-id 8287 --refresh
    uv run python -m jumpcup.predict price --event-id 8287 [--spec PATH] [--n 100000]

``upcoming`` lists the next unstarted WC26 matches with their event ids (so you can
pick one without hunting for ids). ``rates`` fetches the bzzoiro bundle (cached) and
writes ``jumpcup/data/cleaned/rates_{event_id}.csv``. ``price`` simulates stat lines
from that CSV and prices the spec at ``jumpcup/data/live/spec_{event_id}.json``
into ``probs_{event_id}.csv``.
"""

from __future__ import annotations

import argparse

from jumpcup import event_pricer, event_rates
from jumpcup.fetch import fetch_match_bundle, upcoming_matches
from src.const import CON


def _print_upcoming(n: int) -> None:
    for e in upcoming_matches(n):
        when = str(e["event_date"]).replace("T", " ")[:16]
        stage = e.get("group_name") or e.get("round_name") or ""
        CON.print(
            f"  [bold]{e['id']}[/]  {when} UTC  "
            f"{e['home_team']} vs {e['away_team']}  ({stage})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(prog="jumpcup.predict", description=__doc__)
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

    p_price = sub.add_parser("price", help="simulate and price an event spec")
    p_price.add_argument("--event-id", type=int, required=True)
    p_price.add_argument(
        "--spec", help="spec JSON path (default: spec_{event_id}.json)"
    )
    p_price.add_argument(
        "--rates", help="rates CSV path (default: rates_{event_id}.csv)"
    )
    p_price.add_argument(
        "--out", help="output CSV path (default: probs_{event_id}.csv)"
    )
    p_price.add_argument("--n", type=int, default=event_pricer.N_SIMS_DEFAULT)
    p_price.add_argument("--seed", type=int, default=event_pricer.SEED_DEFAULT)

    args = parser.parse_args()
    if args.cmd == "upcoming":
        _print_upcoming(args.n)
    elif args.cmd == "rates":
        if args.event_id is None and not (args.team_a and args.team_b):
            parser.error("rates needs --event-id or both --team-a/--team-b")
        bundle = fetch_match_bundle(
            args.team_a, args.team_b, args.event_id, args.refresh
        )
        event_rates.write_rates(bundle)
    else:
        event_pricer.price(
            args.event_id,
            spec_file=args.spec,
            rates_file=args.rates,
            out=args.out,
            n=args.n,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()
