"""Approved optional locator grants, isolated native PG and synthetic loopback bytes."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
import secrets
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_package_current_scope_pg import ADMIN_DSN, api, exact, requirements, saved, world
from test_package_current_scope_pg import database as scope_database

from packages.domain.providers import original_bytes as byte_port
from packages.domain.review_identity import digest
from packages.model_governance import package_current_original as current
from packages.model_governance import package_current_scope as scope_port

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CURRENT_ORIGINAL_PG") != "1",
    reason="explicit grouped isolated original locator check required",
)
LOGIN = "fusion_current_original_verify"


@pytest.fixture(scope="module")
def database():
    base = scope_database.__wrapped__()
    value = next(base)
    owner = value["owner"]
    password = secrets.token_urlsafe(36)
    try:
        assert not owner.execute(
            "SELECT FROM pg_roles WHERE rolname=ANY(%s)", ([LOGIN, current.GROUP],)
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
            yield value | {"original_verifier": verifier}
    finally:
        # Database objects/ACL disappear with the independent DB. Remove the
        # inter-group dependency before the inner fixture drops its scope role.
        owner.execute("REVOKE tender_current_scope_verify FROM tender_current_original_verify")
        try:
            next(base)
        except StopIteration:
            pass
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LOGIN)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(current.GROUP)))


def observe(w, **changes):
    file = w["saved_scope"]["manifest"]["original_verification"]["files"][0]
    args = {
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "document_version_id": file["document_version_id"],
        "expected_original_digest": file["digest"],
        "expected_method_digest": current.method_digest(),
    } | changes
    return current.observe(w["database"]["original_verifier"], **args)


def test_native_locator_then_complete_actual_loopback_bytes(saved, caplog):
    w = saved
    observed = observe(w)
    public = json.dumps(observed.metadata)
    assert observed.locator not in public and observed.locator not in repr(observed)
    assert observed.metadata["digest"] == digest(
        {k: v for k, v in observed.metadata.items() if k != "digest"}
    )
    attempts = []
    path = "/synthetic-bucket/" + quote(observed.locator, safe="")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == path
            attempts.append(
                {"method": self.command, "accept_encoding": self.headers["Accept-Encoding"]}
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(w["io"]["data"])))
            self.end_headers()
            self.wfile.write(w["io"]["data"])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        m = observed.metadata
        request = byte_port.prepare_get(
            url=f"http://127.0.0.1:{server.server_port}" + path,
            profile="development_s3",
            **{
                k: m[k]
                for k in (
                    "bid_id",
                    "scope_id",
                    "scope_digest",
                    "document_version_id",
                    "source_digest",
                    "source_byte_size",
                )
            },
        )
        result = asyncio.run(
            byte_port.OriginalByteClient().read(
                request,
                expected_request_digest=request.metadata["digest"],
                expected_method_digest=byte_port.method_digest(),
            )
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    assert result.data == w["io"]["data"]
    assert attempts == [{"method": "GET", "accept_encoding": "identity"}]
    assert result.metadata["complete_requested_bytes_verified"] is True
    assert result.metadata["native_permission_verified"] is False
    assert observed.locator not in caplog.text
    for key in (
        "original_bytes_reverified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ):
        assert observed.metadata[key] is False
    evidence = os.environ.get("FUSION_CURRENT_ORIGINAL_EVIDENCE")
    if evidence:
        (Path(evidence) / "original-native-byte-proof.json").write_text(
            json.dumps(
                {
                    "actual_login": LOGIN,
                    "locator_observation": observed.metadata,
                    "byte_receipt": result.metadata,
                    "wire": attempts,
                    "synthetic_content": True,
                    "real_oss_or_s3_reads": 0,
                    "formal_binding_registered": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "field",
    [
        "bid_id",
        "scope_id",
        "document_version_id",
        "expected_scope_digest",
        "expected_original_digest",
        "expected_method_digest",
    ],
)
def test_wrong_identity_or_method_rejects(saved, field):
    with pytest.raises(current.CurrentOriginalError):
        observe(saved, **{field: str(uuid4()) if field.endswith("_id") else "0" * 64})


@pytest.mark.parametrize("change", ["withdrawn", "expired", "future", "revision", "missing"])
def test_every_source_head_is_current_and_old_scope_unchanged(saved, change):
    w = saved
    before = deepcopy(w["saved_scope"])
    rows = before["manifest"]["preview"]["manifest"]["source_snapshot"]
    # Choose a different file's root: verification must check the whole scope.
    file = before["manifest"]["original_verification"]["files"][0]
    root = next(
        r["ancestor_id"] for r in rows if r["document_version_id"] != file["document_version_id"]
    )
    command = {
        "withdrawn": "status='withdrawn'",
        "expired": "valid_from=least(valid_from,clock_timestamp()-interval '2 seconds'),valid_until=clock_timestamp()-interval '1 second'",
        "future": "valid_from=clock_timestamp()+interval '1 hour'",
        "revision": "revision=revision+1",
    }
    owner = w["database"]["owner"]
    if change == "missing":
        owner.execute("DELETE FROM retrieval.source_heads WHERE source_id=%s", (root,))
    else:
        owner.execute(
            "UPDATE retrieval.source_heads SET " + command[change] + " WHERE source_id=%s", (root,)
        )
    with pytest.raises(current.CurrentOriginalError, match="SOURCES_CHANGED"):
        observe(w)
    assert w["saved_scope"] == before
    assert (
        owner.execute(
            "SELECT digest FROM design.bid_package_technical_scopes WHERE id=%s",
            (before["manifest"]["id"],),
        ).fetchone()["digest"]
        == before["digest"]
    )


def test_added_ancestor_rejects_even_if_old_rows_still_match(saved):
    w = saved
    owner = w["database"]["owner"]
    rows = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"]
    original = next(r for r in rows if r["source_id"] == r["ancestor_id"])
    new = str(uuid4())
    owner.execute(
        "INSERT INTO retrieval.source_nodes(id,document_version_id,digest,kind,policy_class,known_at) SELECT %s,document_version_id,digest,kind,policy_class,known_at FROM retrieval.source_nodes WHERE id=%s",
        (new, original["ancestor_id"]),
    )
    owner.execute(
        "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now())",
        (new,),
    )
    owner.execute(
        "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
        (original["source_id"], new),
    )
    with pytest.raises(current.CurrentOriginalError, match="SOURCE_CLOSURE_CHANGED"):
        observe(w)


def test_no_direct_table_read_and_other_logins_cannot_locate(saved):
    w = saved
    for query in (
        "SELECT object_key FROM design.blobs",
        "SELECT * FROM design.bid_package_technical_scopes",
        "SELECT * FROM design.outcomes",
        "SELECT * FROM retrieval.chunks",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w["database"]["original_verifier"].execute(query)
    for key in ("scope_verifier", "owner"):
        with pytest.raises(current.CurrentOriginalError, match="INDEPENDENT"):
            current.observe(
                w["database"][key],
                bid_id=w["technical_scope"][0],
                scope_id=w["saved_scope"]["manifest"]["id"],
                expected_scope_digest=w["saved_scope"]["digest"],
                document_version_id=w["member"].document_version_id,
                expected_original_digest=w["member"].file_digest,
                expected_method_digest=current.method_digest(),
            )
    with psycopg.connect(w["database"]["api_dsn"], autocommit=True) as api_connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api_connection.execute(
                "SELECT current_technical_original.locate(NULL,NULL,NULL,NULL,NULL)"
            )


@pytest.mark.parametrize("grant", ["column", "public_table", "extra_role", "public_definer"])
def test_effective_extra_access_rejects(saved, grant):
    w = saved
    owner = w["database"]["owner"]
    commands = {
        "column": (
            "GRANT SELECT(object_key) ON design.blobs TO tender_current_original_verify",
            "REVOKE SELECT(object_key) ON design.blobs FROM tender_current_original_verify",
        ),
        "public_table": (
            "GRANT SELECT ON design.outcomes TO PUBLIC",
            "REVOKE SELECT ON design.outcomes FROM PUBLIC",
        ),
        "extra_role": (f"GRANT tender_api TO {LOGIN}", f"REVOKE tender_api FROM {LOGIN}"),
        "public_definer": (
            "CREATE FUNCTION current_technical_original.synthetic_extra() RETURNS int LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'",
            "DROP FUNCTION current_technical_original.synthetic_extra()",
        ),
    }
    command, undo = commands[grant]
    try:
        owner.execute(command)
        with pytest.raises(current.CurrentOriginalError):
            observe(w)
    finally:
        owner.execute(undo)
    assert observe(w).metadata["native_current_original_locator_checked"]


@pytest.mark.parametrize("rpc", [current.RPC, scope_port.RPC])
def test_substituted_native_body_is_rejected_before_execution(saved, rpc):
    w = saved
    owner = w["database"]["owner"]
    definition = owner.execute(
        "SELECT pg_get_functiondef(%s::regprocedure) AS ddl", (rpc,)
    ).fetchone()["ddl"]
    marker = "$current_original$" if rpc == current.RPC else "$current_scope$"
    source = current.SQL_FILE if rpc == current.RPC else scope_port.SQL_FILE
    original = source.read_text(encoding="utf-8").split(marker)[1]
    try:
        assert original in definition
        owner.execute(
            definition.replace(
                original, " BEGIN RAISE EXCEPTION 'synthetic body must not execute'; END; "
            )
        )
        with pytest.raises(current.CurrentOriginalError, match="NATIVE_METHOD_MISMATCH"):
            observe(w)
    finally:
        owner.execute(definition)
    assert observe(w).metadata["native_current_original_locator_checked"]


def test_transaction_must_be_owned_and_direct_rpc_requires_readonly(saved):
    verifier = saved["database"]["original_verifier"]
    with verifier.transaction():
        with pytest.raises(current.CurrentOriginalError, match="IDLE_CONNECTION_REQUIRED"):
            observe(saved)
    with pytest.raises(psycopg.errors.ActiveSqlTransaction):
        verifier.execute(
            "SELECT current_technical_original.locate(%s,%s,%s,%s,%s)",
            (
                saved["technical_scope"][0],
                saved["saved_scope"]["manifest"]["id"],
                saved["saved_scope"]["digest"],
                str(uuid4()),
                "a" * 64,
            ),
        )


@pytest.mark.parametrize(
    "rpc,group", [(current.RPC, current.GROUP), (scope_port.RPC, scope_port.GROUP)]
)
def test_inherited_rpc_owner_is_rejected(saved, rpc, group):
    w = saved
    owner = w["database"]["owner"]
    original_owner = owner.execute(
        "SELECT pg_get_userbyid(proowner) AS name FROM pg_proc WHERE oid=%s::regprocedure", (rpc,)
    ).fetchone()["name"]
    try:
        owner.execute(
            sql.SQL("ALTER FUNCTION {} OWNER TO {}").format(sql.SQL(rpc), sql.Identifier(group))
        )
        with pytest.raises(current.CurrentOriginalError, match="NATIVE_METHOD_MISMATCH"):
            observe(w)
    finally:
        owner.execute(
            sql.SQL("ALTER FUNCTION {} OWNER TO {}").format(
                sql.SQL(rpc), sql.Identifier(original_owner)
            )
        )
        owner.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                sql.SQL(rpc), sql.Identifier(group)
            )
        )
    assert observe(w).metadata["native_current_original_locator_checked"]


@pytest.mark.parametrize("phase", ["submitted", "closed", "terminated"])
def test_current_scope_phase_guard_is_inherited(saved, phase):
    w = saved
    w["database"]["owner"].execute(
        "UPDATE design.bid_profiles SET phase=%s WHERE bid_id=%s", (phase, w["technical_scope"][0])
    )
    with pytest.raises(current.CurrentOriginalError, match="NOT_CURRENT_PREBID"):
        observe(w)


def test_actual_graph_depth_limit_rejects_without_truncation(saved):
    w = saved
    owner = w["database"]["owner"]
    root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0]["source_id"]
    previous = root
    for _ in range(65):
        new = str(uuid4())
        owner.execute(
            "INSERT INTO retrieval.source_nodes(id,document_version_id,digest,kind,policy_class,known_at) SELECT %s,document_version_id,digest,kind,policy_class,known_at FROM retrieval.source_nodes WHERE id=%s",
            (new, root),
        )
        owner.execute(
            "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)", (previous, new)
        )
        previous = new
    with pytest.raises(current.CurrentOriginalError, match="SOURCE_LIMIT"):
        observe(w)


def test_sql_failure_exception_does_not_retain_private_native_context(saved, monkeypatch):
    w = saved
    connection = w["database"]["original_verifier"]
    from contextlib import contextmanager

    @contextmanager
    def failing_transaction(*args, **kwargs):
        raise psycopg.OperationalError("synthetic-private-locator-and-signature")
        yield

    monkeypatch.setattr(type(connection), "transaction", failing_transaction)
    with pytest.raises(current.CurrentOriginalError, match="NATIVE_UNAVAILABLE") as caught:
        observe(w)
    assert caught.value.__context__ is None
    assert "synthetic-private" not in str(caught.value)
