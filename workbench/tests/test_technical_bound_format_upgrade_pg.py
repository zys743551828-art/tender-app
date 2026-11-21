"""Previously queued plain structured authoring survives the optional owner upgrade."""
# ruff: noqa: F401,F811

import pytest
from authoring_package_input_fixtures import world
from authoring_package_job_fixtures import case, input_database, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted as adopt_received
from test_authoring_exact_builds_pg import database
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_revisions_pg import published as publish_candidate
from test_stable_lot_identity import api
from test_technical_bid_generation_journey_pg import (
    build_structured_word,
    exact,
    pytestmark,
    requirements,
)

from packages.authoring import bound_format_scope
from packages.domain.runtime import ROOT, connection


def original_records(w):
    with connection() as c:
        return c.execute(
            """SELECT i.manifest AS fixed_input, i.context_digest, i.digest AS input_digest,
                 j.input_manifest, j.input_digest AS job_digest, binding.task_manifest_digest
               FROM design.authoring_package_job_bindings binding
               JOIN design.assistant_jobs j ON j.id=binding.job_id AND j.bid_id=binding.bid_id
               JOIN design.authoring_package_inputs i ON i.id=binding.input_id AND i.bid_id=binding.bid_id
               WHERE binding.job_id=%s AND binding.bid_id=%s""",
            (w["job_id"], w["bid"]),
        ).fetchone()


def test_optional_format_upgrade_leaves_queued_unbound_task_and_its_word_path_intact(queued):
    w = queued
    with connection() as c:
        assert not bound_format_scope.installed(c)
    before = original_records(w)
    assert before["job_digest"]
    assert "bound_format_method" not in before["input_manifest"]["plan"]["execution_policy"]
    w["database"]["owner"].execute((ROOT / bound_format_scope.DDL).read_text())
    with connection() as c:
        assert bound_format_scope.installed(c)
    assert original_records(w) == before
    w = adopt_received.__wrapped__(publish_candidate.__wrapped__(w))
    assert len(w["calls"]) == 1
    _, word, body = build_structured_word(w)
    assert w["raw"]["replacement_text"] in body and word["format"] == "docx"
    assert original_records(w) == before
