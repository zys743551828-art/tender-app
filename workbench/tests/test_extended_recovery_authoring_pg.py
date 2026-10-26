"""B1–B5 native edited Word records survive the extended offline recovery."""
# ruff: noqa: F401,F811

import os

import pytest
from authoring_package_job_fixtures import case, input_database, queued
from authoring_package_job_fixtures import database as job_database
from extended_recovery_helpers import BASE, drill, install_remaining
from test_authoring_exact_builds_pg import adopted, compute, exact, publish, start
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_revisions_pg import published
from test_authoring_exact_text_edits_pg import database as text_edit_database
from test_authoring_exact_text_edits_pg import edit, request_body, world
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api

from deploy import authoring_candidate

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1",
    reason="explicit disposable extended recovery PG/S3 required",
)


@pytest.fixture(scope="module")
def database(text_edit_database):
    install_remaining(text_edit_database["owner"], BASE | set(authoring_candidate.OPTIONAL_SQL))
    return text_edit_database


def test_native_edited_word_all_schema_rows_objects_and_runtime_quarantine(adopted):
    w = adopted
    response = edit(w, request_body(w))
    assert response.status_code == 200, response.text
    w["saved"].update(
        {key: response.json()[key] for key in ("draft_revision", "snapshot_id", "snapshot_digest")}
    )
    build = start(w)
    computed = compute(build)
    publish(build, computed)
    drill(
        w["database"],
        "authoring",
        {
            "design.authoring_package_inputs",
            "design.authoring_package_fact_scopes",
            "design.authoring_package_job_bindings",
            "design.authoring_package_action_bindings",
            "design.authoring_exact_revisions",
            "design.authoring_exact_manual_revisions",
            "design.build_outputs",
        },
        extra_login_dsn=w["database"]["worker_dsn"],
    )
