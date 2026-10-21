"""Fixed business identity from a persisted B1 input; no latest-parse lookup."""

import json
from uuid import UUID

from packages.authoring import package_input_repository as inputs
from packages.domain.runtime import DomainError, clean, fetch


def selected(c, bid, reference, section_id=None):
    row = inputs.load(c, bid, UUID(reference["authoring_input_id"]))
    if row["digest"] != reference["authoring_input_digest"] or (
        section_id is not None
        and row["manifest"]["selection"]["target_section"]["section_id"] != str(section_id)
    ):
        raise DomainError(
            "AUTHORING_PACKAGE_INPUT_BINDING_INVALID", "固定编写输入的摘要或目标章节不一致", 409
        )
    return row


def target(c, bid, input_id, input_digest):
    """Budget preparation still needs a protected job binding before reservation.

    Five selected facts produce the SAME canonical project/section/purpose keys
    as the legacy route. A package, template or input nonce proves no independence.
    The budget's SQL authority RPC independently verifies this exact proof.
    """
    row = selected(
        c,
        bid,
        {"authoring_input_id": str(input_id), "authoring_input_digest": input_digest},
    )
    context = json.loads(row["context_text"])
    choice = context["request"]
    identity_ids = set(choice["facts"]["identity_fact_ids"])
    proofs = []
    for item in context["facts"]["items"]:
        fact = item["item"]["fact"]
        if fact["id"] not in identity_ids:
            continue
        proofs.append(
            {
                "id": fact["id"],
                "name": fact["name"],
                "value": json.loads(fact["value_jsonb_text"]),
                "decision_id": item["item"]["decision"]["id"],
                "evidence_ids": sorted(fact["evidence_ids"]),
                "basis": json.loads(item["item"]["decision_basis_jsonb_text"]),
                "source_closure": item["proof"]["closure"],
            }
        )
    # SQL assistant_check_target consumes the original vocabulary and ordering.
    from packages.assistant.intent_identity import IDENTITY_FACTS

    proofs.sort(key=lambda p: IDENTITY_FACTS.index(p["name"]))
    section_choice = choice["target_section"]
    section = fetch(
        c,
        "SELECT * FROM design.sections WHERE bid_id=%s AND id=%s",
        (bid, section_choice["section_id"]),
    )
    frozen_section = next(
        s for s in context["target"]["sections"] if s["id"] == section_choice["section_revision_id"]
    )
    if section["head_revision"] != section_choice["base_section_revision"]:
        raise DomainError("AUTHORING_PACKAGE_SECTION_CHANGED", "所选章节头已变化", 409)
    canonical = context["facts"]["canonical_project_key"]
    proof = {
        "canonical_project_key": canonical,
        "bid_id": str(bid),
        "identity_authority_id": context["identity"]["authority_id"],
        "identity_snapshot": context["identity"],
        "fact_set_id": choice["facts"]["fact_set_id"],
        "identity_facts": proofs,
    }
    return clean(
        {
            "kind": "section",
            "id": section["id"],
            "purpose": "section_draft",
            "target_key": canonical + ":section:" + str(section["id"]),
            "canonical_project_key": canonical,
            "bid_id": str(bid),
            "object_context": dict(section)
            | {"content": frozen_section["content"], "content_digest": frozen_section["digest"]},
            "proof": proof,
        }
    )
