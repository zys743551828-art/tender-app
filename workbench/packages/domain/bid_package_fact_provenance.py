"""Exact package fact provenance reads; caller supplies connection and observation time."""

from psycopg.types.json import Jsonb

from packages.domain.review_data import effective_at, source_closure
from packages.domain.runtime import DomainError, clean, sha
from packages.rag.indexing import parse_source_id


def _carryover(c, bid, fact):
    # Equivalent names and an audit from another bid/set cannot bind a decision.
    rows = c.execute(
        """SELECT a.payload->'carryovers' AS items FROM design.audit_entries a
        JOIN design.fact_items f ON f.bid_id=a.bid_id AND f.id=%s AND f.fact_set_id=%s
        WHERE a.bid_id=%s AND a.event_type='facts.set_replaced'
        AND a.payload->>'fact_set_id'=f.fact_set_id::text
        AND a.payload->'carryovers' @> %s::jsonb""",
        (fact["id"], fact["fact_set_id"], bid, Jsonb([{"new_fact_id": fact["id"]}])),
    ).fetchall()
    if len(rows) != 1:
        return None
    matches = [value for value in rows[0]["items"] if value.get("new_fact_id") == fact["id"]]
    return matches[0] if len(matches) == 1 else None


def read_proof(c, bid, item, at):
    fact, decision = item["fact"], item["decision"]
    inherited = (
        _carryover(c, bid, fact) if decision and str(decision["object_id"]) != fact["id"] else None
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
