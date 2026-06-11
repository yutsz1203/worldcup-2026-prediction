"""Jump Trading Probability Cup pipeline.

Prices per-match event probabilities (the 10 free-text events Jump publishes per
WC26 match). Run everything from the project root (modules import
``src.*``/``model.*``).

Workflow, per match
-------------------

1. **Pick the match.** List the next fixtures with their bzzoiro event ids::

       uv run python -m jumpcup.predict upcoming [--n 3]

2. **Generate base rates** for the chosen event id::

       uv run python -m jumpcup.predict rates --event-id 8287

   Fetches the lineups, each lineup player's recent per-match stats, and both
   teams' past-year team stats (all cached under ``jumpcup/data/raw/``; reruns
   are free), combines them with the GLM goal model, and writes
   ``jumpcup/data/cleaned/rates_{event_id}.csv``. The console warns while the
   lineup is still ``predicted`` — re-run with ``--refresh`` once lineups are
   confirmed (~1h before kickoff) so player events use the real XI.

3. **Translate Jump's events into a spec.** Paste the 10 free-text events into a
   Claude chat; they are hand-translated into the canonical taxonomy
   (THRESHOLD/COMPARE/FIRST atoms composed with AND/OR — grammar and example in
   ``jumpcup/jump-probability-cup.md``) and saved as
   ``jumpcup/data/live/spec_{event_id}.json``. Deliberately no NL parser.

4. **Price the spec**::

       uv run python -m jumpcup.predict price --event-id 8287

   Simulates 100k per-match stat lines from the rates CSV, evaluates each
   event's indicator, and writes ``jumpcup/data/live/probs_{event_id}.csv``.
   Every run cross-checks the simulated win/draw/over-2.5 against the
   closed-form score matrix and flags red if they diverge by more than 0.01 —
   if flagged, don't submit; the rates are off. The cached
   ``events/{id}/odds.json`` gives de-viggable bookmaker odds as an external
   sanity check.

Modules: ``fetch`` (bzzoiro client + JSON cache), ``event_rates`` (bundle →
rates CSV), ``event_pricer`` (Monte Carlo simulator + spec evaluator),
``predict`` (CLI), ``const`` (paths under ``jumpcup/data/``).
"""
