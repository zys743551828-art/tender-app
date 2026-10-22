"""Real public history API receipts for UI replay; all business evidence is synthetic.

No standalone router replacement, owner business calls, external model calls or
automatic job dispatch. Owner privileges install only a fresh disposable fixture.
"""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
import test_package_history_exposure_bridge_pg as bridge
import test_package_history_pg as native
from psycopg.rows import dict_row
from test_package_history_exposure_bridge_pg import database, public_api

from packages.contracts import package_history_directory_api as directory_contract
from packages.domain.runtime import connection
from packages.model_governance import package_history_cpu as cpu
from packages.model_governance.common import digest

ROOT = Path(__file__).resolve().parents[1]
BASE = "/api/v1/package-historical-research"
DIRECTORY_SQL = ROOT / "deploy/sql/package-history-directory.sql"
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PACKAGE_HISTORY_UI_PG") != "1",
    reason="explicit fresh PG17 public history UI acceptance required",
)


@pytest.fixture
def api(public_api):
    bridge.install(public_api["database"])
    public_api["database"]["owner"].execute(DIRECTORY_SQL.read_text())
    return public_api


class Capture:
    """Keep original JSON and only public response/request metadata, never auth."""

    def __init__(self, api):
        self.api = api
        self.responses = []

    def request(self, name, method, path, *, body=None, params=None, headers=None):
        arguments = {}
        if body is not None:
            arguments["json"] = body
        if params is not None:
            arguments["params"] = params
        if headers is not None:
            arguments["headers"] = headers
        response = self.api["client"].request(method, path, **arguments)
        self.responses.append(
            {
                "name": name,
                "method": method,
                "path": path,
                "query": params or {},
                "request_body": body,
                "request_headers": {
                    key.lower(): value
                    for key, value in (headers or {}).items()
                    if key.lower() in {"if-match", "idempotency-key"}
                },
                "status": response.status_code,
                "etag": response.headers.get("etag"),
                "headers": {
                    key: value
                    for key, value in response.headers.items()
                    if key in {"etag", "cache-control", "vary", "idempotency-replayed"}
                },
                "body": response.json(),
            }
        )
        return response

    def save(self, name, **metadata):
        location = os.environ.get("FUSION_PACKAGE_HISTORY_UI_FIXTURE_DIR")
        if location is None:
            return
        target = Path(location) / name
        assert target.parent.is_dir() and not target.exists()
        fixture = {
            "protocol": "package-history-ui-http/1",
            "synthetic": True,
            "real_qualification": False,
            "paid_calls": 0,
            "provider_requests": 0,
            "transport": "actual public FastAPI main with complete exposure bridge and independent PostgreSQL 17 LOGINs",
            "object_transport": "explicit synthetic in-memory original bytes; no real object-store transport claim",
            "actor_id": self.api["actor"],
            **metadata,
            "responses": self.responses,
        }
        target.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n")


def check(response, schema, status=200):
    return native.validate_http(response, schema, status)


def directory(response, kind):
    assert response.status_code == 200, response.json()
    assert response.headers["cache-control"].replace(" ", "") == "private,no-store"
    assert response.headers["vary"] == "Cookie"
    return directory_contract.validate(kind, response.json())


def counts(api):
    return (
        api["database"]["owner"]
        .execute(
            "SELECT (SELECT count(*) FROM design.commands) AS commands,"
            "(SELECT count(*) FROM design.audit_entries) AS audit,"
            "(SELECT count(*) FROM package_historical_research.exposures) AS exposures,"
            "(SELECT count(*) FROM package_historical_research.admissions) AS admissions,"
            "(SELECT count(*) FROM package_historical_research.protocols) AS protocols,"
            "(SELECT count(*) FROM package_historical_research.cohorts) AS cohorts,"
            "(SELECT count(*) FROM package_historical_research.jobs) AS jobs"
        )
        .fetchone()
    )


def prepared_case(api, tmp_path, capture, name, *, value="0", template_keys=()):
    """Upstream fixtures are explicit; verifier and admission use real purpose ports."""
    import test_package_technical_eligibility_pg as eligibility
    import test_package_technical_scope_pg as scopes

    with pytest.MonkeyPatch.context() as patch:
        raw = b"%PDF-1.7\nSynthetic public history original " + uuid4().hex.encode() + b"\n%%EOF\n"
        patch.setattr(scopes, "RAW", raw)
        patch.setattr(eligibility, "RAW", raw)
        w = native.world.__wrapped__(api)
        w = native.requirements.__wrapped__(w)
        w = native.exact.__wrapped__(w, patch)
        w = native.subject(w, patch, value=value)
    if name == "primary":
        saved = capture.request("saved_scope", "GET", w["scope_path"])
        assert saved.status_code == 200 and saved.json() == w["saved"]
        submissions = capture.request(
            "scope_submissions",
            "GET",
            "/api/v1/bids/" + w["scope"].bid_id + "/submissions",
            params={"limit": 20},
        )
        assert submissions.status_code == 200
        assert any(row["id"] == w["submission"]["id"] for row in submissions.json()["items"])
        outcomes = capture.request(
            "scope_outcomes", "GET", "/api/v1/bids/" + w["scope"].bid_id + "/outcomes"
        )
        assert outcomes.status_code == 200
        assert any(row["id"] == w["result"]["id"] for row in outcomes.json()["items"])
    params = {"submission_id": w["submission"]["id"], "outcome_id": w["result"]["id"]}
    missing = capture.request(
        name + "_missing_proof",
        "GET",
        w["scope_path"] + "/historical-admission-context",
        params=params,
    )
    missing_value = check(missing, "PackageHistoricalAdmissionContext")
    assert missing_value["proofs"] == []
    adapter_id, key = native.adapter(w)
    material = native.material(w, adapter_id)
    envelope = native.evidence(
        material["context"], adapter_id, key, w["originals"], template_keys=template_keys
    )
    process, receipt = native.ingest(w, envelope, adapter_id, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert receipt["result"]["proof_id"]
    assert receipt["result"]["paid_calls"] == 0 and receipt["result"]["provider_requests"] == 0
    context_response = capture.request(
        "admission_context" if name == "primary" else name + "_context",
        "GET",
        w["scope_path"] + "/historical-admission-context",
        params=params,
    )
    context = check(context_response, "PackageHistoricalAdmissionContext")
    assert context["official_technical_value"] == value
    assert "PACKAGE_HISTORY_EXTERNAL_PROOF_ADAPTER_NOT_CONFIGURED" in {
        blocker["code"] for blocker in context["blockers"]
    }
    request = params | {
        "proof_id": receipt["result"]["proof_id"],
        "context_digest": context["context_digest"],
        "reason": "Explicit synthetic research admission through the guarded public API",
    }
    headers = native.headers(w, etag=context_response.headers["etag"])
    accepted = capture.request(
        "admission_created" if name == "primary" else name + "_admitted",
        "POST",
        w["scope_path"] + "/historical-admissions",
        body=request,
        headers=headers,
    )
    w["admission"] = check(accepted, "PackageHistoricalAdmission", 201)
    assert w["admission"]["origin"] == "synthetic"
    assert w["admission"]["state"] == "mechanism_candidate"
    assert not w["admission"]["formal_sample_created"]
    if name != "primary":
        current = check(
            capture.request(name + "_current", "GET", BASE + "/admissions/" + w["admission"]["id"]),
            "PackageHistoricalAdmissionView",
        )
        assert current["current"] and current["admission"] == w["admission"]
    w.update(adapter_id=adapter_id, admission_request=request, admission_headers=headers)
    return w


def test_missing_public_installation_and_unknown_directory_are_not_empty(public_api):
    capture = Capture(public_api)
    before = counts(public_api)
    closed = capture.request("public_guard_unavailable", "GET", BASE + "/cpu-protocol-template")
    assert closed.status_code == 503
    assert closed.json()["code"] == "PACKAGE_HISTORY_PUBLIC_GUARD_UNAVAILABLE"
    for kind in ("admissions", "protocols", "cohorts"):
        observed = directory(capture.request(kind + "_unavailable", "GET", BASE + "/" + kind), kind)
        assert observed["status"] == "unavailable" and observed["total"] is None
        assert observed["observation_digest"] is None and observed["has_more"] is None
    assert counts(public_api) == before
    bridge.install(public_api["database"])
    public_api["database"]["owner"].execute(DIRECTORY_SQL.read_text())
    for kind in ("admissions", "protocols", "cohorts"):
        observed = directory(capture.request(kind + "_empty", "GET", BASE + "/" + kind), kind)
        assert observed["status"] == "observed" and observed["total"] == 0
        assert observed["complete_observation"] and observed["has_more"] is False
    assert counts(public_api) == before
    capture.save("package-history-ui-unavailable-http.json")


def test_actual_public_ui_flow_exact_ack_directories_and_isolated_cpu(api, tmp_path):
    capture = Capture(api)
    cases = [
        prepared_case(api, tmp_path, capture, name, value=value)
        for name, value in (("primary", "0"), ("fit_second", "8"), ("development", "7"))
    ]
    template_key = "synthetic-bridge-" + native.uid()
    unselected_bridge = prepared_case(
        api, tmp_path, capture, "unselected_bridge", value="5", template_keys=(template_key,)
    )
    boundary = datetime.now(timezone.utc).isoformat()
    cases.append(prepared_case(api, tmp_path, capture, "final_known", value="6"))
    cutoff = datetime.now(timezone.utc).isoformat()
    cases.append(
        prepared_case(
            api, tmp_path, capture, "final_crossing", value="9", template_keys=(template_key,)
        )
    )
    cases.append(prepared_case(api, tmp_path, capture, "final_unknown", value="0"))
    w = cases[0]
    admission = check(
        capture.request("admission_current", "GET", BASE + "/admissions/" + w["admission"]["id"]),
        "PackageHistoricalAdmissionView",
    )
    assert admission["current"] and admission["admission"] == w["admission"]
    template_response = capture.request("protocol_template", "GET", BASE + "/cpu-protocol-template")
    template = check(template_response, "PackageHistoricalProtocolTemplate")
    request = {
        "method_digest": template["method_digest"],
        "seed": 17,
        "bootstrap_iterations": 100,
        "reason": "Explicit feature-free CPU baseline protocol; synthetic mechanism evidence",
    }
    protocol = check(
        capture.request(
            "protocol_created", "POST", BASE + "/protocols", body=request, headers=native.headers(w)
        ),
        "PackageHistoricalProtocol",
        201,
    )
    cohort_request = {
        "protocol_id": protocol["id"],
        "submission_split_at": boundary,
        "label_available_as_of": cutoff,
        "selections": [
            {"admission_id": case["admission"]["id"], "purpose": purpose}
            for case, purpose in zip(
                cases, ("fit", "fit", "development", "final", "final", "final"), strict=True
            )
        ],
        "reason": "Exact selected admissions with actual split, cutoff and full related-group closure",
    }
    cohort = check(
        capture.request(
            "cohort_created",
            "POST",
            BASE + "/cohorts",
            body=cohort_request,
            headers=native.headers(w),
        ),
        "PackageHistoricalCohort",
        201,
    )
    members = {member["admission_id"]: member for member in cohort["members"]}
    crossing = members[cases[-2]["admission"]["id"]]
    assert (
        crossing["purpose"] == "excluded"
        and crossing["exclusion_reason"] == "group_spans_submission_split"
    )
    assert unselected_bridge["admission"]["id"] in crossing["closure_ids"]
    assert (
        members[cases[-1]["admission"]["id"]]["exclusion_reason"] == "label_after_available_cutoff"
    )
    cohort_path = BASE + "/cohorts/" + cohort["id"]
    observed = capture.request("cohort_current", "GET", cohort_path)
    assert check(observed, "PackageHistoricalCohortView")["current"]
    task = check(
        capture.request(
            "train_created",
            "POST",
            cohort_path + "/jobs",
            body={
                "kind": "train",
                "reason": "Run the exact independently credentialed CPU baseline",
            },
            headers=native.headers(w, etag=observed.headers["etag"]),
        ),
        "PackageHistoricalJob",
        201,
    )
    task_path = BASE + "/jobs/" + task["job_id"]
    queued = capture.request("train_queued", "GET", task_path)
    assert check(queued, "PackageHistoricalJobView")["state"] == "queued"
    pause_body = {
        "action": "pause",
        "generation": task["generation"],
        "reason": "Pause this exact task before the independent CPU runner",
    }
    pause_headers = native.headers(w, etag=queued.headers["etag"])
    paused = check(
        capture.request(
            "pause_ack", "POST", task_path + "/control", body=pause_body, headers=pause_headers
        ),
        "PackageHistoricalJob",
        200,
    )
    assert paused["generation"] == task["generation"] + 1
    repeated = capture.request(
        "pause_replayed", "POST", task_path + "/control", body=pause_body, headers=pause_headers
    )
    assert repeated.json() == paused and repeated.headers["idempotency-replayed"] == "true"
    stale = capture.request(
        "pause_stale_condition",
        "POST",
        task_path + "/control",
        body=pause_body,
        headers=native.headers(w, etag=queued.headers["etag"]),
    )
    assert stale.status_code == 412
    paused_response = capture.request("train_paused", "GET", task_path)
    assert check(paused_response, "PackageHistoricalJobView")["state"] == "paused"
    resumed = check(
        capture.request(
            "resume_ack",
            "POST",
            task_path + "/control",
            body={
                "action": "resume",
                "generation": paused["generation"],
                "reason": "Resume the same frozen research task",
            },
            headers=native.headers(w, etag=paused_response.headers["etag"]),
        ),
        "PackageHistoricalJob",
        200,
    )
    resumed_response = capture.request("train_resumed", "GET", task_path)
    assert (
        check(resumed_response, "PackageHistoricalJobView")["generation"] == resumed["generation"]
    )
    process, receipt = native.cpu_child(w, resumed, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert receipt["result"]["paid_calls"] == 0 and receipt["result"]["provider_requests"] == 0
    training = check(
        capture.request("train_succeeded", "GET", task_path), "PackageHistoricalJobView"
    )
    assert training["state"] == "succeeded" and training["current"]
    current = capture.request("cohort_after_train", "GET", cohort_path)
    evaluation = check(
        capture.request(
            "evaluate_created",
            "POST",
            cohort_path + "/jobs",
            body={
                "kind": "evaluate",
                "reason": "Explicitly open final exposure and independently evaluate sealed predictions",
            },
            headers=native.headers(w, etag=current.headers["etag"]),
        ),
        "PackageHistoricalJob",
        201,
    )
    evaluation_path = BASE + "/jobs/" + evaluation["job_id"]
    capture.request("evaluate_queued", "GET", evaluation_path)
    process, receipt = native.cpu_child(w, evaluation, tmp_path)
    assert process.returncode == 0, (process.stdout, process.stderr)
    assert receipt["result"]["paid_calls"] == 0 and receipt["result"]["provider_requests"] == 0
    final = check(
        capture.request("evaluate_succeeded", "GET", evaluation_path), "PackageHistoricalJobView"
    )
    assert final["state"] == "succeeded" and final["current"]
    report = final["result"]["report"]
    assert report["denominator"] == 3
    assert report["counts"] == {"succeeded": 1, "failed": 0, "rejected": 1, "unlabeled": 1}
    assert report["group_bootstrap_project_mae_95"] is None
    assert all(interval["coverage"] is None for interval in report["intervals"].values())
    before = counts(api)
    for kind, path in (
        ("admissions", BASE + "/admissions"),
        ("protocols", BASE + "/protocols"),
        ("cohorts", BASE + "/cohorts"),
        ("jobs", cohort_path + "/jobs"),
    ):
        result = directory(capture.request(kind + "_directory", "GET", path), kind)
        assert result["status"] == "observed" and not result["qualification_granted"]
        assert all(row["current_status"] == "not_rechecked" for row in result["items"])
    first = directory(
        capture.request("admissions_page_one", "GET", BASE + "/admissions", params={"limit": 2}),
        "admissions",
    )
    second = directory(
        capture.request(
            "admissions_page_two",
            "GET",
            BASE + "/admissions",
            params={"limit": 2, "cursor": first["next_cursor"]},
        ),
        "admissions",
    )
    assert first["has_more"] and first["observation_digest"] == second["observation_digest"]
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}
    assert counts(api) == before
    # Revoke current use, without changing any frozen ACK, report or source truth.
    api["database"]["owner"].execute(
        "INSERT INTO package_historical_research.adapter_revocations(adapter_id,reason) VALUES(%s,'Synthetic source becomes unavailable after the original result')",
        (w["adapter_id"],),
    )
    stale_cohort = check(
        capture.request("cohort_stale", "GET", cohort_path), "PackageHistoricalCohortView"
    )
    stale_result = check(
        capture.request("evaluation_stale", "GET", evaluation_path), "PackageHistoricalJobView"
    )
    assert not stale_cohort["current"] and not stale_result["current"]
    assert stale_result["result"] == final["result"]
    stale_admission = check(
        capture.request("admission_stale", "GET", BASE + "/admissions/" + w["admission"]["id"]),
        "PackageHistoricalAdmissionView",
    )
    assert not stale_admission["current"] and stale_admission["admission"] == w["admission"]
    restored = capture.request(
        "admission_replayed_after_revocation",
        "POST",
        w["scope_path"] + "/historical-admissions",
        body=w["admission_request"],
        headers=w["admission_headers"],
    )
    assert restored.status_code == 201 and restored.json() == w["admission"]
    assert restored.headers["idempotency-replayed"] == "true"
    assert (
        api["database"]["owner"].execute("SELECT count(*) AS n FROM design.samples").fetchone()["n"]
        == 0
    )
    capture.save(
        "package-history-ui-http.json",
        bid_id=w["scope"].bid_id,
        scope_path=w["scope_path"],
        scope=w["saved"],
        cohort_id=cohort["id"],
    )


def test_protocol_original_ack_survives_current_method_change_but_new_key_refuses(api, monkeypatch):
    capture = Capture(api)
    template = check(
        capture.request("protocol_template", "GET", BASE + "/cpu-protocol-template"),
        "PackageHistoricalProtocolTemplate",
    )
    body = {
        "method_digest": template["method_digest"],
        "seed": 17,
        "bootstrap_iterations": 100,
        "reason": "Original explicit protocol request before a method upgrade",
    }
    headers = native.headers(api)
    saved = capture.request(
        "protocol_created", "POST", BASE + "/protocols", body=body, headers=headers
    )
    protocol = check(saved, "PackageHistoricalProtocol", 201)
    before = counts(api)
    original = cpu.method()
    changed = {k: v for k, v in original.items() if k != "digest"}
    changed["version"] = "synthetic-method-upgrade-for-recovery-test/1"
    changed["digest"] = digest(changed)
    monkeypatch.setattr(cpu, "method", lambda: deepcopy(changed))
    restored = capture.request(
        "protocol_original_replayed", "POST", BASE + "/protocols", body=body, headers=headers
    )
    assert restored.status_code == 201 and restored.json() == protocol
    assert restored.headers["etag"] == saved.headers["etag"]
    assert restored.headers["idempotency-replayed"] == "true"
    refused = capture.request(
        "protocol_new_key_rejected",
        "POST",
        BASE + "/protocols",
        body=body,
        headers=native.headers(api),
    )
    assert refused.status_code == 409 and refused.json()["code"] == "PACKAGE_HISTORY_METHOD_CHANGED"
    assert counts(api) == before
    capture.save("package-history-ui-method-recovery-http.json")


def test_actual_directory_cursor_refuses_changed_observation_and_wrong_scope(api):
    capture = Capture(api)
    template = check(
        capture.request("protocol_template", "GET", BASE + "/cpu-protocol-template"),
        "PackageHistoricalProtocolTemplate",
    )

    def create(seed):
        return check(
            capture.request(
                "protocol_created_" + str(seed),
                "POST",
                BASE + "/protocols",
                body={
                    "method_digest": template["method_digest"],
                    "seed": seed,
                    "bootstrap_iterations": 100,
                    "reason": "Synthetic real HTTP directory observation-change fixture",
                },
                headers=native.headers(api),
            ),
            "PackageHistoricalProtocol",
            201,
        )

    create(1701)
    create(1702)
    first = directory(
        capture.request("protocols_page_one", "GET", BASE + "/protocols", params={"limit": 1}),
        "protocols",
    )
    assert first["has_more"] and first["next_cursor"]
    second = directory(
        capture.request(
            "protocols_page_two",
            "GET",
            BASE + "/protocols",
            params={"limit": 1, "cursor": first["next_cursor"]},
        ),
        "protocols",
    )
    assert first["observation_digest"] == second["observation_digest"]
    assert first["items"][0]["id"] != second["items"][0]["id"]
    create(1703)
    before = counts(api)
    changed = capture.request(
        "protocols_observation_changed",
        "GET",
        BASE + "/protocols",
        params={"limit": 1, "cursor": first["next_cursor"]},
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "PACKAGE_HISTORY_DIRECTORY_OBSERVATION_CHANGED"
    wrong_scope = capture.request(
        "cohorts_wrong_cursor_scope",
        "GET",
        BASE + "/cohorts",
        params={"limit": 1, "cursor": first["next_cursor"]},
    )
    assert wrong_scope.status_code == 422
    refreshed = directory(
        capture.request("protocols_refreshed", "GET", BASE + "/protocols", params={"limit": 1}),
        "protocols",
    )
    assert refreshed["total"] == 3
    assert refreshed["observation_digest"] != first["observation_digest"]
    assert counts(api) == before
    capture.save("package-history-ui-directory-change-http.json")


def test_normal_api_cannot_admit_synthetic_and_purpose_roles_cannot_read_directory(
    api, tmp_path, monkeypatch
):
    capture = Capture(api)
    w = prepared_case(api, tmp_path, capture, "primary")
    before = counts(api)
    with monkeypatch.context() as patch:
        patch.setenv("API_DATABASE_DSN", api["database"]["ordinary_api_dsn"])
        rejected = capture.request(
            "ordinary_api_synthetic_rejected",
            "POST",
            w["scope_path"] + "/historical-admissions",
            body=w["admission_request"],
            headers=native.headers(w, etag=w["admission_headers"]["If-Match"]),
        )
        assert (
            rejected.status_code == 403
            and rejected.json()["code"] == "PACKAGE_HISTORY_SYNTHETIC_ENVIRONMENT_DENIED"
        )
    for purpose in ("api", "worker", "verify", "train", "evaluate"):
        with psycopg.connect(api["database"][purpose + "_dsn"], row_factory=dict_row) as c:
            identity = c.execute(
                "SELECT current_user AS name,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert not any(
                identity[key]
                for key in (
                    "rolsuper",
                    "rolcreaterole",
                    "rolcreatedb",
                    "rolreplication",
                    "rolbypassrls",
                )
            )
            if purpose == "api":
                continue
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT package_historical_research.list_protocols(20,NULL,NULL)")
    assert counts(api) == before
    capture.save("package-history-ui-role-boundaries-http.json", scope_path=w["scope_path"])
