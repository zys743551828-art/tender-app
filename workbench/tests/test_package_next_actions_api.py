"""Exact-run recommendations over real nonowner PG; setup provider responses are synthetic."""
# ruff: noqa: F401,F811

import os
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_bid_package_requirements_api import prepare_requirements
from test_work_contexts_pg import (
    TestExactRunContexts as _Contexts,
)
from test_work_contexts_pg import (
    api,
    database,
    forbid_io,
    headers,
    totals,
    uid,
    world,
)

from packages.contracts import package_next_actions as contract
from packages.work_contexts import repository, service

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="grouped isolated PostgreSQL required",
)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestSelectedNextActions:
    @pytest.fixture
    def requirements(self, world):
        return prepare_requirements(
            world,
            native_rule_scope={
                "bid_id": world["scope"].bid_id,
                "description": "合成完整关键规则范围",
            },
        )

    original_case = _Contexts.original_case
    frozen_case = _Contexts.frozen_case
    execution_case = _Contexts.execution_case
    prepared_case = _Contexts.prepared_case
    exact_inventory_proof_case = _Contexts.exact_inventory_proof_case
    launch_case = _Contexts.launch_case
    post = _Contexts.post
    launch = _Contexts.launch
    message = _Contexts.message
    provider = _Contexts.provider
    equivalent_case = _Contexts.equivalent_case
    finish = _Contexts.finish
    completed = _Contexts.completed

    def read(self, case, **changes):
        return case["w"]["client"].get(
            f"/api/v1/bids/{case['scope'][0]}/package-next-actions/{case['run']['id']}",
            params={"expected_input_digest": case["run"]["input_digest"]} | changes,
        )

    def test_selected_run_read_is_nonowner_readonly_and_has_no_business_or_external_effects(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        forbid_io(monkeypatch)
        before, calls = totals(w["database"]["owner"]), len(case["calls"])
        response = self.read(case)
        assert response.status_code == 200, response.text
        value = response.json()
        contract.validate(value)
        assert value["binding"]["run_id"] == case["run"]["id"]
        assert value["binding"]["result_digest"] == case["run"]["result"]["digest"]
        assert value["basis_status"] == "matched", value
        assert value["current_scope_counts"] is not None
        assert value["action_mode"] == "navigation_only" and not value["submission_eligible"]
        assert totals(w["database"]["owner"]) == before and len(case["calls"]) == calls

    def test_newer_run_is_never_substituted_for_the_explicit_older_run(
        self, completed, monkeypatch
    ):
        case = completed
        other = self.equivalent_case(
            case, rerun={"nonce": uid(), "reason": "另一轮合成核查用于反替换"}
        )
        later = self.finish(other)
        forbid_io(monkeypatch)
        response = self.read(case)
        assert response.status_code == 200, response.text
        assert response.json()["binding"]["run_id"] == case["run"]["id"] != later["id"]

    def test_snapshot_holds_old_source_and_following_read_hides_current_counts(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        original, changed = repository.exact_run, []

        def withdraw_after_resolution(c, bid, run):
            value = original(c, bid, run)
            if not changed:
                w["database"]["owner"].execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (w["sources"][0],),
                )
                changed.append(True)
            return value

        monkeypatch.setattr(repository, "exact_run", withdraw_after_resolution)
        forbid_io(monkeypatch)
        first, second = self.read(case), self.read(case)
        assert first.status_code == second.status_code == 200, (first.text, second.text)
        assert first.json()["basis_status"] == "matched"
        value = second.json()
        assert value["basis_status"] == "changed" and value["primary"]["level"] == 1
        assert value["current_scope_counts"] is value["remaining_critical_count"] is None
        assert value["historical_scope_counts"] is not None

    def test_live_rule_confirmation_updates_counts_without_rewriting_the_run(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        original = self.read(case)
        assert original.status_code == 200, original.text
        before = original.json()
        rid = next(
            row["requirement_id"]
            for row in case["run"]["result"]["manifest"]["matrix"]
            if row["rule_kind"] in {"mandatory", "disqualification"}
        )
        rule = w["client"].get("/api/v1/rules/" + rid)
        assert rule.status_code == 200, rule.text
        chosen = "deferred" if rule.json()["confirmation"] == "confirmed" else "confirmed"
        response = w["client"].post(
            "/api/v1/rules/" + rid + "/decisions",
            json={
                "decision": chosen,
                "reason": "合成验收明确改变当前规则确认，原运行保持不变",
                "evidence_ids": [],
            },
            headers=headers(w, etag=rule.headers["etag"]),
        )
        assert response.status_code == 200, response.text
        forbid_io(monkeypatch)
        after = self.read(case)
        assert after.status_code == 200, after.text
        value = after.json()
        assert value["basis_status"] == "matched"
        assert (
            value["current_scope_counts"]["pending_critical_rules"]
            != before["current_scope_counts"]["pending_critical_rules"]
        )
        assert value["confirmation_digest"] != before["confirmation_digest"]
        assert value["binding"] == before["binding"]

    def test_auth_expected_digest_and_owner_or_worker_role_cannot_bypass_the_read_port(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        assert self.read(case, expected_input_digest="f" * 64).status_code == 412
        path = f"/api/v1/bids/{case['scope'][0]}/package-next-actions/{case['run']['id']}"
        with TestClient(w["app"]) as anonymous:
            assert (
                anonymous.get(
                    path, params={"expected_input_digest": case["run"]["input_digest"]}
                ).status_code
                == 401
            )
        for login in ("owner", "worker"):

            @contextmanager
            def different_connection(selected_login=login):
                dsn = (
                    w["database"]["worker_dsn"]
                    if selected_login == "worker"
                    else make_conninfo(
                        os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"],
                        dbname=w["database"]["owner"].info.dbname,
                    )
                )
                with psycopg.connect(dsn, row_factory=dict_row) as c:
                    c.execute("SET LOCAL search_path=design,public")
                    yield c

            with monkeypatch.context() as patch:
                patch.setattr(service, "connection", different_connection)
                rejected = self.read(case)
                assert (
                    rejected.status_code == 403
                    and rejected.json()["code"] == "WORK_CONTEXT_ROLE_REJECTED"
                )
