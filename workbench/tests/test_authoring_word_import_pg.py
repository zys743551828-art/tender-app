"""Fresh isolated PG17, nonowner API/Worker and real ASGI; memory object transport.

No paid model, network object store, Kafka consumer or Word renderer is started.
Run serially with the existing disposable requirements database fixture.
"""
# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Barrier, local
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_authoring_docx_import_parser import (
    heading,
    image_package,
    image_paragraph,
    merged_table,
    package,
    paragraph,
)
from test_authoring_integration import change
from test_authoring_integration import draft as legacy_draft
from test_authoring_structure_integration import tree_action
from test_bid_package_requirements_api import database
from test_word_intake_integration import disabled, original

from apps.api import authoring_word_import
from apps.api.auth import csrf
from packages.authoring import docx_import_contracts as contracts
from packages.authoring import docx_import_parser as parser
from packages.authoring import docx_import_service as service
from packages.authoring import docx_import_sources as provenance
from packages.authoring import generation, patches, snapshot_structure, structure_repository
from packages.authoring.repository import draft_view, save_draft, snapshot_content
from packages.domain import storage
from packages.domain.runtime import (
    ROOT,
    Command,
    DomainError,
    assert_role,
    connection,
    etag,
    now,
    secret_hash,
    sha,
)
from packages.rag.indexing import original_source_id
from packages.word_intake.repository import word_view

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires dedicated disposable PG17 nonowner Word import fixture",
)


@pytest.fixture(scope="module")
def word_database(database):
    owner = database["owner"]
    assert owner.execute("SELECT to_regclass('design.authoring_word_imports') AS item").fetchone()[
        "item"
    ]
    assert (
        owner.execute("SELECT to_regclass('design.word_intake_receipts') AS item").fetchone()[
            "item"
        ]
        is None
    )
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        disabled_capability = service.capabilities(c)
        assert disabled_capability["enabled"] is False
        assert (
            disabled_capability["unavailable_reason"]["code"]
            == "AUTHORING_WORD_IMPORT_NOT_CONFIGURED"
        )
    # The base schema already succeeded without this optional extension.
    owner.execute((ROOT / "packages/word_intake/schema.sql").read_text())
    return database


@pytest.fixture
def env(word_database, monkeypatch):
    monkeypatch.setenv("WORKER_DATABASE_DSN", word_database["worker_dsn"])
    actor, bid, draft, saved, section = legacy_draft.__wrapped__()
    with connection() as c:
        c.execute("INSERT INTO stream_heads(id,bid_id) VALUES(%s,%s)", (uuid4(), bid))
    active = local()

    @contextmanager
    def tracked_connection():
        active.depth = getattr(active, "depth", 0) + 1
        try:
            with connection() as c:
                yield c
        finally:
            active.depth -= 1

    objects = {}

    def get(key):
        assert getattr(active, "depth", 0) == 0, "Object read inside import DB transaction"
        return objects[key]

    def put(key, data, _media):
        assert getattr(active, "depth", 0) == 0, "Object write inside import DB transaction"
        objects[key] = data

    monkeypatch.setattr(service, "connection", tracked_connection)
    monkeypatch.setattr(storage, "get", get)
    monkeypatch.setattr(storage, "put", put)
    result = {
        "actor": actor,
        "bid": bid,
        "draft": draft,
        "saved": saved,
        "section": section,
        "objects": objects,
    }
    data = image_package(
        heading("施工方法")
        + paragraph("合成准确原文 120 天")
        + merged_table()
        + image_paragraph()
        + heading("子章节", 2)
        + paragraph("子级说明")
    )
    result["data"] = data
    result["word"] = original(result, data, profile=disabled())
    return result


def body_for(env, *, document=None, data=None, revision=1):
    data = env["data"] if data is None else data
    return {
        "source_document_version_id": str(document or env["word"]["version"]),
        "source_digest": sha(data),
        "source_byte_size": len(data),
        "base_draft_revision": revision,
        "method_digest": sha(parser.method_identity()),
        "reason": "合成已核对原件，申请完整候选",
    }


def prepared(env, *, key=None, body=None):
    body = body or body_for(env)
    key = key or uuid4().hex
    value, replay = service.prepare(
        env["bid"],
        env["draft"],
        env["actor"],
        key,
        body,
        etag("draft", env["draft"], body["base_draft_revision"]),
    )
    assert not replay
    contracts.validate("AuthoringWordImportCandidate", value["body"])
    return value["body"], key, body


def resolution_body(candidate, decision="append"):
    return {
        "decision": decision,
        "candidate_digest": candidate["candidate_digest"],
        "acknowledged_issue_ids": [
            item["id"] for item in candidate["issues"] if item["severity"] == "warning"
        ]
        if decision == "append"
        else [],
        "reason": "明确确认逐项限制并追加" if decision == "append" else "明确拒绝本候选",
    }


def resolve(env, candidate, *, key=None, body=None, condition=None):
    body = body or resolution_body(candidate)
    return service.resolve(
        env["bid"],
        env["draft"],
        UUID(candidate["candidate_id"]),
        env["actor"],
        key or uuid4().hex,
        body,
        candidate["base_draft_etag"] if condition is None else condition,
    )


def counts(env):
    with connection() as c:
        return {
            "revision": draft_view(c, env["bid"], env["draft"])["revision"],
            "sections": c.execute(
                "SELECT count(*) AS n FROM sections WHERE draft_id=%s", (env["draft"],)
            ).fetchone()["n"],
            "images": c.execute(
                "SELECT count(*) AS n FROM authoring_image_assets WHERE bid_id=%s", (env["bid"],)
            ).fetchone()["n"],
            "resolutions": c.execute(
                "SELECT count(*) AS n FROM authoring_word_import_resolutions WHERE draft_id=%s",
                (env["draft"],),
            ).fetchone()["n"],
        }


def test_actual_asgi_prepare_private_preview_explicit_append_and_stable_adoption(env):
    assert_role()
    assert_role(True)
    token = uuid4().hex
    with connection() as c:
        c.execute(
            "INSERT INTO sessions(id,member_id,token_digest,csrf_digest,expires_at) VALUES(%s,%s,%s,%s,%s)",
            (
                uuid4(),
                env["actor"],
                secret_hash(token),
                sha(csrf(token).encode()),
                now() + timedelta(hours=1),
            ),
        )
        assert service.capabilities(c)["enabled"]
        browser_caps = service.capabilities(c)
        browser_draft = draft_view(c, env["bid"], env["draft"])
        browser_originals = {
            "items": [word_view(c, env["bid"], env["word"]["version"])],
            "has_more": False,
            "next_after": None,
        }
        assert not c.execute(
            "SELECT 1 FROM document_file_versions WHERE version_id=%s", (env["word"]["version"],)
        ).fetchone()
    app = FastAPI()
    app.include_router(authoring_word_import.router)

    @app.exception_handler(DomainError)
    async def error(_request, exc):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    path = f"/api/v1/bids/{env['bid']}/drafts/{env['draft']}/word-imports"
    headers = {
        "Origin": os.environ["APP_ORIGIN"],
        "X-CSRF-Token": csrf(token),
        "Idempotency-Key": uuid4().hex,
        "If-Match": etag("draft", env["draft"], 1),
    }
    with TestClient(app) as client:
        client.cookies.set("session", token)
        denied = client.post(path, json=body_for(env))
        assert denied.status_code == 403
        accepted = client.post(path, json=body_for(env), headers=headers)
        assert accepted.status_code == 201, accepted.text
        candidate = accepted.json()
        assert candidate["can_apply"] and candidate["state"] == "ready"
        assert counts(env) == {"revision": 1, "sections": 1, "images": 0, "resolutions": 0}
        assert "object_key" not in str(candidate)
        image = candidate["images"][0]
        preview = client.get(path + f"/{candidate['candidate_id']}/images/{image['key']}")
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
        assert sha(preview.content) == image["digest"] == preview.headers["X-Content-SHA256"]
        with connection() as c:
            before, _ = provenance.capture(c, env["bid"], env["word"]["version"])
            # Same normal file adoption identity: expected revision is the immutable version revision.
            c.execute(
                "INSERT INTO document_file_versions(bid_id,file_id,version_id,revision,previous_version_id) VALUES(%s,%s,%s,1,NULL)",
                (env["bid"], env["word"]["file"], env["word"]["version"]),
            )
            c.execute(
                "UPDATE document_files SET head_version_id=%s,revision=revision+1 WHERE id=%s",
                (env["word"]["version"], env["word"]["file"]),
            )
            c.execute(
                "UPDATE upload_transfers SET committed_binding_id=current_binding_id,revision=revision+1 WHERE upload_id=%s",
                (env["word"]["upload"],),
            )
        with connection() as c:
            after, _ = provenance.capture(c, env["bid"], env["word"]["version"])
            assert before == after
        applied = client.post(
            path + f"/{candidate['candidate_id']}/resolve",
            json=resolution_body(candidate),
            headers=headers | {"Idempotency-Key": uuid4().hex},
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        contracts.validate("AuthoringWordImportResult", result)
        assert result["draft_revision"] == 2 and len(result["created_section_ids"]) == 2
        assert client.get(path + f"/{candidate['candidate_id']}").json()["state"] == "applied"
        assert (
            client.get(
                path.replace(str(env["bid"]), str(uuid4())) + f"/{candidate['candidate_id']}"
            ).status_code
            == 404
        )
    with connection() as c:
        snap = snapshot_content(c, env["bid"], UUID(result["snapshot_id"]))
        assert snap["sections"][0] == env["section"]["content"]
        imported = snap["sections"][1]
        assert {node["type"] for node in imported["content"]} >= {"paragraph", "table", "image"}
        assert (
            snap["authoring_structure"]["nodes"][2]["parent_id"] == result["created_section_ids"][0]
        )
        assert counts(env)["images"] == 1
    with connection(True) as c:
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.authoring_word_imports','SELECT') AS allowed"
        ).fetchone()["allowed"]
        frozen = snapshot_content(c, env["bid"], UUID(result["snapshot_id"]))
        authority = snapshot_structure.frozen_authority(
            c, env["bid"], frozen["authoring_structure"], frozen["sections"]
        )
        assert authority["word_imports"]["direct_source_ids"] == [
            str(original_source_id(env["word"]["version"]))
        ]
    with connection(True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        checked = provenance.assert_import_sources(
            c, env["bid"], frozen["authoring_structure"]["metadata"], lock_sources=False
        )
        assert checked["direct_source_ids"] == authority["word_imports"]["direct_source_ids"]
    output = os.environ.get("WORD_IMPORT_SYNTHETIC_DIRECTORY")
    if output:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        for name, value in (
            ("candidate", candidate),
            ("capabilities", browser_caps),
            ("draft", browser_draft),
            ("word-originals", browser_originals),
        ):
            (directory / (name + ".json")).write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            )
        (directory / ("image-" + image["key"] + ".png")).write_bytes(preview.content)


def test_old_exact_prepare_and_apply_ack_precede_closure_method_or_object_gates(env, monkeypatch):
    candidate, prep_key, prep_body = prepared(env)
    apply_key, apply_body = uuid4().hex, resolution_body(candidate)
    ack, _ = resolve(env, candidate, key=apply_key, body=apply_body)
    with connection() as c:
        c.execute("UPDATE bid_profiles SET phase='closed' WHERE bid_id=%s", (env["bid"],))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("old accepted receipt must not open parser/object gates")

    monkeypatch.setattr(parser, "method_identity", forbidden)
    monkeypatch.setattr(storage, "get", forbidden)
    old, replay = service.prepare(
        env["bid"], env["draft"], env["actor"], prep_key, prep_body, candidate["base_draft_etag"]
    )
    assert replay and old["body"] == candidate
    repeated, replay = resolve(env, candidate, key=apply_key, body=apply_body)
    assert replay and repeated == ack
    with pytest.raises(DomainError) as caught:
        resolve(
            env, candidate, key=apply_key, body=apply_body | {"reason": "不同请求不能冒用原回执"}
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert counts(env) == {"revision": 2, "sections": 3, "images": 1, "resolutions": 1}


@pytest.mark.parametrize("gate", ["source", "ancestor", "closed", "cas", "image"])
def test_stale_source_ancestor_lifecycle_draft_or_bytes_reject_without_partial_apply(env, gate):
    ancestor = None
    if gate == "ancestor":
        with connection() as c:
            ancestor = uuid4()
            c.execute(
                "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) SELECT %s,v.id,'document','prebid_content',v.obtained_at,b.digest FROM document_versions v JOIN blobs b ON b.id=v.blob_id WHERE v.id=%s",
                (ancestor, env["word"]["version"]),
            )
            c.execute(
                "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now())",
                (ancestor,),
            )
            provenance.ensure_original(c, env["bid"], env["word"]["version"])
            c.execute(
                "INSERT INTO retrieval.lineage_edges(parent_id,child_id) VALUES(%s,%s)",
                (ancestor, original_source_id(env["word"]["version"])),
            )
    candidate, _, _ = prepared(env)
    before = counts(env)
    if gate in {"source", "ancestor"}:
        with connection() as c:
            c.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                (ancestor or original_source_id(env["word"]["version"]),),
            )
    elif gate == "closed":
        with connection() as c:
            c.execute("UPDATE bid_profiles SET phase='terminated' WHERE bid_id=%s", (env["bid"],))
    elif gate == "cas":
        with connection() as c:
            save_draft(
                c,
                env["bid"],
                env["draft"],
                env["actor"],
                change(env["section"], "并行人工修订"),
                candidate["base_draft_etag"],
            )
        before["revision"] = 2
    else:
        with connection() as c:
            descriptor = service.image_descriptor(
                c,
                env["bid"],
                env["draft"],
                UUID(candidate["candidate_id"]),
                UUID(candidate["images"][0]["key"]),
            )
        env["objects"][descriptor["object_key"]] += b"corrupt"
    with pytest.raises(DomainError) as caught:
        resolve(env, candidate)
    assert caught.value.status in {409, 412}
    assert counts(env) == before
    with connection() as c:
        assert (
            service.load(c, env["bid"], env["draft"], UUID(candidate["candidate_id"]))["state"]
            == "ready"
        )
    rejected, _ = resolve(
        env, candidate, body=resolution_body(candidate, "reject"), condition='"old-unrelated-etag"'
    )
    assert rejected["body"]["state"] == "rejected"
    assert counts(env) == before | {"resolutions": 1}


def test_warned_and_blocked_candidates_require_exact_confirmation_and_stay_readable(env):
    candidate, _, _ = prepared(env)
    assert candidate["warning_count"] > 0
    with pytest.raises(DomainError) as caught:
        resolve(env, candidate, body=resolution_body(candidate) | {"acknowledged_issue_ids": []})
    assert caught.value.code == "AUTHORING_WORD_IMPORT_LOSS_ACK_REQUIRED"
    blocked_data = package(
        heading("未接受修订") + '<w:ins w:id="9">' + paragraph("修订文字") + "</w:ins>"
    )
    word = original(env, blocked_data, filename="synthetic-blocked.docx", profile=disabled())
    blocked, _, _ = prepared(env, body=body_for(env, document=word["version"], data=blocked_data))
    assert blocked["state"] == "blocked" and not blocked["can_apply"]
    body = resolution_body(blocked) | {
        "acknowledged_issue_ids": [issue["id"] for issue in blocked["issues"]]
    }
    with pytest.raises(DomainError) as caught:
        resolve(env, blocked, body=body)
    assert caught.value.code == "AUTHORING_WORD_IMPORT_BLOCKED"
    with connection() as c:
        first = service.history(c, env["bid"], env["draft"], limit=1)
        second = service.history(c, env["bid"], env["draft"], cursor=first["next_cursor"], limit=1)
        contracts.validate("AuthoringWordImportPage", first)
        contracts.validate("AuthoringWordImportPage", second)
        assert first["items"][0]["candidate_id"] == blocked["candidate_id"]
        assert first["has_more"] and not second["has_more"]
        assert {first["items"][0]["candidate_id"], second["items"][0]["candidate_id"]} == {
            candidate["candidate_id"],
            blocked["candidate_id"],
        }
    resolve(env, blocked, body=resolution_body(blocked, "reject"))
    assert counts(env) == {"revision": 1, "sections": 1, "images": 0, "resolutions": 1}


def test_two_concurrent_explicit_appends_consume_candidate_only_once(env):
    candidate, _, _ = prepared(env)
    barrier = Barrier(2)

    def apply(_index):
        barrier.wait()
        try:
            return resolve(env, candidate)[0]["body"]
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, [0, 1]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "AUTHORING_WORD_IMPORT_ALREADY_RESOLVED" in results
    assert counts(env) == {"revision": 2, "sections": 3, "images": 1, "resolutions": 1}


def test_nonowner_cannot_mutate_immutable_history_or_forge_resolution_ack(env):
    candidate, _, _ = prepared(env)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection() as c:
        c.execute(
            "UPDATE authoring_word_imports SET manifest='{}' WHERE id=%s",
            (UUID(candidate["candidate_id"]),),
        )
    with pytest.raises(psycopg.errors.CheckViolation), connection() as c:
        command = Command(
            c, env["actor"], service.RESOLVE_KIND, UUID(candidate["candidate_id"]), uuid4().hex, {}
        )
        body = {
            "bid_id": str(env["bid"]),
            "draft_id": str(env["draft"]),
            "candidate_id": candidate["candidate_id"],
            "decision": "reject",
        }
        c.execute(
            "INSERT INTO authoring_word_import_resolutions(candidate_id,bid_id,draft_id,command_id,resolved_by,decision,result,digest) VALUES(%s,%s,%s,%s,%s,'reject',%s,%s)",
            (
                UUID(candidate["candidate_id"]),
                env["bid"],
                env["draft"],
                command.id,
                env["actor"],
                Jsonb(body),
                sha(body),
            ),
        )
        command.finish(body)
    assert counts(env)["resolutions"] == 0


def test_imported_rich_paragraph_proposal_preserves_table_and_image_and_withdrawal_blocks_new_ai_use(
    env,
):
    candidate, _, _ = prepared(env)
    applied, _ = resolve(env, candidate)
    section_id = UUID(applied["body"]["created_section_ids"][0])
    with connection() as c:
        row = c.execute(
            "SELECT * FROM section_revisions WHERE section_id=%s AND revision=1", (section_id,)
        ).fetchone()
        paragraph_node = next(
            node for node in row["content"]["content"] if node["type"] == "paragraph"
        )
        replacement = deepcopy(paragraph_node)
        replacement["content"] = [{"type": "text", "text": "人工明确预览的新段落"}]
        proposal = patches.create_proposal(
            c,
            env["bid"],
            section_id,
            1,
            paragraph_node["attrs"]["id"],
            sha(paragraph_node),
            replacement,
            [],
        )
    with connection() as c:
        command = Command(c, env["actor"], "synthetic-word-rich-patch", section_id, uuid4().hex, {})
        saved = patches.apply_proposal(
            c,
            env["bid"],
            UUID(proposal["action_id"]),
            env["actor"],
            command.id,
            etag("draft", env["draft"], 2),
        )
        command.finish(saved)
        fresh = c.execute(
            "SELECT * FROM section_revisions WHERE section_id=%s AND revision=2", (section_id,)
        ).fetchone()
        assert [node for node in fresh["content"]["content"] if node["type"] != "paragraph"] == [
            node for node in row["content"]["content"] if node["type"] != "paragraph"
        ]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM section_revisions WHERE draft_id=%s", (env["draft"],)
            ).fetchone()["n"]
            == 4
        )
    with connection() as c:
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (original_source_id(env["word"]["version"]),),
        )
    with pytest.raises(DomainError), connection() as c:
        patches.create_proposal(
            c,
            env["bid"],
            section_id,
            2,
            replacement["attrs"]["id"],
            sha(replacement),
            replacement,
            [],
        )
    with pytest.raises(DomainError), connection() as c:
        generation.freeze_generation_plan(
            c,
            env["bid"],
            {
                "section_id": str(section_id),
                "base_section_revision": 2,
                "instruction": "合成禁止外发测试",
                "source_version_ids": [],
            },
        )


def test_real_copy_delete_and_restore_keep_source_only_for_active_descendants(env):
    candidate, _, _ = prepared(env)
    appended, _ = resolve(env, candidate)
    original_id = appended["body"]["created_section_ids"][0]
    with connection() as c:
        copied, _ = tree_action(
            c,
            env["actor"],
            env["bid"],
            env["draft"],
            2,
            [
                {
                    "op": "copy",
                    "section_id": original_id,
                    "client_key": "copied-import",
                    "parent": None,
                    "ordinal": 2,
                }
            ],
        )
        copied_id = copied["created_ids"]["copied-import"]
    with connection() as c:
        _, removed = tree_action(
            c,
            env["actor"],
            env["bid"],
            env["draft"],
            3,
            [{"op": "delete", "section_id": original_id}],
        )
        snap = snapshot_content(c, env["bid"], UUID(removed["snapshot_id"]))
        extension = snap["authoring_structure"]
        assert provenance.import_source_ids(extension["metadata"], section_ids=[copied_id]) == [
            str(original_source_id(env["word"]["version"]))
        ]
        frozen_proof = deepcopy(extension["metadata"]["word_import_sources"])
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (original_source_id(env["word"]["version"]),),
        )
    with pytest.raises(DomainError), connection(True) as c:
        snapshot_structure.frozen_authority(c, env["bid"], extension, snap["sections"])
    with connection() as c:
        _, removed_copy = tree_action(
            c,
            env["actor"],
            env["bid"],
            env["draft"],
            4,
            [{"op": "delete", "section_id": copied_id}],
        )
        snap = snapshot_content(c, env["bid"], UUID(removed_copy["snapshot_id"]))
        assert snap["authoring_structure"]["metadata"]["word_import_sources"] == frozen_proof
    with connection(True) as c:
        authority = snapshot_structure.frozen_authority(
            c, env["bid"], snap["authoring_structure"], snap["sections"]
        )
        assert "word_imports" not in authority
    with pytest.raises(DomainError), connection() as c:
        structure_repository.preview(
            c,
            env["bid"],
            env["draft"],
            env["actor"],
            {
                "base_draft_revision": 5,
                "changes": [
                    {"op": "restore", "section_id": original_id, "parent": None, "ordinal": 1}
                ],
            },
            etag("draft", env["draft"], 5),
        )


def test_capacity_is_rejected_before_persisting_a_ready_candidate_or_images(env):
    data = package("".join(heading(f"合成容量章节 {i}") + paragraph("正文") for i in range(500)))
    word = original(env, data, filename="synthetic-capacity.docx", profile=disabled())
    with pytest.raises(DomainError) as caught:
        prepared(env, body=body_for(env, document=word["version"], data=data))
    assert caught.value.code == "AUTHORING_WORD_IMPORT_DRAFT_CAPACITY"
    assert counts(env) == {"revision": 1, "sections": 1, "images": 0, "resolutions": 0}
    with connection() as c:
        assert service.history(c, env["bid"], env["draft"])["items"] == []
