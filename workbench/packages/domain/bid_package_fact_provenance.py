"""Exact package fact provenance reads; caller supplies connection and observation time."""

from typing import Any

from psycopg.types.json import Jsonb

from packages.domain.fact_decision_lineage import decision_known, resolve
from packages.domain.package_fact_validation import decision_basis
from packages.domain.review_data import effective_at, source_closure
from packages.domain.review_identity import utc
from packages.domain.runtime import DomainError, clean, sha
from packages.rag.indexing import parse_source_id


def _carryover(c, bid, fact):
    # Equivalent names and an audit from another bid/set cannot bind a decision.
    rows = c.execute(
        """SELECT a.id::text,a.bid_id::text,a.actor_id::text,a.command_id::text,a.event_type,a.created_at,
        a.payload,a.payload::text AS payload_jsonb_text FROM design.audit_entries a
        JOIN design.fact_items f ON f.bid_id=a.bid_id AND f.id=%s AND f.fact_set_id=%s
        WHERE a.bid_id=%s AND a.event_type='facts.set_replaced'
        AND a.payload->>'fact_set_id'=f.fact_set_id::text
        AND a.payload->'carryovers' @> %s::jsonb""",
        (fact["id"], fact["fact_set_id"], bid, Jsonb([{"new_fact_id": fact["id"]}])),
    ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    payload = row["payload"]
    items = payload.get("carryovers")
    if not isinstance(items, list) or any(not isinstance(value, dict) for value in items):
        return None
    matches = [value for value in items if value.get("new_fact_id") == fact["id"]]
    if len(matches) != 1:
        return None
    stamp = utc(row["created_at"].isoformat())
    recorded = {
        "id": row["id"],
        "bid_id": row["bid_id"],
        "actor_id": row["actor_id"],
        "command_id": row["command_id"],
        "event_type": row["event_type"],
        "payload_jsonb_text": row["payload_jsonb_text"],
        "created_at": stamp,
    }
    return {
        **matches[0],
        "bid_id": row["bid_id"],
        "fact_set_id": fact["fact_set_id"],
        "previous_set_recorded": "previous_set_id" in payload,
        "previous_set_id": payload.get("previous_set_id"),
        "audit_id": row["id"],
        "audit_digest": sha(recorded),
        "audit_recorded_at": stamp,
        "actor_id": row["actor_id"],
        "command_id": row["command_id"],
    }


def _fact(c, bid, fact_id):
    row = c.execute(
        """SELECT id::text,bid_id::text,fact_set_id::text,subject,scope,name,value::text AS value_jsonb_text,unit,evidence_ids FROM design.fact_items WHERE bid_id=%s AND id=%s""",
        (bid, fact_id),
    ).fetchone()
    return clean(row) if row else None


def read_proof(c, bid, item, at):
    fact, decision = item["fact"], item["decision"]
    binding = bool(
        decision
        and decision["object_kind"] == "fact"
        and str(decision["bid_id"]) == bid
        and decision_known(decision, at)
    )
    lineage: list[dict[str, Any]] | None = []
    if binding and str(decision["object_id"]) != fact["id"]:
        try:
            lineage = resolve(
                bid,
                fact,
                decision,
                decision_basis(item),
                at,
                lambda node: _carryover(c, bid, node),
                lambda parent_id: _fact(c, bid, parent_id),
            )
        except (ValueError, TypeError, KeyError, OverflowError):
            lineage = None
        binding = lineage is not None
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
    return {
        "version": "package-fact-provenance/2",
        "decision_binding": binding,
        "decision_lineage": lineage or [],
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
