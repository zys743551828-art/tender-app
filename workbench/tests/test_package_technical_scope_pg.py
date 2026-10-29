"""Actual PostgreSQL/API-role scope boundaries; all content and storage are synthetic.

The launcher uses a separate PG17.11 prefix/cluster with the reviewed uuid-ossp
dependency. Opt-in is distinct from the shared requirements test environment.
No provider, scheduler, score job or historical sample is created by this suite.
"""
# ruff: noqa: F401,F811

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_api import world as package_world
from test_bid_package_requirements_api import database as base_database
from test_bid_package_requirements_api import inventory, requirements
from test_stable_lot_identity import api as base_api
from test_stable_lot_identity import headers, uid

from apps.api.package_technical_scope import router
from packages.contracts import package_technical_scope_api as contracts
from packages.domain import bid_package_technical_scope_repository as repository
from packages.domain import bid_package_technical_scope_service as service
from packages.domain import package_technical_scope as policy
from packages.domain import storage
from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import Command, DomainError, connection, sha
from packages.rag.indexing import ensure_parse_sources, original_source_id, parse_source_id

ENABLED = os.environ.get("FUSION_TECHNICAL_SCOPE_PG") == "1"
pytestmark = pytest.mark.skipif(not ENABLED, reason="explicit separate F06 native PG17 required")
ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "packages/contracts/sql/bid-package-technical-scopes.sql"
RAW = b"%PDF-1.7\nSynthetic F06 exact technical scope original.\n%%EOF\n"


@pytest.fixture(scope="module")
def database():
    source = base_database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        # Owner is only used for fresh installation and synthetic fixture setup.
        if (
            owner.execute("SELECT to_regclass(%s) AS name", (repository.RELATION,)).fetchone()[
                "name"
            ]
            is None
        ):
            owner.execute(SQL.read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def api(database):
    wrapped = base_api.__wrapped__(database)
    value = next(wrapped)
    app = value["app"]
    original_routes = list(app.router.routes)
    if not any(
        getattr(route, "path", "").endswith("/technical-scope-context")
        for route in app.router.routes
    ):
        app.include_router(router)
    app.openapi_schema = None
    try:
        yield value
    finally:
        app.router.routes[:] = original_routes
        app.openapi_schema = None
        try:
            next(wrapped)
        except StopIteration:
            pass


@pytest.fixture
def world(api):
    w = package_world.__wrapped__(api, SimpleNamespace(param=RAW))
    w["item"]["parts"][0]["last_page"] = 1
    w["item"]["parts"].append(
        {
            "part_id": "appendix/table",
            "category": "technical",
            "first_page": 2,
            "last_page": 2,
            "shared_attachment": False,
            "heading_path": [12],
        }
    )
    with w["database"]["owner"].transaction():
        c = w["database"]["owner"]
        text = "Synthetic table: term 30 days; alternative 45 days."
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest) VALUES(%s,%s,%s,2,1,'table',%s,%s,%s,%s)",
            (
                uid(),
                w["scope"].bid_id,
                w["member"].parse.parse_run_id,
                text,
                Jsonb([0, 1.25, 100, 200]),
                Jsonb({"rows": [["term", "30 days", "45 days"]]}),
                sha(text.encode()),
            ),
        )
        w["member"] = replace(
            w["member"],
            parse=read_parse_identity(
                c,
                w["scope"].bid_id,
                w["member"].document_version_id,
                w["member"].parse.parse_run_id,
            ),
        )
    return w


@pytest.fixture
def exact(requirements, monkeypatch):
    w = requirements
    bid = w["scope"].bid_id
    with connection() as c:
        role = c.execute(
            "SELECT current_user AS name,(SELECT rolsuper FROM pg_roles WHERE rolname=current_user) AS superuser"
        ).fetchone()
        assert role == {"name": "fusion_package_requirements_service", "superuser": False}
        for revision in (
            w["own"]["manifest"]["revision_id"],
            w["inventory_body"]["authority_revision_id"],
        ):
            members = c.execute(
                "SELECT parse_run_id FROM design.bid_package_members WHERE revision_id=%s",
                (revision,),
            ).fetchall()
            for member in members:
                ensure_parse_sources(c, UUID(bid), member["parse_run_id"], publish_readable=True)
        scoring = []
        for index in range(3):
            identity = uid()
            scoring.append(identity)
            c.execute(
                "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,max_points,evidence_ids,bands) VALUES(%s,%s,%s,'scoring',%s,%s,%s,10,%s,%s)",
                (
                    identity,
                    bid,
                    w["inventory_body"]["rule_set_id"],
                    f"Synthetic scoring clause {index}",
                    Jsonb(["when the technical range applies"]),
                    Jsonb(["explicitly excepted alternative"]),
                    [w["evidence"]],
                    Jsonb(
                        [{"label": "full", "description": "entire required range", "points": "10"}]
                    ),
                ),
            )
            w["inventory_body"]["mappings"].append(
                {
                    "rule_id": identity,
                    "categories": ["technical"],
                    "target_part_ids": ["tech", "appendix/table"],
                    "minimum_count": None,
                    "applicability": "applicable",
                    "applicability_evidence_ids": [],
                    "valid_at": None,
                    "checks": [],
                    "reason": "Synthetic full declared technical range",
                    "basis_evidence_ids": [w["evidence"]],
                }
            )
    created = inventory(w)
    assert created.status_code == 201, created.text
    inv = created.json()
    state = {"reads": [], "data": RAW, "callback": None, "unavailable": False, "concurrent": False}

    class Objects:
        def get_object(self, *, Bucket, Key):
            if not state["concurrent"]:
                sessions = (
                    w["database"]["owner"]
                    .execute(
                        "SELECT xact_start,(SELECT count(*) FROM pg_locks l WHERE l.pid=a.pid AND l.granted) AS locks FROM pg_stat_activity a WHERE datname=current_database() AND usename='fusion_package_requirements_service'"
                    )
                    .fetchall()
                )
                assert all(row["xact_start"] is None and row["locks"] == 0 for row in sessions), (
                    sessions
                )
            state["reads"].append(Key)
            if state["callback"]:
                callback, state["callback"] = state["callback"], None
                callback()
            if state["unavailable"]:
                raise OSError("synthetic object service unavailable")
            return {"Body": io.BytesIO(state["data"])}

    monkeypatch.setattr(storage, "client", lambda: Objects())
    monkeypatch.setattr(storage, "bucket", lambda: "synthetic-f06")
    scope = (bid, inv["manifest"]["package_id"], inv["manifest"]["target_revision_id"])
    base = f"/api/v1/bids/{scope[0]}/packages/{scope[1]}/revisions/{scope[2]}"
    request = {
        "purpose": "current_prebid",
        "package_digest": inv["manifest"]["package_digest"],
        "authority_revision_id": inv["manifest"]["authority_revision_id"],
        "authority_digest": inv["manifest"]["authority_digest"],
        "inventory_id": inv["manifest"]["id"],
        "inventory_digest": inv["digest"],
        "technical_part_ids": ["tech", "appendix/table"],
        "rule_scopes": [
            {
                "rule_id": row["rule_id"],
                "rule_digest": row["rule_digest"],
                "selection": "include" if row["rule_id"] != scoring[-1] else "exclude",
                "part_ids": ["tech", "appendix/table"] if row["rule_id"] != scoring[-1] else [],
                "reason": "Synthetic exact authority clause, declared scope and retained exclusions.",
            }
            for row in inv["manifest"]["requirements"]
            if row["rule_snapshot"]["kind"] == "scoring"
        ],
        "reason": "Synthetic explicit current technical scope; completeness is not proven.",
    }
    return w | {
        "technical_scope": scope,
        "technical_base": base,
        "inventory": inv,
        "request": request,
        "io": state,
    }


def prepare(w):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        value = service.preview(c, w["technical_scope"], w["request"])
    return value, service.preview_etag(value)


def freeze(w, *, key=None, prepared=None):
    value, tag = prepared or prepare(w)
    return service.freeze(
        w["technical_scope"],
        w["actor"],
        key or uid(),
        {"request": w["request"], "preview_digest": value["digest"]},
        tag,
        final_auth=lambda: w["actor"],
    )


def count(w, table="design.bid_package_technical_scopes"):
    # Only this fixed allowlist may become a SQL identifier.
    assert table in {"design.bid_package_technical_scopes", "design.operations"}
    with connection() as c:
        return c.execute(
            f"SELECT count(*) AS count FROM {table} WHERE bid_id=%s", (w["scope"].bid_id,)
        ).fetchone()["count"]


def test_current_scope_api_full_parse_evidence_original_receipt_history_and_no_execution(exact):
    w = exact
    context = w["client"].get(
        w["technical_base"] + "/technical-scope-context",
        params={"inventory_id": w["inventory"]["manifest"]["id"]},
    )
    assert context.status_code == 200, context.text
    assert context.json()["can_freeze"] is True
    assert context.json()["catalog_complete"] is True
    preview = w["client"].post(
        w["technical_base"] + "/technical-scope-previews", json=w["request"], headers=headers(w)
    )
    assert preview.status_code == 200, preview.text
    value = preview.json()
    assert preview.headers["etag"] == context.headers["etag"]
    assert not w["io"]["reads"]
    before_operations = count(w, "design.operations")
    body = {"request": w["request"], "preview_digest": value["digest"]}
    result = w["client"].post(
        w["technical_base"] + "/technical-scopes",
        json=body,
        headers=headers(w, etag=context.headers["etag"]),
    )
    assert result.status_code == 201, result.text
    contracts.validate("PackageTechnicalScopeApplied", result.json())
    saved = result.json()["scope"]
    manifest = saved["manifest"]
    assert manifest["preview"] == value
    assert all(manifest[key] is False for key in policy.FLAGS)
    assert manifest["preview"]["manifest"]["timing"] == policy.TIMING
    assert len(manifest["original_verification"]["files"]) == 2
    assert len(w["io"]["reads"]) == 2
    assert any(
        block["kind"] == "table" and "1.25" in block["bbox_json"]
        for doc in value["manifest"]["documents"]
        for block in doc["blocks"]
    )
    assert value["manifest"]["coverage"]["all_scoring_rule_count"] == 3
    assert any(
        g["code"] == "RULE_EXCLUDED_BY_DECLARATION" for g in value["manifest"]["coverage"]["gaps"]
    )
    detail = w["client"].get(w["technical_base"] + "/technical-scopes/" + manifest["id"])
    assert detail.json() == saved and detail.headers["etag"] == result.headers["etag"]
    history = w["client"].get(w["technical_base"] + "/technical-scopes")
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["id"] == manifest["id"]
    assert "manifest" not in history.json()["items"][0]
    assert count(w) == 1 and count(w, "design.operations") == before_operations
    destination = os.environ.get("FUSION_TECHNICAL_SCOPE_FIXTURE")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        fixture = {
            "schema": "package-technical-scope-http-fixture/1",
            "evidence": "Actual PostgreSQL nonowner API and authenticated ASGI responses; synthetic originals, source content and object transport; no paid model",
            "bidId": w["scope"].bid_id,
            "memberId": w["actor"],
            "scope": list(w["technical_scope"]),
            "basePath": w["technical_base"],
            "target": w["own"],
            "inventory": w["inventory"],
            "context": context.json(),
            "contextEtag": context.headers["etag"],
            "request": w["request"],
            "preview": preview.json(),
            "previewEtag": preview.headers["etag"],
            "freezeRequest": body,
            "applied": result.json(),
            "appliedEtag": result.headers["etag"],
            "history": history.json(),
            "detail": detail.json(),
            "detailEtag": detail.headers["etag"],
        }
        path.write_text(json.dumps(fixture, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def test_original_ack_precedes_closed_project_withdrawn_source_and_storage_failure(exact):
    w, key = exact, uid()
    prepared = prepare(w)
    result, replay = freeze(w, key=key, prepared=prepared)
    assert replay is False
    reads = list(w["io"]["reads"])
    with connection() as c:
        c.execute(
            "UPDATE design.bid_profiles SET phase='submitted' WHERE bid_id=%s", (w["scope"].bid_id,)
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (original_source_id(UUID(w["member"].document_version_id)),),
        )
    w["io"]["unavailable"] = True
    repeated, replay = freeze(w, key=key, prepared=prepared)
    assert replay is True and repeated == result and w["io"]["reads"] == reads
    changed = deepcopy(w["request"])
    changed["reason"] += " changed"
    with pytest.raises(DomainError) as error:
        service.freeze(
            w["technical_scope"],
            w["actor"],
            key,
            {"request": changed, "preview_digest": prepared[0]["digest"]},
            prepared[1],
        )
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("failure", ["corrupt", "unavailable", "source_changed", "submitted"])
def test_original_io_and_final_observation_failures_leave_no_scope_or_command(exact, failure):
    w = exact
    prepared = prepare(w)
    if failure == "corrupt":
        w["io"]["data"] += b"corrupt"
    elif failure == "unavailable":
        w["io"]["unavailable"] = True
    else:

        def during_io():
            with connection() as c:
                if failure == "submitted":
                    c.execute(
                        "UPDATE design.bid_profiles SET phase='submitted' WHERE bid_id=%s",
                        (w["scope"].bid_id,),
                    )
                else:
                    c.execute(
                        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                        (parse_source_id(UUID(w["member"].parse.parse_run_id)),),
                    )

        w["io"]["callback"] = during_io
    key = uid()
    with pytest.raises(DomainError):
        freeze(w, key=key, prepared=prepared)
    assert count(w) == 0
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.commands WHERE actor_id=%s AND command_kind=%s AND idempotency_key=%s",
                (w["actor"], repository.KIND, key),
            ).fetchone()["n"]
            == 0
        )


def test_two_concurrent_identical_requests_share_one_original_receipt(exact):
    w, key = exact, uid()
    prepared = prepare(w)
    w["io"]["concurrent"] = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(freeze, w, key=key, prepared=prepared) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0][0] == results[1][0]
    assert sorted(replay for _, replay in results) == [False, True]
    assert count(w) == 1


def forged(w, mutation, *, receipt=False):
    prepared, condition = prepare(w)
    altered = deepcopy(prepared["manifest"])
    mutation(altered)
    preview = {"manifest": altered, "digest": digest(altered)}
    body = {"request": altered["request"], "preview_digest": preview["digest"]}
    with connection() as c:
        command = Command(
            c,
            w["actor"],
            repository.KIND,
            w["technical_scope"][2],
            uid(),
            repository.request_body(w["technical_scope"], body),
            condition,
        )
        observed = repository.observe(c, w["technical_scope"], w["inventory"]["manifest"]["id"])
        at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
        manifest = {
            "version": "package-technical-scope/1",
            "id": uid(),
            "actor_id": w["actor"],
            "command_id": str(command.id),
            "frozen_at": at,
            "preview": preview,
            "original_verification": {
                "state": "verified_at_recording",
                "verified_at": at,
                "files": observed["snapshot"]["originals"],
            },
            **policy.FLAGS,
        }
        value = {"manifest": manifest, "digest": digest(manifest)}
        repository.insert(c, value)
        if receipt:
            command.finish({"wrong": "receipt"}, 201, {})


@pytest.mark.parametrize("field", ["parts", "rules", "documents", "source_snapshot"])
@pytest.mark.parametrize("missing", [False, True])
def test_api_role_cannot_bypass_missing_or_null_complete_arrays(exact, field, missing):
    def mutate(value):
        if missing:
            value.pop(field)
        else:
            value[field] = None

    with pytest.raises(psycopg.errors.CheckViolation):
        forged(exact, mutate)
    assert count(exact) == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["parts"][0].update(read_physical_pages=[]),
        lambda p: p["parts"][0].update(block_ids=[]),
        lambda p: p["parts"][0].update(text_evidence_present=False),
        lambda p: p["documents"][0].update(blocks=None),
        lambda p: p["rules"][0].update(source_evidence=[]),
        lambda p: p["coverage"].update(all_scoring_rule_count=1),
        lambda p: p["coverage"].update(gaps=[]),
        lambda p: p["coverage"].update(state="pass"),
        lambda p: p["method"]["sources"].update(unreviewed="0" * 64),
        lambda p: p.update(scoring_ready=True),
    ],
)
def test_api_role_cannot_forge_read_range_quotes_coverage_or_execution(exact, mutation):
    with pytest.raises(psycopg.errors.CheckViolation):
        forged(exact, mutation)
    assert count(exact) == 0


def test_api_role_cannot_replace_canonical_parse_roots_with_unrelated_graph(exact):
    w = exact

    def mutate(p):
        old = str(parse_source_id(UUID(w["member"].parse.parse_run_id)))
        replacement = w["sources"][0]
        for row in p["source_snapshot"]:
            if row["source_id"] == old:
                row["source_id"] = replacement
            if row["ancestor_id"] == old:
                row["ancestor_id"] = replacement

    with pytest.raises(psycopg.errors.CheckViolation):
        forged(w, mutate)
    assert count(w) == 0


@pytest.mark.parametrize("receipt", [False, True])
def test_deferred_guard_rejects_missing_or_wrong_original_ack_atomically(exact, receipt):
    with pytest.raises(psycopg.errors.CheckViolation):
        forged(exact, lambda p: None, receipt=receipt)
    assert count(exact) == 0


def test_runtime_and_worker_cannot_mutate_saved_scope_or_install_dependencies(exact):
    saved, _ = freeze(exact)
    identity = saved["body"]["scope"]["manifest"]["id"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection() as c:
            c.execute(
                "UPDATE design.bid_package_technical_scopes SET digest=digest WHERE id=%s",
                (identity,),
            )
    with psycopg.connect(exact["database"]["worker_dsn"], row_factory=dict_row) as c:
        allowed = c.execute(
            "SELECT has_table_privilege(current_user,'design.bid_package_technical_scopes','SELECT') AS read,has_table_privilege(current_user,'design.bid_package_technical_scopes','INSERT') AS write,has_database_privilege(current_user,current_database(),'CREATE') AS owner"
        ).fetchone()
        assert allowed == {"read": False, "write": False, "owner": False}
    with connection() as c:
        assert not c.execute(
            "SELECT has_database_privilege(current_user,current_database(),'CREATE') AS allowed"
        ).fetchone()["allowed"]
        for document in saved["body"]["scope"]["manifest"]["preview"]["manifest"]["documents"]:
            expected = original_source_id(UUID(document["document_version_id"]))
            assert (
                c.execute(
                    "SELECT public.uuid_generate_v5('8d6cdd5c-1a28-45c6-ac26-e293b1d16f42',%s) AS id",
                    ("document-original:" + document["document_version_id"],),
                ).fetchone()["id"]
                == expected
            )
