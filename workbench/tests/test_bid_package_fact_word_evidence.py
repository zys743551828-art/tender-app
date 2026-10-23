"""Fact evidence accepts only the exact, qualified Word-to-PDF ancestry.

The source observation ports are explicit fixtures. Relation/receipt/edge reads
execute actual SQL over isolated SQLite tables (only PostgreSQL casts and bind
syntax are adapted); these checks do not claim renderer or PostgreSQL acceptance.
"""

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError
from packages.rag.indexing import original_source_id
from packages.word_intake.inspection import DOCX, PDF
from packages.word_intake.repository import REQUIRED_ISOLATION
from tests.test_bid_package_fact_evidence import ports, read  # noqa: F401
from tests.test_package_fact_evidence import packet  # noqa: F401
from tests.test_package_fact_scope import uid


@pytest.fixture
def word_ports(ports):  # noqa: F811
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        ATTACH DATABASE ':memory:' AS design;
        ATTACH DATABASE ':memory:' AS retrieval;
        CREATE TABLE design.document_relations(
            bid_id TEXT, document_version_id TEXT, source_document_version_id TEXT,
            kind TEXT, verification TEXT);
        CREATE TABLE design.word_intake_receipts(document_version_id TEXT, bid_id TEXT);
        CREATE TABLE design.document_versions(id TEXT, bid_id TEXT, blob_id TEXT);
        CREATE TABLE design.blobs(id TEXT, digest TEXT, media_type TEXT);
        CREATE TABLE design.operations(id TEXT, bid_id TEXT, state TEXT);
        CREATE TABLE design.word_render_runs(
            operation_id TEXT, bid_id TEXT, source_document_version_id TEXT,
            pdf_document_version_id TEXT, profile_digest TEXT, frozen_profile TEXT,
            outcome TEXT);
        CREATE TABLE retrieval.lineage_edges(child_id TEXT, parent_id TEXT);
    """)
    bid, pdf, word, operation = ports[1][0], uid(10), uid(900), uid(901)
    chain = dict.fromkeys(("renderer_digest", "fontset_digest", "options_digest"), "e" * 64) | {
        "source_docx_digest": "d" * 64,
        "pdf_digest": "a" * 64,
        "profile_digest": "c" * 64,
    }
    outcome = {
        "state": "succeeded",
        "coverage": "complete",
        "conversion_attempted": True,
        "gaps": [],
        "isolation": dict.fromkeys(REQUIRED_ISOLATION, True),
        "chain": chain,
    }
    profile = {
        "profile_digest": chain["profile_digest"],
        "identity": {
            key: chain[key] for key in ("renderer_digest", "fontset_digest", "options_digest")
        },
    }
    db.execute(
        "INSERT INTO design.document_relations VALUES(?,?,?,'controlled_render','verified')",
        (bid, pdf, word),
    )
    db.execute("INSERT INTO design.word_intake_receipts VALUES(?,?)", (word, bid))
    db.executemany(
        "INSERT INTO design.document_versions VALUES(?,?,?)",
        [(pdf, bid, uid(902)), (word, bid, uid(903))],
    )
    db.executemany(
        "INSERT INTO design.blobs VALUES(?,?,?)",
        [(uid(902), "a" * 64, PDF), (uid(903), "d" * 64, DOCX)],
    )
    db.execute("INSERT INTO design.operations VALUES(?,?,'succeeded')", (operation, bid))
    db.execute(
        "INSERT INTO design.word_render_runs VALUES(?,?,?,?,?,?,?)",
        (
            operation,
            bid,
            word,
            pdf,
            chain["profile_digest"],
            json.dumps(profile),
            json.dumps(outcome),
        ),
    )
    closure = ports[3]
    parse_source = closure[0]["id"]
    pdf_source, word_source = str(original_source_id(pdf)), str(original_source_id(word))
    closure.append(
        closure[0]
        | {"id": word_source, "document_version_id": word, "digest": chain["source_docx_digest"]}
    )
    db.executemany(
        "INSERT INTO retrieval.lineage_edges VALUES(?,?)",
        [(parse_source, pdf_source), (pdf_source, word_source)],
    )
    state = {"configured": True, "queries": []}

    def execute(query, params=()):
        state["queries"].append(query)
        if "clock_timestamp()" in query:
            rows = [{"at": datetime(2026, 10, 20, tzinfo=timezone.utc)}]
        elif "to_regclass(" in query:
            rows = [{"ready": state["configured"]}]
        else:
            assert query.lstrip().startswith("SELECT"), "fact evidence must not write sources"
            rows = [
                dict(row)
                for row in db.execute(query.replace("::text", "").replace("%s", "?"), params)
            ]
            for row in rows:
                for key in ("outcome", "frozen_profile"):
                    if key in row and row[key] is not None:
                        row[key] = json.loads(row[key])
        return SimpleNamespace(fetchone=lambda: rows[0] if rows else None, fetchall=lambda: rows)

    ports[0].execute = execute
    yield ports, db, state, outcome, profile
    db.close()


def test_controlled_word_pdf_evidence_retains_complete_verified_ancestry(word_ports):
    case, _, _, _, _ = word_ports
    receipt = read(case)
    assert len(receipt.closure()) == 3
    assert receipt.basis()["source_closure_digest"] == digest(case[3])
    assert receipt.basis()["references"][0]["document_version_id"] == uid(10)
    assert case[4] == ["rc", "bid", "writable", "graph", uid(11)]
    assert all(
        receipt.view()[key] is False
        for key in (
            "original_bytes_verified",
            "facts_qualified",
            "review_ready",
            "launch_available",
            "publication_authorized",
        )
    )


def test_controlled_pdf_cannot_omit_its_word_ancestor(word_ports):
    case, _, _, _, _ = word_ports
    case[3].pop()
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.code == "PACKAGE_FACT_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        "withdrawn",
        "future",
        "expired",
        "official",
        "digest",
        "version",
        "kind",
        "extra_parent",
        "duplicate",
    ],
)
def test_invalid_word_ancestor_is_never_fact_evidence(word_ports, change):
    case, _, _, _, _ = word_ports
    word = case[3][-1]
    if change == "withdrawn":
        word["status"] = "withdrawn"
    elif change == "future":
        word["known_at"] = "2026-10-21T00:00:00+00:00"
    elif change == "expired":
        word["valid_until"] = "2026-10-19T12:00:00+00:00"
    elif change == "official":
        word["policy_class"] = "official_label"
    elif change == "digest":
        word["digest"] = "0" * 64
    elif change == "version":
        word["document_version_id"] = uid(999)
    elif change == "kind":
        word["kind"] = "knowledge"
    elif change == "extra_parent":
        case[3].append(word | {"id": uid(999)})
    else:
        case[3].append(dict(word))
    with pytest.raises(DomainError):
        read(case)


@pytest.mark.parametrize(
    "change",
    [
        "missing_relation",
        "declared_only",
        "unverified_relation",
        "relation_bid",
        "receipt_bid",
        "render_bid",
        "render_pdf",
        "render_source",
        "duplicate_render",
        "operation_failed",
        "word_digest",
        "word_media",
        "pdf_digest",
        "pdf_media",
        "partial",
        "isolation",
        "outcome_source",
        "outcome_pdf",
        "outcome_profile",
        "frozen_renderer",
        "missing_schema",
        "wrong_edges",
        "extra_edge",
    ],
)
def test_unproven_or_crossed_controlled_relation_is_rejected(word_ports, change):
    case, db, state, outcome, profile = word_ports
    if change == "missing_relation":
        db.execute("DELETE FROM design.document_relations")
    elif change == "declared_only":
        db.execute("UPDATE design.document_relations SET kind='user_declared_same_draft'")
    elif change == "unverified_relation":
        db.execute("UPDATE design.document_relations SET verification='unverified'")
    elif change in {"relation_bid", "receipt_bid", "render_bid"}:
        table = {
            "relation_bid": "document_relations",
            "receipt_bid": "word_intake_receipts",
            "render_bid": "word_render_runs",
        }[change]
        db.execute(f"UPDATE design.{table} SET bid_id=?", (uid(999),))
    elif change in {"render_pdf", "render_source"}:
        column = (
            "pdf_document_version_id" if change == "render_pdf" else "source_document_version_id"
        )
        db.execute(f"UPDATE design.word_render_runs SET {column}=?", (uid(999),))
    elif change == "duplicate_render":
        db.execute("INSERT INTO design.word_render_runs SELECT * FROM design.word_render_runs")
    elif change == "operation_failed":
        db.execute("UPDATE design.operations SET state='failed'")
    elif change in {"word_digest", "pdf_digest", "word_media", "pdf_media"}:
        blob = uid(903) if change.startswith("word_") else uid(902)
        column = "digest" if change.endswith("digest") else "media_type"
        value = "0" * 64 if column == "digest" else "application/octet-stream"
        db.execute(f"UPDATE design.blobs SET {column}=? WHERE id=?", (value, blob))
    elif change == "partial":
        outcome["coverage"] = "partial"
    elif change == "isolation":
        outcome["isolation"]["network_none"] = False
    elif change in {"outcome_source", "outcome_pdf", "outcome_profile"}:
        field = {
            "outcome_source": "source_docx_digest",
            "outcome_pdf": "pdf_digest",
            "outcome_profile": "profile_digest",
        }[change]
        outcome["chain"][field] = "0" * 64
    elif change == "frozen_renderer":
        profile["identity"]["renderer_digest"] = "0" * 64
    elif change == "missing_schema":
        state["configured"] = False
    elif change == "wrong_edges":
        db.execute(
            "DELETE FROM retrieval.lineage_edges WHERE child_id=?",
            (str(original_source_id(uid(10))),),
        )
        db.execute(
            "INSERT INTO retrieval.lineage_edges VALUES(?,?)", (case[3][0]["id"], case[3][-1]["id"])
        )
    elif change == "extra_edge":
        db.execute(
            "INSERT INTO retrieval.lineage_edges VALUES(?,?)", (case[3][0]["id"], case[3][-1]["id"])
        )
    db.execute(
        "UPDATE design.word_render_runs SET outcome=?,frozen_profile=?",
        (json.dumps(outcome), json.dumps(profile)),
    )
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.code == "PACKAGE_FACT_EVIDENCE_INVALID"
