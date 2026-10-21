"""Actual non-owner PG target discovery, exact run identity and project isolation."""
# ruff: noqa: F401,F811

import os

import pytest
from test_bid_package_review_preview_api import api, database, requirements, world
from test_package_review_runs_api import TestPackageReviewRuns as RunCases

from packages.domain.runtime import DomainError, connection
from packages.knowledge import bridge
from packages.knowledge.contracts import validate_actual

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires explicitly isolated non-owner PG17 package reference test",
)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageKnowledgeTargets:
    original_case = RunCases.original_case
    frozen_case = RunCases.frozen_case
    execution_case = RunCases.execution_case
    prepared_case = RunCases.prepared_case
    exact_inventory_proof_case = RunCases.exact_inventory_proof_case
    launch_case = RunCases.launch_case
    post = RunCases.post
    launch = RunCases.launch

    def test_directory_and_lookup_bind_exact_run_without_editing_frozen_input(self, launch_case):
        case = launch_case
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        bid = case["scope"][0]
        web = case["w"]["client"]
        response = web.get(f"/api/v1/bids/{bid}/knowledge-reference-targets", params={"limit": 1})
        assert response.status_code == 200, response.text
        page = response.json()
        validate_actual("KnowledgePackageReviewTargetPage", page)
        assert {part.strip() for part in response.headers["Cache-Control"].split(",")} == {
            "private",
            "no-store",
        }
        assert page["items"] == [
            {
                "id": run["id"],
                "target_kind": "package_review_run",
                "created_at": run["created_at"],
                "input_digest": run["input_digest"],
                "execution_input_id": case["prepared"]["manifest"]["id"],
                "state": "queued",
                "package_id": case["scope"][1],
                "revision_id": case["scope"][2],
                "inventory_id": case["scope"][3],
                "frozen_input_id": case["frozen"]["manifest"]["id"],
                "result_digest": None,
            }
        ]
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            bridge.require_reference_target(c, bid, "package_review_run", run["id"])
            assert c.execute(
                "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == {"rolsuper": False}
        with connection() as c, pytest.raises(DomainError) as caught:
            bridge.require_reference_target(
                c, "00000000-0000-4000-8000-000000000099", "package_review_run", run["id"]
            )
        assert caught.value.code == "NOT_FOUND"
        assert web.get(case["path"] + "/" + run["id"]).json() == run
        assert (
            web.get(f"/api/v1/bids/{bid}/knowledge-reference-targets?offset=1").json()["items"]
            == []
        )
