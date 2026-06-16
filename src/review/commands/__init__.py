"""CLI command modules.

Commands are split by workflow tier:

- :mod:`review.commands.reviews` — the individual-edit commands (``new``,
  ``edit``, ``fetch-cover`` …). These must stay bulletproof across environments.
- :mod:`review.commands.covers` — the bulk cover-repair pipeline
  (``stage-covers`` → ``pick-covers`` …), tuned to specific problems.

Both register flat on the top-level ``review`` group (see :mod:`review.cli`);
the split is internal organisation only.
"""
