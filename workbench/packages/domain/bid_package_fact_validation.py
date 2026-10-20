"""Read current provenance in one readonly snapshot, independently of authoring/latest."""

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import package_fact_validation as policy
from packages.domain.bid_package_frozen_originals import capture
from packages.domain.fact_sets import carryover
from packages.domain.review_data import effective_at, source_closure
from packages.domain.runtime import DomainError, clean, connection, sha
from packages.rag.indexing import parse_source_id


def _proof(c, bid, item, at):
    fact, decision = item["fact"], item["decision"]
    inherited = (
        carryover(c, fact["id"]) if decision and str(decision["object_id"]) != fact["id"] else None
    )
    binding = bool(
        decision
        and decision["object_kind"] == "fact"
        and str(decision["bid_id"]) == bid
        and (
            str(decision["object_id"]) == fact["id"]
            or inherited
            and inherited["from_decision_id"] == str(decision["id"])
            and inherited["from_fact_id"] == str(decision["object_id"])
        )
    )
    rows = c.execute(
        """SELECT e.id,e.parse_id,p.document_version_id,p.coverage,page.quality,page.gaps
        FROM design.evidence_blocks e JOIN design.parse_runs p ON p.bid_id=e.bid_id AND p.id=e.parse_id
        JOIN design.pages page ON page.bid_id=e.bid_id AND page.parse_id=e.parse_id AND page.physical_page=e.physical_page
        WHERE e.bid_id=%s AND e.id=ANY(%s::uuid[]) ORDER BY e.id""",
        (bid, fact["evidence_ids"]),
    ).fetchall()
    refs = []
    for row in rows:
        source = parse_source_id(row["parse_id"])
        head = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()
        if head:
            refs.append(
                clean(
                    {
                        "source_id": source,
                        "source_revision": head["revision"],
                        "evidence_id": row["id"],
                        "document_version_id": row["document_version_id"],
                    }
                )
            )
    closure, effective = None, False
    if refs:
        try:
            closure = source_closure(
                c, [{"id": source} for source in sorted({ref["source_id"] for ref in refs})]
            )
            effective_at(closure, at)
            effective = True
        except (DomainError, TypeError, ValueError):
            effective = False
    if inherited:
        try:
            import json

            binding = binding and inherited["equivalence_digest"] == sha(
                json.loads(item["decision_basis_jsonb_text"])
            )
        except (TypeError, ValueError):
            binding = False
    return {
        "decision_binding": binding,
        "references": refs,
        "closure": closure,
        "sources_effective": effective,
        "evidence_usable": bool(rows)
        and len(rows) == len(set(fact["evidence_ids"]))
        and all(
            row["coverage"] == "complete" and row["quality"] == "usable" and row["gaps"] == []
            for row in rows
        ),
    }


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
            policy.assess(item, _proof(c, scope[0], item, context["manifest"]["as_of"]))
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
