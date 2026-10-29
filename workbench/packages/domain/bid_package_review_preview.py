"""Read-only preflight coordination; no input freezing, storage IO or scheduling."""

from typing import Any

from packages.domain import bid_package_review_repository as repository
from packages.domain.bid_package_review_documents import evidence_matches
from packages.domain.bid_package_review_policy import evaluate
from packages.domain.review_identity import digest


def preview(c: Any, bid: str, package: str, revision: str, inventory_id: str, body: dict[str, Any]):
    # Caller owns one REPEATABLE READ / READ ONLY transaction for all observations.
    manifest = repository.selected(c, bid, package, revision, inventory_id, body)
    observations = repository.observations(c, manifest)
    result = evaluate(manifest, observations, evidence_matches=evidence_matches(c, manifest))
    return {
        "manifest": manifest,
        "digest": digest(manifest),
        "review_ready": False,
        "launch_available": False,
        **result,
    }
