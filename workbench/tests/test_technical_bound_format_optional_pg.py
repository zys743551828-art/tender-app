"""No migration at application startup; a saved style is not a generation capability."""
# ruff: noqa: F401,F811

from authoring_package_input_fixtures import save
from test_technical_bound_format_generation_pg import (
    api,
    capture_body,
    confirmed_format,
    counts,
    current_layout,
    database,
    draft_path,
    input_database,
    job_database,
    pytestmark,
    requirements,
    revision_database,
    world,
)


def test_confirmed_current_format_is_blocked_without_optional_native_scope(confirmed_format):
    w = confirmed_format
    stored = w["confirmed_format"]["saved"]
    gate = current_layout(w, draft_path(w), w["technical_journey"]["chapter"]["section_id"])
    assert gate["snapshot_id"] == stored["snapshot_id"]
    assert gate["state"] == "structure_not_supported"
    assert gate["unsupported_reasons"] == ["bound_project_format"]
    blocked = "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED"
    pinned = capture_body(w, blocker=blocked)
    before = counts()
    result = save(w, body=pinned)
    assert result.status_code == 409, result.text
    assert result.json()["code"] == blocked
    assert counts() == before
