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
            "INSERT INTO design.rule_items(id,bid_id,rule_set_id,kind,statement,conditions,exceptions,evidence_ids,bands) VALUES(%s,%s,%s,'mandatory','Synthetic original obligation','[]','[]',%s,'[]')",
            (rule, scope.bid_id, rule_set, [evidence]),
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
