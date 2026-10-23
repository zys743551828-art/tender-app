"""Real frozen scope/current facts behind one independent native RPC."""
# ruff: noqa: F401,F811

import json
import os
import secrets
from copy import deepcopy
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_bid_package_requirements_api import ADMIN_DSN
from test_bid_package_requirements_api import inventory as append_inventory
from test_package_technical_scope_pg import api, exact, freeze, requirements, world
from test_package_technical_scope_pg import database as scope_database
from test_stable_lot_identity import headers

from packages.domain.review_identity import digest
from packages.model_governance import package_current_scope as current

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CURRENT_SCOPE_PG") != "1",
    reason="explicit grouped native current scope required",
)
LOGIN = "fusion_current_scope_verify"


@pytest.fixture(scope="module")
def database():
    original = scope_database.__wrapped__()
    value = next(original)
    owner = value["owner"]
    password = secrets.token_urlsafe(36)
    try:
        assert not owner.execute(
            "SELECT 1 AS present FROM pg_roles WHERE rolname=ANY(%s)", ([LOGIN, current.GROUP],)
        ).fetchone()
        owner.execute(current.SQL_FILE.read_text(encoding="utf-8"))
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(LOGIN), sql.Literal(password))
        )
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(current.GROUP), sql.Identifier(LOGIN))
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=LOGIN, password=password)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as verifier:
            yield value | {"scope_verifier": verifier}
    finally:
        try:
            next(original)
        except StopIteration:
            pass
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LOGIN)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(current.GROUP)))


@pytest.fixture
def saved(exact):
    response, replayed = freeze(exact)
    assert not replayed
    return exact | {"saved_scope": response["body"]["scope"]}


def observe(w, **changes):
    args = {
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "expected_method_digest": current.method_digest(),
    } | changes
    return current.observe(w["database"]["scope_verifier"], **args)


def test_native_current_packages_identity_inventory_and_exclusions(saved):
    w = saved
    value = observe(w).metadata
    assert value["scope"] == w["saved_scope"]
    assert value["native_current_facts_checked"]
    assert value["current_identity"]["binding_status"] == "confirmed"
    assert value["digest"] == digest({k: v for k, v in value.items() if k != "digest"})
    for key in (
        "necessary_scope_verified",
        "original_bytes_reverified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ):
        assert value[key] is False
    preview = value["scope"]["manifest"]["preview"]["manifest"]
    assert any(row["selection"] == "exclude" for row in preview["rules"])
    assert preview["coverage"]["required_range_completeness"] == "unproven"
    verifier = w["database"]["scope_verifier"]
    for query in (
        "SELECT * FROM design.bid_package_technical_scopes",
        "SELECT * FROM design.outcomes",
        "SELECT * FROM design.submission_records",
        "SELECT * FROM design.audit_entries",
        "SELECT * FROM retrieval.chunks",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            verifier.execute(query)
    evidence = os.environ.get("FUSION_CURRENT_SCOPE_EVIDENCE")
    if evidence:
        (Path(evidence) / "current-scope-native-observation.json").write_text(
            json.dumps(
                {"actual_login": LOGIN, "observation": value, "denied_direct_queries": 5}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize("phase", ["submitted", "closed", "terminated"])
def test_closed_or_submitted_project_rejects_and_old_scope_is_unchanged(saved, phase):
    w = saved
    original = deepcopy(w["saved_scope"])
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase=%s WHERE bid_id=%s", (phase, w["technical_scope"][0])
    )
    with pytest.raises(current.CurrentScopeError, match="NOT_CURRENT_PREBID"):
        observe(w)
    assert w["saved_scope"] == original


def test_current_identity_changed_rejects(saved):
    w = saved
    w["database"]["owner"].execute(
        "UPDATE design.engineering_projects SET title=title||' changed' WHERE id=%s",
        (w["scope"].engineering_project_id,),
    )
    with pytest.raises(current.CurrentScopeError, match="IDENTITY_CHANGED"):
        observe(w)


def test_current_rule_set_changed_rejects(saved):
    w = saved
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET current_rule_set_id=NULL WHERE bid_id=%s",
        (w["technical_scope"][0],),
    )
    with pytest.raises(current.CurrentScopeError, match="RULES_CHANGED"):
        observe(w)


@pytest.mark.parametrize(
    "field", ["scope_id", "bid_id", "expected_scope_digest", "expected_method_digest"]
)
def test_wrong_frozen_identity_or_method_rejects(saved, field):
    from uuid import uuid4

    value = str(uuid4()) if field.endswith("_id") else "0" * 64
    with pytest.raises(current.CurrentScopeError):
        observe(saved, **{field: value})


def test_owner_api_and_borrowed_transaction_reject(saved):
    w = saved
    args = {
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "expected_method_digest": current.method_digest(),
    }
    with pytest.raises(current.CurrentScopeError, match="INDEPENDENT_LOGIN_REQUIRED"):
        current.observe(w["database"]["owner"], **args)
    with psycopg.connect(w["database"]["api_dsn"], autocommit=True) as api_connection:
        with pytest.raises(current.CurrentScopeError, match="INDEPENDENT_MEMBERSHIP_REQUIRED"):
            current.observe(api_connection, **args)
    with w["database"]["scope_verifier"].transaction():
        with pytest.raises(current.CurrentScopeError, match="IDLE_CONNECTION_REQUIRED"):
            observe(w)


@pytest.mark.parametrize("grant", ["table", "label", "extra_role", "public_definer"])
def test_effective_excess_permissions_reject(saved, grant):
    w = saved
    c = w["database"]["owner"]
    if grant == "table":
        command = (
            "GRANT SELECT(id) ON design.bid_package_technical_scopes TO tender_current_scope_verify"
        )
        undo = "REVOKE SELECT(id) ON design.bid_package_technical_scopes FROM tender_current_scope_verify"
    elif grant == "label":
        command = "GRANT SELECT ON design.outcomes TO PUBLIC"
        undo = "REVOKE SELECT ON design.outcomes FROM PUBLIC"
    elif grant == "extra_role":
        command = f"GRANT tender_api TO {LOGIN}"
        undo = f"REVOKE tender_api FROM {LOGIN}"
    else:
        c.execute(
            "CREATE FUNCTION current_technical_scope.synthetic_definer() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
        )
        command = "GRANT EXECUTE ON FUNCTION current_technical_scope.synthetic_definer() TO PUBLIC"
        undo = "DROP FUNCTION current_technical_scope.synthetic_definer()"
    try:
        c.execute(command)
        with pytest.raises(current.CurrentScopeError):
            observe(w)
    finally:
        c.execute(undo)
    assert observe(w).metadata["native_current_facts_checked"]


def test_native_rpc_body_replacement_rejects_without_executing_it(saved):
    w = saved
    c = w["database"]["owner"]
    original = c.execute(
        "SELECT pg_get_functiondef(%s::regprocedure) AS ddl", (current.RPC,)
    ).fetchone()["ddl"]
    try:
        c.execute(
            "CREATE OR REPLACE FUNCTION current_technical_scope.observe(target_bid uuid,target_scope uuid,expected_digest text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,design,pg_temp AS $$ BEGIN RAISE EXCEPTION 'must not execute substituted body'; END $$"
        )
        with pytest.raises(current.CurrentScopeError, match="NATIVE_METHOD_MISMATCH"):
            observe(w)
    finally:
        c.execute(original)
    assert observe(w).metadata["native_current_facts_checked"]


@pytest.mark.parametrize("role", ["target", "authority"])
def test_real_new_package_revision_rejects_old_scope_without_changing_receipt(saved, role):
    w = saved
    old = observe(w).metadata
    manifest = old[role]["manifest"]
    path = w["base"] + "/" + manifest["package_id"]
    current_package = w["client"].get(path)
    assert current_package.status_code == 200
    members = [
        {
            "member_id": m["member_id"],
            "document_version_id": m["document_version_id"],
            "parse_run_id": m["parse"]["parse_run_id"],
            "purposes": m["purposes"],
            "parts": m["parts"],
        }
        for m in manifest["members"]
    ]
    response = w["client"].post(
        path + "/revisions",
        json={"members": members},
        headers=headers(w, etag=current_package.headers["etag"]),
    )
    assert response.status_code == 201, response.text
    code = "TARGET_CHANGED" if role == "target" else "AUTHORITY_CHANGED"
    with pytest.raises(current.CurrentScopeError, match=code):
        observe(w)
    assert old["scope"] == w["saved_scope"]


def test_real_new_inventory_rejects_old_scope(saved):
    w = saved
    current_inventory = w["client"].get(
        w["requirement_base"] + "/" + w["inventory"]["manifest"]["id"]
    )
    assert current_inventory.status_code == 200
    response = append_inventory(w, tag=current_inventory.headers["etag"])
    assert response.status_code == 201, response.text
    with pytest.raises(current.CurrentScopeError, match="INVENTORY_CHANGED"):
        observe(w)


def test_default_rpc_call_without_owned_readonly_transaction_is_rejected(saved):
    w = saved
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        w["database"]["scope_verifier"].execute(
            "SELECT current_technical_scope.observe(%s,%s,%s)",
            (
                w["technical_scope"][0],
                w["saved_scope"]["manifest"]["id"],
                w["saved_scope"]["digest"],
            ),
        )


def test_rpc_owned_by_inherited_group_is_not_independent(saved):
    w = saved
    c = w["database"]["owner"]
    owner = c.execute(
        "SELECT pg_get_userbyid(proowner) AS name FROM pg_proc WHERE oid=%s::regprocedure",
        (current.RPC,),
    ).fetchone()["name"]
    try:
        c.execute(
            "ALTER FUNCTION current_technical_scope.observe(uuid,uuid,text) OWNER TO tender_current_scope_verify"
        )
        with pytest.raises(current.CurrentScopeError, match="NATIVE_METHOD_MISMATCH"):
            observe(w)
    finally:
        c.execute(
            sql.SQL(
                "ALTER FUNCTION current_technical_scope.observe(uuid,uuid,text) OWNER TO {}"
            ).format(sql.Identifier(owner))
        )
        c.execute(
            "GRANT EXECUTE ON FUNCTION current_technical_scope.observe(uuid,uuid,text) TO tender_current_scope_verify"
        )
    assert observe(w).metadata["native_current_facts_checked"]
