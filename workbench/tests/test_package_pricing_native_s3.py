"""Explicit synthetic pricing acceptance: real PG/S3, unchanged business API and arithmetic."""
# ruff: noqa: F811

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from test_bid_package_api import world  # noqa: F401
from test_bid_package_requirements_api import database  # noqa: F401
from test_package_pricing_pg import priced, register, scenario, simulate  # noqa: F401
from test_stable_lot_identity import api, headers, uid  # noqa: F401

from packages.domain import storage
from packages.domain.runtime import connection
from packages.pricing import repository

NATIVE_GET, NATIVE_PUT = storage.get, storage.put
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PRICING_NATIVE_S3") != "1",
    reason="explicit disposable native PG17/private S3 pricing acceptance required",
)


@pytest.fixture
def native(priced, monkeypatch):
    assert os.environ["OBJECT_STORE_BACKEND"] == "s3"
    monkeypatch.setattr(storage, "get", NATIVE_GET)
    monkeypatch.setattr(storage, "put", NATIVE_PUT)
    return priced


def save(w, simulation, *, key=None, reason="synthetic arithmetic reference"):
    return w["client"].post(
        w["pricing_base"] + "/pricing-plans",
        json={"simulation_id": simulation.json()["id"], "reason": reason},
        headers=headers(w, key=key, etag=simulation.headers["etag"]),
    )


def test_real_formula_object_arithmetic_versions_replay_and_application_restart(
    native, monkeypatch
):
    w = native
    formula = register(w)
    assert not w["objects"]  # No in-memory object transport was used.
    with connection() as c:
        blob = c.execute(
            "SELECT object_key FROM design.blobs WHERE id=%s",
            (formula.json()["formula_version_id"],),
        ).fetchone()
    assert blob and storage.client().head_object(Bucket=storage.bucket(), Key=blob["object_key"])
    result = simulate(w, formula)
    # Independent hand calculation: 30 * minimum(120,100,100) / 120 = 25.
    assert result.json()["price_score"] == "25.00"
    cookies = dict(w["client"].cookies)
    w["client"].cookies.clear()
    try:
        assert save(w, result, reason="unauthenticated must not save").status_code == 401
    finally:
        w["client"].cookies.update(cookies)
    first = save(w, result, key="native-pricing-lost-ack")
    assert first.status_code == 201, first.text
    replay = save(w, result, key="native-pricing-lost-ack")
    assert replay.status_code == 201 and replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    second = save(w, result, reason="second immutable version")
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]
    # Force an ID unrelated to chronological order; this must still appear first.
    newest_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    monkeypatch.setattr(repository, "uid", lambda: UUID(newest_id))
    third = save(w, result, reason="latest chronological version")
    assert third.status_code == 201, third.text
    expected = [third.json()["id"], second.json()["id"], first.json()["id"]]
    with connection() as c:
        old_order = [
            str(row["id"])
            for row in c.execute(
                "SELECT id FROM design.pricing_plans WHERE bid_id=%s ORDER BY id",
                (w["scope"].bid_id,),
            ).fetchall()
        ]
    assert old_order != expected  # Negative control: the former query violates chronology.
    path = w["pricing_base"] + "/pricing-plans"
    one = w["client"].get(path, params={"limit": 1}).json()
    two = w["client"].get(path, params={"limit": 1, "cursor": one["next_cursor"]}).json()
    three = w["client"].get(path, params={"limit": 1, "cursor": two["next_cursor"]}).json()
    assert [p["items"][0]["id"] for p in (one, two, three)] == expected
    assert three["next_cursor"] is None

    # Browser is mandatory in the dedicated pricing suite, optional for direct
    # native test invocation. No mocked HTTP or persisted Cookie file is used.
    if os.environ.get("FUSION_PRICING_BROWSER") == "1":
        browser_history(w, expected)
    program = r"""
import json,sys
from fastapi.testclient import TestClient
from apps.api.main import app
v=json.loads(sys.stdin.read())
with TestClient(app) as client:
    client.cookies.update(v['cookies'])
    plans=client.get(v['path'])
    assert plans.status_code==200,plans.text
    formula=client.get(v['formula'])
    assert formula.status_code==200,formula.text
    print(json.dumps({'ids':[p['id'] for p in plans.json()['items']],'formula':formula.json()['formula_digest']}))
"""
    for _ in range(2):
        child = subprocess.run(
            [sys.executable, "-c", program],
            input=json.dumps(
                {
                    "cookies": dict(w["client"].cookies),
                    "path": path,
                    "formula": w["pricing_base"]
                    + "/pricing-formulas/"
                    + formula.json()["formula_version_id"],
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        assert child.returncode == 0, child.stderr
        recovered = json.loads(child.stdout)
        assert recovered["ids"] == expected
        assert recovered["formula"] == formula.json()["formula_digest"]

    original = storage.get(blob["object_key"])
    try:
        storage.put(blob["object_key"], b"{}", repository.FORMULA_MEDIA)
        damaged = w["client"].get(
            w["pricing_base"] + "/pricing-formulas/" + formula.json()["formula_version_id"]
        )
        assert damaged.status_code == 409 and damaged.json()["code"] == "PRICING_FORMULA_CORRUPTED"
    finally:
        storage.put(blob["object_key"], original, repository.FORMULA_MEDIA)


def test_equal_timestamps_use_stable_id_tiebreaker_and_cursor_is_bid_scoped(native):
    w = native
    formula = register(w)
    simulation = simulate(w, formula)
    saved = save(w, simulation)
    assert saved.status_code == 201
    owner = w["database"]["owner"]
    ids = ["00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"]
    for identity in ids:
        owner.execute(
            "INSERT INTO design.pricing_plans(id,bid_id,formula_digest,input_manifest,result,created_by,created_at,simulation_id) SELECT %s,bid_id,formula_digest,input_manifest,result,created_by,'2099-01-01T00:00:00Z',simulation_id FROM design.pricing_plans WHERE id=%s",
            (identity, saved.json()["id"]),
        )
    path = w["pricing_base"] + "/pricing-plans"
    first = w["client"].get(path, params={"limit": 1}).json()
    second = w["client"].get(path, params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert first["items"][0]["id"] == ids[1] and second["items"][0]["id"] == ids[0]
    assert w["client"].get(path, params={"cursor": uid()}).status_code == 404
    foreign_bid, foreign_plan = uid(), uid()
    owner.execute(
        "INSERT INTO design.bids(id,title,settings,created_by) SELECT %s,'synthetic foreign cursor',settings,created_by FROM design.bids WHERE id=%s",
        (foreign_bid, w["scope"].bid_id),
    )
    owner.execute(
        "INSERT INTO design.pricing_plans(id,bid_id,formula_digest,input_manifest,result,created_by,simulation_id) SELECT %s,%s,formula_digest,input_manifest,result,created_by,simulation_id FROM design.pricing_plans WHERE id=%s",
        (foreign_plan, foreign_bid, saved.json()["id"]),
    )
    assert w["client"].get(path, params={"cursor": foreign_plan}).status_code == 404


def browser_history(
    w, expected, journeys=None, *, browser_script="scripts/check-pricing-native-browser.mjs"
):
    import time
    import urllib.request

    from deploy.ci_object_store import unused_ports
    from packages.domain.runtime import ROOT

    api_port, ui_port = unused_ports(2)
    origin = f"http://127.0.0.1:{ui_port}"
    backend = f"http://127.0.0.1:{api_port}"
    environment = os.environ | {"APP_ORIGIN": origin}
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--log-level",
            "error",
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(backend + "/openapi.json", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("native pricing API did not become ready")
        # Allow only browser selectors, public tool paths and process basics.
        browser_env = {
            k: v
            for k, v in os.environ.items()
            if k
            in {
                "PATH",
                "HOME",
                "LANG",
                "TMPDIR",
                "TEMP",
                "SYSTEMROOT",
                "WINDIR",
                "PLAYWRIGHT_MODULE",
                "PLAYWRIGHT_BROWSERS_PATH",
                "CHROMIUM_EXECUTABLE",
            }
        }
        completed = subprocess.run(
            ["node", browser_script],
            cwd=ROOT / "apps/web",
            env=browser_env,
            input=json.dumps(
                {
                    "backend": backend,
                    "port": ui_port,
                    "bid": str(w["scope"].bid_id),
                    "binding": w["binding"],
                    "expected": expected,
                    "journeys": journeys,
                    "cookie": w["client"].cookies["session"],
                }
            ),
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        receipt = json.loads(completed.stdout)
        if journeys:
            return receipt["cases"][0]
        assert len(receipt["cases"]) == 2 and all(c["reload_consistent"] for c in receipt["cases"])
        if report := os.environ.get("FUSION_PRICING_BROWSER_REPORT"):
            Path(report).write_text(json.dumps(receipt, indent=2) + "\n")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def test_native_workspace_combined_journeys_and_notification_recovery(native):
    if os.environ.get("FUSION_PRICING_BROWSER") != "1":
        pytest.fail("combined browser journeys require the dedicated native suite")
    w = native
    register(w)
    from packages.domain.runtime import sha

    # Package intake fixtures do not populate the independent single-body
    # material directory. Supply an explicit synthetic frozen directory for
    # the existing human/knowledge UI; this is not upload/parser acceptance.
    with connection() as c:
        snapshot = UUID(uid())
        c.execute(
            "INSERT INTO material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,'{}',%s)",
            (snapshot, w["scope"].bid_id, sha({})),
        )
        for role, member in [("body", w["member"]), ("tender", w["authority_member"])]:
            c.execute(
                "INSERT INTO material_assignments VALUES(%s,%s,%s,%s,0)",
                (snapshot, w["scope"].bid_id, member.document_version_id, role),
            )
        c.execute(
            "UPDATE bid_profiles SET current_material_id=%s,current_body_id=%s WHERE bid_id=%s",
            (snapshot, w["member"].document_version_id, w["scope"].bid_id),
        )
    from packages.domain.runtime import Command, enqueue

    # The original review queue requires the material intake operation identity.
    # Use the existing producer in this explicit fixture, never a fabricated
    # success receipt or a compute handler/provider substitute.
    with connection() as c:
        payload = {"id": snapshot, "digest": sha({})}
        command = Command(
            c,
            UUID(w["actor"]),
            "synthetic-material-directory",
            w["scope"].bid_id,
            uid(),
            {"snapshot": str(snapshot)},
            None,
        )
        queued = enqueue(c, w["scope"].bid_id, command.id, "parse-materials", payload)
        command.finish({"fixture_operation_id": queued["id"]}, 201)
    knowledge = native_knowledge_version(w)
    from test_stable_lot_identity import catalog, post

    project, lot, round_value, bidder = catalog(w)
    life = post(
        w,
        "/bids",
        {
            "title": "synthetic lifecycle isolated bid",
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    ).json()
    assert life["identity"]["lot_id"] == lot["id"]
    assert life["identity"]["engineering_project_id"] == project["id"]

    def extra_bid(title):
        _, _, extra_round, extra_bidder = catalog(w)
        return post(
            w,
            "/bids",
            {"title": title, "round_id": extra_round["id"], "bidder_id": extra_bidder["id"]},
        ).json()["id"]

    submitted = extra_bid("synthetic submitted-state UI fixture, not actual submission acceptance")
    # Explicit test-only state setup to cover the existing submitted -> closed UI.
    # No submission fact, real qualification or business acceptance is fabricated.
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase='submitted' WHERE bid_id=%s", (submitted,)
    )
    ack_bid = extra_bid("synthetic lost-ACK lifecycle bid")
    result = browser_history(
        w,
        [],
        {
            "phase": "write",
            "knowledge_id": knowledge,
            "lifecycle_bid": life["id"],
            "submitted_bid": submitted,
        },
    )
    ack = browser_history(w, [], {"phase": "lifecycle_ack", "lifecycle_bid": ack_bid})
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM audit_entries WHERE bid_id=%s AND event_type='project.lifecycle_changed' AND payload->>'action'='start'",
                (ack_bid,),
            ).fetchone()["n"]
            == 1
        )
    from packages.tasks import runs

    # The original bounded notification producer consumes the real local task result;
    # no owner INSERT or substituted execution/transport supplies a successful event.
    with connection() as c:
        assert runs.notify(c, w["scope"].bid_id, UUID(result["run_id"])) is True
    with connection() as c:
        assert runs.notify(c, w["scope"].bid_id, UUID(result["run_id"])) is False
    # Existing bounded Worker reconciliation closes a requested cancellation.
    # It performs SQL recovery only, never compute/provider I/O or Kafka sending.
    recovered_worker = subprocess.run(
        [sys.executable, "-c", "from apps.worker.engine import reconcile; reconcile(once=True)"],
        env=os.environ | {"WORKER_DATABASE_DSN": w["database"]["worker_dsn"]},
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert recovered_worker.returncode == 0, recovered_worker.stderr
    cancelled = w["client"].get(w["pricing_base"] + "/task-runs/" + result["cancel_run_id"])
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled", cancelled.text
    with connection() as c:
        assert runs.notify(c, w["scope"].bid_id, UUID(result["cancel_run_id"])) is True
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM model_calls m JOIN operations o ON o.id=m.operation_id WHERE o.bid_id=%s",
                (w["scope"].bid_id,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM effect_receipts WHERE operation_id=%s",
                (cancelled.json()["root_operation_id"],),
            ).fetchone()["n"]
            == 0
        )
    current_life = w["client"].get("/api/v1/bids/" + life["id"]).json()
    assert current_life["identity"] == life["identity"]
    recovered = browser_history(
        w,
        [],
        {"phase": "recover", "run_id": result["run_id"], "cancel_run_id": result["cancel_run_id"]},
    )
    assert recovered["notification_count"] == 2
    from fastapi.testclient import TestClient

    from apps.api.auth import password_hash

    actor, login, password = uid(), "synthetic-notification-" + uid(), uid()
    owner = w["database"]["owner"]
    owner.execute(
        "INSERT INTO design.members(id,display_name) VALUES(%s,'synthetic separate notification recipient')",
        (actor,),
    )
    owner.execute(
        "INSERT INTO design.credentials(member_id,login_name,password_hash) VALUES(%s,%s,%s)",
        (actor, login, password_hash(password)),
    )
    with TestClient(w["app"]) as other:
        logged = other.post(
            "/api/v1/auth/login",
            json={"login_name": login, "password": password},
            headers={"Origin": "http://identity-v2.test"},
        )
        assert logged.status_code == 200
        # Shared project visibility is intentional; notifications are recipient-scoped.
        assert other.get(w["pricing_base"]).status_code == 200
        notifications = other.get(w["pricing_base"] + "/task-notifications")
        assert notifications.status_code == 200 and notifications.json()["items"] == []
        member_receipt = browser_history(
            w | {"client": other}, [], {"phase": "lifecycle_member", "lifecycle_bid": life["id"]}
        )
        with connection() as c:
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM audit_entries WHERE bid_id=%s AND actor_id=%s AND event_type='project.lifecycle_changed'",
                    (life["id"], actor),
                ).fetchone()["n"]
                == 2
            )
        owner.execute("UPDATE design.members SET active=false WHERE id=%s", (actor,))
        inactive_receipt = browser_history(
            w | {"client": other}, [], {"phase": "lifecycle_inactive", "lifecycle_bid": life["id"]}
        )
    if report := os.environ.get("FUSION_PRICING_BROWSER_REPORT"):
        Path(report).with_name("workspace-journeys.json").write_text(
            json.dumps(
                {
                    "write": result,
                    "lifecycle_ack": ack,
                    "active_member": member_receipt,
                    "inactive_member": inactive_receipt,
                    "new_api_process": recovered,
                    "synthetic": True,
                    "model_calls": 0,
                },
                indent=2,
            )
            + "\n"
        )


def native_knowledge_version(w):
    """Use this test's explicit synthetic parse and actual native source registry."""
    from datetime import timedelta

    from packages.domain.runtime import now
    from packages.rag.indexing import parse_source_id

    member = w["authority_member"]
    source = parse_source_id(UUID(member.parse.parse_run_id))
    with connection() as c:
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()["revision"]
        evidence = c.execute(
            "SELECT id,text_content FROM evidence_blocks WHERE parse_id=%s AND physical_page=1 ORDER BY ordinal LIMIT 1",
            (member.parse.parse_run_id,),
        ).fetchone()
        bidder = c.execute(
            "SELECT bidder_id FROM bid_profiles WHERE bid_id=%s", (w["scope"].bid_id,)
        ).fetchone()["bidder_id"]
    candidate = w["client"].post(
        "/api/v1/knowledge",
        json={
            "title": "合成范围核对知识",
            "content": "仅验证合成来源的知识状态机，不表示真实业务依据",
            "scope": "隔离工程机制",
            "source_version_ids": [member.document_version_id],
        },
        headers=headers(w),
    )
    assert candidate.status_code == 201, candidate.text
    path = "/api/v1/knowledge/" + candidate.json()["id"]
    body = {
        "title": "合成范围核对知识",
        "content": "仅验证合成来源的知识状态机，不表示真实业务依据",
        "scope": "隔离工程机制",
        "categories": ["method"],
        "applicability": {
            "bidder_ids": [str(bidder)],
            "bid_ids": [],
            "regions": ["合成地区"],
            "engineering_types": ["合成工程"],
            "conditions": [],
            "purposes": ["assist"],
            "validity_kind": "bounded",
            "valid_from": (now() - timedelta(days=1)).isoformat(),
            "valid_until": (now() + timedelta(days=30)).isoformat(),
            "validity_basis": "隔离夹具窗口不授真实资格",
            "specificity_note": "仅验证工程行为",
        },
        "source_refs": [
            {
                "source_id": str(source),
                "source_revision": revision,
                "document_version_id": member.document_version_id,
                "parse_id": member.parse.parse_run_id,
                "physical_page": 1,
                "evidence_id": str(evidence["id"]),
                "excerpt": evidence["text_content"][:30],
            }
        ],
    }
    version = w["client"].post(
        path + "/versions", json=body, headers=headers(w, etag=candidate.headers["etag"])
    )
    assert version.status_code == 201, version.text
    return candidate.json()["id"]
