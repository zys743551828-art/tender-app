"""Real PG/nonowner/ASGI comparison of explicitly rerun synthetic-port reports."""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy

import pytest
from test_package_review_runs_api import TestPackageReviewRuns as RunCases
from test_package_review_runs_api import api, database, headers, requirements, uid, world

from apps.worker import engine
from packages.contracts.package_review_comparisons_api import valid
from packages.domain import bid_package_dependency_plans as plans
from packages.domain import bid_package_input_dependencies as dependencies
from packages.domain import bid_package_review_eligibility as eligibility
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires grouped isolated PG17 comparison checks",
)


def totals(case):
    return (
        case["w"]["database"]["owner"]
        .execute(
            """SELECT (SELECT count(*) FROM design.commands) AS commands,
        (SELECT count(*) FROM design.operations) AS operations,
        (SELECT count(*) FROM design.model_calls) AS calls,
        (SELECT count(*) FROM design.audit_entries) AS audits"""
        )
        .fetchone()
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageReviewComparisons:
    original_case = RunCases.original_case
    frozen_case = RunCases.frozen_case
    execution_case = RunCases.execution_case
    prepared_case = RunCases.prepared_case
    exact_inventory_proof_case = RunCases.exact_inventory_proof_case
    launch_case = RunCases.launch_case
    launch = RunCases.launch
    post = RunCases.post
    message = RunCases.message
    provider = RunCases.provider

    def rerun_case(self, case):
        """An actual new prepared input/plan with an explicit saved rerun nonce."""
        w, frozen = case["w"], case["frozen"]
        current = eligibility.inspect(case["scope"], frozen["manifest"]["id"], frozen["digest"])
        path = case["path"].rsplit("/", 2)[0]
        response = w["client"].post(
            path,
            headers=headers(w),
            json={
                "frozen_digest": frozen["digest"],
                "context_digest": current["current_context"]["semantic_digest"],
                "rerun": {"nonce": uid(), "reason": "明确进行第二轮合成核查以验收历史对比"},
            },
        )
        assert response.status_code == 201, response.text
        prepared = response.json()
        args = (case["scope"], frozen["manifest"]["id"], prepared["manifest"]["id"])
        declarations = case["plan"]["manifest"]["assessment"]["manifest"]["requirements"]
        selected = {
            "execution_input_digest": prepared["digest"],
            "purpose": "prebid_compliance",
            "fact_ids": [],
            "dependencies": [deepcopy(row["declaration"]) for row in declarations],
        }
        assessment = dependencies.check(*args, selected)
        saved, _ = plans.save(
            str(w["actor"]),
            *args,
            uid(),
            selected
            | {
                "assessment_digest": assessment["digest"],
                "reason": "采用显式复检的逐条依赖计划",
            },
        )
        plan = saved["body"]
        return case | {
            "args": args,
            "prepared": prepared,
            "plan": plan,
            "path": path + "/" + args[2] + "/review-runs",
            "headers": headers(w),
            "body": {
                "execution_input_digest": prepared["digest"],
                "dependency_plan_id": plan["manifest"]["id"],
                "dependency_plan_digest": plan["digest"],
            },
        }

    def finish(self, case):
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        engine.handle_lane("review", self.message(case, run))
        response = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["operation"]["state"] == "succeeded" and run["result"] is not None, run
        return run

    @pytest.fixture
    def pair_case(self, launch_case, monkeypatch):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        left = self.finish(case)
        other = self.rerun_case(case)
        right = self.finish(other)
        assert len(calls) == 2 and left["execution_digest"] != right["execution_digest"]
        return case | {
            "left": left,
            "right": right,
            "other": other,
            "calls": calls,
            "comparison_path": "/api/v1/bids/" + case["scope"][0] + "/package-review-comparisons",
        }

    def compare(self, case, **params):
        return case["w"]["client"].get(
            case["comparison_path"],
            params={
                "left_run_id": case["left"]["id"],
                "right_run_id": case["right"]["id"],
                **params,
            },
        )

    def test_explicit_rerun_comparison_is_paginated_and_honest_about_qualification(self, pair_case):
        case = pair_case
        before = totals(case)
        response = self.compare(case, limit=1)
        assert response.status_code == 200, response.text
        first = response.json()
        assert valid("PackageReviewComparisonPage", first)
        assert (
            first["left"]["id"] == case["left"]["id"]
            and first["right"]["id"] == case["right"]["id"]
        )
        assert first["input_changes"]["rerun_intent"] and first["input_changes"]["prepared_input"]
        assert not first["input_changes"]["method"] and not first["input_changes"]["requirements"]
        assert (
            first["counts"]["unchanged"] == case["left"]["result"]["manifest"]["requirement_count"]
        )
        items, page = list(first["items"]), first
        while page["has_more"]:
            response = self.compare(case, limit=1, cursor=page["next_cursor"])
            assert response.status_code == 200, response.text
            page = response.json()
            assert page["comparison_digest"] == first["comparison_digest"]
            items.extend(page["items"])
        assert len({item["requirement_id"] for item in items}) == first["counts"]["unchanged"]
        assert first["overall_coverage"] == "partial" and not any(
            first[key]
            for key in (
                "risk_resolution_assessed",
                "inventory_complete",
                "formal_scoring_eligible",
                "submission_eligible",
            )
        )
        assert "target_quotes" not in json.dumps(first) and "inspected_ranges" not in json.dumps(
            first
        )
        assert totals(case) == before and len(case["calls"]) == 2
        assert self.compare(case, limit=101).status_code == 422

    def test_human_opinion_stays_separate_and_invalidates_prior_cursor(self, pair_case):
        case = pair_case
        first = self.compare(case, limit=1).json()
        right = case["right"]
        row = right["result"]["manifest"]["matrix"][0]
        path = (
            case["other"]["path"]
            + "/"
            + right["id"]
            + "/requirements/"
            + row["requirement_id"]
            + "/human-decisions"
        )
        response = case["w"]["client"].post(
            path,
            headers=headers(case["w"]),
            json={
                "result_digest": right["result"]["digest"],
                "row_digest": digest(row),
                "expected_head": None,
                "state": "rejected",
                "reason": "不采用此项机器判断，仍需人工复查",
                "selected_quotes": [],
            },
        )
        assert response.status_code == 201, response.text
        after = self.compare(case, limit=100).json()
        changed = next(
            item for item in after["items"] if item["requirement_id"] == row["requirement_id"]
        )
        assert changed["right_human"]["state"] == "rejected"
        assert changed["right"]["verdict"] == row["verdict"] and after["counts"] == first["counts"]
        assert after["comparison_digest"] != first["comparison_digest"]
        if first["has_more"]:
            denied = self.compare(case, cursor=first["next_cursor"])
            assert denied.status_code == 422 and denied.json()["code"] == "INVALID_CURSOR"
        assert len(case["calls"]) == 2

    def test_closed_project_withdrawn_sources_and_missing_provider_do_not_rewrite_history(
        self, pair_case, monkeypatch
    ):
        case = pair_case
        first = self.compare(case).json()
        c = case["w"]["database"]["owner"]
        c.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        monkeypatch.setattr(
            storage, "client", lambda: pytest.fail("comparison must not read originals")
        )
        monkeypatch.setattr(
            DeepSeekClient,
            "from_env",
            classmethod(lambda cls: pytest.fail("comparison must not require provider")),
        )
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://unavailable.invalid/do-not-read")
        before = totals(case)
        response = self.compare(case)
        assert response.status_code == 200 and response.json() == first, response.text
        assert totals(case) == before and len(case["calls"]) == 2

    def test_same_foreign_missing_and_unfinished_runs_cannot_be_compared(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        left = self.finish(case)
        other = self.rerun_case(case)
        response = self.launch(other)
        assert response.status_code == 202, response.text
        pending = response.json()
        case = case | {
            "left": left,
            "right": pending,
            "comparison_path": "/api/v1/bids/" + case["scope"][0] + "/package-review-comparisons",
        }
        before = totals(case)
        denied = self.compare(case)
        assert (
            denied.status_code == 409
            and denied.json()["code"] == "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED"
        )
        assert self.compare(case, right_run_id=left["id"]).status_code == 422
        assert self.compare(case, right_run_id=uid()).status_code == 404
        foreign = case | {
            "comparison_path": "/api/v1/bids/" + uid() + "/package-review-comparisons"
        }
        assert self.compare(foreign).status_code == 404
        assert totals(case) == before and len(calls) == 1
