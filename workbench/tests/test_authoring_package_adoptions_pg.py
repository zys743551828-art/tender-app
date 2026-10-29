"""Real PG/nonowner/Worker Word publication; explicit memory objects, no renderer/model.

Uses the existing disposable fresh-schema fixture. Run alone/serially with
FUSION_REQUIREMENTS_ADMIN_DSN; this is not a real Word/PDF visual acceptance.
"""
# ruff: noqa: F401,F811

import copy
import io
import os
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb
from test_bid_package_requirements_api import database

from apps.worker import engine
from packages.authoring import package_adoptions, package_outputs
from packages.authoring.build_repository import DEFAULT_TEMPLATE_ID, freeze_build
from packages.authoring.content import SCHEMA_DIGEST
from packages.authoring.repository import create_draft, save_draft
from packages.domain import bid_package_service, storage
from packages.domain.runtime import Command, DomainError, connection, enqueue_plan, etag, sha
from packages.rag.indexing import ensure_parse_sources, original_source_id, parse_source_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated PG17 nonowner adoption fixture required",
)


@pytest.fixture
def env(database, monkeypatch):
    monkeypatch.setenv("WORKER_DATABASE_DSN", database["worker_dsn"])
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("AUTHORING_RICH_RENDER_PROFILE_PATH", raising=False)
    monkeypatch.delenv("AUTHORING_GENERATED_RENDER_PROFILE_PATH", raising=False)
    actor, bid, project, lot, round_id, bidder = [uuid4() for _ in range(6)]
    with connection() as c:
        c.execute(
            "INSERT INTO members(id,display_name) VALUES(%s,'synthetic authoring adoption')",
            (actor,),
        )
        c.execute(
            "INSERT INTO engineering_projects(id,title) VALUES(%s,'synthetic project')", (project,)
        )
        c.execute(
            "INSERT INTO engineering_lots(id,engineering_project_id,label) VALUES(%s,%s,'synthetic lot')",
            (lot, project),
        )
        c.execute(
            "INSERT INTO bid_rounds(id,engineering_project_id,lot_id,round_no) VALUES(%s,%s,%s,1)",
            (round_id, project, lot),
        )
        c.execute("INSERT INTO bidders(id,name) VALUES(%s,'synthetic bidder')", (bidder,))
        c.execute(
            "INSERT INTO bids(id,title,settings,created_by) VALUES(%s,'synthetic authoring adoption','{}',%s)",
            (bid, actor),
        )
        c.execute(
            "INSERT INTO bid_profiles(bid_id,round_id,bidder_id,phase) VALUES(%s,%s,%s,'working')",
            (bid, round_id, bidder),
        )
        c.execute("INSERT INTO stream_heads(id,bid_id) VALUES(%s,%s)", (uuid4(), bid))
        c.execute("INSERT INTO review_slots(bid_id,revision) VALUES(%s,1)", (bid,))
        draft, _ = create_draft(c, bid, actor, "synthetic authored draft")
        section = c.execute(
            "SELECT * FROM section_revisions WHERE draft_id=%s", (draft,)
        ).fetchone()
    document, blob, parse, evidence = [uuid4() for _ in range(4)]
    basis = f"explicit synthetic original basis for {bid}".encode()
    owner = database["owner"]
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        owner.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
            (blob, sha(basis), f"synthetic/{blob}", len(basis)),
        )
        owner.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic-basis.pdf',now(),'bid_body',%s)",
            (document, bid, blob, actor),
        )
        owner.execute(
            "INSERT INTO parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'partial','[]')",
            (parse, bid, document, "a" * 64, "b" * 64),
        )
        owner.execute(
            "INSERT INTO pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,100,100,0,'partial','[]')",
            (bid, parse),
        )
        owner.execute(
            "INSERT INTO evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text','synthetic basis',%s)",
            (evidence, bid, parse, sha("synthetic basis")),
        )
        owner.execute("UPDATE bid_profiles SET current_body_id=%s WHERE bid_id=%s", (document, bid))
    # Registration is a real worker transaction. The bootstrap fixture's owner
    # uses autocommit even inside its seeding context and is not a runtime role.
    with connection(True) as c:
        ensure_parse_sources(c, bid, parse, publish_readable=True)
        source_revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s",
            (parse_source_id(parse),),
        ).fetchone()["revision"]
    content = copy.deepcopy(section["content"])
    content["attrs"]["source_refs"] = [
        {
            "source_id": str(parse_source_id(parse)),
            "source_revision": source_revision,
            "evidence_id": str(evidence),
            "document_version_id": str(document),
        }
    ]
    content["content"][0]["content"] = [
        {"type": "text", "text": "Synthetic manual authoring, no claim about tender quality."}
    ]
    with connection() as c:
        saved = save_draft(
            c,
            bid,
            draft,
            actor,
            {
                "base_draft_revision": 1,
                "changes": [
                    {
                        "section_id": str(section["section_id"]),
                        "base_section_revision": 1,
                        "schema_digest": SCHEMA_DIGEST,
                        "content": content,
                    }
                ],
            },
            etag("draft", draft, 1),
        )
    objects = {}
    monkeypatch.setattr(storage, "put", lambda key, raw, media: objects.__setitem__(key, raw))
    monkeypatch.setattr(storage, "get", objects.__getitem__)
    monkeypatch.setattr(storage, "bucket", lambda: "explicit-memory-only")
    active = {"count": 0}
    real_connection = package_adoptions.connection

    @contextmanager
    def observed_connection():
        with real_connection() as c:
            active["count"] += 1
            try:
                yield c
            finally:
                active["count"] -= 1

    class MemoryClient:
        def get_object(self, *, Bucket, Key):
            assert active["count"] == 0, "adoption must close all transactions before object I/O"
            return {"Body": io.BytesIO(objects[Key])}

    monkeypatch.setattr(package_adoptions, "connection", observed_connection)
    monkeypatch.setattr(storage, "client", MemoryClient)
    return {
        "actor": actor,
        "bid": bid,
        "draft": draft,
        "saved": saved,
        "source_document": document,
        "parse": parse,
        "objects": objects,
        "database": database,
    }


def build(env):
    body = {
        "draft_id": str(env["draft"]),
        "draft_revision": 2,
        "template_version_id": str(DEFAULT_TEMPLATE_ID),
        "formats": ["docx"],
        "follow_up": "none",
    }
    with connection() as c:
        cmd = Command(c, env["actor"], "synthetic-adoption-build", env["bid"], uuid4().hex, body)
        input_id, manifest = freeze_build(c, env["bid"], body, env["actor"], None)
        operation = enqueue_plan(
            c,
            env["bid"],
            cmd.id,
            "build",
            {"id": str(input_id), "manifest": manifest},
            stages=[{"key": "build-document", "depends_on": []}],
            handler_version="export/1",
            topic="tender.task.export.v1",
        )
        build_id = uuid4()
        c.execute(
            "INSERT INTO builds(id,bid_id,input_id,operation_id) VALUES(%s,%s,%s,%s)",
            (build_id, env["bid"], input_id, UUID(operation["id"])),
        )
        message = c.execute(
            "SELECT payload FROM outbox WHERE operation_id=%s AND topic='tender.task.export.v1'",
            (UUID(operation["id"]),),
        ).fetchone()["payload"]
        cmd.finish({"build_id": str(build_id)})
    lease = engine.acquire(message)
    assert lease is not None
    computed = engine.run_compute(message, lease)
    assert engine.finish(message, lease, computed)
    with connection() as c:
        document = c.execute(
            "SELECT document_version_id FROM build_outputs WHERE build_id=%s AND format='docx' AND state='succeeded'",
            (build_id,),
        ).fetchone()["document_version_id"]
        snapshot = c.execute(
            "SELECT digest FROM draft_snapshots WHERE id=%s", (UUID(env["saved"]["snapshot_id"]),)
        ).fetchone()["digest"]
    request = {
        "snapshot_id": env["saved"]["snapshot_id"],
        "snapshot_digest": snapshot,
        "package_id": None,
        "member": {
            "member_id": "authored-word",
            "document_version_id": str(document),
            "purposes": ["technical"],
            "parts": [],
        },
        "reason": "explicit synthetic generated output selection",
    }
    return build_id, request, computed


def adopt(env, build_id, body, *, key=None, condition=None, final_auth=None):
    return package_adoptions.adopt(
        env["bid"],
        build_id,
        env["actor"],
        key or uuid4().hex,
        body,
        condition,
        final_auth=final_auth or (lambda: env["actor"]),
    )


def test_actual_word_generated_adoption_keeps_heads_and_exact_source_closure(env):
    build_id, body, _ = build(env)
    response, replay = adopt(env, build_id, body)
    assert not replay and response["status"] == 201
    saved = response["body"]
    assert saved["package"]["manifest"]["members"][0]["parse"]["status"] == "not_frozen"
    assert saved["package"]["review_ready"] is False
    with connection() as c:
        profile = c.execute(
            "SELECT current_body_id,current_material_id,current_review_id FROM bid_profiles WHERE bid_id=%s",
            (env["bid"],),
        ).fetchone()
        assert profile == {
            "current_body_id": env["source_document"],
            "current_material_id": None,
            "current_review_id": None,
        }
        root = original_source_id(UUID(body["member"]["document_version_id"]))
        ancestry = {
            row["ancestor_id"]
            for row in c.execute(
                "SELECT ancestor_id FROM retrieval.source_ancestors WHERE source_id=%s", (root,)
            ).fetchall()
        }
        assert ancestry == {
            root,
            parse_source_id(env["parse"]),
            original_source_id(env["source_document"]),
        }
        assert package_outputs.admitted(c, env["bid"], body["member"]["document_version_id"])
        assert not c.execute(
            "SELECT 1 FROM uploads WHERE verified_version_id=%s",
            (UUID(body["member"]["document_version_id"]),),
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM operations WHERE bid_id=%s AND kind<>'build'", (env["bid"],)
        ).fetchone()


def test_exact_ack_replays_after_closed_and_without_object_reverification(env, monkeypatch):
    build_id, body, _ = build(env)
    key = uuid4().hex
    accepted, _ = adopt(env, build_id, body, key=key)
    with connection() as c:
        c.execute("UPDATE bid_profiles SET phase='closed' WHERE bid_id=%s", (env["bid"],))
    monkeypatch.setattr(
        package_outputs,
        "verify_bytes",
        lambda *_args: pytest.fail("historical ACK must precede bytes/current gates"),
    )
    replayed, old = adopt(env, build_id, body, key=key)
    assert old and replayed == accepted


def test_blob_corruption_and_actor_change_do_not_leave_qualification_or_package(env):
    build_id, body, computed = build(env)
    object_key = computed["outputs"][0]["object_key"]
    original = env["objects"][object_key]
    env["objects"][object_key] = original + b"corruption"
    with pytest.raises(DomainError) as error:
        adopt(env, build_id, body)
    assert error.value.code == "ORIGINAL_BYTES_CORRUPTED"
    env["objects"][object_key] = original
    with pytest.raises(DomainError) as error:
        adopt(env, build_id, body, final_auth=uuid4)
    assert error.value.code == "AUTHORING_ADOPTION_ACTOR_CHANGED"
    with connection() as c:
        assert not c.execute("SELECT 1 FROM bid_packages WHERE bid_id=%s", (env["bid"],)).fetchone()
        assert not c.execute(
            "SELECT 1 FROM audit_entries WHERE bid_id=%s AND event_type=%s",
            (env["bid"], package_outputs.EVENT),
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM commands WHERE actor_id=%s AND command_kind=%s",
            (env["actor"], package_adoptions.KIND),
        ).fetchone()


def test_unqualified_generated_artifact_cannot_use_generic_package_write(env):
    build_id, body, _ = build(env)
    from packages.domain.bid_packages import PackageError

    with pytest.raises(PackageError) as error, connection() as c:
        bid_package_service.lock_bid(c, env["bid"])
        bid_package_service.create_revision(
            c, env["bid"], {"kind": "bid", "members": [body["member"]]}
        )
    assert error.value.code == "PACKAGE_VERIFIED_UPLOAD_REQUIRED"
    # Explicit adoption is the only new route that registers a qualification.
    assert adopt(env, build_id, body)[0]["status"] == 201


def test_source_withdrawal_between_bytes_and_final_use_rolls_back(env, monkeypatch):
    build_id, body, _ = build(env)
    verify = package_outputs.verify_bytes

    def withdraw(packet):
        verify(packet)
        with connection() as c:
            c.execute(
                "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
                (parse_source_id(env["parse"]),),
            )

    monkeypatch.setattr(package_outputs, "verify_bytes", withdraw)
    with pytest.raises(DomainError):
        adopt(env, build_id, body)
    with connection() as c:
        assert not c.execute("SELECT 1 FROM bid_packages WHERE bid_id=%s", (env["bid"],)).fetchone()
        assert not c.execute(
            "SELECT 1 FROM audit_entries WHERE bid_id=%s AND event_type=%s",
            (env["bid"], package_outputs.EVENT),
        ).fetchone()
