"""Read-only fact authority capture for explicit packages, independent of current_body."""

from typing import Any

from packages.domain import package_review_method as method
from packages.domain.package_review_identity import candidate
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import clean


def _decision_basis(c: Any, bid: str, decision: dict | None, as_of: str | None):
    if decision is None:
        return None
    rows = c.execute(
        """SELECT actor_id::text,payload,created_at,(payload->'basis')::text AS basis_jsonb_text,
        created_at<=COALESCE(%s::timestamptz,clock_timestamp()) AS not_future
        FROM design.audit_entries WHERE bid_id=%s AND event_type='human.decision_recorded'
        AND payload->>'decision_id'=%s LIMIT 2""",
        (as_of, bid, str(decision["id"])),
    ).fetchall()
    if len(rows) != 1:
        return None
    row = rows[0]
    payload = row["payload"]
    if (
        not isinstance(payload, dict)
        or not row["not_future"]
        or row["created_at"] < decision["created_at"]
        or row["actor_id"] != str(decision["actor_id"])
        or str(decision["bid_id"]) != bid
        or decision["object_kind"] != "fact"
        or any(
            payload.get(key) != str(decision[key])
            for key in ("object_kind", "object_id", "decision")
        )
    ):
        return None
    return row["basis_jsonb_text"]


def read_facts(
    c: Any,
    bid: str,
    selected_parses: set,
    *,
    fact_ids: list[str] | None = None,
    as_of: str | None = None,
):
    head = c.execute(
        """SELECT h.fact_set_id,h.revision,s.digest AS fact_set_digest FROM design.fact_heads h
        LEFT JOIN design.fact_sets s ON s.bid_id=h.bid_id AND s.id=h.fact_set_id WHERE h.bid_id=%s""",
        (bid,),
    ).fetchone()
    if head is None:
        head = {"fact_set_id": None, "revision": 0, "fact_set_digest": None}
    rows = (
        c.execute(
            """SELECT f.id,f.bid_id,f.fact_set_id,f.subject,f.scope,f.name,
        f.value::text AS value_jsonb_text,f.unit,f.evidence_ids,s.digest AS fact_set_digest
        FROM design.fact_items f JOIN design.fact_sets s ON s.bid_id=f.bid_id AND s.id=f.fact_set_id
        WHERE f.bid_id=%s AND f.fact_set_id=%s AND (%s::uuid[] IS NULL OR f.id=ANY(%s::uuid[])) ORDER BY f.id""",
            (bid, head["fact_set_id"], fact_ids, fact_ids),
        ).fetchall()
        if head["fact_set_id"] is not None
        else []
    )
    items = []
    for fact in rows:
        decision = current_decision(c, bid, "fact", fact["id"])
        evidence = c.execute(
            """SELECT e.id::text,e.parse_id::text,p.document_version_id::text,e.physical_page,e.digest
            FROM design.evidence_blocks e JOIN design.parse_runs p ON p.bid_id=e.bid_id AND p.id=e.parse_id
            WHERE e.bid_id=%s AND e.id=ANY(%s::uuid[]) ORDER BY e.id""",
            (bid, list(fact["evidence_ids"])),
        ).fetchall()
        basis = _decision_basis(c, bid, decision, as_of)
        # This records provenance status, not an authoring/current-material qualification.
        in_scope = (
            bool(fact["evidence_ids"])
            and len(evidence) == len(set(fact["evidence_ids"]))
            and all(
                (row["document_version_id"], row["parse_id"]) in selected_parses for row in evidence
            )
        )
        items.append(
            {
                "fact": clean(fact),
                "decision": clean(decision),
                "decision_basis_jsonb_text": basis,
                "evidence": clean(evidence),
                "scope_binding": "selected_frozen_parse" if in_scope else "unproven",
            }
        )
    return {
        "version": "package-review-facts/1",
        "head": clean(head),
        "items": items,
        "value_encoding": "postgresql-jsonb-text",
        "qualification": "not_validated",
    }


def facts(c: Any, selected: dict[str, Any], *, as_of: str | None = None):
    selected_parses = {
        (member["document_version_id"], member["parse"]["parse_run_id"])
        for role in ("target", "authority")
        for member in selected[role]["manifest"]["members"]
        if member["parse"]["status"] == "frozen"
    }
    return read_facts(c, selected["bid_id"], selected_parses, as_of=as_of)


def capture(c: Any, selected: dict[str, Any], observations: dict[str, Any]):
    return candidate(
        selected,
        facts(c, selected, as_of=observations["at"].isoformat()),
        observations["sources"],
        method.profile(),
        method.POLICY,
        observations["at"].isoformat(),
    )
