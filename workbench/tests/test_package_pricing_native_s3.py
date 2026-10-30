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


def browser_history(w, expected):
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
                "PLAYWRIGHT_MODULE",
                "PLAYWRIGHT_BROWSERS_PATH",
                "CHROMIUM_EXECUTABLE",
            }
        }
        completed = subprocess.run(
            ["node", "scripts/check-pricing-native-browser.mjs"],
            cwd=ROOT / "apps/web",
            env=browser_env,
            input=json.dumps(
                {
                    "backend": backend,
                    "port": ui_port,
                    "bid": str(w["scope"].bid_id),
                    "binding": w["binding"],
                    "expected": expected,
                    "cookie": w["client"].cookies["session"],
                }
            ),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        receipt = json.loads(completed.stdout)
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
