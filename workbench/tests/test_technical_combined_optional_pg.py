"""Even both existing extensions do not opt a draft into the combined mode."""
# ruff: noqa: F401,F811

import psycopg
import pytest
from authoring_package_input_fixtures import save
from test_technical_combined_scope_pg import (
    api,
    capture_body,
    combined_draft,
    confirmed_format,
    counts,
    current_layout,
    database,
    draft_path,
    formatted_schema,
    input_database,
    job_database,
    planned_schema,
    pytestmark,
    requirements,
    revision_database,
    world,
)

from packages.authoring import combined_authoring_scope, saved_chapter_plans
from packages.domain.runtime import ROOT, connection


def test_rejects_install_without_both_required_constraints(job_database):
    owner = job_database["owner"]
    script = (ROOT / combined_authoring_scope.DDL).read_text()
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as denied:
        owner.execute(script)
    assert denied.value.diag.message_primary == "AUTHORING_COMBINED_SCOPE_REQUIRES_BOTH_CONTRACTS"
    owner.execute("ROLLBACK")
    with connection() as c:
        assert not combined_authoring_scope.installed(c)


def test_both_old_scopes_alone_refuse_same_draft_without_writes(
    combined_draft, planned_schema, formatted_schema
):
    w = combined_draft
    with connection() as c:
        assert saved_chapter_plans.installed(c)
        assert not combined_authoring_scope.installed(c)
    chapter = w["technical_journey"]["chapter"]
    observed = current_layout(w, draft_path(w), chapter["section_id"])
    assert observed["unsupported_reasons"] == ["bound_project_format"]
    assert observed["plan_state"] == "requires_fixed_evidence"
    blocked = "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED"
    body = capture_body(w, blocker=blocked)
    before = counts()
    denied = save(w, body=body)
    assert denied.status_code == 409 and denied.json()["code"] == blocked, denied.text
    assert counts() == before
