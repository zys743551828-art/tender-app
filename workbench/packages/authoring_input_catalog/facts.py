"""Exact fact items and native evidence observations; no current-head substitution."""

import json

from packages.assistant.intent_identity import IDENTITY_FACTS
from packages.authoring_input_catalog import nodes, policy
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_service import historical, view
from packages.domain.package_fact_validation import assess
from packages.domain.package_review_context import read_decision_basis
from packages.domain.review_identity import digest
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import clean


def current_head(c, bid):
    row = c.execute(
        """SELECT h.fact_set_id::text,h.revision,s.digest AS fact_set_digest
        FROM design.fact_heads h LEFT JOIN design.fact_sets s ON s.bid_id=h.bid_id AND s.id=h.fact_set_id
        WHERE h.bid_id=%s""",
        (bid,),
    ).fetchone()
    if row is None or row["fact_set_id"] is None:
        return None
    policy.check(row["fact_set_digest"] is not None and row["revision"] >= 1)
    return clean(row)


def sets(c, bid):
    blockers = nodes.project_blockers(c, bid)
    head = current_head(c, bid)
    rows = c.execute(
        """SELECT s.id::text AS fact_set_id,s.digest AS fact_set_digest,
        (SELECT count(*) FROM design.fact_items f WHERE f.bid_id=s.bid_id AND f.fact_set_id=s.id) AS fact_count
        FROM design.fact_sets s WHERE s.bid_id=%s ORDER BY s.id LIMIT 1001""",
        (bid,),
    ).fetchall()
    return (
        {
            "protocol": "package-authoring-fact-set-page/1",
            "bid_id": bid,
            "current_head": head,
            "blocking_reasons": blockers
            + ([] if head else ["AUTHORING_PACKAGE_FACT_HEAD_MISSING"]),
        },
        [
            dict(row) | {"is_current": bool(head and row["fact_set_id"] == head["fact_set_id"])}
            for row in rows
        ],
    )


def packages(c, bid, target, authority):
    selected = {}
    for role, kind, ref in (("target", "bid", target), ("authority", "authority", authority)):
        package = historical(c, bid, ref["package_id"], ref["revision_id"])
        if package.kind.value != kind or package.manifest_digest != ref["manifest_digest"]:
            policy.fail("SELECTION_CHANGED", "所选资料包类型、修订或摘要不一致", 412)
        selected[role] = view(c, package)
    if (
        selected["target"]["manifest"]["scope"] != selected["authority"]["manifest"]["scope"]
        or selected["target"]["identity"] != selected["authority"]["identity"]
    ):
        policy.fail("PACKAGE_SCOPE_MISMATCH", "所选目标包与依据包的冻结项目范围不一致")
    identity = c.execute("SELECT design.identity_snapshot_v2(%s) AS value", (bid,)).fetchone()[
        "value"
    ]
    frozen = selected["target"]["identity"]
    matches = identity["binding_status"] == "confirmed" and identity == frozen
    parses = {
        (member["document_version_id"], member["parse"]["parse_run_id"])
        for value in selected.values()
        for member in value["manifest"]["members"]
        if member["parse"]["status"] == "frozen"
    }
    subjects = [
        {"kind": kind, "id": frozen[field]}
        for kind, field in (
            ("engineering_project", "engineering_project_id"),
            ("lot", "lot_id"),
            ("round", "round_id"),
            ("bidder", "bidder_id"),
        )
    ]
    return matches, parses, subjects


def item(c, bid, row, parses, at):
    """Keep the B1 fact observation byte-for-byte equivalent; native tests assert parity."""
    decision = current_decision(c, bid, "fact", row["id"])
    evidence = c.execute(
        """SELECT e.id::text,e.parse_id::text,p.document_version_id::text,e.physical_page,e.digest
        FROM design.evidence_blocks e JOIN design.parse_runs p ON p.bid_id=e.bid_id AND p.id=e.parse_id
        WHERE e.bid_id=%s AND e.id=ANY(%s::uuid[]) ORDER BY e.id""",
        (bid, row["evidence_ids"]),
    ).fetchall()
    observation = {
        "fact": clean(row),
        "decision": clean(decision),
        "decision_basis_jsonb_text": read_decision_basis(c, bid, decision, at),
        "evidence": clean(evidence),
        "scope_binding": "selected_frozen_parse"
        if evidence
        and len(evidence) == len(set(row["evidence_ids"]))
        and all((e["document_version_id"], e["parse_id"]) in parses for e in evidence)
        else "unproven",
    }
    proof = read_proof(c, bid, observation, at)
    status = assess(observation, proof)
    value = json.loads(row["value_jsonb_text"])
    identity_name = row["name"] if row["name"] in IDENTITY_FACTS else None
    public_decision = None
    if decision:
        public_decision = {
            **{
                k: clean(decision[k])
                for k in (
                    "id",
                    "decision",
                    "decision_revision",
                    "object_id",
                    "actor_id",
                    "created_at",
                )
            },
            "binding_verified": proof["decision_binding"],
            "basis_verified": "FACT_DECISION_BASIS_UNPROVEN" not in status["blockers"],
            "carryover_steps": len(proof["decision_lineage"]),
        }
    return {
        "fact_id": str(row["id"]),
        "fact_item_digest": digest(observation),
        "proof_digest": digest(proof),
        "name": row["name"],
        "subject_text": row["subject"],
        "scope_text": row["scope"],
        "value_jsonb_text": row["value_jsonb_text"],
        "unit": row["unit"],
        "identity_name": identity_name,
        "identity_value_usable": bool(identity_name and isinstance(value, str) and value.strip()),
        "decision": public_decision,
        "evidence": clean(evidence),
        "provenance_status": status["provenance_status"],
        "scope_binding": observation["scope_binding"],
        "facts_qualified": False,
        "blocking_reasons": status["blockers"],
    }


def catalog(c, bid, selection, at):
    blockers = nodes.project_blockers(c, bid)
    row = c.execute(
        "SELECT digest FROM design.fact_sets WHERE bid_id=%s AND id=%s",
        (bid, selection["fact_set_id"]),
    ).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目下没有明确选择的事实集", 404)
    if row["digest"] != selection["fact_set_digest"]:
        policy.fail("SELECTION_CHANGED", "所选事实集与预期摘要不一致", 412)
    head = current_head(c, bid)
    head_matches = bool(
        head
        and head["fact_set_id"] == selection["fact_set_id"]
        and head["revision"] == selection["fact_head_revision"]
        and head["fact_set_digest"] == selection["fact_set_digest"]
    )
    if not head_matches:
        blockers.append("AUTHORING_PACKAGE_FACT_HEAD_CHANGED")
    matches, parses, subjects = packages(c, bid, selection["target"], selection["authority"])
    if not matches:
        blockers.append("AUTHORING_PACKAGE_IDENTITY_CHANGED")
    rows = c.execute(
        """SELECT f.id,f.bid_id,f.fact_set_id,f.subject,f.scope,f.name,
        f.value::text AS value_jsonb_text,f.unit,f.evidence_ids,s.digest AS fact_set_digest
        FROM design.fact_items f JOIN design.fact_sets s ON s.bid_id=f.bid_id AND s.id=f.fact_set_id
        WHERE f.bid_id=%s AND f.fact_set_id=%s ORDER BY f.id LIMIT 1001""",
        (bid, selection["fact_set_id"]),
    ).fetchall()
    if len(rows) > policy.MAX_ITEMS:
        policy.fail("CAPACITY_EXCEEDED", "完整事实观察超过 1000 项，未截断后授予选择", 413)
    values = [item(c, bid, row, parses, at) for row in rows]
    if not values:
        blockers.append("FACT_SET_EMPTY")
    return {
        "protocol": "package-authoring-fact-catalog/1",
        "bid_id": bid,
        "selection": selection,
        "current_head": head,
        "head_matches": head_matches,
        "package_identity_matches": matches,
        "subject_choices": subjects,
        "identity_names": list(IDENTITY_FACTS),
        "blocking_reasons": blockers,
    }, values
