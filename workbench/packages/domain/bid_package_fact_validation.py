"""Read current provenance in one readonly snapshot, independently of authoring/latest."""

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import package_fact_validation as policy
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_frozen_originals import capture
from packages.domain.runtime import DomainError, connection


def inspect(scope, frozen_id, input_id, prepared_digest):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = inputs.load_packet(c, scope, frozen_id, input_id)
        if packet.digest != prepared_digest:
            raise DomainError("PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不符", 409)
        manifest = packet.view()["manifest"]
        binding = manifest["identity"]["binding"]
        current = capture(c, scope, frozen_id, binding["frozen_digest"])
        context = current["context"]
        facts = context["manifest"]["facts"]
        checks = [
            policy.assess(item, read_proof(c, scope[0], item, context["manifest"]["as_of"]))
            for item in facts["items"]
        ]
        return {
            "kind": "fact_validation_observation",
            "bid_id": scope[0],
            "package_id": scope[1],
            "revision_id": scope[2],
            "inventory_id": scope[3],
            "frozen_input_id": frozen_id,
            "execution_input_id": input_id,
            "execution_input_digest": prepared_digest,
            "prepared_context_digest": binding["context_digest"],
            "observed_context_digest": context["semantic_digest"],
            "observed_facts_digest": context["manifest"]["facts_digest"],
            "matches_prepared_context": binding["context_digest"] == context["semantic_digest"],
            "checked_at": context["manifest"]["as_of"],
            "fact_count": len(checks),
            "provenance_verified_count": sum(x["provenance_status"] == "verified" for x in checks),
            "fact_checks": checks,
            "blockers": [] if checks else ["FACT_SET_EMPTY"],
            "facts_qualified": False,
            "original_verification": "not_performed",
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        }
