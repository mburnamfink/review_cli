"""Top-level ``review`` command group.

Commands live in :mod:`review.commands` and are registered flat here, so the user
sees one flat command set (`review new`, `review stage-covers`, …). The split into
``commands.reviews`` (individual edits) and ``commands.covers`` (bulk repair) is
internal organisation; see :mod:`review.commands` for the rationale.
"""
from __future__ import annotations

import click

from .commands import covers, reviews

# Re-exported for tests and external callers that import it from here.
from .commands.covers import _apply_staged  # noqa: F401


@click.group(context_settings={"max_content_width": 120, "terminal_width": 120})
def cli():
    """Book review manager."""


# Individual-edit commands (the bulletproof core).
cli.add_command(reviews.new)
cli.add_command(reviews.edit)
cli.add_command(reviews.add_read)
cli.add_command(reviews.link)
cli.add_command(reviews.bsky)
cli.add_command(reviews.list_reviews)
cli.add_command(reviews.validate)
cli.add_command(reviews.fetch_cover)
cli.add_command(reviews.process_cover_cmd)
cli.add_command(reviews.crop)
cli.add_command(reviews.init)

# Bulk cover-repair pipeline.
cli.add_command(covers.find_low_res_cmd)
cli.add_command(covers.find_covers_cmd)
cli.add_command(covers.stage_covers_cmd)
cli.add_command(covers.pick_covers_cmd)
cli.add_command(covers.pick_covers_web_cmd)
