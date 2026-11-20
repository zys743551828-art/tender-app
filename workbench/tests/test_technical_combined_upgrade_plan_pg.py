"""Already queued plan-backed drafting remains on the original provider method."""
# ruff: noqa: F401,F811

from technical_combined_upgrade_support import keep_queued_original
from test_technical_bound_format_generation_pg import formatted_schema
from test_technical_combined_scope_pg import (
    api,
    case,
    database,
    input_database,
    job_database,
    planned_schema,
    pytestmark,
    queued,
    requirements,
    revision_database,
    world,
)
from test_technical_saved_plan_generation_pg import exact


def test_plan_job_keeps_original_binding_after_combined_upgrade(queued, formatted_schema):
    keep_queued_original(queued, plan=True)
