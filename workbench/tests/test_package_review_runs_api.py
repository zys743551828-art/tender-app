"""Real PG17/nonowner/ASGI/worker composition; originals and model HTTP are explicit synthetic ports."""
# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_bid_package_review_freezing_api import TestFreezing as FreezingCases
from test_bid_package_review_preview_api import api, database, headers, requirements, uid, world

from apps.worker import engine
from packages.contracts.package_review_runs_api import valid
from packages.domain import bid_package_dependency_plans as plans
from packages.domain import bid_package_input_dependencies as dependencies
from packages.domain import bid_package_review_eligibility as eligibility
from packages.domain import bid_package_review_runs as runs
from packages.domain import bid_package_scope_review as admission
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean, connection

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires isolated PG17 scope review checks",
)


def totals(c, bid):
    return c.execute(
        """SELECT (SELECT count(*) FROM design.bid_package_review_runs WHERE bid_id=%s) AS runs,
        (SELECT count(*) FROM design.operations WHERE bid_id=%s AND kind='package-scope-review') AS jobs,
        (SELECT count(*) FROM design.outbox x JOIN design.operations o ON o.id=x.operation_id
          WHERE o.bid_id=%s AND o.kind='package-scope-review') AS messages,
        (SELECT count(*) FROM design.commands WHERE command_kind='package-scope-review-start' AND actor_id=%s) AS commands""",
        (
            bid,
            bid,
            bid,
            c.execute("SELECT created_by FROM design.bids WHERE id=%s", (bid,)).fetchone()[
                "created_by"
            ],
        ),
    ).fetchone()


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageReviewRuns:
    original_case = FreezingCases.original_case
    frozen_case = FreezingCases.frozen_case
    execution_case = FreezingCases.execution_case
    prepared_case = FreezingCases.prepared_case
    exact_inventory_proof_case = FreezingCases.exact_inventory_proof_case
    post = FreezingCases.post

    @pytest.fixture
    def launch_case(self, exact_inventory_proof_case, monkeypatch):
        f, scope, frozen, prepared, _, _ = exact_inventory_proof_case
        w = f["w"]
        inv = w["client"].get(w["requirement_base"] + "/" + scope[3]).json()["manifest"]
        selected = {
            "execution_input_digest": prepared["digest"],
            "purpose": "prebid_compliance",
            "fact_ids": [],
            "dependencies": [
                {
                    "requirement_id": row["rule_id"],
                    "requirement_digest": row["requirement_digest"],
                    "state": "not_needed",
                    "fact_ids": [],
                    "evidence_ids": row["rule_snapshot"]["evidence_ids"],
                    "reason": "本合成要求只核对实际响应原文，不依赖外部事实",
                }
                for row in inv["requirements"]
            ],
        }
        args = (scope, frozen["manifest"]["id"], prepared["manifest"]["id"])
        assessment = dependencies.check(*args, selected)
        saved, _ = plans.save(
            str(w["actor"]),
            *args,
            uid(),
            selected
            | {
                "assessment_digest": assessment["digest"],
                "reason": "明确采用完整的合成逐条依赖计划",
            },
        )
        plan = saved["body"]
        path = (
            w["requirement_base"]
            + "/"
            + scope[3]
            + "/frozen-review-inputs/"
            + args[1]
            + "/execution-inputs/"
            + args[2]
            + "/review-runs"
        )
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        return {
            "w": w,
            "f": f,
            "scope": scope,
            "args": args,
            "frozen": frozen,
            "prepared": prepared,
            "plan": plan,
            "path": path,
            "headers": headers(w),
            "body": {
                "execution_input_digest": prepared["digest"],
                "dependency_plan_id": plan["manifest"]["id"],
                "dependency_plan_digest": plan["digest"],
            },
        }

    def launch(self, case, body=None, request_headers=None):
        return case["w"]["client"].post(
            case["path"],
            json=case["body"] if body is None else body,
            headers=case["headers"] if request_headers is None else request_headers,
        )

    def message(self, case, run):
        return clean(
            case["w"]["database"]["owner"]
            .execute(
                "SELECT payload FROM design.outbox WHERE operation_id=%s AND topic='tender.task.review.v1'",
                (run["operation"]["id"],),
            )
            .fetchone()["payload"]
        )

    def test_launch_records_one_atomic_job_ack_and_does_not_change_preparation(self, launch_case):
        case = launch_case
        c = case["w"]["database"]["owner"]
        response = self.launch(case)
        assert response.status_code == 202, response.text
        value = response.json()
        assert valid("PackageReviewRunView", value)
        assert value["operation"]["state"] == "queued" and value["result"] is None
        assert value["dependency_plan_id"] == case["plan"]["manifest"]["id"]
        assert totals(c, case["scope"][0]) == {"runs": 1, "jobs": 1, "messages": 1, "commands": 1}
        row = c.execute(
            "SELECT input_manifest,input_digest FROM design.bid_package_review_runs WHERE id=%s",
            (value["id"],),
        ).fetchone()
        assert digest(row["input_manifest"]) == row["input_digest"] == value["input_digest"]
        assert (
            row["input_manifest"]["execution_input"]["identity"]
            == case["prepared"]["manifest"]["identity"]
        )
        for table, old in (
            ("bid_package_execution_inputs", case["prepared"]),
            ("bid_package_review_inputs", case["frozen"]),
        ):
            assert (
                c.execute(
                    "SELECT manifest FROM design." + table + " WHERE id=%s",
                    (old["manifest"]["id"],),
                ).fetchone()["manifest"]
                == old["manifest"]
            )
        page = case["w"]["client"].get(case["path"]).json()
        assert valid("PackageReviewRunPage", page) and page["items"] == [value]

    def test_exact_ack_replay_survives_failure_source_withdrawal_and_unavailable_objects(
        self, launch_case, monkeypatch
    ):
        from packages.domain import storage

        case = launch_case
        first = self.launch(case)
        assert first.status_code == 202, first.text
        run = first.json()
        message = self.message(case, run)
        lease = engine.acquire(message)
        assert lease is not None
        engine.finish(message, lease, None, DomainError("SYNTHETIC_FAILURE", "合成失败"))
        c = case["w"]["database"]["owner"]
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        c.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        monkeypatch.setattr(
            storage, "client", lambda: pytest.fail("ACK replay must not call object store")
        )
        again = self.launch(case)
        assert again.status_code == 202 and again.json() == run
        assert again.headers["idempotent-replayed"] == "true"
        current = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert current.status_code == 200, current.text
        assert current.json()["operation"]["state"] == "failed"
        assert current.json()["operation"]["error_code"] == "SYNTHETIC_FAILURE"
        assert current.json()["result"] is None
        saved_input = case["w"]["client"].get(case["path"] + "/" + run["id"] + "/input")
        assert saved_input.status_code == 200, saved_input.text
        assert valid("PackageReviewRunInputView", saved_input.json())
        assert digest(saved_input.json()["manifest"]) == saved_input.json()["digest"]
        assert saved_input.json()["digest"] == run["input_digest"]

    def test_different_request_key_reuses_exact_existing_run_without_another_job(self, launch_case):
        case = launch_case
        first = self.launch(case)
        assert first.status_code == 202, first.text
        second = self.launch(case, request_headers=headers(case["w"]))
        assert second.status_code == 202 and second.json() == first.json(), second.text
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == {
            "runs": 1,
            "jobs": 1,
            "messages": 1,
            "commands": 2,
        }

    def equivalent_case(self, case, *, new_prepared=True, rerun=None):
        w, frozen = case["w"], case["frozen"]
        prepared = case["prepared"]
        path = case["path"].rsplit("/", 2)[0]
        if new_prepared:
            current = eligibility.inspect(case["scope"], frozen["manifest"]["id"], frozen["digest"])
            response = w["client"].post(
                path,
                headers=headers(w),
                json={
                    "frozen_digest": frozen["digest"],
                    "context_digest": current["current_context"]["semantic_digest"],
                    "rerun": rerun,
                },
            )
            assert response.status_code == 201, response.text
            prepared = response.json()
        args = (case["scope"], frozen["manifest"]["id"], prepared["manifest"]["id"])
        selected = {
            "execution_input_digest": prepared["digest"],
            "purpose": "prebid_compliance",
            "fact_ids": [],
            "dependencies": [
                deepcopy(row["declaration"])
                for row in case["plan"]["manifest"]["assessment"]["manifest"]["requirements"]
            ],
        }
        assessment = dependencies.check(*args, selected)
        saved, _ = plans.save(
            str(w["actor"]),
            *args,
            uid(),
            selected
            | {
                "assessment_digest": assessment["digest"],
                "reason": "重新保存语义相同的合成依赖计划，非新增付费意图",
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

    @pytest.mark.parametrize("new_prepared", [False, True])
    def test_equivalent_saved_ids_cannot_authorize_another_paid_run(
        self, launch_case, new_prepared
    ):
        case = launch_case
        first = self.launch(case)
        assert first.status_code == 202, first.text
        other = self.equivalent_case(case, new_prepared=new_prepared)
        before = totals(case["w"]["database"]["owner"], case["scope"][0])
        refused = self.launch(other)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "PACKAGE_REVIEW_ALREADY_EXISTS"
        original = refused.json()["details"]["existing_run"]
        assert valid("PackageReviewRunSummary", original)
        assert original["id"] == first.json()["id"]
        assert original["scope"] == first.json()["scope"]
        assert original["execution_input_id"] == case["prepared"]["manifest"]["id"]
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == before

    def test_explicit_saved_rerun_intent_creates_a_distinct_execution(self, launch_case):
        case = launch_case
        first = self.launch(case)
        assert first.status_code == 202, first.text
        rerun = {"nonce": uid(), "reason": "明确申请同输入第二轮核查，承担新的执行意图"}
        other = self.equivalent_case(case, rerun=rerun)
        second = self.launch(other)
        assert second.status_code == 202 and second.json()["id"] != first.json()["id"], second.text
        c = case["w"]["database"]["owner"]
        stored = c.execute(
            "SELECT execution_key,input_manifest FROM design.bid_package_review_runs WHERE bid_id=%s ORDER BY created_at,id",
            (case["scope"][0],),
        ).fetchall()
        assert len(stored) == 2 and stored[0]["execution_key"] != stored[1]["execution_key"]
        assert (
            stored[0]["input_manifest"]["model_input_digest"]
            == stored[1]["input_manifest"]["model_input_digest"]
        )
        assert stored[1]["input_manifest"]["execution_input"]["identity"]["rerun"] == rerun

    def test_competing_equivalent_preparations_accept_one_execution(self, launch_case, monkeypatch):
        case = launch_case
        other = self.equivalent_case(case)
        phase = Barrier(2)
        verify = admission.verify

        def synchronized_originals(observed):
            # Both read-only observations have ended before original IO, and
            # both original reads finish before competing for the write lock.
            # The shared fixture can therefore retain its global no-open-TX guard.
            phase.wait(timeout=30)
            result = verify(observed)
            phase.wait(timeout=30)
            return result

        monkeypatch.setattr(admission, "verify", synchronized_originals)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(self.launch, selected) for selected in (case, other)]
            results = [future.result(timeout=30) for future in pending]
        assert sorted(value.status_code for value in results) == [202, 409], [
            r.text for r in results
        ]
        assert (
            next(r for r in results if r.status_code == 409).json()["code"]
            == "PACKAGE_REVIEW_ALREADY_EXISTS"
        )
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == {
            "runs": 1,
            "jobs": 1,
            "messages": 1,
            "commands": 1,
        }

    def test_database_recomputes_semantic_execution_key(self, launch_case, monkeypatch):
        case = launch_case
        before = totals(case["w"]["database"]["owner"], case["scope"][0])
        monkeypatch.setattr(admission, "execution_key", lambda *args: "0" * 64)
        response = self.launch(case)
        assert response.status_code == 409, response.text
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == before

    @pytest.mark.parametrize(
        "change", ["prepared_digest", "plan_digest", "plan_id", "unknown_field"]
    )
    def test_invalid_selection_never_creates_a_command_job_or_dispatch(self, launch_case, change):
        case = launch_case
        body = dict(case["body"])
        body[
            {
                "prepared_digest": "execution_input_digest",
                "plan_digest": "dependency_plan_digest",
                "plan_id": "dependency_plan_id",
                "unknown_field": "launch_available",
            }[change]
        ] = uid() if change == "plan_id" else True if change == "unknown_field" else "a" * 64
        before = totals(case["w"]["database"]["owner"], case["scope"][0])
        response = self.launch(case, body)
        assert response.status_code in {404, 409, 422}, response.text
        assert totals(case["w"]["database"]["owner"], case["scope"][0]) == before

    def test_withdrawal_during_original_read_aborts_acceptance(self, launch_case):
        case = launch_case
        c = case["w"]["database"]["owner"]
        before = totals(c, case["scope"][0])
        case["f"]["state"]["during_read"] = lambda: c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        response = self.launch(case)
        assert response.status_code == 409, response.text
        assert totals(c, case["scope"][0]) == before

    def test_worker_without_provider_configuration_fails_honestly_with_no_model_reservation(
        self, launch_case
    ):
        case = launch_case
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        engine.handle_lane("review", self.message(case, run))
        current = case["w"]["client"].get(case["path"] + "/" + run["id"]).json()
        assert current["operation"]["state"] == "failed"
        assert current["operation"]["error_code"] == "MODEL_NOT_CONFIGURED"
        assert current["result"] is None
        assert (
            case["w"]["database"]["owner"]
            .execute(
                "SELECT count(*) AS n FROM design.model_calls WHERE operation_id=%s",
                (run["operation"]["id"],),
            )
            .fetchone()["n"]
            == 0
        )

    def provider(self, case, monkeypatch, during=None):
        calls = []
        c = case["w"]["database"]["owner"]

        def respond(request):
            # Real role sessions have no active transaction while the HTTP port runs.
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND usename IN('fusion_package_requirements_service','fusion_package_requirements_worker') AND xact_start IS NOT NULL"
                ).fetchone()["n"]
                == 0
            )
            batch = json.loads(json.loads(request.content)["messages"][-1]["content"])
            calls.append(batch)
            if during:
                during()
            data = {"scope_digest": batch["scope_digest"], "judgments": []}
            target = next(d for d in batch["documents"] if d["package_role"] == "target")
            for row in batch["requirements"]:
                authority = next(
                    d
                    for d in batch["documents"]
                    if d["package_role"] == "authority"
                    and any(b["id"] in row["rule"]["evidence_ids"] for b in d["blocks"])
                )
                authority_block = next(
                    b for b in authority["blocks"] if b["id"] in row["rule"]["evidence_ids"]
                )
                data["judgments"].append(
                    {
                        "requirement_id": row["requirement_id"],
                        "verdict": "satisfied",
                        "statement": "合成HTTP响应仅验证交付机制，待人工核对原文",
                        "target_quotes": [
                            {
                                "member_id": target["member_id"],
                                "evidence_id": target["blocks"][0]["id"],
                                "quote": target["blocks"][0]["text_content"],
                            }
                        ],
                        "authority_quotes": [
                            {
                                "member_id": authority["member_id"],
                                "evidence_id": authority_block["id"],
                                "quote": authority_block["text_content"],
                            }
                        ],
                        "used_fact_ids": [],
                    }
                )
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-package-review",
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": json.dumps(data)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                },
            )

        client = DeepSeekClient(
            api_key="explicit-synthetic-no-network", transport=httpx.MockTransport(respond)
        )
        monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: client))
        return calls

    def test_real_worker_publishes_bound_result_and_duplicate_delivery_has_no_second_call(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        message = self.message(case, run)
        engine.handle_lane("review", message)
        current = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert current.status_code == 200, current.text
        value = current.json()
        assert value["operation"]["state"] == "succeeded", value
        assert len(calls) == 1 and len(calls[0]["documents"]) == 2
        result = value["result"]
        assert digest(result["manifest"]) == result["digest"]
        assert result["manifest"]["overall_coverage"] == "partial"
        assert (
            result["manifest"]["formal_scoring_eligible"]
            is result["manifest"]["submission_eligible"]
            is False
        )
        assert (
            result["manifest"]["matrix"][0]["target_quotes"]
            and result["manifest"]["matrix"][0]["authority_quotes"]
        )
        engine.handle_lane("review", message)
        assert len(calls) == 1
        assert case["w"]["client"].get(case["path"] + "/" + run["id"]).json() == value
        page = case["w"]["client"].get(case["path"]).json()
        assert valid("PackageReviewRunPage", page)
        assert page["items"][0]["result"] == {
            "digest": result["digest"],
            "requirement_count": result["manifest"]["requirement_count"],
            "matrix_coverage": result["manifest"]["matrix_coverage"],
            "overall_coverage": "partial",
        }
        assert '"matrix":' not in json.dumps(page)

    def cancel(self, case, run):
        path = "/api/v1/operations/" + run["operation"]["id"]
        state = case["w"]["client"].get(path)
        assert state.status_code == 200, state.text
        request_headers = headers(case["w"]) | {"If-Match": state.headers["etag"]}
        body = {"reason": "合成取消用于验证迟到结果不会发布", "cancel_pending_same_input": False}
        response = case["w"]["client"].post(path + "/cancel", json=body, headers=request_headers)
        assert response.status_code == 200, response.text
        replay = case["w"]["client"].post(path + "/cancel", json=body, headers=request_headers)
        assert replay.status_code == 200 and replay.json() == response.json(), replay.text
        assert replay.headers["idempotent-replayed"] == "true"
        return response.json()

    def test_queued_cancel_replays_and_never_reserves_a_model_call(self, launch_case, monkeypatch):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        assert self.cancel(case, run)["state"] == "cancel_requested"
        engine.handle_lane("review", self.message(case, run))
        engine.reconcile(once=True)
        current = case["w"]["client"].get(case["path"] + "/" + run["id"]).json()
        assert current["operation"]["state"] == "cancelled" and current["result"] is None
        assert not calls
        assert (
            case["w"]["database"]["owner"]
            .execute(
                "SELECT count(*) AS n FROM design.model_calls WHERE operation_id=%s",
                (run["operation"]["id"],),
            )
            .fetchone()["n"]
            == 0
        )

    def test_cancel_during_model_response_preserves_receipt_but_never_publishes(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        calls = self.provider(case, monkeypatch, lambda: self.cancel(case, run))
        engine.handle_lane("review", self.message(case, run))
        current = case["w"]["client"].get(case["path"] + "/" + run["id"]).json()
        assert len(calls) == 1 and current["result"] is None
        assert current["operation"]["state"] in {"cancel_requested", "cancelled"}
        c = case["w"]["database"]["owner"]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.bid_package_review_results WHERE run_id=%s",
                (run["id"],),
            ).fetchone()["n"]
            == 0
        )
        receipt = c.execute(
            "SELECT state,response_ref,usage FROM design.model_calls WHERE operation_id=%s",
            (run["operation"]["id"],),
        ).fetchone()
        assert receipt["state"] == "succeeded" and receipt["response_ref"] is not None
        assert receipt["usage"]["actual"]["total_tokens"] == 120
        engine.reconcile(once=True)
        assert (
            case["w"]["client"].get(case["path"] + "/" + run["id"]).json()["operation"]["state"]
            == "cancelled"
        )
        engine.handle_lane("review", self.message(case, run))
        assert len(calls) == 1

    @pytest.mark.parametrize("part", ["package", "revision", "inventory", "frozen", "prepared"])
    def test_cross_scope_input_and_result_urls_cannot_read_the_run(self, launch_case, part):
        case = launch_case
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        selected = {
            "package": case["scope"][1],
            "revision": case["scope"][2],
            "inventory": case["scope"][3],
            "frozen": case["args"][1],
            "prepared": case["args"][2],
        }[part]
        other_path = case["path"].replace(selected, uid()) + "/" + run["id"]
        for suffix in ("", "/input"):
            denied = case["w"]["client"].get(other_path + suffix)
            assert denied.status_code == 404, denied.text

    def test_source_withdrawn_during_model_response_cannot_publish_old_result(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        c = case["w"]["database"]["owner"]
        calls = self.provider(
            case,
            monkeypatch,
            lambda: c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (case["w"]["sources"][0],),
            ),
        )
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        engine.handle_lane("review", self.message(case, run))
        current = case["w"]["client"].get(case["path"] + "/" + run["id"]).json()
        assert len(calls) == 1
        assert current["operation"]["state"] == "failed" and current["result"] is None
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.bid_package_review_results WHERE run_id=%s",
                (run["id"],),
            ).fetchone()["n"]
            == 0
        )

    def test_worker_cannot_change_runs_or_read_unrelated_commands_and_api_cannot_publish(
        self, launch_case
    ):
        with connection(True) as c:
            assert not c.execute(
                "SELECT has_table_privilege(current_user,'design.commands','SELECT') AS allowed"
            ).fetchone()["allowed"]
            assert c.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_dependency_plan_command_receipts','SELECT') AS allowed"
            ).fetchone()["allowed"]
            assert not c.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_review_runs','INSERT') AS allowed"
            ).fetchone()["allowed"]
        with connection() as c:
            assert not c.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_review_results','INSERT') AS allowed"
            ).fetchone()["allowed"]
