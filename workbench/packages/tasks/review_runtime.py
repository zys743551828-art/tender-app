"""Explicit task/review composition shared by API-role process entrypoints."""

from packages.domain import reviews
from packages.tasks.inputs import review_guard


def configure_review_guard():
    """Install the exact frozen-input guard without opening resources or importing Web."""
    reviews.TASK_INPUT_GUARD = review_guard
