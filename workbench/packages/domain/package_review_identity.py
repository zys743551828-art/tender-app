"""Pure versioned package execution candidate identity; no persistence or scheduling."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from packages.domain.review_identity import digest, utc


def candidate(
    selected: dict[str, Any],
    facts: dict[str, Any],
    sources: list[dict[str, Any]],
    method: dict[str, Any],
    policy: dict[str, Any],
    as_of: str,
):
    at = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("package_context_timezone_required")
    if (
        method["purpose"] != policy["purpose"]
        or policy["purpose"] != "prebid_compliance"
        or method["executor_available"] is not False
        or policy["executor_available"] is not False
        or method["formal_scoring_eligible"] is not False
        or policy["formal_scoring_eligible"] is not False
    ):
        raise ValueError("package_context_method_policy_mismatch")
    manifest = {
        "version": "package-review-context/1",
        "kind": "candidate",
        "input_digest": digest(selected),
        "bid_id": selected["bid_id"],
        "identity": selected["target"]["identity"],
        "purpose": policy["purpose"],
        "method": method,
        "method_digest": digest(method),
        "policy": policy,
        "policy_digest": digest(policy),
        "facts": facts,
        "facts_digest": digest(facts),
        "sources": sources,
        "sources_digest": digest(sources),
        "as_of": utc(as_of),
    }
    # A captured candidate owns its data; later caller mutations cannot rewrite it.
    manifest = deepcopy(manifest)
    return {
        "manifest": manifest,
        "semantic_digest": digest(
            {key: value for key, value in manifest.items() if key != "as_of"}
        ),
        "snapshot_digest": digest(manifest),
    }


def summary(context: dict[str, Any]):
    manifest = context["manifest"]
    facts = manifest["facts"]
    return {
        "version": manifest["version"],
        "kind": "candidate",
        "input_digest": manifest["input_digest"],
        "semantic_digest": context["semantic_digest"],
        "snapshot_digest": context["snapshot_digest"],
        "as_of": manifest["as_of"],
        "purpose": manifest["purpose"],
        "method_digest": manifest["method_digest"],
        "policy_digest": manifest["policy_digest"],
        "facts_digest": manifest["facts_digest"],
        "sources_digest": manifest["sources_digest"],
        "fact_set_id": facts["head"]["fact_set_id"],
        "fact_count": len(facts["items"]),
        "confirmed_fact_count": sum(
            item["decision"] is not None and item["decision"]["decision"] == "confirmed"
            for item in facts["items"]
        ),
        "facts_binding": "unproven" if facts["items"] else "empty",
        "executor_available": False,
        "formal_scoring_eligible": False,
    }
