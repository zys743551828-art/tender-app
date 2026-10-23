"""Native source snapshot via a separate LOGIN in the grouped disposable database."""

import json
import os
import secrets
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_bid_package_requirements_api import ADMIN_DSN
from test_bid_package_requirements_api import database as base_database

from packages.domain.bid_package_repository import read_parse_identity
from packages.domain.review_identity import digest
from packages.model_governance import package_current_sources as sources
from packages.model_governance.technical_png import digest_bytes

ENABLED = os.environ.get("FUSION_CURRENT_SOURCE_PG") == "1"
pytestmark = pytest.mark.skipif(
    not ENABLED, reason="explicit grouped independent source PG required"
)
LOGIN = "fusion_current_source_verify"


def uid():
    return str(uuid4())


@pytest.fixture(scope="module")
def database():
    source = base_database.__wrapped__()
    value = next(source)
    owner = value["owner"]
    password = secrets.token_urlsafe(36)
    try:
        from deploy.schema_plan import ROOT

        assert not owner.execute(
            "SELECT 1 AS present FROM pg_roles WHERE rolname=ANY(%s)", ([LOGIN, sources.GROUP],)
        ).fetchone()
        owner.execute(
            (ROOT / "deploy/sql/package-current-source-grants.sql").read_text(encoding="utf-8")
        )
        owner.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(LOGIN), sql.Literal(password))
        )
        owner.execute(
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(sources.GROUP), sql.Identifier(LOGIN))
        )
        dsn = make_conninfo(ADMIN_DSN, dbname=owner.info.dbname, user=LOGIN, password=password)
        with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as verifier:
            yield {"owner": owner, "verifier": verifier, "api_dsn": value["api_dsn"]}
    finally:
        try:
            next(source)
        except StopIteration:
            pass
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(LOGIN)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(sources.GROUP)))


@pytest.fixture
def native(database, request):
    c = database["owner"]
    case = getattr(request.node, "callspec", None)
    mutation = case.params.get("mutation") if case is not None else None
    member, bid, blob, document, parse, block = (uid() for _ in range(6))
    raw = b"synthetic original metadata only:" + document.encode()
    text = "Synthetic complete native text"
    original = sources.source_id("original", document)
    parsed = sources.source_id("parse", parse)
    c.execute(
        "INSERT INTO design.members(id,display_name) VALUES(%s,'synthetic source verifier')",
        (member,),
    )
    c.execute(
        "INSERT INTO design.bids(id,title,settings,created_by) VALUES(%s,'synthetic current source','{}',%s)",
        (bid, member),
    )
    c.execute(
        "INSERT INTO design.blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
        (blob, digest_bytes(raw), "synthetic-source/" + document, len(raw)),
    )
    sha = digest_bytes(raw)
    c.execute(
        "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic.pdf',now(),'source_original',%s)",
        (document, bid, blob, member),
    )
    c.execute(
        "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,%s,'[]')",
        (
            parse,
            bid,
            document,
            "1" * 64,
            "2" * 64,
            "partial" if mutation == "partial" else "complete",
        ),
    )
    c.execute(
        "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,100,150,0,'usable','[]')",
        (bid, parse),
    )
    c.execute(
        "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,1,'text',%s,%s)",
        (block, bid, parse, text, digest_bytes(text.encode())),
    )
    for node in (original, parsed):
        c.execute(
            "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,%s,%s,CASE WHEN %s THEN now()+interval '1 day' ELSE now()-interval '1 day' END,%s)",
            (
                node,
                document,
                "label" if mutation == "label" and node == original else "document",
                "official_label"
                if mutation == "label" and node == original
                else "derived_mixed"
                if mutation == "mixed" and node == parsed
                else "prebid_content",
                mutation == "future" and node == original,
                "a" * 64 if mutation == "root_digest" and node == original else sha,
            ),
        )
        c.execute(
            "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now()-interval '1 day')",
            (node,),
        )
    if mutation != "missing_edge":
        c.execute(
            "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
            (parsed, original),
        )
    parse_digest = (
        "f" * 64
        if mutation == "partial"
        else read_parse_identity(c, bid, document, parse, lock=False).evidence_digest
    )
    expected = {
        "document_version_id": document,
        "source_digest": sha,
        "source_byte_size": len(raw),
        "parse_run_id": parse,
        "parse_digest": parse_digest,
        "page_count": 1,
    }
    return database | {
        "bid": bid,
        "document": document,
        "parse": parse,
        "block": block,
        "original": original,
        "parsed": parsed,
        "expected": [expected],
    }


def observe(w, **kwargs):
    return sources.observe(
        w["verifier"],
        bid_id=w["bid"],
        expected_documents=w["expected"],
        expected_method_digest=sources.method_digest(),
        **kwargs,
    )


def test_native_login_observation_and_denied_history_and_object_locator(native):
    w = native
    value = observe(w).metadata
    assert value["native_parse_and_current_sources_reverified"]
    assert not any(
        value[key]
        for key in (
            "original_bytes_reverified",
            "necessary_scope_verified",
            "input_authority_granted",
            "execution_authorized",
            "historical_existence_verified",
        )
    )
    assert value["documents"] == w["expected"] and value["counts"]["blocks"] == 1
    assert len(value["graph"]["nodes"]) == 2
    assert value["digest"] == digest({k: v for k, v in value.items() if k != "digest"})
    assert "synthetic-source/" not in json.dumps(value) and "Synthetic complete" not in json.dumps(
        value
    )
    for query in (
        "SELECT object_key FROM design.blobs",
        "SELECT * FROM design.submission_records",
        "SELECT * FROM design.outcomes",
        "SELECT * FROM retrieval.chunks",
        "SELECT * FROM design.model_calls",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            w["verifier"].execute(query)
    assert w["verifier"].execute("SELECT current_user AS name").fetchone()["name"] == LOGIN
    evidence = os.environ.get("FUSION_CURRENT_SOURCE_EVIDENCE")
    if evidence:
        (Path(evidence) / "current-source-native-observation.json").write_text(
            json.dumps(
                {
                    "actual_login": LOGIN,
                    "observation": value,
                    "denied_history_rag_model_and_locator_queries": 5,
                    "original_bytes_checked": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "withdrawn",
        "future",
        "expired",
        "label",
        "mixed",
        "cross_bid",
        "root_digest",
        "missing_edge",
        "wrong_parse",
        "partial",
    ],
)
def test_reject_changed_or_ineligible_native_sources(native, mutation):
    w = native
    c = w["owner"]
    if mutation == "withdrawn":
        c.execute(
            "UPDATE retrieval.source_heads SET status='withdrawn' WHERE source_id=%s",
            (w["original"],),
        )
    elif mutation == "expired":
        c.execute(
            "UPDATE retrieval.source_heads SET valid_from=now()-interval '2 days',valid_until=now()-interval '1 day' WHERE source_id=%s",
            (w["original"],),
        )
    elif mutation == "cross_bid":
        w["bid"] = uid()
    elif mutation == "wrong_parse":
        w["expected"][0]["parse_digest"] = "f" * 64
    with pytest.raises(sources.CurrentSourceError):
        observe(w)


def test_graph_checks_transitive_ancestors(native):
    w = native
    c = w["owner"]
    ancestor = uid()
    c.execute(
        "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document','prebid_content',now()-interval '1 day',%s)",
        (ancestor, w["document"], w["expected"][0]["source_digest"]),
    )
    c.execute(
        "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'published',now()-interval '1 day')",
        (ancestor,),
    )
    c.execute(
        "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
        (w["original"], ancestor),
    )
    assert len(observe(w).metadata["graph"]["nodes"]) == 3
    c.execute(
        "UPDATE retrieval.source_heads SET status='withdrawn' WHERE source_id=%s", (ancestor,)
    )
    with pytest.raises(sources.CurrentSourceError, match="GRAPH_SOURCE_UNAVAILABLE"):
        observe(w)


def test_reject_owner_api_and_borrowed_transaction(native):
    w = native
    with pytest.raises(sources.CurrentSourceError, match="INDEPENDENT_LOGIN_REQUIRED"):
        sources.observe(
            w["owner"],
            bid_id=w["bid"],
            expected_documents=w["expected"],
            expected_method_digest=sources.method_digest(),
        )
    with psycopg.connect(w["api_dsn"], autocommit=True) as api:
        with pytest.raises(sources.CurrentSourceError, match="INDEPENDENT_MEMBERSHIP_REQUIRED"):
            sources.observe(
                api,
                bid_id=w["bid"],
                expected_documents=w["expected"],
                expected_method_digest=sources.method_digest(),
            )
    with w["verifier"].transaction():
        with pytest.raises(sources.CurrentSourceError, match="IDLE_CONNECTION_REQUIRED"):
            observe(w)


@pytest.mark.parametrize(
    "grant",
    [
        "label_read",
        "object_write",
        "locator_read",
        "definer",
        "extra_membership",
        "schema_create",
        "database_create",
    ],
)
def test_excess_effective_grants_fail_closed(native, grant):
    w = native
    c = w["owner"]
    if grant == "label_read":
        command = "GRANT SELECT ON design.outcomes TO tender_current_source_verify"
        undo = "REVOKE SELECT ON design.outcomes FROM tender_current_source_verify"
    elif grant == "object_write":
        command = "GRANT UPDATE(digest) ON design.blobs TO tender_current_source_verify"
        undo = "REVOKE UPDATE(digest) ON design.blobs FROM tender_current_source_verify"
    elif grant == "locator_read":
        command = "GRANT SELECT(object_key) ON design.blobs TO tender_current_source_verify"
        undo = "REVOKE SELECT(object_key) ON design.blobs FROM tender_current_source_verify"
    elif grant == "extra_membership":
        command = f"GRANT tender_api TO {LOGIN}"
        undo = f"REVOKE tender_api FROM {LOGIN}"
    elif grant == "schema_create":
        command = "GRANT CREATE ON SCHEMA design TO tender_current_source_verify"
        undo = "REVOKE CREATE ON SCHEMA design FROM tender_current_source_verify"
    elif grant == "database_create":
        command = f"GRANT CREATE ON DATABASE {c.info.dbname} TO tender_current_source_verify"
        undo = f"REVOKE CREATE ON DATABASE {c.info.dbname} FROM tender_current_source_verify"
    else:
        c.execute(
            "CREATE FUNCTION design.synthetic_source_definer() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
        )
        command = "GRANT EXECUTE ON FUNCTION design.synthetic_source_definer() TO PUBLIC"
        undo = "DROP FUNCTION design.synthetic_source_definer()"
    try:
        c.execute(command)
        with pytest.raises(sources.CurrentSourceError):
            observe(w)
    finally:
        c.execute(undo)
    assert observe(w).metadata["native_parse_and_current_sources_reverified"]


def test_existing_parse_and_original_namespaces_are_exact(native):
    from packages.rag.indexing import original_source_id, parse_source_id

    assert native["original"] == str(original_source_id(UUID(native["document"])))
    assert native["parsed"] == str(parse_source_id(UUID(native["parse"])))


def test_parse_limit_rejects_before_unbounded_identity_fetch(native, monkeypatch):
    w = native
    monkeypatch.setattr(sources, "MAX_TEXT_BYTES", 1)
    with pytest.raises(sources.CurrentSourceError, match="PARSE_LIMIT"):
        observe(w)


def test_repeated_observation_preserves_old_receipt_after_revocation(native):
    w = native
    old = observe(w).metadata
    copy = deepcopy(old)
    w["owner"].execute(
        "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
        (w["parsed"],),
    )
    with pytest.raises(sources.CurrentSourceError):
        observe(w)
    assert old == copy


def test_concurrent_revocation_is_snapshot_only_and_next_observation_rejects(native, monkeypatch):
    w = native
    original = sources._documents

    def revoke_after_read(*args):
        cursor = args[0]
        assert (
            cursor.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        )
        assert (
            cursor.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
            == "repeatable read"
        )
        value = original(*args)
        w["owner"].execute(
            "UPDATE retrieval.source_heads SET status='withdrawn' WHERE source_id=%s",
            (w["original"],),
        )
        return value

    with monkeypatch.context() as patch:
        patch.setattr(sources, "_documents", revoke_after_read)
        snapshot = observe(w).metadata
    assert not snapshot["execution_authorized"]
    with pytest.raises(sources.CurrentSourceError, match="GRAPH_SOURCE_UNAVAILABLE"):
        observe(w)


@pytest.mark.parametrize(
    "limit,value,error",
    [
        ("MAX_NODES", 1, "GRAPH_LIMIT"),
        ("MAX_EDGES", 0, "GRAPH_LIMIT"),
        ("MAX_DEPTH", 0, "GRAPH_DEPTH_LIMIT"),
    ],
)
def test_graph_limits_reject_instead_of_partial_receipt(native, monkeypatch, limit, value, error):
    monkeypatch.setattr(sources, limit, value)
    with pytest.raises(sources.CurrentSourceError, match=error):
        observe(native)


def test_corrupt_graph_cycle_is_rejected_even_if_writer_guard_was_bypassed(native):
    w = native
    c = w["owner"]
    c.execute("ALTER TABLE retrieval.lineage_edges DISABLE TRIGGER acyclic")
    try:
        c.execute(
            "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
            (w["original"], w["parsed"]),
        )
    finally:
        c.execute("ALTER TABLE retrieval.lineage_edges ENABLE TRIGGER acyclic")
    with pytest.raises(sources.CurrentSourceError, match="GRAPH_CYCLE"):
        observe(w)


def test_wrong_owned_method_and_change_during_observation_reject(native, monkeypatch):
    w = native
    with pytest.raises(sources.CurrentSourceError, match="METHOD_MISMATCH"):
        sources.observe(
            w["verifier"],
            bid_id=w["bid"],
            expected_documents=w["expected"],
            expected_method_digest="0" * 64,
        )
    original = sources._documents

    def change_method(*args):
        result = original(*args)
        monkeypatch.setattr(sources, "MAX_DEPTH", 63)
        return result

    monkeypatch.setattr(sources, "_documents", change_method)
    with pytest.raises(sources.CurrentSourceError, match="METHOD_CHANGED"):
        observe(w)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "extra_label",
        "boolean_size",
        "boolean_pages",
        "noncanonical_id",
        "bad_digest",
        "total_pages",
        "document_count",
    ],
)
def test_projection_rejects_before_database_access(native, case):
    rows = deepcopy(native["expected"])
    if case == "duplicate":
        rows *= 2
    elif case == "extra_label":
        rows[0]["official_score"] = 90
    elif case == "boolean_size":
        rows[0]["source_byte_size"] = True
    elif case == "boolean_pages":
        rows[0]["page_count"] = True
    elif case == "noncanonical_id":
        rows[0]["document_version_id"] = "{" + rows[0]["document_version_id"] + "}"
    elif case == "bad_digest":
        rows[0]["source_digest"] = "G" * 64
    elif case == "document_count":
        rows *= 33
    else:
        rows = [dict(rows[0], document_version_id=uid(), page_count=128) for _ in range(3)]
    with pytest.raises(sources.CurrentSourceError):
        sources.observe(
            object(),
            bid_id=native["bid"],
            expected_documents=rows,
            expected_method_digest=sources.method_digest(),
        )
