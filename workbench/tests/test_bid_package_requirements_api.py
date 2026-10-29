"""Actual nonowner/auth/ASGI and deferred PG guards; run only in grouped checks."""
# ruff: noqa: F811,F401

import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_api import attach, create, world
from test_stable_lot_identity import api, catalog, headers, post, uid

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.review_identity import digest

ADMIN_DSN = os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires grouped isolated requirements PG17")


@pytest.fixture(scope="module")
def database():
    from deploy.bootstrap_fresh import BASE_SQL, ROOT

    ddl = "packages/contracts/sql/bid-package-requirements.sql"
    plan = list(BASE_SQL)
    if ddl not in plan:
        plan.insert(plan.index("packages/contracts/sql/roles.sql"), ddl)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_ENV_FILE", "explicit-grouped-requirement-tests")
        patch.setenv("APP_ORIGIN", "http://identity-v2.test")
        patch.setenv("SESSION_SECRET", uid())
        patch.setenv("CSRF_SECRET", uid())
        with psycopg.connect(ADMIN_DSN, autocommit=True, row_factory=dict_row) as admin:
            assert admin.info.dbname == "postgres"
            assert not admin.execute(
                "SELECT 1 FROM pg_database WHERE datname='fusion_package_requirements_api'"
            ).fetchone()
            assert not admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='fusion_package_requirements_service'"
            ).fetchone()
            assert not admin.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='fusion_package_requirements_worker'"
            ).fetchone()
            admin.execute("CREATE DATABASE fusion_package_requirements_api TEMPLATE template0")
            try:
                owner_dsn = make_conninfo(ADMIN_DSN, dbname="fusion_package_requirements_api")
                with psycopg.connect(owner_dsn, autocommit=True, row_factory=dict_row) as owner:
                    assert owner.info.dbname == "fusion_package_requirements_api"
                    for name in plan:
                        owner.execute((ROOT / name).read_text(encoding="utf-8"))
                    owner.execute(
                        (ROOT / "deploy/sql/bid-package-requirement-runtime-grants.sql").read_text(
                            encoding="utf-8"
                        )
                    )
                    service_password = secrets.token_urlsafe(36)
                    admin.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                        ).format(
                            sql.Identifier("fusion_package_requirements_service"),
                            sql.Literal(service_password),
                        )
                    )
                    admin.execute("GRANT tender_api TO fusion_package_requirements_service")
                    api_dsn = make_conninfo(
                        owner_dsn,
                        user="fusion_package_requirements_service",
                        password=service_password,
                    )
                    worker_password = secrets.token_urlsafe(36)
                    admin.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                        ).format(
                            sql.Identifier("fusion_package_requirements_worker"),
                            sql.Literal(worker_password),
                        )
                    )
                    admin.execute("GRANT tender_worker TO fusion_package_requirements_worker")
                    worker_dsn = make_conninfo(
                        owner_dsn,
                        user="fusion_package_requirements_worker",
                        password=worker_password,
                    )
                    patch.setenv("API_DATABASE_DSN", api_dsn)
                    yield {"owner": owner, "api_dsn": api_dsn, "worker_dsn": worker_dsn}
            finally:
                admin.execute("DROP DATABASE fusion_package_requirements_api WITH(FORCE)")
                admin.execute("DROP ROLE IF EXISTS fusion_package_requirements_service")
                admin.execute("DROP ROLE IF EXISTS fusion_package_requirements_worker")


@pytest.fixture
def requirements(world):
    return prepare_requirements(world)


def prepare_requirements(world, *, native_rule_scope=None):
    c = world["database"]["owner"]
    scope = world["scope"]
    with c.transaction():
        version, parse = uid(), uid()
        c.execute(
            "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) SELECT %s,bid_id,blob_id,'synthetic-authority.pdf',now(),'source_original',created_by FROM design.document_versions WHERE id=%s",
            (version, world["member"].document_version_id),
        )
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) SELECT %s,bid_id,%s,parser_digest,config_digest,page_count,coverage,gaps FROM design.parse_runs WHERE id=%s",
            (parse, version, world["member"].parse.parse_run_id),
        )
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) SELECT bid_id,%s,physical_page,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s",
            (parse, world["member"].parse.parse_run_id),
        )
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest) SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE parse_id=%s",
            (parse, world["member"].parse.parse_run_id),
        )
        authority = replace(
            world["member"],
            document_version_id=version,
            parse=read_parse_identity(c, scope.bid_id, version, parse),
            source_kind="authority",
        )
        attach(c, scope.bid_id, world["actor"], authority, "tender")
    own_response = create(world)
    assert own_response.status_code == 201, own_response.text
    authority_response = create(
        world,
        body={
            "kind": "authority",
            "members": [
                world["item"]
                | {
                    "member_id": "authority",
                    "document_version_id": authority.document_version_id,
                    "parse_run_id": authority.parse.parse_run_id,
                }
            ],
        },
    )
    assert authority_response.status_code == 201, authority_response.text
    own = own_response.json()
    official = authority_response.json()
    material, rule_set, rule, decision = uid(), uid(), uid(), uid()
    with c.transaction():
        evidence = c.execute(
            "SELECT id::text FROM design.evidence_blocks WHERE parse_id=%s ORDER BY physical_page LIMIT 1",
            (authority.parse.parse_run_id,),
        ).fetchone()["id"]
        body_evidence = c.execute(
            "SELECT id::text FROM design.evidence_blocks WHERE parse_id=%s ORDER BY physical_page LIMIT 1",
            (world["member"].parse.parse_run_id,),
        ).fetchone()["id"]
        c.execute(
            "INSERT INTO design.material_snapshots(id,bid_id,revision,manifest,digest) VALUES(%s,%s,1,'{}',%s)",
            (material, scope.bid_id, digest({})),
        )
        c.execute(
            "INSERT INTO design.rule_sets(id,bid_id,material_id,revision,digest,coverage) VALUES(%s,%s,%s,1,%s,'complete')",
            (rule_set, scope.bid_id, material, digest(rule_set)),
        )
        c.execute(
            "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,evidence_ids,bands,applicability_scope) VALUES(%s,%s,%s,'mandatory','Synthetic original obligation','[]','[]',%s,'[]',%s)",
            (rule, scope.bid_id, rule_set, [evidence], Jsonb(native_rule_scope or {})),
        )
        c.execute(
            "UPDATE design.bid_profiles SET current_rule_set_id=%s WHERE bid_id=%s",
            (rule_set, scope.bid_id),
        )
        c.execute(
            "INSERT INTO design.decisions(id,bid_id,object_kind,object_id,object_revision,decision,reason,evidence_ids,actor_id) VALUES(%s,%s,'rule',%s,1,'confirmed','Synthetic confirmation',%s,%s)",
            (decision, scope.bid_id, rule, [evidence], world["actor"]),
        )
        c.execute(
            "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'rule',%s,1,%s)",
            (scope.bid_id, rule, decision),
        )
        sources = []
        for member in (world["member"], authority):
            source = uid()
            sources.append(source)
            c.execute(
                "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document','prebid_content',now()-interval '1 minute',%s)",
                (source, member.document_version_id, member.file_digest),
            )
            c.execute(
                "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now()-interval '1 minute')",
                (source,),
            )
    body = {
        "authority_revision_id": official["manifest"]["revision_id"],
        "rule_set_id": rule_set,
        "mappings": [
            {
                "rule_id": rule,
                "categories": ["technical"],
                "target_part_ids": ["tech"],
                "minimum_count": None,
                "applicability": "applicable",
                "applicability_evidence_ids": [],
                "valid_at": None,
                "checks": [],
                "reason": "人工检查计划",
                "basis_evidence_ids": [evidence],
            }
        ],
    }
    base = (
        world["base"]
        + "/"
        + own["manifest"]["package_id"]
        + "/revisions/"
        + own["manifest"]["revision_id"]
        + "/requirement-inventories"
    )
    return world | {
        "requirement_base": base,
        "inventory_body": body,
        "rule": rule,
        "evidence": evidence,
        "body_evidence": body_evidence,
        "sources": sources,
        "own": own,
    }


def inventory(w, *, key=None, tag=None, body=None):
    conditions = {"If-Match": tag} if tag else {"If-None-Match": "*"}
    return w["client"].post(
        w["requirement_base"],
        json=body or w["inventory_body"],
        headers=headers(w, key=key) | conditions,
    )


def attempt_body(w, inv, *, state="verified"):
    return {
        "inventory_digest": inv["digest"],
        "package_digest": inv["manifest"]["package_digest"],
        "results": [
            {
                "rule_id": w["rule"],
                "requirement_digest": inv["manifest"]["requirements"][0]["requirement_digest"],
                "state": state,
                "inspected": [{"part_id": "tech", "first_page": 1, "last_page": 2}],
                "evidence_ids": [w["body_evidence"]],
                "reason": "人工明确声明已核对范围，不表示合规结论",
                "basis_type": "human_scope_declaration"
                if state in {"verified", "not_applicable"}
                else "human_observation",
            }
        ],
    }


def package_extraction_document(c, package):
    member = package.members[0]
    parse = c.execute(
        "SELECT parser_digest,config_digest,page_count,coverage,gaps FROM design.parse_runs WHERE id=%s",
        (member.parse.parse_run_id,),
    ).fetchone()
    pages = c.execute(
        "SELECT physical_page,quality,gaps FROM design.pages WHERE parse_id=%s ORDER BY physical_page",
        (member.parse.parse_run_id,),
    ).fetchall()
    blocks = c.execute(
        """SELECT id::text AS id,physical_page,ordinal,kind,text_content,bbox,structure,digest
                FROM design.evidence_blocks WHERE parse_id=%s ORDER BY physical_page,ordinal""",
        (member.parse.parse_run_id,),
    ).fetchall()
    return {
        "document_version_id": member.document_version_id,
        "role": "tender",
        "digest": member.file_digest,
        "parse_id": member.parse.parse_run_id,
        "parser_digest": parse["parser_digest"],
        "config_digest": parse["config_digest"],
        "page_count": parse["page_count"],
        "coverage": parse["coverage"],
        "gaps": parse["gaps"],
        "pages": pages,
        "blocks": blocks,
    }


def test_worker_completion_binds_exact_frozen_input_without_claiming_quality(
    requirements, monkeypatch
):
    from packages.domain import storage
    from packages.domain.bid_package_extraction import (
        freeze_matching_input,
        record_completion,
        validate_frozen_input,
    )
    from packages.domain.bid_package_repository import load_revision
    from packages.domain.review_data import save_json
    from packages.domain.review_identity import digest
    from packages.domain.runtime import enqueue_plan

    w = requirements
    legacy_response = inventory(w)
    assert legacy_response.status_code == 201
    legacy = legacy_response.json()
    legacy_tag = legacy_response.headers["etag"]
    c = w["database"]["owner"]
    authority_id = w["inventory_body"]["authority_revision_id"]
    authority = load_revision(c, w["scope"].bid_id, authority_id)
    document = package_extraction_document(c, authority)
    method = {"engine": "synthetic-test-only", "version": "1"}
    method_digest = digest(method)
    frozen = freeze_matching_input(
        c,
        w["scope"].bid_id,
        "10000000-0000-0000-0000-000000000001",
        [document],
        method,
        method_digest,
    )
    assert frozen is not None
    assert frozen["manifest"]["scope"]["lot_id"] == w["scope"].lot_id
    assert frozen["manifest"]["authority_package"]["revision_id"] == authority_id
    assert frozen["manifest"]["members"][0]["parse_run_id"] == document["parse_id"]
    assert frozen["manifest"]["extraction_scope"]["parts"][0]["shared_attachment"] is False

    stored_objects = {}
    monkeypatch.setattr(
        storage,
        "put",
        lambda key, data, media: stored_objects.__setitem__(key, data),
    )
    monkeypatch.setattr(storage, "get", lambda key: stored_objects[key])
    monkeypatch.setenv("WORKER_DATABASE_DSN", w["database"]["worker_dsn"])
    descriptor = {
        "documents": [document],
        "package_rule_extraction_input": frozen,
    }
    blob = save_json(descriptor, worker=True)
    command_id, operation_digest = uid(), digest({"frozen": frozen["digest"]})
    with c.transaction():
        c.execute(
            """INSERT INTO design.commands
                    (id,actor_id,command_kind,target_id,idempotency_key,request_digest)
                    VALUES(%s,%s,'synthetic_prepare',%s,%s,%s)""",
            (command_id, w["actor"], w["scope"].bid_id, uid(), operation_digest),
        )
        operation = enqueue_plan(
            c,
            w["scope"].bid_id,
            command_id,
            "prepare-review",
            {"id": blob["id"]},
            stages=[{"key": "extract-rules", "depends_on": []}],
            handler_version="prepare/1",
            topic="tender.task.review.v1",
            input_digest=operation_digest,
        )
    result = {
        "input_digest": frozen["digest"],
        "rule_set_id": w["inventory_body"]["rule_set_id"],
        "authority_revision_id": authority_id,
        "authority_digest": authority.manifest_digest,
        "method_digest": method_digest,
        "range_status": "all_frozen_evidence_submitted",
        "read_evidence_ids_digest": digest(["synthetic-evidence-set"]),
        "extraction_coverage": "partial",
        "quality_status": "not_measured",
    }
    message = {
        "bid_id": w["scope"].bid_id,
        "operation_id": operation["id"],
        "input_digest": operation_digest,
        "payload_ref": blob["id"],
    }
    with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as worker:
        worker.execute("SET search_path=design,public")
        validate_frozen_input(
            worker,
            w["scope"].bid_id,
            frozen,
            [document],
            method,
            method_digest,
            "10000000-0000-0000-0000-000000000001",
        )
        record_completion(
            worker,
            message,
            frozen,
            w["inventory_body"]["rule_set_id"],
            result,
        )
        worker.execute(
            """INSERT INTO design.effect_receipts(operation_id,effect_key,result)
                    VALUES(%s,'extract-rules',%s)""",
            (
                operation["id"],
                Jsonb(
                    {
                        "result_ref": w["inventory_body"]["rule_set_id"],
                        "method_digest": method_digest,
                        "extraction_input_digest": frozen["digest"],
                    }
                ),
            ),
        )
        worker.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=now() WHERE id=%s",
            (operation["id"],),
        )
    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as api:
        api.execute("SET search_path=design,public")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute(
                """INSERT INTO design.bid_package_requirement_extraction_runs(id)
                        VALUES(%s)""",
                (uid(),),
            )

    # Reading history must not depend on object storage being online.
    def unavailable_object_store(key):
        raise AssertionError("historical inventory read accessed object storage")

    monkeypatch.setattr(storage, "get", unavailable_object_store)
    response = inventory(w, tag=legacy_tag)
    assert response.status_code == 201, response.text
    manifest = response.json()["manifest"]
    assert manifest["version"] == "bid-package-requirements/2"
    assert manifest["extraction_binding"] == "exact_frozen_input_result"
    assert manifest["extraction_input_digest"] == frozen["digest"]
    assert manifest["extraction_coverage"] == "partial"
    assert manifest["extraction_quality_status"] == "not_measured"
    assert manifest["inventory_complete"] is False
    assert manifest["review_ready"] is False
    current = w["client"].get(w["requirement_base"] + "/" + manifest["id"])
    assert current.status_code == 200
    assert current.json() == response.json()
    old = w["client"].get(w["requirement_base"] + "/" + legacy["manifest"]["id"])
    assert old.status_code == 200
    assert old.json() == legacy


def test_same_file_new_parse_creates_new_frozen_identity_and_keeps_old_input_unchanged(
    requirements,
):
    from packages.domain.bid_package_extraction import (
        freeze_matching_input,
        validate_frozen_input,
    )
    from packages.domain.bid_package_repository import (
        load_revision,
        read_parse_identity,
        save_revision,
    )
    from packages.domain.bid_packages import PackageError
    from packages.domain.review_identity import digest

    w = requirements
    c = w["database"]["owner"]
    old_revision_id = w["inventory_body"]["authority_revision_id"]
    old_package = load_revision(c, w["scope"].bid_id, old_revision_id)
    old_document = package_extraction_document(c, old_package)
    method = {"engine": "synthetic-test-only", "version": "1"}
    method_digest = digest(method)
    frozen_old = freeze_matching_input(
        c,
        w["scope"].bid_id,
        "10000000-0000-0000-0000-000000000002",
        [old_document],
        method,
        method_digest,
    )
    assert frozen_old is not None
    old_digest = frozen_old["digest"]

    new_parse_id = uid()
    with c.transaction():
        c.execute(
            """INSERT INTO design.parse_runs
                    (id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps)
                    SELECT %s,bid_id,document_version_id,%s,%s,page_count,coverage,gaps
                    FROM design.parse_runs WHERE id=%s""",
            (new_parse_id, "e" * 64, "f" * 64, old_document["parse_id"]),
        )
        c.execute(
            """INSERT INTO design.pages
                    (bid_id,parse_id,physical_page,printed_label,width,height,rotation,quality,gaps)
                    SELECT bid_id,%s,physical_page,printed_label,width,height,rotation,quality,gaps
                    FROM design.pages WHERE parse_id=%s""",
            (new_parse_id, old_document["parse_id"]),
        )
        c.execute(
            """INSERT INTO design.evidence_blocks
                    (id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest)
                    SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest
                    FROM design.evidence_blocks WHERE parse_id=%s""",
            (new_parse_id, old_document["parse_id"]),
        )
    changed_member = replace(
        old_package.members[0],
        parse=read_parse_identity(
            c, w["scope"].bid_id, old_document["document_version_id"], new_parse_id
        ),
    )
    new_package = old_package.next_revision(uid(), (changed_member,))
    save_revision(c, new_package, expected_digest=old_package.manifest_digest)
    new_document = package_extraction_document(c, new_package)
    frozen_new = freeze_matching_input(
        c,
        w["scope"].bid_id,
        "10000000-0000-0000-0000-000000000002",
        [new_document],
        method,
        method_digest,
    )
    assert frozen_new is not None
    assert frozen_new["digest"] != old_digest
    assert frozen_old["digest"] == old_digest
    assert frozen_old["manifest"]["authority_package"]["revision_id"] == old_revision_id
    assert frozen_new["manifest"]["authority_package"]["revision_id"] == new_package.revision_id
    assert frozen_new["manifest"]["members"][0]["parse_run_id"] == new_parse_id

    # A newer parse/head must not invalidate or silently replace the exact old
    # execution input. This exercises the worker-side flattened member shape.
    validate_frozen_input(
        c,
        w["scope"].bid_id,
        frozen_old,
        [old_document],
        method,
        method_digest,
        "10000000-0000-0000-0000-000000000002",
    )

    partial_document = new_document | {"coverage": "partial"}
    assert (
        freeze_matching_input(
            c,
            w["scope"].bid_id,
            "10000000-0000-0000-0000-000000000002",
            [partial_document],
            method,
            method_digest,
        )
        is None
    )
    with pytest.raises(PackageError, match="PACKAGE_EXTRACTION_INPUT_IDENTITY_MISMATCH"):
        validate_frozen_input(
            c,
            uid(),
            frozen_new,
            [new_document],
            method,
            method_digest,
            "10000000-0000-0000-0000-000000000002",
        )


@pytest.mark.parametrize("change", ["text", "missing-block", "page", "member-parts", "scope"])
def test_frozen_extraction_rejects_changed_execution_content(requirements, change):
    from packages.domain.bid_package_extraction import freeze_matching_input, validate_frozen_input
    from packages.domain.bid_package_repository import load_revision
    from packages.domain.bid_packages import PackageError

    w = requirements
    c = w["database"]["owner"]
    bid = w["scope"].bid_id
    package = load_revision(c, bid, w["inventory_body"]["authority_revision_id"])
    document = package_extraction_document(c, package)
    method = {"engine": "synthetic-mechanism-only", "version": "1"}
    material_id = uid()
    frozen = freeze_matching_input(c, bid, material_id, [document], method, digest(method))
    assert frozen is not None
    original = deepcopy(frozen)
    changed = deepcopy(document)
    if change == "text":
        changed["blocks"][0]["text_content"] += " altered"
    elif change == "missing-block":
        changed["blocks"].pop()
    elif change == "page":
        changed["pages"][0]["physical_page"] = 99
    elif change == "member-parts":
        frozen["manifest"]["members"][0]["parts"][0]["last_page"] = 1
        frozen["digest"] = digest(frozen["manifest"])
    else:
        frozen["manifest"]["scope"]["round_id"] = uid()
        frozen["digest"] = digest(frozen["manifest"])
    with pytest.raises(PackageError):
        validate_frozen_input(c, bid, frozen, [changed], method, digest(method), material_id)
    assert digest(original["manifest"]) == original["digest"]
    if change in {"text", "missing-block", "page"}:
        assert freeze_matching_input(c, bid, material_id, [changed], method, digest(method)) is None


def counts(w):
    c = w["database"]["owner"]
    return tuple(
        c.execute("SELECT count(*) AS n FROM design." + table).fetchone()["n"]
        for table in (
            "bid_package_requirement_inventories",
            "bid_package_requirements",
            "bid_package_coverage_attempts",
            "bid_package_coverage_results",
            "commands",
        )
    )


@pytest.mark.parametrize(
    "world", [b"synthetic original bytes for extraction execution"], indirect=True
)
@pytest.mark.parametrize("case", ["duplicate", "fenced", "missing-evidence", "late-rule"])
def test_prepare_compute_publish_with_real_nonowner_execution(requirements, monkeypatch, case):
    from apps.worker import engine
    from packages.domain import model_calls, reviews, storage
    from packages.domain.providers.deepseek import DeepSeekClient
    from packages.domain.review_data import read_json_blob
    from packages.domain.runtime import clean, enqueue_plan

    w = requirements
    c = w["database"]["owner"]
    bid = w["scope"].bid_id
    raw = b"synthetic original bytes for extraction execution"
    objects = {}
    blobs = c.execute(
        "SELECT b.object_key FROM design.blobs b JOIN design.document_versions v ON v.blob_id=b.id WHERE v.bid_id=%s",
        (bid,),
    ).fetchall()
    for blob in blobs:
        objects[blob["object_key"]] = raw
    monkeypatch.setattr(storage, "get", lambda key: objects[key])
    monkeypatch.setattr(storage, "put", lambda key, data, media: objects.__setitem__(key, data))
    monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setenv("WORKER_DATABASE_DSN", w["database"]["worker_dsn"])
    material = str(
        c.execute(
            "SELECT material_id FROM design.rule_sets WHERE id=%s",
            (w["inventory_body"]["rule_set_id"],),
        ).fetchone()["material_id"]
    )
    # Source metadata/parse rows are synthetic; original-byte verification is real.
    authority_version = c.execute(
        "SELECT manifest->'members'->0->>'document_version_id' AS version FROM design.bid_package_revisions WHERE id=%s",
        (w["inventory_body"]["authority_revision_id"],),
    ).fetchone()["version"]
    with c.transaction():
        for role, version in [
            ("body", w["member"].document_version_id),
            ("tender", authority_version),
        ]:
            c.execute(
                "INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal) VALUES(%s,%s,%s,%s,0)",
                (material, bid, version, role),
            )
        c.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s,current_body_id=%s WHERE bid_id=%s",
            (material, w["member"].document_version_id, bid),
        )
        c.execute("UPDATE design.bids SET material_revision=1 WHERE id=%s", (bid,))
        command = uid()
        c.execute(
            "INSERT INTO design.commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic-parse-seed',%s,%s,%s)",
            (command, w["actor"], bid, uid(), digest({"material": material})),
        )
        parsed = enqueue_plan(
            c,
            bid,
            command,
            "parse-materials",
            {"id": material},
            stages=[{"key": "parse", "depends_on": []}],
            handler_version="document/2",
            topic="tender.task.document.v1",
            input_digest=digest({"material": material}),
        )
        c.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=now() WHERE id=%s",
            (parsed["id"],),
        )

    calls = []

    def model(message, lease, **kwargs):
        content = json.loads(kwargs["messages"][-1]["content"])
        blocks = [
            block for document in content["documents"] for block in document["evidence_blocks"]
        ]
        calls.append(content)
        if case == "late-rule":
            with c.transaction():
                replacement = uid()
                c.execute(
                    "INSERT INTO design.rule_sets(id,bid_id,material_id,revision,digest,coverage) VALUES(%s,%s,%s,2,%s,'partial')",
                    (replacement, bid, material, digest(replacement)),
                )
                c.execute(
                    "UPDATE design.bid_profiles SET current_rule_set_id=%s WHERE bid_id=%s",
                    (replacement, bid),
                )
        return {
            "data": {
                "rules": [
                    {
                        "kind": "mandatory",
                        "statement": blocks[0]["text_content"],
                        "conditions": [],
                        "exceptions": [],
                        "scope": {"bid_id": bid, "description": "Synthetic execution only"},
                        "maximum": None,
                        "bands": [],
                        "evidence_quotes": [
                            {
                                "evidence_id": str(blocks[0]["id"]),
                                "quote": blocks[0]["text_content"],
                            }
                        ],
                    }
                ],
                "ambiguities": [],
                "read_evidence_ids": [
                    str(block["id"])
                    for block in (blocks[:-1] if case == "missing-evidence" else blocks)
                ],
            }
        }, uid()

    monkeypatch.setattr(model_calls, "generate", model)
    detail = w["client"].get("/api/v1/bids/" + bid)
    request_headers = headers(w) | {"If-Match": detail.headers["etag"]}
    response = w["client"].post(
        "/api/v1/bids/" + bid + "/reviews",
        json={
            "body_version_id": w["member"].document_version_id,
            "material_revision": 1,
            "trigger": "manual",
        },
        headers=request_headers,
    )
    assert response.status_code == 202, response.text
    reviews.prepare_intent(bid)
    slot = c.execute(
        "SELECT pending_intent FROM design.review_slots WHERE bid_id=%s", (bid,)
    ).fetchone()["pending_intent"]
    operation = slot["prepare_operation_id"]
    assert operation != str(parsed["id"])
    message = clean(
        c.execute(
            "SELECT payload FROM design.outbox WHERE operation_id=%s AND payload->>'step_key'='extract-rules'",
            (operation,),
        ).fetchone()["payload"]
    )
    descriptor = read_json_blob(
        c.execute("SELECT * FROM design.blobs WHERE id=%s", (message["payload_ref"],)).fetchone()
    )
    frozen = descriptor["package_rule_extraction_input"]
    assert (
        frozen["manifest"]["authority_package"]["revision_id"]
        == w["inventory_body"]["authority_revision_id"]
    )
    if case == "fenced":
        old_lease = engine.acquire(message)
        c.execute(
            "UPDATE design.step_receipts SET lease_until=now()-interval '1 second' WHERE operation_id=%s",
            (operation,),
        )
        lease = engine.acquire(message)
        assert lease["fence"] > old_lease["fence"]
        outcome = engine.run_compute(message, lease)
        assert engine.finish(message, old_lease, outcome) is False
        assert engine.finish(message, lease, outcome) is True
    else:
        engine.handle(message)
    engine.handle(message)
    assert len(calls) == 1
    state = c.execute("SELECT state FROM design.operations WHERE id=%s", (operation,)).fetchone()[
        "state"
    ]
    result = c.execute(
        "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='extract-rules'",
        (operation,),
    ).fetchone()["result"]
    records = c.execute(
        "SELECT * FROM design.bid_package_requirement_extraction_runs WHERE operation_id=%s",
        (operation,),
    ).fetchall()
    if case in {"missing-evidence", "late-rule"}:
        assert state == "failed", result
        assert result["error_code"] == (
            "EXTRACTION_RANGE_INCOMPLETE"
            if case == "missing-evidence"
            else "PREPARATION_RULE_SET_CHANGED"
        )
        assert records == []
    else:
        assert state == "succeeded", result
        assert len(records) == 1
        assert records[0]["input_digest"] == frozen["digest"]
        assert result["extraction_input_digest"] == frozen["digest"]
        body = {
            "authority_revision_id": w["inventory_body"]["authority_revision_id"],
            "rule_set_id": result["result_ref"],
            "mappings": [],
        }
        saved = inventory(w, body=body)
        assert saved.status_code == 201, saved.text
        assert saved.json()["manifest"]["extraction_binding"] == "exact_frozen_input_result"
        assert saved.json()["manifest"]["inventory_complete"] is False


def test_actual_nonowner_inventory_attempt_history_and_cas(requirements):
    w = requirements
    key = uid()
    first = inventory(w, key=key)
    assert first.status_code == 201, first.text
    value = first.json()
    assert valid("PackageRequirementInventoryView", value)
    assert value["manifest"]["inventory_complete"] is False
    assert value["manifest"]["extraction_binding"] == "unproven_legacy_rule_set"
    assert inventory(w, key=key).json() == value
    assert inventory(w).status_code == 412
    second = inventory(w, tag=first.headers["etag"])
    assert second.status_code == 201, second.text
    assert second.json()["manifest"]["predecessor_digest"] == value["digest"]
    assert w["client"].get(w["requirement_base"] + "/" + value["manifest"]["id"]).json() == value
    page = w["client"].get(w["requirement_base"]).json()
    assert valid("PackageRequirementInventoryPage", page)
    inv = second.json()
    path = w["requirement_base"] + "/" + inv["manifest"]["id"] + "/coverage-attempts"
    checked = w["client"].post(path, json=attempt_body(w, inv), headers=headers(w))
    assert checked.status_code == 201, checked.text
    assert valid("PackageCoverageAttemptView", checked.json())
    assessment = checked.json()["manifest"]["assessment"]
    assert assessment["requirement_states"] == {w["rule"]: "verified"}
    assert assessment["complete"] is False
    assert w["client"].get(path + "/" + checked.json()["manifest"]["id"]).json() == checked.json()
    assert valid("PackageRequirementHistoryPage", w["client"].get(path).json())


@pytest.mark.parametrize("bad", ["bad\x00id", "bad\ud800id", "bad\udfffid"])
def test_raw_escaped_json_invalid_part_is_422_without_command_or_rows(requirements, bad):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    body = attempt_body(w, response.json(), state="unknown")
    body["results"][0]["inspected"][0]["part_id"] = bad
    before = counts(w)
    path = w["requirement_base"] + "/" + response.json()["manifest"]["id"] + "/coverage-attempts"
    rejected = w["client"].post(
        path,
        content=json.dumps(body, ensure_ascii=True),
        headers=headers(w) | {"Content-Type": "application/json"},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["retryable"] is False
    assert counts(w) == before


def test_required_precondition_and_real_auth_csrf(requirements):
    w = requirements
    before = counts(w)
    assert (
        w["client"]
        .post(w["requirement_base"], json=w["inventory_body"], headers=headers(w))
        .status_code
        == 428
    )
    no_csrf = headers(w)
    no_csrf.pop("X-CSRF-Token")
    assert (
        w["client"]
        .post(
            w["requirement_base"],
            json=w["inventory_body"],
            headers=no_csrf | {"If-None-Match": "*"},
        )
        .status_code
        == 403
    )
    assert counts(w) == before


def test_commit_time_expiry_is_nonretryable_409_and_rolls_back_ack(requirements):
    w = requirements
    c = w["database"]["owner"]
    # This test-only DB trigger delays the real Command ACK, after early checks.
    c.execute(
        "UPDATE retrieval.source_heads SET valid_until=clock_timestamp()+interval '500 milliseconds' WHERE source_id=%s",
        (w["sources"][0],),
    )
    c.execute(
        "CREATE FUNCTION design.synthetic_requirements_ack_delay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_kind='create_package_requirement_inventory' THEN PERFORM pg_sleep(0.7); END IF; RETURN NEW; END $$"
    )
    c.execute(
        "CREATE TRIGGER synthetic_requirements_ack_delay BEFORE UPDATE ON design.commands FOR EACH ROW EXECUTE FUNCTION design.synthetic_requirements_ack_delay()"
    )
    before = counts(w)
    try:
        rejected = inventory(w)
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["code"] == "PACKAGE_REQUIREMENT_SOURCE_NOT_EFFECTIVE"
        assert rejected.json()["retryable"] is False
        assert counts(w) == before
    finally:
        c.execute("DROP TRIGGER synthetic_requirements_ack_delay ON design.commands")
        c.execute("DROP FUNCTION design.synthetic_requirements_ack_delay()")


def insert_attempt(c, w, manifest):
    c.execute(
        "INSERT INTO design.bid_package_coverage_attempts(id,bid_id,inventory_id,digest,manifest,actor_id) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            manifest["id"],
            w["scope"].bid_id,
            manifest["inventory_id"],
            digest(manifest),
            Jsonb(manifest),
            w["actor"],
        ),
    )


def test_direct_sql_cannot_forge_verified_assessment_with_omitted_results(requirements):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    target = w["own"]["manifest"]["revision_id"]
    from packages.domain.bid_package_requirement_repository import create_attempt

    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as c:
        c.execute("SET LOCAL search_path=design,public")
        legal = create_attempt(
            c,
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            target,
            inv["manifest"]["id"],
            attempt_body(w, inv) | {"actor_id": w["actor"]},
        )
    forged = deepcopy(legal["manifest"])
    forged["id"] = uid()
    forged["results"] = []
    before = counts(w)
    with pytest.raises(psycopg.errors.CheckViolation, match="requirement_assessment_mismatch"):
        with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as c:
            c.execute("SET LOCAL search_path=design,public")
            insert_attempt(c, w, forged)
    assert counts(w) == before


def test_direct_sql_rechecks_changed_current_decision_at_commit(requirements):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    c = w["database"]["owner"]
    replacement = uid()
    c.execute(
        "INSERT INTO design.decisions(id,bid_id,object_kind,object_id,object_revision,decision,reason,evidence_ids,actor_id) VALUES(%s,%s,'rule',%s,2,'rejected','Synthetic changed decision',%s,%s)",
        (replacement, w["scope"].bid_id, w["rule"], [w["evidence"]], w["actor"]),
    )
    c.execute(
        "UPDATE design.decision_heads SET revision=2,decision_id=%s WHERE bid_id=%s AND object_id=%s",
        (replacement, w["scope"].bid_id, w["rule"]),
    )
    from packages.domain.bid_package_repository import load_revision
    from packages.domain.bid_package_requirement_repository import load_inventory
    from packages.domain.bid_package_requirements import assess_records

    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as reader:
        reader.execute("SET LOCAL search_path=design,public")
        p = load_revision(reader, w["scope"].bid_id, w["own"]["manifest"]["revision_id"])
        assert (
            load_inventory(
                reader,
                w["scope"].bid_id,
                w["own"]["manifest"]["package_id"],
                p.revision_id,
                inv["manifest"]["id"],
            )
            == inv
        )
    manifest = {
        "version": "bid-package-coverage/1",
        "id": uid(),
        "bid_id": w["scope"].bid_id,
        "inventory_id": inv["manifest"]["id"],
        "inventory_digest": inv["digest"],
        "package_digest": p.manifest_digest,
        "actor_id": w["actor"],
        "results": [],
        "assessment": assess_records(p, inv["manifest"]["requirements"], []),
        "review_ready": False,
    }
    before = counts(w)
    with pytest.raises(psycopg.errors.CheckViolation, match="requirement_decision_stale"):
        with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as writer:
            writer.execute("SET LOCAL search_path=design,public")
            insert_attempt(writer, w, manifest)
    assert counts(w) == before


@pytest.mark.parametrize(
    "value", ["2026-10-19T24:00:00Z", "2026-10-19T12:01:60Z", "2026-02-30T12:00:00Z"]
)
def test_database_timestamp_shape_matches_python_rejection(requirements, value):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    req = deepcopy(response.json()["manifest"]["requirements"][0]["requirement"])
    req["valid_at"] = value
    c = w["database"]["owner"]
    assert (
        c.execute("SELECT design.bid_requirement_shape(%s) AS ok", (Jsonb(req),)).fetchone()["ok"]
        is False
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("applicability", None),
        ("minimum_count", 9007199254740992),
        ("checks", [None]),
        ("conditions", ["duplicate", "duplicate"]),
        ("target_part_ids", False),
    ],
)
def test_database_requirement_shape_rejects_null_type_unsafe_and_duplicates(
    requirements, field, value
):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    req = deepcopy(response.json()["manifest"]["requirements"][0]["requirement"])
    req[field] = value
    assert (
        w["database"]["owner"]
        .execute("SELECT design.bid_requirement_shape(%s) AS ok", (Jsonb(req),))
        .fetchone()["ok"]
        is False
    )


def wait_for_service_lock(w, other_pid, role="fusion_package_requirements_service"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if (
            w["database"]["owner"]
            .execute(
                "SELECT 1 FROM pg_stat_activity WHERE usename=%s AND pid<>%s AND wait_event_type='Lock'",
                (role, other_pid),
            )
            .fetchone()
        ):
            return
        time.sleep(0.02)
    raise AssertionError("second real service connection did not wait on authority lock")


def test_absent_decision_head_insert_wins_and_waiting_api_rolls_back(requirements):
    w = requirements
    owner = w["database"]["owner"]
    decision = owner.execute(
        "DELETE FROM design.decision_heads WHERE bid_id=%s AND object_id=%s RETURNING decision_id",
        (w["scope"].bid_id, w["rule"]),
    ).fetchone()["decision_id"]
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    assert inv["manifest"]["requirements"][0]["decision_id"] is None
    before = counts(w)
    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as writer:
        writer.execute("SET LOCAL search_path=design,public")
        pid = writer.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
        writer.execute(
            "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'rule',%s,1,%s)",
            (w["scope"].bid_id, w["rule"], decision),
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                w["client"].post,
                w["requirement_base"] + "/" + inv["manifest"]["id"] + "/coverage-attempts",
                json=attempt_body(w, inv, state="unknown"),
                headers=headers(w),
            )
            try:
                wait_for_service_lock(w, pid)
            finally:
                writer.commit()
            rejected = pending.result(timeout=10)
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["code"] == "PACKAGE_REQUIREMENT_DECISION_STALE"
    assert rejected.json()["retryable"] is False
    assert counts(w) == before


def test_absent_decision_head_waits_for_attempt_commit_and_history_remains_exact(requirements):
    w = requirements
    owner = w["database"]["owner"]
    decision = owner.execute(
        "DELETE FROM design.decision_heads WHERE bid_id=%s AND object_id=%s RETURNING decision_id",
        (w["scope"].bid_id, w["rule"]),
    ).fetchone()["decision_id"]
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    from packages.domain.bid_package_requirement_repository import create_attempt

    def insert_head():
        with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as other:
            other.execute("SET LOCAL search_path=design,public")
            other.execute(
                "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'rule',%s,1,%s)",
                (w["scope"].bid_id, w["rule"], decision),
            )

    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as writer:
        writer.execute("SET LOCAL search_path=design,public")
        pid = writer.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
        frozen = create_attempt(
            writer,
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            inv["manifest"]["id"],
            attempt_body(w, inv, state="unknown") | {"actor_id": w["actor"]},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(insert_head)
            try:
                wait_for_service_lock(w, pid)
            finally:
                writer.commit()
            pending.result(timeout=10)
    history = w["client"].get(
        w["requirement_base"]
        + "/"
        + inv["manifest"]["id"]
        + "/coverage-attempts/"
        + frozen["manifest"]["id"]
    )
    assert history.status_code == 200, history.text
    assert history.json() == frozen


def test_worker_carryover_empty_key_waits_for_same_bid_without_bids_update_privilege(requirements):
    w = requirements
    owner = w["database"]["owner"]
    owner.execute(
        "DELETE FROM design.decision_heads WHERE bid_id=%s AND object_id=%s",
        (w["scope"].bid_id, w["rule"]),
    )
    old_set, old_rule, old_decision = uid(), uid(), uid()
    owner.execute(
        "INSERT INTO design.rule_sets(id,bid_id,material_id,revision,digest,coverage) SELECT %s,bid_id,material_id,2,%s,coverage FROM design.rule_sets WHERE id=%s",
        (old_set, digest(old_set), w["inventory_body"]["rule_set_id"]),
    )
    owner.execute(
        "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,evidence_ids,bands) SELECT %s,bid_id,%s,kind,statement,conditions,exceptions,evidence_ids,bands FROM design.rule_items WHERE id=%s",
        (old_rule, old_set, w["rule"]),
    )
    owner.execute(
        "INSERT INTO design.decisions(id,bid_id,object_kind,object_id,object_revision,decision,reason,evidence_ids,actor_id) VALUES(%s,%s,'rule',%s,1,'confirmed','Synthetic prior rule decision',%s,%s)",
        (old_decision, w["scope"].bid_id, old_rule, [w["evidence"]], w["actor"]),
    )
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    from packages.domain.bid_package_requirement_repository import create_attempt

    def insert_carryover():
        with psycopg.connect(w["database"]["worker_dsn"], row_factory=dict_row) as worker:
            worker.execute("SET LOCAL search_path=design,public")
            assert (
                worker.execute(
                    "SELECT has_table_privilege(current_user,'design.bids','UPDATE') AS allowed"
                ).fetchone()["allowed"]
                is False
            )
            worker.execute(
                "INSERT INTO design.rule_carryovers(bid_id,new_rule_id,from_rule_id,from_decision_id,equivalence_digest) VALUES(%s,%s,%s,%s,%s)",
                (
                    w["scope"].bid_id,
                    w["rule"],
                    old_rule,
                    old_decision,
                    digest("synthetic equivalent"),
                ),
            )

    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as writer:
        writer.execute("SET LOCAL search_path=design,public")
        pid = writer.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
        frozen = create_attempt(
            writer,
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            inv["manifest"]["id"],
            attempt_body(w, inv, state="unknown") | {"actor_id": w["actor"]},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(insert_carryover)
            try:
                wait_for_service_lock(w, pid, "fusion_package_requirements_worker")
            finally:
                writer.commit()
            pending.result(timeout=10)
    assert frozen["manifest"]["assessment"]["requirement_states"] == {w["rule"]: "unknown"}
    before = counts(w)
    rejected = w["client"].post(
        w["requirement_base"] + "/" + inv["manifest"]["id"] + "/coverage-attempts",
        json=attempt_body(w, inv, state="unknown"),
        headers=headers(w),
    )
    assert rejected.status_code == 409, rejected.text
    assert counts(w) == before


def test_new_known_source_alias_waits_for_graph_locked_attempt(requirements):
    w = requirements
    response = inventory(w)
    assert response.status_code == 201, response.text
    inv = response.json()
    from packages.domain.bid_package_requirement_repository import create_attempt

    def insert_alias():
        with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as other:
            other.execute("SET LOCAL search_path=design,public")
            other.execute(
                "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'label','official_label',now(),%s)",
                (uid(), w["member"].document_version_id, digest("synthetic forbidden alias")),
            )

    with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as writer:
        writer.execute("SET LOCAL search_path=design,public")
        pid = writer.execute("SELECT pg_backend_pid() AS id").fetchone()["id"]
        create_attempt(
            writer,
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            inv["manifest"]["id"],
            attempt_body(w, inv, state="unknown") | {"actor_id": w["actor"]},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(insert_alias)
            try:
                wait_for_service_lock(w, pid)
            finally:
                writer.commit()
            pending.result(timeout=10)
    before = counts(w)
    rejected = inventory(w, tag=response.headers["etag"])
    assert rejected.status_code == 409, rejected.text
    assert counts(w) == before
