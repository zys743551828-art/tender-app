"""Current qualification observation over a frozen selection; never a dispatch permit."""

from typing import Any

from packages.domain.bid_package_review_policy import evaluate
from packages.domain.package_review_identity import summary


def assess(
    frozen: dict[str, Any],
    root: dict[str, Any],
    observations: dict[str, Any],
    context: dict[str, Any],
    *,
    evidence_matches: bool,
):
    result = evaluate(root["selection"], observations, evidence_matches=evidence_matches)
    blockers = list(result["blockers"])
    previous = frozen["manifest"]["execution_context"]
    current = summary(context)
    for field, code in (
        ("method_digest", "PACKAGE_REVIEW_METHOD_CHANGED"),
        ("policy_digest", "PACKAGE_REVIEW_POLICY_CHANGED"),
        ("facts_digest", "PACKAGE_REVIEW_FACTS_CHANGED"),
        ("sources_digest", "PACKAGE_REVIEW_SOURCE_CHANGED"),
    ):
        if current[field] != previous[field] and code not in blockers:
            blockers.append(code)
    if context["manifest"]["facts"]["qualification"] != "validated":
        blockers.append("PACKAGE_REVIEW_FACTS_UNPROVEN")
    return {
        "kind": "eligibility_observation",
        "frozen_input_id": frozen["manifest"]["id"],
        "frozen_digest": frozen["digest"],
        "input_digest": frozen["manifest"]["input_digest"],
        "checked_at": current["as_of"],
        "current_context": current,
        "parse_evidence_status": "matched" if evidence_matches else "mismatch",
        "original_verification": "not_performed",
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
        "blockers": blockers,
    }
