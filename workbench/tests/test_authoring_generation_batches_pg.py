"""Actual nonowner PG/ASGI/Worker batch protocol; all provider I/O is MockTransport.

Uses one explicitly disposable database, independent API and Worker LOGINs, real
confirmed project facts, real budget RPCs and the existing native call ledger.
"""
# ruff: noqa: F401,F811

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from psycopg.types.json import Jsonb
from test_assistant_budget_nonowner import (
    SYNTHETIC_CSRF,
    SYNTHETIC_SESSION,
    _confirm_api,
    _seed_api,
    _seed_worker,
)
from test_authoring_section_patch_set import rich_plan
from test_bid_package_requirements_api import database

from apps.api import authoring_generation_batches
from apps.api.assistant_routes import router as assistant_router
from apps.worker import engine
from packages.assistant import actions, budget, coordinator, jobs
from packages.assistant import generation_batch_contracts as contracts
from packages.assistant import generation_batches as service
from packages.authoring import repository, rich_assets, rich_images, section_patch_set
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import ROOT, DomainError, assert_role, clean, connection, now, sha

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires isolated generation batch PG17",
)
EXTENSIONS = (
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/assistant/sql/generation-batches.sql",
)


def client():
    app = FastAPI()
    app.include_router(authoring_generation_batches.router)
    app.include_router(assistant_router)

    @app.exception_handler(DomainError)
    async def error(_request, exc):
        return JSONResponse(
            {"code": exc.code, "message": exc.message, "details": clean(exc.details)},
            status_code=exc.status,
        )

    return TestClient(app)


def cookie(actor):
    return {"Cookie": "session=" + str(actor) + SYNTHETIC_SESSION}


@pytest.fixture(scope="module")
def batch_database(database):
    seed = clean(_seed_api({}))
    with client() as browser:
        response = browser.get(
            "/api/v1/authoring/generation-batch-capabilities", headers=cookie(seed["actor"])
        )
        assert response.status_code == 200, response.text
        contracts.validate("AuthoringGenerationBatchCapabilities", response.json())
        assert not response.json()["enabled"]
        assert response.json()["unavailable_reason"]["code"] == "ASSISTANT_NOT_READY"
    for path in EXTENSIONS:
        database["owner"].execute((ROOT / path).read_text())
    with client() as browser:
        response = browser.get(
            "/api/v1/authoring/generation-batch-capabilities", headers=cookie(seed["actor"])
        )
        assert response.status_code == 200, response.text
        assert not response.json()["enabled"]
        assert response.json()["unavailable_reason"]["code"] in {
            "MODEL_NOT_CONFIGURED",
            "ASSISTANT_PRICE_UNAVAILABLE",
        }
    price = uuid4()
    database["owner"].execute(
        """INSERT INTO design.assistant_price_versions(id,version,provider,model,currency,
        input_per_million_minor,output_per_million_minor,input_hard_ceiling,output_hard_ceiling,
        source_kind,source_uri,source_sha256,verified_at,valid_from,valid_until)
        VALUES(%s,%s,'deepseek','deepseek-flash','USD',1000000,1000000,2097152,8192,
        'explicit_mock_fixture','https://synthetic.invalid/batch-tariff',%s,now(),now()-interval '1 hour',now()+interval '4 hours')""",
        (
            price,
            "batch-mock-" + uuid4().hex,
            sha(b"explicit synthetic tariff; never payment authority"),
        ),
    )
    return database | {"price": price}


@pytest.fixture
def env(batch_database, monkeypatch):
    monkeypatch.setenv("WORKER_DATABASE_DSN", batch_database["worker_dsn"])
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    ids = clean(_seed_api({}))
    ids |= clean(_seed_worker(ids))
    ids |= clean(_confirm_api(ids))
    actor, bid = UUID(ids["actor"]), UUID(ids["bid"])
    clock = now()
    for scope, owner in (
        ("global", "assistant"),
        ("member", str(actor)),
        ("project", ids["canonical_project_key"]),
    ):
        batch_database["owner"].execute(
            """INSERT INTO design.assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason)
            VALUES(%s,%s,%s,'USD',%s,1000000000000,%s,%s,'explicit synthetic batch fixture only')""",
            (
                uuid4(),
                scope,
                owner,
                int(clock.timestamp() * 1000000),
                clock - timedelta(hours=1),
                clock + timedelta(hours=4),
            ),
        )
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, data, media: objects.__setitem__(key, data))
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    ref = {
        "document_version_id": ids["version"],
        "evidence_id": ids["evidence"],
        "source_id": ids["source"],
        "source_revision": 1,
    }
    with connection() as c:
        ref["source_revision"] = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (UUID(ids["source"]),)
        ).fetchone()["revision"]
    output = io.BytesIO()
    raster = Image.frombytes("RGB", (4, 4), uuid4().bytes * 3)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("fixture", "synthetic batch original")
    raster.save(output, format="PNG", pnginfo=metadata)
    raw = output.getvalue()
    normalized = rich_images.normalize(raw, "image/png")

    def descriptor(data, name):
        key = f"authoring-images/{bid}/{uuid4()}/{name}"
        objects[key] = data
        return {
            "digest": sha(data),
            "byte_size": len(data),
            "media_type": "image/png",
            "object_key": key,
        }

    with connection() as c:
        image = rich_assets.insert(
            c,
            bid,
            actor,
            "合成现场图",
            "明确登记本地合成像素",
            [ref],
            normalized["proof"],
            descriptor(raw, "original"),
            descriptor(normalized["bytes"], "normalized"),
        )
        draft = uuid4()
        c.execute("INSERT INTO drafts(id,bid_id,revision) VALUES(%s,%s,1)", (draft, bid))
        sections = []
        for ordinal, title in enumerate(("施工组织安排", "质量检查安排")):
            section = uuid4()
            document = deepcopy(rich_plan.__wrapped__()["original_content"])
            document["attrs"] = {
                "title": title,
                "ordinal": ordinal,
                "rule_ids": [],
                "source_refs": [ref],
            }

            def rename(node, prefix=f"chapter-{ordinal}-"):
                if "id" in node.get("attrs", {}):
                    node["attrs"]["id"] = prefix + node["attrs"]["id"]
                if node["type"] == "image":
                    node["attrs"].update(
                        asset_id=image["asset_id"], asset_revision=1, asset_version_id=image["id"]
                    )
                for child in node.get("content", []):
                    rename(child)

            rename(document)
            c.execute(
                "INSERT INTO sections(id,bid_id,draft_id,head_revision) VALUES(%s,%s,%s,1)",
                (section, bid, draft),
            )
            repository.append_section(c, bid, draft, section, 1, document, actor)
            sections.append({"id": section, "content": document})
        saved = repository.freeze(c, bid, draft, 1, "合成批次正文", actor=actor)
        c.execute("UPDATE bid_profiles SET current_draft_id=%s WHERE bid_id=%s", (draft, bid))
    value = {
        "actor": actor,
        "bid": bid,
        "draft": draft,
        "saved": saved,
        "sections": sections,
        "objects": objects,
        "ids": ids,
        "database": batch_database,
        "price": batch_database["price"],
        "calls": [],
        "raw": None,
        "mode": "success",
        "image": image,
    }

    def transport(request):
        value["calls"].append(json.loads(request.content))
        if value["mode"] == "timeout":
            raise httpx.ReadTimeout("explicit offline unknown fee", request=request)
        data = (
            value["raw"]
            if value["mode"] == "success"
            else {"unrecognized": "explicit malformed offline output"}
        )
        return httpx.Response(
            200,
            json={
                "id": "mock-batch-" + uuid4().hex,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(data, ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
            },
        )

    provider = DeepSeekClient(
        api_key="explicit-offline-fixture-only", transport=httpx.MockTransport(transport)
    )
    monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: provider))

    def forbidden(*args, **kwargs):
        raise AssertionError("Generation batch test attempted real model network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    with client() as browser:
        value["client"] = browser
        yield value


def headers(env, *, key=None, condition=None):
    return cookie(env["actor"]) | {
        "Origin": os.environ["APP_ORIGIN"],
        "X-CSRF-Token": SYNTHETIC_CSRF,
        "Idempotency-Key": key or uuid4().hex,
        "If-Match": condition or repository.draft_etag(env["draft"], 1),
    }


def base(env):
    return f"/api/v1/bids/{env['bid']}/drafts/{env['draft']}/generation-batches"


def create_body(env):
    return {
        "base_draft_revision": 1,
        "price_version_id": str(env["price"]),
        "currency": "USD",
        "amount_scale": 1000000000,
        "total_limit_minor": 20000000,
        "sections": [
            {
                "section_id": str(s["id"]),
                "base_section_revision": 1,
                "instruction": "依据已确认的合成资料补充" + s["content"]["attrs"]["title"],
                "source_version_ids": [env["ids"]["version"]],
                "selected_node_ids": None,
                "max_tokens": 2048,
                "budget_limit_minor": 10000000,
            }
            for s in env["sections"]
        ],
        "reason": "明确确认所有章基线、每章额度和批次总额",
    }


def create(env, body=None, key=None):
    body = body or create_body(env)
    key = key or uuid4().hex
    response = env["client"].post(base(env), json=body, headers=headers(env, key=key))
    assert response.status_code == 201, response.text
    contracts.validate("AuthoringGenerationBatchReceipt", response.json())
    batch = get(env, response.json()["batch_id"])
    return batch, response.json(), body, key


def get(env, identity):
    response = env["client"].get(base(env) + "/" + str(identity), headers=cookie(env["actor"]))
    assert response.status_code == 200, response.text
    contracts.validate("AuthoringGenerationBatch", response.json())
    assert response.headers["etag"] == response.json()["etag"]
    return response.json()


def run(env, batch, index, *, mode="success", publish=True):
    attempt = batch["sections"][index]["attempts"][-1]
    with connection() as c:
        job = jobs.job(c, UUID(attempt["job_id"]))
        plan = job["input_manifest"]["plan"]
        editable = next(
            v for v in plan["patch_scope"]["replacement_targets"] if v["node_id"].endswith("-p1")
        )
        anchor = next(
            v
            for v in plan["patch_scope"]["insertion_targets"]
            if v["after_node_id"] == editable["node_id"]
        )
        env["raw"] = {
            "replacements": [
                editable
                | {"inline": [{"type": "text", "text": "经核对的新说明；表格图片仍完整保留"}]}
            ],
            "insertions": [
                anchor | {"paragraphs": [{"inline": [{"type": "text", "text": "新增实施步骤"}]}]}
            ],
            "evidence_ids": [env["ids"]["evidence"]],
        }
        message = c.execute(
            "SELECT payload FROM outbox WHERE operation_id=%s AND topic='tender.task.assistant.v1'",
            (job["operation_id"],),
        ).fetchone()["payload"]
    env["mode"] = mode
    before = len(env["calls"])
    engine.handle(message)
    engine.handle(message)
    assert len(env["calls"]) - before == 1
    if publish:
        coordinator.tick([UUID(attempt["job_id"])])
    return get(env, batch["batch_id"])


def selection(batch, index):
    chapter = batch["sections"][index]
    current = chapter["attempts"][-1]
    return {
        "section_id": chapter["section_id"],
        **{k: current[k] for k in ("attempt", "job_id", "action_id", "candidate_digest")},
    }


def resolve_body(batch, indices=(0, 1), decision="apply"):
    return {
        "decision": decision,
        "batch_digest": batch["batch_digest"],
        "selections": [selection(batch, i) for i in indices] if decision == "apply" else [],
        "reason": "逐章看过完整前后文后明确处理",
    }


def counts(env):
    with connection() as c:
        return {
            "draft": repository.draft_view(c, env["bid"], env["draft"])["revision"],
            "sections": c.execute(
                "SELECT count(*) AS n FROM section_revisions WHERE draft_id=%s", (env["draft"],)
            ).fetchone()["n"],
            **{
                table: c.execute(
                    "SELECT count(*) AS n FROM " + table + " WHERE bid_id=%s", (env["bid"],)
                ).fetchone()["n"]
                for table in (
                    "assistant_jobs",
                    "assistant_generation_batches",
                    "assistant_generation_batch_attempts",
                    "assistant_generation_batch_resolutions",
                    "proposed_actions",
                )
            },
            "reservations": c.execute(
                "SELECT count(*) AS n FROM assistant_budget_reservations r JOIN assistant_jobs j ON j.id=r.job_id WHERE j.bid_id=%s",
                (env["bid"],),
            ).fetchone()["n"],
            "outbox": c.execute(
                "SELECT count(*) AS n FROM outbox ob JOIN operations op ON op.id=ob.operation_id WHERE op.bid_id=%s",
                (env["bid"],),
            ).fetchone()["n"],
        }


def test_actual_nonowner_two_chapters_ledger_preview_atomic_save_and_original_replay(env):
    assert_role()
    assert_role(True)
    with connection(True) as c:
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.assistant_generation_batch_resolutions','INSERT') AS ok"
        ).fetchone()["ok"]
    caps = env["client"].get(
        "/api/v1/authoring/generation-batch-capabilities", headers=cookie(env["actor"])
    )
    assert caps.status_code == 200 and caps.json()["enabled"]
    contracts.validate("AuthoringGenerationBatchCapabilities", caps.json())
    batch, prepared, body, key = create(env)
    assert not env["calls"] and batch["budget"]["reserved_minor"] == 4198400
    assert counts(env)["draft"] == 1
    batch = run(env, batch, 0)
    assert batch["sections"][0]["attempts"][-1]["publication_state"] == "published", batch[
        "sections"
    ][0]
    blocked = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, (0,)),
        headers=headers(env),
    )
    assert (
        blocked.status_code == 409
        and blocked.json()["code"] == "AUTHORING_GENERATION_BATCH_RUNNING"
    )
    batch = run(env, batch, 1)
    assert batch["budget"]["charged_minor"] == 64 and batch["budget"]["reserved_minor"] == 0
    previews = []
    for index in range(2):
        current = batch["sections"][index]["attempts"][-1]
        response = env["client"].get(current["candidate_url"], headers=cookie(env["actor"]))
        assert response.status_code == 200, response.text
        candidate = response.json()
        contracts.validate("AuthoringGenerationBatchCandidate", candidate)
        assert candidate["before_digest"] == sha(candidate["before"])
        assert candidate["after_digest"] == sha(candidate["after"])
        assert candidate["changes"]["added_paragraphs"] == 1
        for kind in ("table", "image"):
            assert [n for n in candidate["before"]["content"] if n["type"] == kind] == [
                n for n in candidate["after"]["content"] if n["type"] == kind
            ]
        previews.append(candidate)
    # Share the actual synthetic service response with the browser acceptance
    # harness; never export session tokens, database credentials or business data.
    fixture = Path("/tmp/tender-completion-runtime/generation-batch-browser")
    fixture.mkdir(parents=True, exist_ok=True)
    with connection() as c:
        public_draft = repository.draft_view(c, env["bid"], env["draft"])
        image_versions = rich_assets.freeze_assets(
            c, env["bid"], [(env["image"]["asset_id"], 1, env["image"]["id"])]
        )
    for filename, value in {
        "batch.json": batch,
        "candidates.json": previews,
        "capabilities.json": caps.json(),
        "draft.json": public_draft,
        "sections.json": clean(env["sections"]),
        "image.json": env["image"],
    }.items():
        (fixture / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (fixture / "normalized.png").write_bytes(
        env["objects"][image_versions[0]["normalized_blob"]["object_key"]]
    )
    request = resolve_body(batch)
    applied_key = uuid4().hex
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=request,
        headers=headers(env, key=applied_key),
    )
    assert response.status_code == 200, response.text
    contracts.validate("AuthoringGenerationBatchReceipt", response.json())
    assert response.json()["draft_revision"] == 2
    assert counts(env)["sections"] == 4 and counts(env)["draft"] == 2
    with connection() as c:
        snapshot = repository.snapshot_content(c, env["bid"], UUID(response.json()["snapshot_id"]))
        assert snapshot["sections"] == [p["after"] for p in previews]
        for selection_ in request["selections"]:
            assert actions.view(c, UUID(selection_["action_id"]))["state"] == "executed"
    repeated = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=request,
        headers=headers(env, key=applied_key),
    )
    assert repeated.status_code == 200 and repeated.json() == response.json()
    repeated_create = env["client"].post(base(env), json=body, headers=headers(env, key=key))
    assert repeated_create.status_code == 201 and repeated_create.json() == prepared
    assert len(env["calls"]) == 2


def test_last_reservation_failure_rolls_back_entire_queue_and_header(env):
    # First real reservation succeeds, second exceeds the independently configured
    # aggregate member budget. The first outbox/job/hold must not survive.
    clock = now()
    env["database"]["owner"].execute(
        """INSERT INTO design.assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason)
        VALUES(%s,'member',%s,'USD',%s,3000000,%s,%s,'explicit synthetic rollback boundary')""",
        (
            uuid4(),
            str(env["actor"]),
            int(clock.timestamp() * 1000000),
            clock - timedelta(hours=1),
            clock + timedelta(hours=1),
        ),
    )
    before = counts(env)
    response = env["client"].post(base(env), json=create_body(env), headers=headers(env))
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ASSISTANT_BUDGET_EXHAUSTED"
    assert counts(env) == before and not env["calls"]


def retry_body(batch, index):
    chapter = batch["sections"][index]
    attempt = chapter["attempts"][-1]
    return {
        "batch_digest": batch["batch_digest"],
        "section_id": chapter["section_id"],
        "previous_attempt": attempt["attempt"],
        "previous_job_id": attempt["job_id"],
        "reason": "费用已核清，明确授权本章新的尝试",
    }


def test_known_paid_failure_explicit_retry_keeps_old_charge_and_exact_scope(env):
    request = create_body(env)
    request["sections"][0]["selected_node_ids"] = ["chapter-0-p1"]
    batch, _, _, _ = create(env, request)
    batch = run(env, batch, 0, mode="invalid")
    attempt = batch["sections"][0]["attempts"][-1]
    assert attempt["state"] == "failed" and attempt["budget_state"] == "settled"
    assert attempt["charged_minor"] == 32 and attempt["retry_allowed"]
    original_job = attempt["job_id"]
    request = retry_body(batch, 0)
    key = uuid4().hex
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/retry", json=request, headers=headers(env, key=key)
    )
    assert response.status_code == 200, response.text
    contracts.validate("AuthoringGenerationBatchReceipt", response.json())
    repeated = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/retry", json=request, headers=headers(env, key=key)
    )
    assert repeated.json() == response.json() and repeated.status_code == 200
    batch = get(env, batch["batch_id"])
    attempts = batch["sections"][0]["attempts"]
    assert (
        len(attempts) == 2
        and attempts[-1]["attempt"] == 2
        and attempts[-1]["job_id"] != original_job
    )
    assert batch["budget"]["charged_minor"] == 32 and batch["budget"]["reserved_minor"] == 4198400
    with connection() as c:
        old = jobs.job(c, UUID(original_job))["input_manifest"]
        new = jobs.job(c, UUID(attempts[-1]["job_id"]))["input_manifest"]
        assert old["plan"] == new["plan"] and old["project_memory"] == new["project_memory"]
        assert new["plan"]["patch_scope"]["selected_node_ids"] == ["chapter-0-p1"]
    batch = run(env, batch, 0)
    batch = run(env, batch, 1)
    assert batch["budget"]["charged_minor"] == 96
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch),
        headers=headers(env),
    )
    assert response.status_code == 200, response.text
    assert response.json()["draft_revision"] == 2 and len(env["calls"]) == 3


def test_unknown_fee_blocks_new_attempt_and_reject_preserves_original_hold(env):
    batch, _, _, _ = create(env)
    batch = run(env, batch, 0, mode="timeout")
    failed = batch["sections"][0]["attempts"][-1]
    assert failed["state"] == "failed" and failed["budget_state"] == "unknown"
    assert failed["requires_reconciliation"] and not failed["retry_allowed"]
    before = counts(env)
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/retry",
        json=retry_body(batch, 0),
        headers=headers(env),
    )
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_GENERATION_BATCH_RECONCILIATION_REQUIRED"
    )
    assert counts(env) == before and len(env["calls"]) == 1
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, decision="reject"),
        headers=headers(env, condition='"stale-but-explicit-reject"'),
    )
    assert response.status_code == 200, response.text
    assert response.json()["draft_revision"] is None
    rejected = get(env, batch["batch_id"])
    assert rejected["state"] == "rejected" and rejected["budget"]["requires_reconciliation"]
    assert rejected["budget"]["reserved_minor"] == 4198400 and counts(env)["draft"] == 1
    assert rejected["sections"][1]["attempts"][-1]["state"] == "cancel_requested"


def test_partial_apply_waits_for_publication_closes_batch_and_rejects_other_leaf(env):
    batch, _, _, _ = create(env)
    batch = run(env, batch, 0)
    batch = run(env, batch, 1, publish=False)
    with connection() as c:
        budget.settle(c, UUID(batch["sections"][1]["attempts"][-1]["job_id"]))
    batch = get(env, batch["batch_id"])
    assert batch["running_count"] == 1
    body = resolve_body(batch, (0,))
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve", json=body, headers=headers(env)
    )
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_GENERATION_BATCH_RUNNING"
    )
    coordinator.tick([UUID(batch["sections"][1]["attempts"][-1]["job_id"])])
    batch = get(env, batch["batch_id"])
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, (0,)),
        headers=headers(env),
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied_section_ids"] == [batch["sections"][0]["section_id"]]
    assert response.json()["unselected_section_ids"] == [batch["sections"][1]["section_id"]]
    assert counts(env)["sections"] == 3 and counts(env)["draft"] == 2
    with connection() as c:
        assert (
            actions.view(c, UUID(batch["sections"][1]["attempts"][-1]["action_id"]))["state"]
            == "rejected"
        )
        after = repository.latest_sections(c, env["bid"], env["draft"])
        assert after[1]["content"] == env["sections"][1]["content"] and after[1]["revision"] == 1
    second = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, (1,)),
        headers=headers(env),
    )
    assert (
        second.status_code == 409 and second.json()["code"] == "AUTHORING_GENERATION_BATCH_RESOLVED"
    )


def test_single_chapter_action_buttons_cannot_consume_batch_candidates(env):
    batch, _, _, _ = create(env)
    batch = run(env, batch, 0)
    action = batch["sections"][0]["attempts"][-1]["action_id"]
    path = "/api/v1/assistant/actions/" + action
    before = counts(env)
    view = env["client"].get(path, headers=cookie(env["actor"]))
    assert view.status_code == 200, view.text
    for decision in ("confirm", "reject"):
        response = env["client"].post(
            path + "/resolve",
            json={"decision": decision},
            headers=headers(env, condition=view.headers["etag"]),
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "AUTHORING_BATCH_CONFIRM_REQUIRED"
    assert counts(env) == before
    with connection() as c:
        assert (
            c.execute(
                "SELECT 1 FROM action_consumptions WHERE action_id=%s", (UUID(action),)
            ).fetchone()
            is None
        )


def test_last_chapter_database_failure_rolls_back_first_revision_all_consumptions_and_ack(env):
    batch, _, _, _ = create(env)
    batch = run(env, batch, 0)
    batch = run(env, batch, 1)
    owner = env["database"]["owner"]
    owner.execute("""CREATE FUNCTION design.synthetic_batch_last_section_failure() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic_last_chapter_failure' USING ERRCODE='23514'; END $$""")
    from psycopg import sql

    owner.execute(
        sql.SQL("""CREATE TRIGGER synthetic_batch_last_section_failure BEFORE INSERT ON design.section_revisions
        FOR EACH ROW WHEN(NEW.section_id={} AND NEW.revision=2) EXECUTE FUNCTION design.synthetic_batch_last_section_failure()""").format(
            sql.Literal(env["sections"][1]["id"])
        )
    )
    before = counts(env)
    key = uuid4().hex
    try:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="synthetic_last_chapter_failure"),
            connection() as c,
        ):
            service.resolve(
                c,
                env["bid"],
                env["draft"],
                UUID(batch["batch_id"]),
                env["actor"],
                key,
                resolve_body(batch),
                batch["base_draft_etag"],
            )
    finally:
        owner.execute(
            "DROP TRIGGER synthetic_batch_last_section_failure ON design.section_revisions"
        )
        owner.execute("DROP FUNCTION design.synthetic_batch_last_section_failure()")
    assert counts(env) == before
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM commands WHERE actor_id=%s AND idempotency_key=%s", (env["actor"], key)
        ).fetchone()
        for section in batch["sections"]:
            assert not c.execute(
                "SELECT 1 FROM action_consumptions WHERE action_id=%s",
                (UUID(section["attempts"][-1]["action_id"]),),
            ).fetchone()
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch),
        headers=headers(env, key=key),
    )
    assert response.status_code == 200, response.text


def test_source_withdrawal_keeps_readable_history_and_original_ack_but_blocks_apply(env):
    from packages.rag.indexing import withdraw_source

    batch, receipt, body, key = create(env)
    batch = run(env, batch, 0)
    batch = run(env, batch, 1)
    with connection() as c:
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s",
            (UUID(env["ids"]["root"]),),
        ).fetchone()["revision"]
        withdraw_source(c, env["bid"], UUID(env["ids"]["root"]), revision)
    before = counts(env)
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch),
        headers=headers(env),
    )
    assert response.status_code == 409, response.text
    assert counts(env) == before
    repeated = env["client"].post(base(env), json=body, headers=headers(env, key=key))
    assert repeated.status_code == 201 and repeated.json() == receipt
    history = env["client"].get(base(env), headers=cookie(env["actor"]))
    assert history.status_code == 200, history.text
    contracts.validate("AuthoringGenerationBatchPage", history.json())
    assert get(env, batch["batch_id"])["state"] == "open"
    view = env["client"].get(
        batch["sections"][0]["attempts"][-1]["candidate_url"], headers=cookie(env["actor"])
    )
    assert view.status_code == 200, view.text
    rejected = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, decision="reject"),
        headers=headers(env),
    )
    assert rejected.status_code == 200, rejected.text


def test_complete_frozen_input_capacity_rolls_back_all_attempts(env, monkeypatch):
    before = counts(env)
    monkeypatch.setattr(contracts, "MAX_FROZEN_BYTES", 1000)
    response = env["client"].post(base(env), json=create_body(env), headers=headers(env))
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "AUTHORING_GENERATION_BATCH_TOO_LARGE"
    assert counts(env) == before and not env["calls"]


def test_concurrent_same_key_creates_one_batch_and_one_set_of_holds(env):
    barrier = Barrier(2)
    request = create_body(env)
    key = uuid4().hex

    def send():
        barrier.wait()
        return env["client"].post(base(env), json=request, headers=headers(env, key=key))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send) for _ in range(2)]
        responses = [future.result(timeout=20) for future in futures]
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    actual = counts(env)
    assert actual["assistant_generation_batches"] == 1
    assert (
        actual["assistant_jobs"]
        == actual["reservations"]
        == actual["assistant_generation_batch_attempts"]
        == 2
    )
    assert actual["outbox"] == 2 and not env["calls"]
    changed = deepcopy(request)
    changed["reason"] = "different explicit request"
    rejected = env["client"].post(base(env), json=changed, headers=headers(env, key=key))
    assert rejected.status_code == 409 and rejected.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert counts(env) == actual


def test_changed_draft_cas_and_closed_project_block_new_work_but_replay_exact_ack(env, monkeypatch):
    from packages.domain.runtime import Command
    from packages.lifecycle import service as lifecycle

    batch, receipt, body, key = create(env)
    batch = run(env, batch, 0)
    batch = run(env, batch, 1)
    with connection() as c:
        original = env["sections"][0]
        content = deepcopy(original["content"])
        content["content"][1]["content"] = [{"type": "text", "text": "成员明确手工修改后的原文"}]
        repository.save_draft(
            c,
            env["bid"],
            env["draft"],
            env["actor"],
            {
                "base_draft_revision": 1,
                "changes": [
                    {
                        "section_id": str(original["id"]),
                        "base_section_revision": 1,
                        "schema_digest": section_patch_set.materialize(
                            jobs.job(c, UUID(batch["sections"][0]["attempts"][-1]["job_id"]))[
                                "input_manifest"
                            ]["plan"],
                            batch["sections"][0]["attempts"][-1]["writing_plan_id"],
                            c.execute(
                                "SELECT payload FROM assistant_outputs WHERE job_id=%s",
                                (UUID(batch["sections"][0]["attempts"][-1]["job_id"]),),
                            ).fetchone()["payload"],
                        )["schema_digest"],
                        "content": content,
                    }
                ],
            },
            batch["base_draft_etag"],
        )
    before = counts(env)
    response = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch),
        headers=headers(env),
    )
    assert response.status_code == 412, response.text
    assert counts(env) == before
    with connection() as c:
        command = Command(
            c,
            env["actor"],
            "synthetic-lifecycle-terminate",
            env["bid"],
            uuid4().hex,
            {"action": "terminate"},
        )
        command.finish(
            lifecycle.change(
                c, env["bid"], env["actor"], "terminate", "explicit synthetic closure", command.id
            )
        )

    def no_model(cls):
        raise DomainError("MODEL_NOT_CONFIGURED", "synthetic removed model configuration", 503)

    monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(no_model))
    replay = env["client"].post(base(env), json=body, headers=headers(env, key=key))
    assert replay.status_code == 201 and replay.json() == receipt
    fresh = env["client"].post(base(env), json=body, headers=headers(env))
    assert fresh.status_code == 409 and fresh.json()["code"] == "PROJECT_WORK_CLOSED"
    rejected = env["client"].post(
        base(env) + "/" + batch["batch_id"] + "/resolve",
        json=resolve_body(batch, decision="reject"),
        headers=headers(env),
    )
    assert rejected.status_code == 200, rejected.text
    assert counts(env)["draft"] == before["draft"]


def test_identical_content_in_other_draft_does_not_bypass_native_independence_gate(env):
    request = create_body(env)
    request["sections"] = request["sections"][:1]
    batch, _, _, _ = create(env, request)
    with connection() as c:
        draft, section = uuid4(), uuid4()
        c.execute("INSERT INTO drafts(id,bid_id,revision) VALUES(%s,%s,1)", (draft, env["bid"]))
        c.execute(
            "INSERT INTO sections(id,bid_id,draft_id,head_revision) VALUES(%s,%s,%s,1)",
            (section, env["bid"], draft),
        )
        repository.append_section(
            c, env["bid"], draft, section, 1, env["sections"][0]["content"], env["actor"]
        )
        repository.freeze(c, env["bid"], draft, 1, "合成相同内容的其他草稿", actor=env["actor"])
        c.execute(
            "UPDATE bid_profiles SET current_draft_id=%s WHERE bid_id=%s", (draft, env["bid"])
        )
    other = env | {
        "draft": draft,
        "sections": [{"id": section, "content": env["sections"][0]["content"]}],
    }
    body = create_body(other)
    body["sections"][0]["instruction"] = "不同文字指令不授权相同内容重复扣费"
    before = counts(env)
    response = env["client"].post(base(other), json=body, headers=headers(other))
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "AUTHORING_GENERATION_BATCH_INDEPENDENCE_UNPROVEN"
    assert set(response.json()["details"]["section_ids"]) == {
        str(section),
        batch["sections"][0]["section_id"],
    }
    assert counts(env) == before and not env["calls"]


def test_restricted_direct_sql_cannot_consume_leaf_or_mutate_immutable_batch(env):
    from packages.domain.runtime import Command

    batch, _, _, _ = create(env)
    batch = run(env, batch, 0)
    action = UUID(batch["sections"][0]["attempts"][-1]["action_id"])
    before = counts(env)
    with (
        pytest.raises(
            psycopg.errors.CheckViolation, match="generation_batch_leaf_requires_atomic_resolution"
        ),
        connection() as c,
    ):
        command = Command(c, env["actor"], "synthetic-forged-leaf", action, uuid4().hex, {})
        c.execute(
            "INSERT INTO action_consumptions(action_id,command_id,consumed_by,result) VALUES(%s,%s,%s,%s)",
            (
                action,
                command.id,
                env["actor"],
                Jsonb({"assistant_resolution": {"state": "executed", "http_status": 200}}),
            ),
        )
        command.finish({"synthetic": "forged direct consumption"})
    assert counts(env) == before
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection() as c:
        c.execute(
            "UPDATE assistant_generation_batches SET digest=%s WHERE id=%s",
            ("a" * 64, UUID(batch["batch_id"])),
        )
    with connection() as c:
        assert actions.view(c, action)["state"] == "pending"
        assert not c.execute(
            "SELECT 1 FROM action_consumptions WHERE action_id=%s", (action,)
        ).fetchone()
