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
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable
from packages.rag.indexing import original_source_id


@dataclass(frozen=True, slots=True)
class FrozenFactEvidenceBasis:
    digest: str
    _text: str = field(repr=False)
    _basis_text: str = field(repr=False)

    def view(self):
        return json.loads(self._text)

    def basis(self):
        return json.loads(self._basis_text)


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
    for row in selected:
        ancestors = [item for item in closure if item["source_id"] == row["source_id"]]
        expected = {row["source_id"], str(original_source_id(UUID(row["document_version_id"])))}
        if (
            len(ancestors) != 2
            or {item["id"] for item in ancestors} != expected
            or any(
                item["kind"] != "document"
                or item["document_version_id"] != row["document_version_id"]
                or item["digest"] != row["file_digest"]
                for item in ancestors
            )
        ):
            raise DomainError(
                "PACKAGE_FACT_EVIDENCE_INVALID", "事实依据祖先范围与明确冻结原件不一致", 409
            )
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
        digest(manifest), canonical(manifest).decode("utf-8"), canonical(basis).decode("utf-8")
    )
