"""Actual PG17/nonowner/HTTP with explicit synthetic originals/model responses.

The new router is mounted only in a test app. No production main, exported
OpenAPI, user preference, business head, model route or original is changed.
"""
# ruff: noqa: F401,F811

import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
import uvicorn
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_authoring_package_adoptions_pg import adopt, build, env
from test_bid_package_api import attach
from test_bid_package_submissions_pg import (
    api,
    catalog,
    database,
    exact,
    headers,
    inventory,
    register,
    requirements,
    uid,
    world,
)
from test_bid_package_submissions_pg import request as submission_request
from test_package_outcomes_pg import setup as official_result
from test_package_review_runs_api import TestPackageReviewRuns as _RunCases
from work_context_fixtures import context_app, openapi

from apps.worker import engine
from deploy.work_context_readiness import verify
from packages.contracts import work_context_api as contract
from packages.domain import bid_package_service, package_scope_review, storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean, connection, secret_hash, sha
from packages.work_contexts import observations, permissions, relations, repository, service

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner work-context PostgreSQL 17 required",
)


def totals(owner):
    return owner.execute(
        """SELECT (SELECT count(*) FROM design.commands) AS commands,
        (SELECT count(*) FROM design.operations) AS operations,
        (SELECT count(*) FROM design.model_calls) AS model_calls,
        (SELECT count(*) FROM design.audit_entries) AS audits,
        (SELECT count(*) FROM design.bid_package_revisions) AS package_revisions,
        (SELECT count(*) FROM design.bid_package_heads) AS package_heads,
        (SELECT count(*) FROM design.bid_package_requirement_heads) AS inventory_heads,
        (SELECT count(*) FROM design.bid_package_fact_scopes) AS fact_scopes,
        (SELECT count(*) FROM design.submission_records) AS submissions,
        (SELECT count(*) FROM design.submission_heads) AS submission_heads,
        (SELECT count(*) FROM retrieval.source_heads) AS source_heads,
        (SELECT count(*) FROM retrieval.lineage_edges) AS lineage"""
    ).fetchone()


@contextmanager
def client_for(w):
    with TestClient(context_app()) as client:
        client.cookies.update(w["client"].cookies)
        yield client


def run_url(bid, identity):
    return f"/api/v1/bids/{bid}/work-contexts/package_review_run/{identity}"


def submission_url(bid, identity):
    return f"/api/v1/bids/{bid}/work-contexts/package_submission/{identity}"


def relation_url(env, build_id):
    return f"/api/v1/bids/{env['bid']}/work-contexts/build/{build_id}/relations"


def forbid_io(monkeypatch):
    monkeypatch.setattr(
        storage, "client", lambda: pytest.fail("read context must not access original storage")
    )
    monkeypatch.setattr(
        storage, "get", lambda *_: pytest.fail("read context must not read original bytes")
    )
    monkeypatch.setattr(
        DeepSeekClient,
        "from_env",
        classmethod(lambda cls: pytest.fail("read context must not call a model")),
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestExactRunContexts:
    original_case = _RunCases.original_case
    frozen_case = _RunCases.frozen_case
    execution_case = _RunCases.execution_case
    prepared_case = _RunCases.prepared_case
    exact_inventory_proof_case = _RunCases.exact_inventory_proof_case
    launch_case = _RunCases.launch_case
    post = _RunCases.post
    launch = _RunCases.launch
    message = _RunCases.message
    provider = _RunCases.provider
    equivalent_case = _RunCases.equivalent_case

    def finish(self, case):
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        engine.handle_lane("review", self.message(case, run))
        response = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert (
            response.status_code == 200 and response.json()["operation"]["state"] == "succeeded"
        ), response.text
        return response.json()

    @pytest.fixture
    def completed(self, launch_case, monkeypatch):
        calls = self.provider(launch_case, monkeypatch)
        return launch_case | {"run": self.finish(launch_case), "calls": calls}

    def test_exact_older_run_nonowner_rr_ro_and_no_business_or_external_effects(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        second_case = self.equivalent_case(
            case, rerun={"nonce": uid(), "reason": "明确产生另一次合成核查"}
        )
        later = self.finish(second_case)
        forbid_io(monkeypatch)
        checked, original_require = [], permissions.require

        def checked_read(c, kind):
            result = original_require(c, kind)
            checked.append(result)
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), c.transaction():
                c.execute("UPDATE design.bids SET title=title WHERE id=%s", (w["scope"].bid_id,))
            return result

        monkeypatch.setattr(permissions, "require", checked_read)
        before = totals(w["database"]["owner"])
        with client_for(w) as client:
            result = client.get(run_url(case["scope"][0], case["run"]["id"]))
            assert result.status_code == 200, result.text
            value = result.json()
            assert contract.valid("PackageWorkContext", value)
            assert value["selection"]["run_id"] == case["run"]["id"] != later["id"]
            assert value["selection"]["execution_input_id"] == case["prepared"]["manifest"]["id"]
            assert value["summary"]["review"]["requirement_count"] == len(
                case["run"]["result"]["manifest"]["matrix"]
            )
            assert value["summary"]["review"]["overall_coverage"] == "partial"
            assert value["summary"]["whole_package_blocking_risk_count"] is None
            assert value["summary"]["formal_scoring"]["numeric_prediction"] is None
            assert value["current_observation"]["review_run_head"]["status"] == "not_applicable"
            assert result.headers["cache-control"] == "private, no-store"
            same = client.get(
                run_url(case["scope"][0], case["run"]["id"]),
                params={"expected_selection_digest": value["selection_digest"]},
            )
            assert (
                same.status_code == 200
                and same.json()["observation_digest"] == value["observation_digest"]
            )
        assert checked and all(
            row["role"]["isolation"] == "repeatable read" and row["role"]["read_only"] == "on"
            for row in checked
        )
        assert totals(w["database"]["owner"]) == before and len(case["calls"]) == 2

    def test_real_http_auth_scope_parameters_expected_digest_and_wrong_database_roles(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        path = run_url(case["scope"][0], case["run"]["id"])
        with TestClient(context_app()) as unauth:
            assert unauth.get(path).status_code == 401
        with client_for(w) as client:
            assert client.get(run_url(uid(), case["run"]["id"])).status_code == 404
            assert client.get(run_url(case["scope"][0], uid())).status_code == 404
            assert (
                client.get(path, params={"expected_selection_digest": "0" * 64}).status_code == 412
            )
            assert client.get(path + "?latest=true").status_code == 422
            assert (
                client.get(
                    path
                    + "?expected_selection_digest="
                    + "0" * 64
                    + "&expected_selection_digest="
                    + "1" * 64
                ).status_code
                == 422
            )
            assert client.post(path, json={}).status_code == 405
            real = service.connection

            @contextmanager
            def worker_connection():
                with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as c:
                    c.execute("SET LOCAL search_path=design,public")
                    yield c

            with monkeypatch.context() as patch:
                patch.setattr(service, "connection", worker_connection)
                rejected = client.get(path)
                assert (
                    rejected.status_code == 403
                    and rejected.json()["code"] == "WORK_CONTEXT_ROLE_REJECTED"
                ), rejected.text
            with monkeypatch.context() as patch:

                @contextmanager
                def owner_connection():
                    with psycopg.connect(
                        make_conninfo(
                            os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"],
                            dbname=w["database"]["owner"].info.dbname,
                        ),
                        row_factory=dict_row,
                    ) as c:
                        yield c

                patch.setattr(service, "connection", owner_connection)
                assert client.get(path).status_code == 403
            assert service.connection is real
            owner = w["database"]["owner"]
            owner.execute(
                "REVOKE SELECT ON design.bid_package_review_decision_heads FROM tender_api"
            )
            try:
                response = client.get(path)
                assert (
                    response.status_code == 503
                    and response.json()["code"] == "WORK_CONTEXT_UNAVAILABLE"
                ), response.text
            finally:
                owner.execute(
                    "GRANT SELECT ON design.bid_package_review_decision_heads TO tender_api"
                )
            owner.execute(
                "UPDATE design.sessions SET revoked_at=clock_timestamp() WHERE member_id=%s",
                (w["actor"],),
            )
            assert client.get(path).status_code == 401

    def test_one_snapshot_keeps_pre_change_observation_and_next_read_marks_source_change(
        self, completed, monkeypatch
    ):
        case, w = completed, completed["w"]
        original, changed = repository.exact_run, []

        def change_after_resolution(c, bid, run):
            value = original(c, bid, run)
            if not changed:
                w["database"]["owner"].execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (w["sources"][0],),
                )
                changed.append(True)
            return value

        monkeypatch.setattr(repository, "exact_run", change_after_resolution)
        forbid_io(monkeypatch)
        with client_for(w) as client:
            path = run_url(case["scope"][0], case["run"]["id"])
            first, second = client.get(path), client.get(path)
            assert first.status_code == second.status_code == 200, (first.text, second.text)
            assert first.json()["current_observation"]["sources"]["status"] == "matched"
            assert second.json()["current_observation"]["sources"]["status"] == "changed"
            assert first.json()["selection"] == second.json()["selection"]
            assert first.json()["observation_digest"] != second.json()["observation_digest"]
            assert second.json()["summary"]["primary_action"] == "inspect_changed_basis"

    def test_human_opinion_package_head_and_method_changes_remain_separate_from_machine(
        self, completed, monkeypatch
    ):
        case, w, run = completed, completed["w"], completed["run"]
        path = run_url(case["scope"][0], run["id"])
        with client_for(w) as client:
            first = client.get(path)
            assert first.status_code == 200, first.text
            row = run["result"]["manifest"]["matrix"][0]
            human_path = (
                case["path"]
                + "/"
                + run["id"]
                + "/requirements/"
                + row["requirement_id"]
                + "/human-decisions"
            )
            saved = w["client"].post(
                human_path,
                json={
                    "result_digest": run["result"]["digest"],
                    "row_digest": digest(row),
                    "expected_head": None,
                    "state": "confirmed",
                    "reason": "本合成测试仅核对这条意见的原报告绑定",
                    "selected_quotes": [],
                },
                headers=headers(w),
            )
            assert saved.status_code == 201, saved.text
            head_path = w["base"] + "/" + case["scope"][1]
            head = w["client"].get(head_path)
            appended = w["client"].post(
                head_path + "/revisions",
                json={"members": [w["item"]]},
                headers=headers(w) | {"If-Match": head.headers["etag"]},
            )
            assert appended.status_code == 201, appended.text
            profile = package_scope_review.method_profile()
            monkeypatch.setattr(
                package_scope_review,
                "method_profile",
                lambda: {**profile, "source_digest": "0" * 64},
            )
            second = client.get(path)
            assert second.status_code == 200, second.text
            a, b = first.json(), second.json()
            assert a["selection"] == b["selection"]
            assert b["current_observation"]["package_head"]["status"] == "changed"
            assert b["current_observation"]["executor_method"]["status"] == "changed"
            assert b["summary"]["review"]["human_counts"]["confirmed"] == 1
            assert (
                a["summary"]["review"]["machine_counts"] == b["summary"]["review"]["machine_counts"]
            )
            assert not b["summary"]["review"]["risk_resolution_assessed"]

    @pytest.mark.parametrize("change", ["counts", "duplicate", "wrong_definition"])
    def test_resealed_stored_result_rejected_by_actual_http(self, completed, change):
        case, w = completed, completed["w"]
        run, owner = case["run"], w["database"]["owner"]
        altered = deepcopy(run["result"]["manifest"])
        if change == "counts":
            altered["counts"]["satisfied"] = 0
        elif change == "duplicate":
            altered["matrix"].append(deepcopy(altered["matrix"][0]))
            altered["requirement_count"] += 1
            altered["counts"]["satisfied"] += 1
        else:
            altered["matrix"][0]["rule_digest"] = "0" * 64
        # Explicit corruption injection in the disposable owner fixture only.
        owner.execute(
            "ALTER TABLE design.bid_package_review_results DISABLE TRIGGER immutable_guard"
        )
        try:
            owner.execute(
                "UPDATE design.bid_package_review_results SET manifest=%s,digest=%s WHERE run_id=%s",
                (Jsonb(altered), digest(altered), run["id"]),
            )
            with client_for(w) as client:
                response = client.get(run_url(case["scope"][0], run["id"]))
                assert response.status_code == 500, response.text
        finally:
            owner.execute(
                "UPDATE design.bid_package_review_results SET manifest=%s,digest=%s WHERE run_id=%s",
                (Jsonb(run["result"]["manifest"]), run["result"]["digest"], run["id"]),
            )
            owner.execute(
                "ALTER TABLE design.bid_package_review_results ENABLE TRIGGER immutable_guard"
            )

    def bind_submission(self, case, run):
        w = case["w"]
        inv = w["client"].get(w["requirement_base"] + "/" + case["scope"][3]).json()
        selected = {
            "package_id": case["scope"][1],
            "revision_id": case["scope"][2],
            "package_digest": w["own"]["digest"],
            "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]},
            "coverage": None,
            "review_run": {
                "id": run["id"],
                "input_digest": run["input_digest"],
                "result_digest": run["result"]["digest"] if run["result"] else None,
            },
        }
        declared = w | {
            "submission_scope": case["scope"][:3],
            "selection": selected,
            "attachment": {
                "document_version_id": w["member"].document_version_id,
                "digest": w["member"].file_digest,
                "byte_size": len(b"synthetic-original-v1"),
            },
        }
        preview, body = submission_request(declared)
        saved, _ = register(declared, body, preview["bid_etag"])
        return saved["body"]["submission"]

    def test_submission_preserves_missing_bound_result_when_late_worker_is_refused(
        self, launch_case, monkeypatch
    ):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        started = self.launch(case)
        assert started.status_code == 202, started.text
        pending = started.json()
        saved = self.bind_submission(case, pending)
        with client_for(case["w"]) as client:
            path = submission_url(case["scope"][0], saved["id"])
            before = client.get(path)
            assert before.status_code == 200, before.text
            assert before.json()["selection"]["review_run"]["run_id"] == pending["id"]
            assert before.json()["summary"]["review_status"] == "bound_result_missing"
            engine.handle_lane("review", self.message(case, pending))
            native = case["w"]["client"].get(case["path"] + "/" + pending["id"])
            assert native.status_code == 200, native.text
            assert native.json()["operation"]["state"] == "failed", native.text
            assert native.json()["operation"]["error_code"] == "PACKAGE_REVIEW_INPUT_CHANGED"
            after = client.get(path)
            assert after.status_code == 200, after.text
            assert after.json()["selection"] == before.json()["selection"]
            assert after.json()["summary"]["review"] is None
            assert after.json()["native_targets"]["package_review_run"]["result_digest"] is None
            assert after.json()["current_observation"]["bound_run_state"]["status"] == "changed"
            explicit = client.get(run_url(case["scope"][0], pending["id"]))
            assert explicit.status_code == 200, explicit.text
            assert explicit.json()["summary"]["review"] is None
            assert explicit.json()["state"]["operation_state"] == "failed"
        # Registration changes the lifecycle/revision. The native worker refuses
        # the stale prepared input before model IO; this test preserves that rule.
        assert len(calls) == 0

    def test_submission_uses_completed_bound_run_even_with_another_completed_run(
        self, completed, monkeypatch
    ):
        case = completed
        other = self.finish(
            self.equivalent_case(case, rerun={"nonce": uid(), "reason": "另一次独立核查"})
        )
        submission = self.bind_submission(case, case["run"])
        forbid_io(monkeypatch)
        with client_for(case["w"]) as client:
            response = client.get(submission_url(case["scope"][0], submission["id"]))
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["selection"]["review_run"]["run_id"] == case["run"]["id"] != other["id"]
            assert value["summary"]["review"]["result_digest"] == case["run"]["result"]["digest"]
            assert value["current_observation"]["bound_run_state"]["status"] == "matched"
            assert other["id"] not in json.dumps(value)

    def test_actual_loopback_http_uses_cookie_and_native_nonowner_resolution(self, completed):
        case, w = completed, completed["w"]
        channel = socket.socket()
        channel.bind(("127.0.0.1", 0))
        channel.listen(16)
        port = channel.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(context_app(), log_level="critical", access_log=False, lifespan="off")
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [channel]}, daemon=True)
        worker.start()
        deadline = time.monotonic() + 10
        try:
            while not server.started and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            url = f"http://127.0.0.1:{port}" + run_url(case["scope"][0], case["run"]["id"])
            with httpx.Client(trust_env=False, timeout=15) as client:
                assert client.get(url).status_code == 401
                response = client.get(
                    url, headers={"Cookie": "session=" + w["client"].cookies.get("session")}
                )
                assert (
                    response.status_code == 200
                    and response.json()["selection"]["run_id"] == case["run"]["id"]
                ), response.text
                assert response.headers["cache-control"] == "private, no-store"
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            channel.close()
            assert not worker.is_alive()


def test_no_run_submission_official_results_cannot_feed_prebid_or_fabricate_risk(
    exact, monkeypatch
):
    w = official_result(exact)
    owner = w["database"]["owner"]
    assert w["result"]["value"] == "0"
    names = [
        row["name"]
        for row in owner.execute(
            """SELECT n.nspname||'.'||c.relname AS name FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='design' AND c.relname IN ('outcomes','outcome_heads','business_results','business_result_heads','package_outcome_verifications') ORDER BY c.relname"""
        ).fetchall()
    ]
    for name in names:
        owner.execute(
            sql.SQL("REVOKE SELECT ON {} FROM tender_api").format(sql.Identifier(*name.split(".")))
        )
    forbid_io(monkeypatch)
    before = totals(owner)
    try:
        with client_for(w) as client:
            response = client.get(submission_url(w["scope"].bid_id, w["submission"]["id"]))
            assert response.status_code == 200, response.text
            value = response.json()
            assert value["selection"]["review_run"] is None and value["summary"]["review"] is None
            assert value["summary"]["review_status"] == "not_selected"
            assert value["summary"]["formal_scoring"]["numeric_prediction"] is None
            assert not value["summary"]["official_labels_read"]
            serialized = json.dumps(value)
            assert w["result"]["id"] not in serialized and "technical_total" not in serialized
            assert (
                "platform_submission_verified" in serialized
                and not value["state"]["platform_submission_verified"]
            )
            assert client.get(submission_url(uid(), w["submission"]["id"])).status_code == 404
        assert totals(owner) == before
    finally:
        for name in names:
            owner.execute(
                sql.SQL("GRANT SELECT ON {} TO tender_api").format(sql.Identifier(*name.split(".")))
            )


def test_single_body_submission_cannot_be_misread_as_package(exact):
    identity = uid()
    with connection() as c:
        c.execute(
            "INSERT INTO design.submission_records(id,bid_id,subject_kind,body_version_id,kind,evidence,submitted_at,created_by) VALUES(%s,%s,'single_body',%s,'offline_fact','{}',clock_timestamp(),%s)",
            (identity, exact["scope"].bid_id, exact["member"].document_version_id, exact["actor"]),
        )
    with client_for(exact) as client:
        response = client.get(submission_url(exact["scope"].bid_id, identity))
        assert response.status_code == 404, response.text


@pytest.fixture
def build_client(env):
    token = uuid4().hex
    with connection() as c:
        c.execute(
            "INSERT INTO design.sessions(id,member_id,token_digest,csrf_digest,expires_at) VALUES(%s,%s,%s,%s,clock_timestamp()+interval '10 minutes')",
            (uuid4(), env["actor"], secret_hash(token), sha(b"unused read-only CSRF")),
        )
    with TestClient(context_app()) as client:
        client.cookies.set("session", token)
        yield client


def test_adoption_multiple_builds_and_membership_have_native_proofs_and_exact_pagination(
    env, build_client, monkeypatch
):
    first, body, _ = build(env)
    adopted, _ = adopt(env, first, body)
    second, body_two, _ = build(env)
    other, _ = adopt(env, second, body_two)
    one = adopted["body"]["package"]
    # A later ordinary package revision contains the exact output but has no
    # adoption receipt for this revision. It cannot become an adopted_into edge.
    with connection() as c:
        previous = bid_package_service.head(c, env["bid"], one["manifest"]["package_id"])
        newer = bid_package_service.create_revision(
            c, env["bid"], {"kind": "bid", "members": [body["member"]]}, previous
        )
    before = totals(env["database"]["owner"])
    forbid_io(monkeypatch)
    path = relation_url(env, first)
    response = build_client.get(path, params={"target": "package_revision", "limit": 1})
    assert response.status_code == 200, response.text
    first_page, current = response.json(), response.json()
    assert first_page["seed"]["build_id"] == str(first)
    assert first_page["seed"]["snapshot_id"] == env["saved"]["snapshot_id"]
    items = list(current["items"])
    while current["has_more"]:
        response = build_client.get(
            path,
            params={"target": "package_revision", "limit": 1, "cursor": current["next_cursor"]},
        )
        assert response.status_code == 200, response.text
        current = response.json()
        assert current["observation_digest"] == first_page["observation_digest"]
        items.extend(current["items"])
    assert len(items) == len({item["id"] for item in items}) == first_page["total"] == 3
    assert sum(item["kind"] == "adopted_into" for item in items) == 1
    new_membership = [
        item for item in items if item["package_revision"]["revision_id"] == newer.revision_id
    ]
    assert len(new_membership) == 1 and new_membership[0]["kind"] == "contains_output"
    assert other["body"]["package"]["manifest"]["revision_id"] not in json.dumps(items)
    assert all(
        item["current_package_head"]["status"] == "changed"
        for item in items
        if item["package_revision"]["revision_id"] == one["manifest"]["revision_id"]
    )
    serialized = json.dumps(first_page)
    assert not any(
        word in serialized
        for word in ("idempotency_key", "object_key", "original_name", '"request"', body["reason"])
    )
    assert (
        build_client.get(path + "?target=package_revision&target=package_revision").status_code
        == 422
    )
    assert build_client.get(path, params={"target": "latest"}).status_code == 422
    assert build_client.get(path).status_code == 422
    assert (
        build_client.get(
            relation_url(env | {"bid": uid()}, first), params={"target": "package_revision"}
        ).status_code
        == 404
    )
    assert (
        build_client.get(
            relation_url(env, second),
            params={"target": "package_revision", "cursor": first_page["next_cursor"]},
        ).status_code
        == 422
    )
    assert totals(env["database"]["owner"]) == before


def test_source_withdrawal_and_new_adoption_invalidate_pagination_without_erasing_history(
    env, build_client
):
    build_id, body, _ = build(env)
    adopt(env, build_id, body)
    path = relation_url(env, build_id)
    first = build_client.get(path, params={"target": "package_revision", "limit": 1})
    assert first.status_code == 200, first.text
    adopt(env, build_id, body | {"reason": "第二次明确采用到另一个独立包"})
    stale = build_client.get(
        path, params={"target": "package_revision", "cursor": first.json()["next_cursor"]}
    )
    assert (
        stale.status_code == 409 and stale.json()["code"] == "WORK_CONTEXT_OBSERVATION_CHANGED"
    ), stale.text
    fresh = build_client.get(path, params={"target": "package_revision", "limit": 1})
    assert fresh.status_code == 200, fresh.text
    env["database"]["owner"].execute(
        "UPDATE retrieval.source_heads h SET status='withdrawn',revision=revision+1 FROM retrieval.source_nodes n WHERE h.source_id=n.id AND n.document_version_id=%s",
        (env["source_document"],),
    )
    source_stale = build_client.get(
        path, params={"target": "package_revision", "cursor": fresh.json()["next_cursor"]}
    )
    assert source_stale.status_code == 409, source_stale.text
    history = build_client.get(path, params={"target": "package_revision"})
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 4
    assert all(
        item["current_source_basis"]["status"] == "changed"
        for item in history.json()["items"]
        if item["kind"] == "adopted_into"
    )


def test_same_bytes_and_filename_do_not_manufacture_a_build_package_relation(env, build_client):
    build_id, body, _ = build(env)
    clone = uuid4()
    with connection() as c:
        # Explicit synthetic imported copy: same blob and original filename,
        # distinct logical document UUID, verified body membership, no adoption.
        c.execute(
            """INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by)
            SELECT %s,bid_id,blob_id,original_name,clock_timestamp(),'bid_body',created_by
            FROM design.document_versions WHERE bid_id=%s AND id=%s""",
            (clone, env["bid"], body["member"]["document_version_id"]),
        )
        same = c.execute(
            """SELECT b.digest FROM design.document_versions d JOIN design.blobs b ON b.id=d.blob_id
            WHERE d.bid_id=%s AND d.id=%s""",
            (env["bid"], clone),
        ).fetchone()
        attach(
            c,
            env["bid"],
            env["actor"],
            SimpleNamespace(document_version_id=clone, file_digest=same["digest"]),
        )
        package = bid_package_service.create_revision(
            c,
            env["bid"],
            {"kind": "bid", "members": [body["member"] | {"document_version_id": str(clone)}]},
        )
    response = build_client.get(relation_url(env, build_id), params={"target": "package_revision"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0 and response.json()["items"] == []
    assert package.revision_id not in json.dumps(response.json())


@pytest.mark.parametrize("mutation", ["proof", "missing_ack", "extra_ack_field", "duplicate_audit"])
def test_wrong_or_missing_native_adoption_proof_fails_closed(env, build_client, mutation):
    build_id, body, _ = build(env)
    saved, _ = adopt(env, build_id, body)
    command_id = saved["body"]["command_id"]
    with connection() as c:
        if mutation == "duplicate_audit":
            c.execute(
                "INSERT INTO design.audit_entries(id,actor_id,bid_id,command_id,event_type,payload) SELECT %s,actor_id,bid_id,command_id,event_type,payload FROM design.audit_entries WHERE command_id=%s AND event_type='authoring.output_qualified'",
                (uuid4(), command_id),
            )
        else:
            altered = deepcopy(saved)
            if mutation == "proof":
                altered["body"]["output"]["publication_receipt_digest"] = "0" * 64
            elif mutation == "missing_ack":
                altered = None
            else:
                altered["body"]["auto_select_latest"] = True
            c.execute(
                "UPDATE design.commands SET response=%s WHERE id=%s",
                (Jsonb(altered) if altered is not None else None, command_id),
            )
    response = build_client.get(relation_url(env, build_id), params={"target": "package_revision"})
    assert response.status_code == 500 and response.json()["code"] == "WORK_CONTEXT_CORRUPT", (
        response.text
    )


def test_build_without_adoption_has_empty_directory_and_bounded_capacity_is_explicit(
    env, build_client, monkeypatch
):
    build_id, body, _ = build(env)
    empty = build_client.get(relation_url(env, build_id), params={"target": "package_revision"})
    assert empty.status_code == 200, empty.text
    assert (
        empty.json()["items"] == [] and empty.json()["total"] == 0 and not empty.json()["has_more"]
    )
    adopt(env, build_id, body)
    adopt(env, build_id, body | {"reason": "明确第二条不同采用"})
    monkeypatch.setattr(relations, "MAX_RECORDS", 1)
    too_many = build_client.get(relation_url(env, build_id), params={"target": "package_revision"})
    assert (
        too_many.status_code == 413 and too_many.json()["code"] == "WORK_CONTEXT_CAPACITY_EXCEEDED"
    ), too_many.text


def test_actual_readiness_and_opt_in_openapi_are_closed(database):
    result = verify()
    assert result["ready"] and not result["ddl_applied"]
    assert set(result["checks"]) == {"run", "submission", "relations"}
    actual = openapi(context_app())
    assert set(actual["paths"]) == {
        contract.RUN_PATH,
        contract.SUBMISSION_PATH,
        contract.RELATIONS_PATH,
    }
    assert all(set(methods) == {"get"} for methods in actual["paths"].values())
    assert all(
        get["get"]["security"] == [{"SessionCookie": []}] for get in actual["paths"].values()
    )
