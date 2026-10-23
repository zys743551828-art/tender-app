"""Nonowner PG + ordinary Worker + real PDFium bytes; memory object store only.

Run serially with FUSION_REQUIREMENTS_ADMIN_DSN. These are synthetic technical
fixtures, not external Word conversion, OCR accuracy or business acceptance.
"""
# ruff: noqa: F401,F811

import copy
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from psycopg.errors import ActiveSqlTransaction, CheckViolation
from test_authoring_package_adoptions_pg import database, env
from test_bid_package_api import attach
from test_document_parses import original

from apps.worker import document_parse_handlers as handler
from apps.worker import engine
from packages.contracts.document_parses_api import validate
from packages.domain import document_parse_policy as policy
from packages.domain import document_parses as service
from packages.domain.runtime import DomainError, connection, sha
from packages.rag.indexing import original_source_id, parse_source_id

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated PG17 standalone parse fixture required",
)


@pytest.fixture
def parsed_file(env, monkeypatch):
    monkeypatch.delenv("PARSING_RUNTIME_TOKEN", raising=False)
    doc, blob = uuid4(), uuid4()
    # Keep each module-scoped database fixture's immutable blob unique without
    # changing its PDF pages or parser semantics. Trailing PDF comments are legal.
    raw = original() + f"\n% synthetic document {doc}\n".encode()
    key = f"explicit-pdf/{blob}"
    owner = env["database"]["owner"]
    with owner.transaction():
        owner.execute("SET LOCAL search_path TO design,public")
        owner.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
            (blob, sha(raw), key, len(raw)),
        )
        owner.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic standalone.pdf',now(),'bid_body',%s)",
            (doc, env["bid"], blob, env["actor"]),
        )
        attach(
            owner,
            str(env["bid"]),
            str(env["actor"]),
            SimpleNamespace(document_version_id=str(doc), file_digest=sha(raw)),
        )
    env["objects"][key] = raw
    return env | {"document": doc, "object_key": key}


def request(env, *, key=None, actor=None):
    context = service.read_context(env["bid"], env["document"])
    validate("DocumentParseContext", context)
    body = {
        "context_digest": context["context_digest"],
        "reason": "Read only this explicitly selected PDF",
    }
    response, replayed = service.start(
        env["bid"], env["document"], actor or env["actor"], key or uuid4().hex, body
    )
    assert not replayed
    validate("DocumentParseStarted", response["body"])
    return response["body"], body


def task(ack):
    with connection() as c:
        return c.execute(
            "SELECT payload FROM outbox WHERE operation_id=%s AND topic='tender.task.document.v1'",
            (ack["request"]["operation"]["id"],),
        ).fetchone()["payload"]


def assert_unchanged_heads(env):
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


def test_nonowner_standalone_parse_exact_pages_and_reused_request_without_head_changes(parsed_file):
    env = parsed_file
    ack, _ = request(env)
    other = uuid4()
    with connection() as c:
        c.execute(
            "INSERT INTO members(id,display_name) VALUES(%s,'other synthetic member')", (other,)
        )
    reused, _ = request(env, actor=other)
    assert reused["reused"] and reused["actor_id"] == str(other)
    assert reused["request"]["id"] == ack["request"]["id"]
    assert reused["request"]["actor_id"] == str(env["actor"])
    message = task(ack)
    lease = engine.acquire(message)
    outcome = engine.run_compute(message, lease)
    assert outcome["parsed"]["coverage"] == "partial"
    assert engine.finish(message, lease, outcome)
    value = service.read(env["bid"], env["document"], ack["request"]["id"])
    validate("DocumentParseView", value)
    assert value["operation"]["state"] == "succeeded"
    assert value["result"]["page_count"] == 2 and value["result"]["coverage"] == "partial"
    assert value["result"]["word_coverage_claimed"] is False
    parse = UUID(value["result"]["parse_run_id"])
    with connection(True) as c:
        pages = c.execute(
            "SELECT physical_page,rotation FROM pages WHERE parse_id=%s ORDER BY physical_page",
            (parse,),
        ).fetchall()
        assert pages == [{"physical_page": 1, "rotation": 0}, {"physical_page": 2, "rotation": 90}]
        assert c.execute(
            "SELECT 1 FROM retrieval.lineage_edges WHERE child_id=%s AND parent_id=%s",
            (parse_source_id(parse), original_source_id(env["document"])),
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM operations WHERE bid_id=%s AND kind IN('parse-materials','review')",
            (env["bid"],),
        ).fetchone()
    validate("DocumentParsePage", service.directory(env["bid"], env["document"]))
    assert_unchanged_heads(env)


def test_old_ack_replays_after_closed_without_parser_probe(parsed_file, monkeypatch):
    env = parsed_file
    key = uuid4().hex
    ack, body = request(env, key=key)
    with connection() as c:
        c.execute("UPDATE bid_profiles SET phase='closed' WHERE bid_id=%s", (env["bid"],))
    monkeypatch.setattr(
        policy, "method", lambda: pytest.fail("historical ACK must precede any parser identity IO")
    )
    response, replayed = service.start(env["bid"], env["document"], env["actor"], key, body)
    assert replayed and response["body"] == ack
    with pytest.raises(DomainError) as mismatch:
        service.start(
            env["bid"],
            env["document"],
            env["actor"],
            key,
            body | {"reason": "changed original request"},
        )
    assert mismatch.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("change", ["cancel", "close"])
def test_cancellation_or_closed_project_blocks_late_publication(parsed_file, change):
    env = parsed_file
    ack, _ = request(env)
    message = task(ack)
    lease = engine.acquire(message)
    outcome = engine.run_compute(message, lease)
    with connection() as c:
        if change == "cancel":
            c.execute(
                "UPDATE operations SET state='cancel_requested',cancel_requested_at=now() WHERE id=%s",
                (message["operation_id"],),
            )
        else:
            c.execute("UPDATE bid_profiles SET phase='closed' WHERE bid_id=%s", (env["bid"],))
    finished = engine.finish(message, lease, outcome)
    assert finished is (change == "close")
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM document_parse_results WHERE request_id=%s", (ack["request"]["id"],)
        ).fetchone()
        assert not c.execute(
            "SELECT 1 FROM parse_runs WHERE bid_id=%s AND document_version_id=%s",
            (env["bid"], env["document"]),
        ).fetchone()
    assert_unchanged_heads(env)


def test_withdrawal_during_original_io_prevents_postcheck_and_publication(parsed_file, monkeypatch):
    env = parsed_file
    ack, _ = request(env)
    message = task(ack)
    lease = engine.acquire(message)
    original_reader = handler._bytes

    def withdraw(value):
        data = original_reader(value)
        c = env["database"]["owner"]
        root = original_source_id(env["document"])
        with c.transaction():
            c.execute(
                "INSERT INTO retrieval.source_nodes(id,document_version_id,kind,policy_class,known_at,digest) VALUES(%s,%s,'document','prebid_content',now(),%s)",
                (root, env["document"], value["digest"]),
            )
            c.execute(
                "INSERT INTO retrieval.source_heads(source_id,revision,status,valid_from) VALUES(%s,1,'withdrawn',now())",
                (root,),
            )
        return data

    monkeypatch.setattr(handler, "_bytes", withdraw)
    with pytest.raises(DomainError) as failure:
        engine.run_compute(message, lease)
    assert failure.value.code == "KNOWLEDGE_SOURCE_INVALID"
    assert engine.finish(message, lease, None, failure.value)
    value = service.read(env["bid"], env["document"], ack["request"]["id"])
    assert value["operation"]["state"] == "failed" and value["result"] is None


def test_body_artifact_label_cannot_replace_upload_or_generated_admission(parsed_file):
    env = parsed_file
    with env["database"]["owner"].transaction():
        env["database"]["owner"].execute(
            "UPDATE design.uploads SET state='quarantined' WHERE bid_id=%s AND verified_version_id=%s",
            (env["bid"], env["document"]),
        )
    with pytest.raises(DomainError) as failure:
        service.read_context(env["bid"], env["document"])
    assert failure.value.code == "DOCUMENT_PARSE_ORIGINAL_UNPROVEN"
    assert_unchanged_heads(env)


def test_wrong_bytes_do_not_publish_parse_under_valid_metadata(parsed_file):
    env = parsed_file
    ack, _ = request(env)
    message = task(ack)
    lease = engine.acquire(message)
    env["objects"][env["object_key"]] += b"tampered"
    with pytest.raises(DomainError) as failure:
        engine.run_compute(message, lease)
    assert failure.value.code == "ORIGINAL_BYTES_CORRUPTED"
    assert engine.finish(message, lease, None, failure.value)
    value = service.read(env["bid"], env["document"], ack["request"]["id"])
    assert value["operation"]["state"] == "failed" and value["result"] is None


def test_successful_parse_closes_page_and_evidence_appends_before_any_package_freeze(parsed_file):
    env = parsed_file
    ack, _ = request(env)
    message = task(ack)
    lease = engine.acquire(message)
    outcome = engine.run_compute(message, lease)
    assert engine.finish(message, lease, outcome)
    value = service.read(env["bid"], env["document"], ack["request"]["id"])
    parse = value["result"]["parse_run_id"]
    with pytest.raises(CheckViolation, match="document_parse_output_closed"), connection(True) as c:
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,3,420,595,0,'usable','[]')",
            (env["bid"], parse),
        )
    with pytest.raises(CheckViolation, match="document_parse_output_closed"), connection(True) as c:
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,999,'text','late extra content',%s)",
            (uuid4(), env["bid"], parse, sha(b"late extra content")),
        )
    assert (
        service.read(env["bid"], env["document"], ack["request"]["id"])["result"] == value["result"]
    )


def test_old_repeatable_read_snapshot_cannot_append_after_another_transaction_publishes(
    parsed_file,
):
    env = parsed_file
    ack, _ = request(env)
    message = task(ack)
    lease = engine.acquire(message)
    outcome = engine.run_compute(message, lease)
    with (
        pytest.raises(ActiveSqlTransaction, match="document_parse_content_requires_read_committed"),
        connection(True) as stale,
    ):
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert not stale.execute(
            "SELECT 1 FROM design.document_parse_results WHERE request_id=%s",
            (ack["request"]["id"],),
        ).fetchone()
        assert engine.finish(message, lease, outcome)
        value = service.read(env["bid"], env["document"], ack["request"]["id"])
        stale.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,999,'text','late RR content',%s)",
            (uuid4(), env["bid"], value["result"]["parse_run_id"], sha(b"late RR content")),
        )
    with connection(True) as c:
        assert not c.execute(
            "SELECT 1 FROM design.evidence_blocks WHERE parse_id=%s AND ordinal=999",
            (value["result"]["parse_run_id"],),
        ).fetchone()


@pytest.mark.parametrize(
    ("section", "field", "value", "constraint"),
    [
        ("method", "mode", None, "document_parse_input_binding"),
        ("qualification", "kind", None, "document_parse_input_binding"),
        ("source", "state", None, "document_parse_input_binding"),
        ("source", "authority_digest", "f" * 64, "document_parse_source_binding"),
        (
            "qualification",
            "identity_digest",
            "f" * 64,
            "document_parse_upload_qualification",
        ),
    ],
)
def test_sql_independently_rejects_forged_input_observations(
    parsed_file, monkeypatch, section, field, value, constraint
):
    env = parsed_file
    captured = service.capture

    def corrupted_capture(*args):
        context, document = captured(*args)
        context = copy.deepcopy(context)
        context[section][field] = value
        return context, document

    # Deliberately bypass the correct application capture in this synthetic test.
    # The nonowner transaction must still be unable to commit its forged packet.
    monkeypatch.setattr(service, "capture", corrupted_capture)
    observed = service.read_context(env["bid"], env["document"])
    with pytest.raises(CheckViolation, match=constraint):
        service.start(
            env["bid"],
            env["document"],
            env["actor"],
            uuid4().hex,
            {"context_digest": observed["context_digest"], "reason": "Synthetic SQL boundary"},
        )
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM document_parse_requests WHERE bid_id=%s", (env["bid"],)
        ).fetchone()
