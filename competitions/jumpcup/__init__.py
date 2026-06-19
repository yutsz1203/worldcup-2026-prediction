"""Jump Trading Probability Cup pipeline.

Prices per-match event probabilities (the 10 free-text events Jump publishes per
WC26 match). Run everything from the project root (modules import
``src.*``/``model.*``).

Workflow
--------
0. **Show upcoming matches.**
       uv run python -m competitions.jumpcup.predict upcoming [--n 3]

1. **Prep the next N matches** — one command does everything up to translation::

       uv run python -m competitions.jumpcup.predict prep --n 3

2. **Prompt Claude to translate the questions into specs** in ``spec_{event_id}.json``.

3. **Price the specs** — by id (several at once, with an end-of-run cross-check
   summary) or, more simply, ``--pending`` to price every translated-but-unpriced
   spec in one go::

       uv run python -m competitions.jumpcup.predict price --pending
       uv run python -m competitions.jumpcup.predict price --event-id 8287 8299 (price specific event with its id)

4. **Check status (specs ready? / priced?) of upcoming matches**

       uv run python -m competitions.jumpcup.predict status

5. **Show prices of upcoming matches**
    uv run python -m competitions.jumpcup.predict show [--all / --event-id 8296 ...]
"""
