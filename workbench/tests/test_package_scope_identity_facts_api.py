"""Real selected-fact declarations bind the SQL/Python execution key across re-saves.

Uses the existing actual PG17/nonowner/ASGI provenance and exact inventory fixtures.
No provider is called; runs stay queued so this tests identity and admission only.
"""
# ruff: noqa: F401,F811

import os
from copy import deepcopy

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_bid_package_review_freezing_api import TestFreezing as FreezingCases
from test_package_review_runs_api import TestPackageReviewRuns as RunCases
from test_package_review_runs_api import api, database, headers, requirements, totals, uid, world

from packages.domain import bid_package_dependency_plans as plans
from packages.domain import bid_package_input_dependencies as dependencies
from packages.domain import bid_package_review_eligibility as eligibility
from packages.domain import bid_package_scope_review as admission
from packages.domain import package_scope_review_identity as identity
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest
from packages.domain.runtime import connection

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires grouped isolated PG17 selected-fact execution identity checks",
)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageScopeIdentityFacts:
    original_case = FreezingCases.original_case
    frozen_case = FreezingCases.frozen_case
    provenance_case = FreezingCases.provenance_case
    exact_inventory_proof_case = FreezingCases.exact_inventory_proof_case
    post = FreezingCases.post
    launch = RunCases.launch

    @pytest.fixture
    def prepared_case(self, provenance_case):
        # Seed the real confirmed fact before taking the newer exact inventory
        # root, so a later fact change is not mistaken for equivalent input.
        return provenance_case[:4]

    def select(self, case, prepared):
        w, scope, frozen, fact = (case[key] for key in ("w", "scope", "frozen", "fact"))
        args = (scope, frozen["manifest"]["id"], prepared["manifest"]["id"])
        base = (
            w["requirement_base"]
            + "/"
            + scope[3]
            + "/frozen-review-inputs/"
            + args[1]
            + "/execution-inputs/"
            + args[2]
        )
        body = {
            "execution_input_digest": prepared["digest"],
            "fact_id": fact,
            "action": "bind",
            "subject": {"kind": "lot", "id": str(w["scope"].lot_id)},
            "reason": "明确同一事实及原证据用于本标段的已声明核查范围",
            "previous_digest": None,
        }
        response = w["client"].post(
            base + "/fact-scope-declarations", json=body, headers=headers(w)
        )
        assert response.status_code == 201, response.text
        declaration = response.json()
        inventory = w["client"].get(w["requirement_base"] + "/" + scope[3]).json()["manifest"]
        selected = {
            "execution_input_digest": prepared["digest"],
            "purpose": "prebid_compliance",
            "fact_ids": [fact],
            "dependencies": [
                {
                    "requirement_id": row["rule_id"],
                    "requirement_digest": row["requirement_digest"],
                    "state": "required",
                    "fact_ids": [fact],
                    "evidence_ids": row["rule_snapshot"]["evidence_ids"],
                    "reason": "逐项明确使用已确认并绑定本范围的事实",
                }
                for row in inventory["requirements"]
            ],
        }
        assessed = dependencies.check(*args, selected)
        stored, _ = plans.save(
            str(w["actor"]),
            *args,
            uid(),
            selected
            | {
                "assessment_digest": assessed["digest"],
                "reason": "采用本次完整的已选事实依赖计划",
            },
        )
        plan = stored["body"]
        return case | {
            "args": args,
            "prepared": prepared,
            "declaration": declaration,
            "scope_body": body,
            "scope_path": base + "/fact-scope-declarations",
            "plan": plan,
            "path": base + "/review-runs",
            "headers": headers(w),
            "body": {
                "execution_input_digest": prepared["digest"],
                "dependency_plan_id": plan["manifest"]["id"],
                "dependency_plan_digest": plan["digest"],
            },
        }

    @pytest.fixture
    def selected_case(self, exact_inventory_proof_case, provenance_case, monkeypatch):
        f, scope, frozen, prepared, _, _ = exact_inventory_proof_case
        monkeypatch.setattr(
            DeepSeekClient,
            "from_env",
            classmethod(lambda cls: pytest.fail("identity test must not create a model client")),
        )
        case = {"w": f["w"], "f": f, "scope": scope, "frozen": frozen, "fact": provenance_case[4]}
        return self.select(case, prepared)

    def verified_key(self, case):
        token = admission.verify(admission.observe(*case["args"], case["body"]))
        with connection() as c:
            manifest = admission.recheck(c, token)
            actual = admission.execution_key(token, manifest)
            pure = identity.identify(manifest, [case["declaration"]])
            sql_key = c.execute(
                "SELECT design.bid_scope_review_execution_key(%s) AS value", (Jsonb(manifest),)
            ).fetchone()["value"]
        assert actual == pure["digest"] == sql_key
        return manifest, pure

    def test_real_fact_declarations_rebind_navigation_without_new_execution_and_withdrawal_still_denies(
        self, selected_case
    ):
        case = selected_case
        m1, key1 = self.verified_key(case)
        binding = key1["manifest"]["fact_scope_bindings"][0]["binding"]
        original_binding = case["declaration"]["manifest"]["binding"]
        assert binding["fact_item_digest"] == original_binding["fact_item_digest"]
        assert binding["proof_digest"] == original_binding["proof_digest"]
        assert "execution_input_id" not in binding and "execution_input_digest" not in binding
        response = self.launch(case)
        assert response.status_code == 202, response.text
        first = response.json()
        stored = (
            case["w"]["database"]["owner"]
            .execute(
                "SELECT execution_key FROM design.bid_package_review_runs WHERE id=%s",
                (first["id"],),
            )
            .fetchone()
        )
        assert stored["execution_key"] == key1["digest"]
        current = eligibility.inspect(case["scope"], case["args"][1], case["frozen"]["digest"])
        prepare_path = case["path"].rsplit("/", 2)[0]
        response = case["w"]["client"].post(
            prepare_path,
            headers=headers(case["w"]),
            json={
                "frozen_digest": case["frozen"]["digest"],
                "context_digest": current["current_context"]["semantic_digest"],
                "rerun": None,
            },
        )
        assert response.status_code == 201, response.text
        other = self.select(case, response.json())
        m2, key2 = self.verified_key(other)
        assert m1["model_input_digest"] == m2["model_input_digest"]
        assert digest(m1) != digest(m2) and key1 == key2
        assert case["declaration"]["manifest"]["id"] != other["declaration"]["manifest"]["id"]
        before = totals(case["w"]["database"]["owner"], case["scope"][0])
        denied = self.launch(other)
        assert (
            denied.status_code == 409 and denied.json()["code"] == "PACKAGE_REVIEW_ALREADY_EXISTS"
        ), denied.text
        assert denied.json()["details"]["existing_run"]["id"] == first["id"]
        assert (
            denied.json()["details"]["existing_run"]["execution_input_id"]
            == case["prepared"]["manifest"]["id"]
        )
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == before

        # SQL independently rejects a genuine declaration from the other prepared
        # input, even when its projected semantics would otherwise be equivalent.
        crossed = deepcopy(m1)
        crossed["fact_admission"]["fact_declarations"] = deepcopy(
            m2["fact_admission"]["fact_declarations"]
        )
        with pytest.raises(psycopg.errors.CheckViolation), connection() as c:
            c.execute("SELECT design.bid_scope_review_execution_key(%s)", (Jsonb(crossed),))

        withdrawal = other["scope_body"] | {
            "action": "withdraw",
            "subject": None,
            "previous_digest": other["declaration"]["digest"],
            "reason": "明确撤回本准备输入中的事实用途",
        }
        withdrawn = case["w"]["client"].post(
            other["scope_path"], json=withdrawal, headers=headers(case["w"])
        )
        assert withdrawn.status_code == 201, withdrawn.text
        refused = self.launch(other, request_headers=headers(case["w"]))
        assert (
            refused.status_code == 409
            and refused.json()["code"] == "PACKAGE_SELECTED_FACTS_UNPROVEN"
        ), refused.text
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == before
