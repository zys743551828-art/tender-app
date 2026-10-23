"""Synthetic fixed inputs with real native bindings, PG roles, authentication and S3."""

import hashlib
import os
import secrets
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_api import world as base_world
from test_bid_package_requirements_api import package_extraction_document
from test_stable_lot_identity import headers, uid

from packages.domain.review_identity import digest

ADMIN_DSN = os.environ.get("FUSION_AUTHORING_INPUT_ADMIN_DSN")
RAW = b"synthetic B1 original bytes; physical parse is an explicit test fixture\n"
DDL = "packages/contracts/sql/authoring-package-inputs.sql"


@pytest.fixture
def world(api):
    return base_world.__wrapped__(api, SimpleNamespace(param=RAW))


@pytest.fixture(scope="module")
def database():
    from apps.api.authoring_package_inputs import router
    from apps.api.main import app
    from deploy.bootstrap_fresh import BASE_SQL, ROOT
    from packages.authoring.package_input_repository import capabilities

    assert DDL not in BASE_SQL
    old_routes = list(app.router.routes)
    app.include_router(router)
    app.openapi_schema = None
    dbname = "fusion_authoring_package_inputs"
    roles = {"api": dbname + "_api", "worker": dbname + "_worker"}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-authoring-input-no-business-profile")
        patch.setenv("APP_ORIGIN", "http://identity-v2.test")
        patch.setenv("SESSION_SECRET", uid())
        patch.setenv("CSRF_SECRET", uid())
        with psycopg.connect(ADMIN_DSN, autocommit=True, row_factory=dict_row) as admin:
            assert admin.info.dbname == "postgres"
            assert not admin.execute(
                "SELECT FROM pg_database WHERE datname=%s", (dbname,)
            ).fetchone()
            admin.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(dbname))
            )
            try:
                owner_dsn = make_conninfo(ADMIN_DSN, dbname=dbname)
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    for name in BASE_SQL:
                        owner.execute((ROOT / name).read_text())
                    owner.execute(
                        (ROOT / "deploy/sql/bid-package-requirement-runtime-grants.sql").read_text()
                    )
                    connections = {}
                    for kind, name in roles.items():
                        password = secrets.token_urlsafe(36)
                        admin.execute(
                            sql.SQL(
                                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                            ).format(sql.Identifier(name), sql.Literal(password))
                        )
                        admin.execute(
                            sql.SQL("GRANT {} TO {}").format(
                                sql.Identifier("tender_" + kind), sql.Identifier(name)
                            )
                        )
                        connections[kind + "_dsn"] = make_conninfo(
                            owner_dsn, user=name, password=password
                        )
                    patch.setenv("API_DATABASE_DSN", connections["api_dsn"])
                    patch.setenv("WORKER_DATABASE_DSN", connections["worker_dsn"])
                    with psycopg.connect(
                        connections["api_dsn"], row_factory=dict_row
                    ) as api_connection:
                        before = capabilities(api_connection)
                        assert not before["capture_available"]
                    owner.execute((ROOT / DDL).read_text())
                    yield {"owner": owner, "base_capabilities": before, **connections}
            finally:
                app.router.routes[:] = old_routes
                app.openapi_schema = None
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(dbname))
                )
                for name in roles.values():
                    admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def seed_extraction_receipt(w):
    """Explicit synthetic upstream result; actual API command and Worker receipt RPC."""
    from packages.domain.bid_package_extraction import freeze_matching_input, record_completion
    from packages.domain.bid_package_repository import load_revision
    from packages.domain.review_data import save_json
    from packages.domain.runtime import Command, connection, enqueue_plan

    bid = w["scope"].bid_id
    with connection() as c:
        authority = load_revision(c, bid, w["inventory_body"]["authority_revision_id"])
        document = package_extraction_document(c, authority)
        method = {"engine": "explicit-synthetic-B1-upstream", "version": "1"}
        frozen = freeze_matching_input(c, bid, uid(), [document], method, digest(method))
        assert frozen is not None
    blob = save_json(
        {"documents": [document], "package_rule_extraction_input": frozen}, worker=True
    )
    operation_digest = digest({"synthetic_upstream": frozen["digest"]})
    with connection() as c:
        command = Command(
            c,
            w["actor"],
            "synthetic-authoring-input-fixture",
            bid,
            uid(),
            {"digest": operation_digest},
        )
        operation = enqueue_plan(
            c,
            bid,
            command.id,
            "prepare-review",
            {"id": blob["id"]},
            stages=[{"key": "extract-rules", "depends_on": []}],
            handler_version="prepare/1",
            topic="tender.task.review.v1",
            input_digest=operation_digest,
        )
        command.finish({"operation_id": str(operation["id"])}, 202)
    result = {
        "input_digest": frozen["digest"],
        "rule_set_id": w["inventory_body"]["rule_set_id"],
        "authority_revision_id": authority.revision_id,
        "authority_digest": authority.manifest_digest,
        "method_digest": digest(method),
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest(sorted(block["id"] for block in document["blocks"])),
        "extraction_coverage": "complete",
        "quality_status": "not_measured",
    }
    message = {
        "bid_id": bid,
        "operation_id": operation["id"],
        "input_digest": operation_digest,
        "payload_ref": blob["id"],
    }
    with connection(True) as worker:
        record_completion(worker, message, frozen, result["rule_set_id"], result)
        worker.execute(
            "INSERT INTO design.effect_receipts(operation_id,effect_key,result) VALUES(%s,'extract-rules',%s)",
            (
                operation["id"],
                Jsonb(
                    {
                        "result_ref": result["rule_set_id"],
                        "method_digest": result["method_digest"],
                        "extraction_input_digest": frozen["digest"],
                    }
                ),
            ),
        )
        worker.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=now() WHERE id=%s",
            (operation["id"],),
        )


@pytest.fixture
def exact(requirements):
    from test_assistant_budget_nonowner import _confirm_api
    from test_bid_package_requirements_api import inventory

    from packages.assistant.generation import nodes
    from packages.authoring import package_input_observation as observation
    from packages.authoring.repository import create_draft
    from packages.domain import storage
    from packages.domain.bid_package_service import lock_bid
    from packages.domain.runtime import clean, connection
    from packages.rag.indexing import ensure_parse_sources

    w = requirements
    bid = str(w["scope"].bid_id)
    owner = w["database"]["owner"]
    assert owner.info.dbname == "fusion_authoring_package_inputs"
    # Fixture originals are explicit synthetic bytes, sent through the actual S3 transport.
    blob = owner.execute(
        "SELECT b.* FROM design.blobs b JOIN design.document_versions v ON v.blob_id=b.id WHERE v.id=%s",
        (w["member"].document_version_id,),
    ).fetchone()
    assert blob["digest"] == hashlib.sha256(RAW).hexdigest() and blob["byte_size"] == len(RAW)
    storage.put(blob["object_key"], RAW, "application/pdf")
    with connection(True) as c:
        parses = c.execute("SELECT id FROM design.parse_runs WHERE bid_id=%s", (bid,)).fetchall()
        for row in parses:
            ensure_parse_sources(c, UUID(bid), row["id"], publish_readable=True)
    with connection() as c:
        lock_bid(c, bid)
        c.execute(
            "UPDATE design.bid_profiles SET current_body_id=%s WHERE bid_id=%s",
            (w["member"].document_version_id, bid),
        )
    _confirm_api({"bid": bid, "actor": w["actor"], "evidence": w["body_evidence"]})
    seed_extraction_receipt(w)
    response = inventory(w)
    assert response.status_code == 201, response.text
    inventory_value = response.json()
    with connection() as c:
        lock_bid(c, bid)
        draft_id, snapshot = create_draft(c, UUID(bid), UUID(w["actor"]), "Synthetic B1 draft")
        section = c.execute(
            "SELECT r.* FROM design.section_revisions r JOIN design.draft_snapshot_sections link ON link.section_revision_id=r.id WHERE link.snapshot_id=%s ORDER BY link.ordinal",
            (snapshot["snapshot_id"],),
        ).fetchone()
        head = c.execute("SELECT * FROM design.fact_heads WHERE bid_id=%s", (bid,)).fetchone()
        fact_ids = [
            str(r["id"])
            for r in c.execute(
                "SELECT id FROM design.fact_items WHERE bid_id=%s AND fact_set_id=%s ORDER BY name",
                (bid, head["fact_set_id"]),
            ).fetchall()
        ]
    with connection() as c:
        authority = c.execute(
            "SELECT package_id,id,digest FROM design.bid_package_revisions WHERE id=%s",
            (w["inventory_body"]["authority_revision_id"],),
        ).fetchone()
    body = {
        "protocol": "package-authoring-input-request/1",
        "purpose": "authoring",
        "target_relation": "draft_using_package_context",
        "package_context": {
            "target": {
                "package_id": w["own"]["manifest"]["package_id"],
                "revision_id": w["own"]["manifest"]["revision_id"],
                "manifest_digest": w["own"]["digest"],
            },
            "authority": {
                "package_id": str(authority["package_id"]),
                "revision_id": str(authority["id"]),
                "manifest_digest": authority["digest"],
            },
            "inventory": {
                "id": inventory_value["manifest"]["id"],
                "digest": inventory_value["digest"],
                "rule_set_id": w["inventory_body"]["rule_set_id"],
            },
        },
        "target_section": {
            "draft_id": str(draft_id),
            "snapshot_id": str(snapshot["snapshot_id"]),
            "snapshot_digest": snapshot["snapshot_digest"],
            "base_draft_revision": 1,
            "section_id": str(section["section_id"]),
            "section_revision_id": str(section["id"]),
            "base_section_revision": 1,
            "section_digest": section["digest"],
            "schema_digest": section["schema_digest"],
            "node_id": nodes(section["content"])[0]["node_id"],
            "before_node_digest": nodes(section["content"])[0]["before_digest"],
        },
        "facts": {
            "fact_set_id": str(head["fact_set_id"]),
            "fact_head_revision": head["revision"],
            "identity_fact_ids": fact_ids,
            "uses": [],
        },
    }
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        selection, identity = observation.selected_packages(c, bid, body)
        docs = observation.documents(c, bid, selection)
        at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat()
        facts = observation.facts(c, bid, body, docs, identity, at)
    chosen = facts["items"][0]
    body["facts"]["uses"] = [
        {
            "fact_id": chosen["item"]["fact"]["id"],
            "fact_item_digest": chosen["item_digest"],
            "subject": {"kind": "bidder", "id": identity["bidder_id"]},
            "reason": "Explicit synthetic authoring purpose only",
        }
    ]
    return {
        **w,
        "bid": bid,
        "input_body": clean(body),
        "input_base": f"/api/v1/bids/{bid}/authoring/package-inputs",
        "blob": blob,
        "inventory": inventory_value,
        "identity": identity,
    }


def save(w, *, key=None, body=None):
    return w["client"].post(
        w["input_base"], json=body or w["input_body"], headers=headers(w, key=key)
    )


def saved(w):
    response = save(w)
    assert response.status_code == 201, response.text
    return response.json()


def status(w, value):
    return w["client"].post(
        w["input_base"] + "/" + value["manifest"]["id"] + "/check",
        json={"input_digest": value["digest"]},
        headers=headers(w),
    )
