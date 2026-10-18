"""Deterministic intent identity. Context revisions and model profiles never prove independence."""

from __future__ import annotations

import unicodedata
from uuid import UUID

from packages.domain.runtime import DomainError, clean, fetch, sha

PURPOSES = {
    "general": ("general_reference",),
    "project": ("project_reference",),
    "finding": ("finding_explanation",),
    "rule": ("rule_explanation",),
    "section": ("section_reference", "section_draft"),
}
IDENTITY_FACTS = (
    "procurement_issuer_identifier",
    "procurement_project_identifier",
    "procurement_lot_identifier",
    "procurement_round_identifier",
    "bidder_identity_identifier",
)


def normalize_question(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n")).split()
    )


def association_key(values: dict) -> str:
    """Use evidenced business values, never a newly created project/round/bidder UUID."""
    if set(values) != set(IDENTITY_FACTS) or any(
        not isinstance(value, str) or not normalize_question(value) for value in values.values()
    ):
        raise DomainError(
            "ASSISTANT_TARGET_IDENTITY_UNPROVEN", "工程标段轮次或主体编号的已确认依据不足", 409
        )
    return sha(
        "\x1f".join(key + "=" + normalize_question(values[key]) for key in IDENTITY_FACTS).encode()
    )


def keys(question: str, target_key: str, purpose: str):
    normalized = normalize_question(question)
    coarse = sha((target_key + "\x1f" + purpose).encode())
    return normalized, coarse, sha((target_key + "\x1f" + purpose + "\x1f" + normalized).encode())


def project_identity(c, bid):
    from packages.domain.fact_sets import decision_basis
    from packages.domain.review_data import source_closure
    from packages.domain.rule_sets import current_decision
    from packages.identity.repository import snapshot
    from packages.knowledge.bridge import confirmed_fact

    identity = snapshot(c, bid)
    if identity["binding_status"] != "confirmed":
        raise DomainError(
            "ASSISTANT_TARGET_IDENTITY_UNPROVEN",
            "项目主体尚无当前确认依据，不能据项目壳证明独立",
            409,
        )
    head = fetch(c, "SELECT fact_set_id FROM fact_heads WHERE bid_id=%s", (bid,))
    rows = c.execute(
        "SELECT * FROM fact_items WHERE bid_id=%s AND fact_set_id=%s AND name=ANY(%s) ORDER BY id",
        (bid, head["fact_set_id"], list(IDENTITY_FACTS)),
    ).fetchall()
    values, proofs = {}, []
    at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    for name in IDENTITY_FACTS:
        facts = [row for row in rows if row["name"] == name]
        if len(facts) != 1 or not confirmed_fact(c, bid, facts[0], at):
            raise DomainError(
                "ASSISTANT_TARGET_IDENTITY_UNPROVEN",
                "尚缺当前原页证据支持的工程标段轮次或主体编号",
                409,
                {"missing_identity_fact": name},
            )
        fact = facts[0]
        values[name] = fact["value"]
        decision = current_decision(c, bid, "fact", fact["id"])
        basis = decision_basis(c, decision["id"])
        closure = source_closure(
            c, [{"id": ref["source_id"]} for ref in basis["evidence"]["references"]], lock=True
        )
        proofs.append(
            {
                "id": str(fact["id"]),
                "name": name,
                "value": fact["value"],
                "decision_id": str(decision["id"]),
                "evidence_ids": sorted(map(str, fact["evidence_ids"])),
                "basis": basis,
                "source_closure": closure,
            }
        )
    canonical = association_key(values)
    return clean(
        {
            "canonical_project_key": canonical,
            "bid_id": bid,
            "identity_authority_id": identity["authority_id"],
            "identity_snapshot": identity,
            "fact_set_id": head["fact_set_id"],
            "identity_facts": proofs,
        }
    )


def resolve(c, actor, body, bid=None, *, generation=False):
    selected = body.get("target")
    if generation:
        selected = {"kind": "section", "id": body["section_id"]}
    if selected is None:
        selected = {"kind": "project", "id": str(bid)} if bid else {"kind": "general", "id": None}
    kind = selected["kind"]
    purpose = body.get("intent_purpose") or ("section_draft" if generation else PURPOSES[kind][0])
    if (
        kind not in PURPOSES
        or purpose not in PURPOSES[kind]
        or (purpose == "section_draft") != generation
    ):
        raise DomainError(
            "ASSISTANT_INTENT_PURPOSE_INVALID", "用途和真实作用对象不属于已实现组合", 422
        )
    if kind == "general":
        if bid or selected.get("id") is not None:
            raise DomainError("ASSISTANT_TARGET_INVALID", "通用参考不能伪装工程目标", 422)
        return {
            "kind": kind,
            "id": None,
            "purpose": purpose,
            "target_key": "general:" + str(actor),
            "canonical_project_key": None,
            "bid_id": None,
            "object_context": {},
            "proof": None,
        }
    object_id = UUID(selected["id"])
    if kind == "project":
        object_bid, object_row = (
            object_id,
            fetch(c, "SELECT id,title FROM bids WHERE id=%s", (object_id,)),
        )
        stable = "project"
    else:
        table = {"section": "sections", "finding": "findings", "rule": "rule_items"}[kind]
        from psycopg import sql

        object_row = fetch(
            c, sql.SQL("SELECT * FROM {} WHERE id=%s").format(sql.Identifier(table)), (object_id,)
        )
        object_bid = object_row["bid_id"]
        if kind == "finding":
            visited = set()
            root = object_row
            while root["carried_from_id"]:
                if root["id"] in visited:
                    raise DomainError("ASSISTANT_TARGET_INVALID", "问题沿用链无法确定", 409)
                visited.add(root["id"])
                root = fetch(
                    c,
                    "SELECT * FROM findings WHERE id=%s AND bid_id=%s",
                    (root["carried_from_id"], object_bid),
                )
            stable = str(root["id"])
        elif kind == "rule":
            root_id = object_row["manual_origin_rule_id"]
            stable = (
                str(root_id)
                if root_id
                else sha(
                    (
                        normalize_question(object_row["kind"])
                        + "\x1f"
                        + normalize_question(object_row["statement"])
                    ).encode()
                )
            )
        else:
            stable = str(object_id)
            revision = fetch(
                c,
                "SELECT content,digest FROM section_revisions WHERE section_id=%s AND revision=%s",
                (object_id, object_row["head_revision"]),
            )
            object_row = dict(object_row) | {
                "content": revision["content"],
                "content_digest": revision["digest"],
            }
    if bid and UUID(str(bid)) != object_bid:
        raise DomainError("ASSISTANT_TARGET_INVALID", "作用对象不属于当前项目", 404)
    if not bid and not any(
        source["kind"] == "project" and source["id"] == str(object_bid)
        for source in body.get("source_selection", [])
    ):
        raise DomainError(
            "ASSISTANT_TARGET_SELECTION_REQUIRED", "全局新问题须明确选择目标所属项目", 422
        )
    proof = project_identity(c, object_bid)
    return clean(
        {
            "kind": kind,
            "id": object_id,
            "purpose": purpose,
            "target_key": proof["canonical_project_key"] + ":" + kind + ":" + stable,
            "canonical_project_key": proof["canonical_project_key"],
            "bid_id": object_bid,
            "object_context": object_row,
            "proof": proof,
        }
    )


def revalidate(c, target, actor, body, bid=None, *, generation=False):
    current = resolve(c, actor, body, bid, generation=generation)
    if current != target:
        raise DomainError(
            "ASSISTANT_INTENT_TARGET_CHANGED",
            "作用对象或编号证据已变化，旧候选不能成为当前答案",
            409,
        )
    return current
