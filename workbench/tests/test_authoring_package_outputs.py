"""Synthetic immutable observations: admission mechanisms, not renderer acceptance."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.authoring import package_adoptions
from packages.authoring import package_outputs as outputs
from packages.authoring.package_adoption_contracts import validate
from packages.domain.runtime import DomainError, sha
from packages.word_intake.inspection import DOCX, PDF


def uid(n):
    return str(UUID(int=n))


@pytest.fixture
def packet_db(monkeypatch):
    profile = {"identity": {"protocol": "explicit-test-converter"}}
    profile["profile_digest"] = sha(profile["identity"])
    manifest = {
        "snapshot_digest": "a" * 64,
        "writer_kind": "strict_text/1",
        "template_version_id": uid(9),
        "formats": ["docx", "pdf"],
        "follow_up": "none",
        "artifact_kind": "bid_body",
        "renderer_identity": profile,
    }
    row = {
        "id": uid(1),
        "bid_id": uid(2),
        "input_id": uid(3),
        "operation_id": uid(4),
        "draft_snapshot_id": uid(5),
        "draft_id": uid(6),
        "draft_revision": 7,
        "snapshot_digest": manifest["snapshot_digest"],
        "manifest": manifest,
        "input_digest": sha({"id": uid(3), "manifest": manifest}),
        "operation_kind": "build",
        "operation_state": "succeeded",
        "operation_handler": "export/1",
    }
    documents = [
        {
            "format": fmt,
            "state": "succeeded",
            "document_version_id": uid(n),
            "bid_id": uid(2),
            "artifact_kind": "bid_body",
            "obtained_at": "2026-01-01T00:00:00+00:00",
            "file_id": uid(n + 100),
            "role": "body",
            "file_revision": 1,
            "digest": sha(fmt.encode()),
            "byte_size": len(fmt),
            "media_type": media,
            "object_key": f"private/{fmt}",
        }
        for fmt, media, n in [("docx", DOCX, 10), ("pdf", PDF, 11)]
    ]
    receipt = {
        "build_id": uid(1),
        "snapshot_id": uid(5),
        "outputs": {item["format"]: item["document_version_id"] for item in documents},
        "conversion_chain": {
            "source_docx_digest": documents[0]["digest"],
            "pdf_digest": documents[1]["digest"],
            "profile_digest": profile["profile_digest"],
        },
    }
    snapshot = {
        "snapshot_id": uid(5),
        "snapshot_digest": manifest["snapshot_digest"],
        "sections": [],
    }
    state = {
        "row": row,
        "documents": documents,
        "receipts": [{"payload": receipt}],
        "relations": [
            {
                "source_document_version_id": uid(10),
                "kind": "controlled_render",
                "verification": "verified",
            }
        ],
        "snapshot": snapshot,
    }

    class Connection:
        def execute(self, query, params=()):
            if "FROM design.builds" in query:
                rows = [state["row"]] if params == (uid(1), uid(2)) else []
            elif "FROM design.build_outputs" in query:
                assert params == (uid(2), uid(1))
                rows = state["documents"]
            elif "FROM design.audit_entries" in query:
                assert params == (uid(2), uid(1))
                rows = state["receipts"]
            elif "FROM design.document_relations" in query:
                assert params == (uid(2), uid(11))
                rows = state["relations"]
            else:
                raise AssertionError(query)
            return SimpleNamespace(
                fetchone=lambda: deepcopy(rows[0]) if rows else None,
                fetchall=lambda: deepcopy(rows),
            )

    monkeypatch.setattr(outputs, "snapshot_content", lambda *_args: deepcopy(state["snapshot"]))
    monkeypatch.setattr(outputs, "source_authority_manifest", lambda *_args: [])
    return Connection(), state


def test_exact_docx_and_controlled_pdf_have_independent_qualification(packet_db):
    c, _ = packet_db
    word = outputs.capture(c, uid(2), uid(1), uid(10))
    pdf = outputs.capture(c, uid(2), uid(1), uid(11))
    assert len(word["documents"]) == 1 and len(pdf["documents"]) == 2
    assert word["proof"]["word_pdf_relation"] == "not_applicable"
    assert pdf["proof"]["word_pdf_relation"] == "verified"
    validate("AuthoringOutputQualification", word["proof"])
    validate("AuthoringOutputQualification", pdf["proof"])
    assert "private/" not in repr(pdf["proof"])


@pytest.mark.parametrize(
    "change",
    [
        "failed_operation",
        "wrong_operation_kind",
        "wrong_handler",
        "wrong_input_digest",
        "wrong_snapshot",
        "wrong_bid",
        "wrong_artifact",
        "wrong_role",
        "wrong_media",
        "missing_file",
        "empty_bytes",
        "failed_word",
        "missing_receipt",
        "duplicate_receipt",
        "wrong_receipt_snapshot",
        "wrong_receipt_output",
        "wrong_word_digest",
        "wrong_pdf_digest",
        "wrong_profile",
        "partial_relation",
        "foreign_word",
        "missing_relation",
        "extra_relation",
    ],
)
def test_identity_gaps_and_partial_word_conversion_fail_closed(packet_db, change):
    c, state = packet_db
    row, docs = state["row"], state["documents"]
    receipt = state["receipts"][0]["payload"]
    mutations = {
        "failed_operation": lambda: row.update(operation_state="failed"),
        "wrong_operation_kind": lambda: row.update(operation_kind="review"),
        "wrong_handler": lambda: row.update(operation_handler="document/1"),
        "wrong_input_digest": lambda: row.update(input_digest="f" * 64),
        "wrong_snapshot": lambda: state["snapshot"].update(snapshot_digest="f" * 64),
        "wrong_bid": lambda: docs[1].update(bid_id=uid(99)),
        "wrong_artifact": lambda: docs[1].update(artifact_kind="review_report"),
        "wrong_role": lambda: docs[1].update(role="tender"),
        "wrong_media": lambda: docs[1].update(media_type=DOCX),
        "missing_file": lambda: docs[1].update(file_id=None),
        "empty_bytes": lambda: docs[1].update(byte_size=0),
        "failed_word": lambda: docs[0].update(state="failed"),
        "missing_receipt": lambda: state.update(receipts=[]),
        "duplicate_receipt": lambda: state["receipts"].append(deepcopy(state["receipts"][0])),
        "wrong_receipt_snapshot": lambda: receipt.update(snapshot_id=uid(99)),
        "wrong_receipt_output": lambda: receipt["outputs"].update(pdf=uid(99)),
        "wrong_word_digest": lambda: receipt["conversion_chain"].update(
            source_docx_digest="f" * 64
        ),
        "wrong_pdf_digest": lambda: receipt["conversion_chain"].update(pdf_digest="f" * 64),
        "wrong_profile": lambda: receipt["conversion_chain"].update(profile_digest="f" * 64),
        "partial_relation": lambda: state["relations"][0].update(verification="unverified"),
        "foreign_word": lambda: state["relations"][0].update(source_document_version_id=uid(99)),
        "missing_relation": lambda: state.update(relations=[]),
        "extra_relation": lambda: state["relations"].append(deepcopy(state["relations"][0])),
    }
    mutations[change]()
    with pytest.raises(DomainError) as error:
        outputs.capture(c, uid(2), uid(1), uid(11))
    assert error.value.code in {"AUTHORING_OUTPUT_NOT_QUALIFIED", "BUILD_INPUT_CORRUPT"}


def test_partial_pdf_does_not_revoke_successful_word(packet_db):
    c, state = packet_db
    state["relations"][0]["verification"] = "unverified"
    value = outputs.capture(c, uid(2), uid(1), uid(10))
    assert value["proof"]["format"] == "docx"
    with pytest.raises(DomainError):
        outputs.capture(c, uid(2), uid(1), uid(11))


def test_cross_bid_build_cannot_be_adopted(packet_db):
    c, _ = packet_db
    with pytest.raises(DomainError):
        outputs.capture(c, uid(99), uid(1), uid(10))


def test_each_selected_original_is_verified_without_weakening_digest_port(packet_db, monkeypatch):
    c, _ = packet_db
    packet = outputs.capture(c, uid(2), uid(1), uid(11))
    seen = []
    monkeypatch.setattr(outputs.original_verification, "verify", lambda row: seen.append(row))
    outputs.verify_bytes(packet)
    assert [row["format"] for row in seen] == ["docx", "pdf"]
    assert all(row["digest"] and row["object_key"] and row["byte_size"] for row in seen)


def test_final_observation_change_stops_before_any_qualification_audit(packet_db, monkeypatch):
    c, state = packet_db
    packet = outputs.capture(c, uid(2), uid(1), uid(10))
    state["documents"][0]["object_key"] = "another-object"
    monkeypatch.setattr(outputs.sources, "lock_graph", lambda *_args: None)
    monkeypatch.setattr(
        outputs, "audit", lambda *_args: pytest.fail("must not write qualification")
    )
    with pytest.raises(DomainError):
        outputs.qualify(c, packet, uid(20), uid(21))


def test_snapshot_choice_is_explicit_and_never_uses_new_draft_head(packet_db):
    c, _ = packet_db
    packet = outputs.capture(c, uid(2), uid(1), uid(10))
    package_adoptions._snapshot(packet, {"snapshot_id": uid(5), "snapshot_digest": "a" * 64})
    with pytest.raises(DomainError) as error:
        package_adoptions._snapshot(packet, {"snapshot_id": uid(99), "snapshot_digest": "a" * 64})
    assert error.value.code == "AUTHORING_ADOPTION_SNAPSHOT_MISMATCH"
