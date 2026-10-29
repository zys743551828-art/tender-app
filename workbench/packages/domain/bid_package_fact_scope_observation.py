"""Observe an exact fact's declaration head and fresh applicability gaps, without writes."""

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import bid_package_fact_scope_repository as repository
from packages.domain import package_fact_scope as policy
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_frozen_originals import assert_same, capture
from packages.domain.package_fact_validation import assess
from packages.domain.review_identity import utc
from packages.domain.runtime import DomainError, connection


def inspect(scope, frozen_id, input_id, fact_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = inputs.load_packet(c, scope, frozen_id, input_id)
        prepared = packet.snapshot()
        cm = prepared["context"]["manifest"]
        if not any(item["fact"]["id"] == fact_id for item in cm["facts"]["items"]):
            raise DomainError("PACKAGE_FACT_NOT_FOUND", "事实不在明确准备输入中", 404)
        head = repository.head(c, scope[0], input_id, fact_id)
        choices = []
        identity = cm["identity"]
        if identity["binding_status"] == "confirmed":
            labels = {
                "engineering_project": identity["engineering_title"],
                "lot": identity["lot"] or "本标段",
                "round": f"第{identity['round_no']}轮",
                "bidder": identity["bidder_name"],
            }
            choices = [
                {"kind": kind, "id": identity[field], "label": labels[kind]}
                for kind, field in policy.SUBJECTS.items()
            ]
        binding = packet.view()["manifest"]["identity"]["binding"]
        at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        matches, provenance, status, gap = False, "unproven", "unproven", None
        observed = None
        try:
            current = capture(c, scope, frozen_id, binding["frozen_digest"])
            context = current["context"]["manifest"]
            observed = current["context"]["semantic_digest"]
            try:
                assert_same({k: v for k, v in prepared.items() if k != "version"}, current)
                matches = True
            except DomainError:
                pass
            items = [x for x in context["facts"]["items"] if x["fact"]["id"] == fact_id]
            if len(items) == 1:
                proof = read_proof(c, scope[0], items[0], context["as_of"])
                provenance = assess(items[0], proof)["provenance_status"]
                if head and head["manifest"]["action"] == "bind" and matches:
                    try:
                        status = policy.current_status(head, packet, current, fact_id, proof)
                    except ValueError:
                        pass
        except DomainError as error:
            if error.status != 409:
                raise
            gap = error.code
        if head and head["manifest"]["action"] == "withdraw":
            status = "withdrawn"
        return {
            "kind": "fact_scope_observation",
            **dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            ),
            "frozen_input_id": frozen_id,
            "execution_input_id": input_id,
            "execution_input_digest": packet.digest,
            "fact_id": fact_id,
            "prepared_context_digest": binding["context_digest"],
            "observed_context_digest": observed,
            "matches_prepared_input": matches,
            "provenance_status": provenance,
            "subject_choices": choices,
            "head": head,
            "binding_status": status,
            "observation_gap": gap,
            "checked_at": utc(at.isoformat()),
            "facts_qualified": False,
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        }
