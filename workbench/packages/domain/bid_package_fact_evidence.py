"""Caller-owned fact evidence transaction; exact frozen references, no model/object IO."""

import json
from dataclasses import dataclass, field
from uuid import UUID

from packages.domain import bid_package_review_input_repository as inputs
from packages.domain import package_fact_evidence as selection_policy
from packages.domain.bid_package_review_documents import read_member
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_data import effective_at, source_closure
from packages.domain.review_identity import canonical, digest, utc
from packages.domain.runtime import DomainError, require_read_committed
from packages.domain.word_materials import configured as word_configured
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable
from packages.rag.indexing import original_source_id
from packages.word_intake.inspection import DOCX, PDF
from packages.word_intake.repository import controlled_qualified


@dataclass(frozen=True, slots=True)
class FrozenFactEvidenceBasis:
    digest: str
    _text: str = field(repr=False)
    _basis_text: str = field(repr=False)
    _closure_text: str = field(repr=False)

    def view(self):
        return json.loads(self._text)

    def basis(self):
        return json.loads(self._basis_text)

    def closure(self):
        return json.loads(self._closure_text)


def _require_ancestry(condition):
    if not condition:
        raise DomainError(
            "PACKAGE_FACT_EVIDENCE_INVALID", "事实依据祖先范围与明确冻结原件不一致", 409
        )


def _controlled_word(c, bid, document, file_digest):
    relation = c.execute(
        """SELECT source_document_version_id::text,kind,verification
        FROM design.document_relations WHERE bid_id=%s AND document_version_id=%s""",
        (bid, document),
    ).fetchone()
    if relation is None or relation["kind"] != "controlled_render":
        return None
    _require_ancestry(relation["verification"] == "verified" and word_configured(c))
    # Read the receipt for this exact PDF, never today's latest Word render. All
    # records are already immutable; the caller retains the bid and source locks.
    rows = c.execute(
        """SELECT r.outcome,r.profile_digest,r.frozen_profile,
        wb.digest AS word_digest,wb.media_type AS word_media_type,
        pb.digest AS pdf_digest,pb.media_type AS pdf_media_type
        FROM design.word_intake_receipts w
        JOIN design.word_render_runs r ON r.bid_id=w.bid_id
            AND r.source_document_version_id=w.document_version_id
        JOIN design.operations o ON o.bid_id=r.bid_id AND o.id=r.operation_id
        JOIN design.document_versions v ON v.bid_id=w.bid_id AND v.id=w.document_version_id
        JOIN design.blobs wb ON wb.id=v.blob_id
        JOIN design.document_versions p ON p.bid_id=r.bid_id AND p.id=r.pdf_document_version_id
        JOIN design.blobs pb ON pb.id=p.blob_id
        WHERE w.bid_id=%s AND w.document_version_id=%s
            AND r.pdf_document_version_id=%s AND o.state='succeeded'""",
        (bid, relation["source_document_version_id"], document),
    ).fetchall()
    _require_ancestry(len(rows) == 1)
    receipt = rows[0]
    outcome, profile = receipt["outcome"], receipt["frozen_profile"]
    _require_ancestry(
        isinstance(outcome, dict)
        and isinstance(outcome.get("chain"), dict)
        and controlled_qualified(outcome)
        and isinstance(profile, dict)
        and isinstance(profile.get("identity"), dict)
    )
    chain = outcome["chain"]
    _require_ancestry(
        receipt["word_media_type"] == DOCX
        and receipt["pdf_media_type"] == PDF
        and receipt["word_digest"] == chain["source_docx_digest"]
        and receipt["pdf_digest"] == chain["pdf_digest"] == file_digest
        and receipt["profile_digest"] == chain["profile_digest"] == profile.get("profile_digest")
        and all(
            chain[key] == profile["identity"].get(key)
            for key in ("renderer_digest", "fontset_digest", "options_digest")
        )
    )
    return relation["source_document_version_id"], receipt["word_digest"]


def _check_ancestry(c, bid, row, ancestors):
    document, file_digest = row["document_version_id"], row["file_digest"]
    original = str(original_source_id(UUID(document)))
    expected = {row["source_id"]: (document, file_digest), original: (document, file_digest)}
    word = _controlled_word(c, bid, document, file_digest)
    if word is not None:
        word_original = str(original_source_id(UUID(word[0])))
        expected[word_original] = word
    _require_ancestry(
        len(ancestors) == len(expected)
        and {item["id"] for item in ancestors} == set(expected)
        and all(
            item["kind"] == "document"
            and (item["document_version_id"], item["digest"]) == expected[item["id"]]
            for item in ancestors
        )
    )
    if word is not None:
        edges = c.execute(
            """SELECT child_id::text,parent_id::text FROM retrieval.lineage_edges
            WHERE child_id IN (%s,%s,%s) ORDER BY child_id,parent_id""",
            (row["source_id"], original, word_original),
        ).fetchall()
        _require_ancestry(
            len(edges) == 2
            and {(edge["child_id"], edge["parent_id"]) for edge in edges}
            == {(row["source_id"], original), (original, word_original)}
        )


def read_basis(c, scope, frozen_id, frozen_digest, evidence_ids):
    if c.autocommit:
        raise ValueError("Package fact evidence requires a transaction")
    require_read_committed(c)
    lock_bid(c, scope[0])
    assert_work_writable(c, scope[0])
    lock_graph(c)
    packet = inputs.load_input(c, scope, frozen_id)
    selection = selection_policy.select(packet, frozen_digest, evidence_ids)
    selected = selection.view()["selected"]
    parses = {row["parse_run_id"] for row in selected}
    root = packet.evidence()
    # Re-read the exact frozen parse identity, including its complete evidence digest.
    for role in ("target", "authority"):
        for member in root["selection"][role]["manifest"]["members"]:
            if member["parse"]["parse_run_id"] in parses:
                read_member(c, scope[0], member)
    sources = sorted({row["source_id"] for row in selected})
    closure = source_closure(c, [{"id": value} for value in sources], lock=True)
    at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
    effective_at(closure, at)
    refs = []
    checked = set()
    for row in selected:
        if row["source_id"] not in checked:
            ancestors = [item for item in closure if item["source_id"] == row["source_id"]]
            _check_ancestry(c, scope[0], row, ancestors)
            checked.add(row["source_id"])
        heads = [
            item
            for item in closure
            if item["source_id"] == row["source_id"] and item["id"] == row["source_id"]
        ]
        if (
            len(heads) != 1
            or heads[0]["document_version_id"] != row["document_version_id"]
            or heads[0]["digest"] != row["file_digest"]
        ):
            raise DomainError("PACKAGE_FACT_EVIDENCE_INVALID", "事实依据来源与冻结原件不一致", 409)
        refs.append(
            {key: row[key] for key in ("source_id", "evidence_id", "document_version_id")}
            | {"source_revision": heads[0]["revision"]}
        )
    basis = {"references": refs, "source_closure_digest": digest(closure)}
    manifest = {
        "version": "package-fact-evidence-basis/1",
        "selection": selection.view(),
        "selection_digest": selection.digest,
        "checked_at": at,
        "basis_digest": digest(basis),
        "original_bytes_verified": False,
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    selection_policy.validate("BasisObservation", manifest)
    return FrozenFactEvidenceBasis(
        digest(manifest),
        canonical(manifest).decode("utf-8"),
        canonical(basis).decode("utf-8"),
        canonical(closure).decode("utf-8"),
    )
