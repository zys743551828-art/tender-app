"""Pure preflight policy: no database, storage, provider or job access."""

from datetime import datetime
from typing import Any


def physical_gaps(package: dict[str, Any], role: str) -> list[dict[str, Any]]:
    """Union shared ranges without counting pages or iterating unknown page counts."""
    gaps = []
    for member in package["members"]:
        count = member["page_count"]
        if count is None:
            continue
        end = 0
        for part in sorted(
            member["parts"], key=lambda item: (item["first_page"], item["last_page"])
        ):
            if part["first_page"] > end + 1:
                gaps.append(
                    {
                        "role": role,
                        "member_id": member["member_id"],
                        "first_page": end + 1,
                        "last_page": part["first_page"] - 1,
                    }
                )
            end = max(end, part["last_page"])
        if end < count:
            gaps.append(
                {
                    "role": role,
                    "member_id": member["member_id"],
                    "first_page": end + 1,
                    "last_page": count,
                }
            )
    return gaps


def evaluate(manifest: dict[str, Any], observations: dict[str, Any], *, evidence_matches: bool):
    target_view, authority_view = manifest["target"], manifest["authority"]
    inv = manifest["inventory"]["manifest"]
    current = observations["current"]
    state = observations["lifecycle"]
    heads_by_package = observations["package_heads"]
    inventory_head = observations["inventory_head"]
    snapshot, at = observations["sources"], observations["at"]
    codes = []
    if state["archived_at"] is not None or state["phase"] in {"closed", "terminated"}:
        codes.append("PROJECT_WORK_CLOSED")
    if target_view["manifest"]["scope"]["bidder_status"] != "confirmed":
        codes.append("PACKAGE_BIDDER_UNCONFIRMED")
    if any(
        v["identity"]["digest"] != current["identity"]["digest"]
        for v in (target_view, authority_view)
    ):
        codes.append("PACKAGE_REVIEW_IDENTITY_STALE")
    if (
        heads_by_package.get(target_view["manifest"]["package_id"])
        != target_view["manifest"]["revision_id"]
        or heads_by_package.get(authority_view["manifest"]["package_id"])
        != authority_view["manifest"]["revision_id"]
    ):
        codes.append("PACKAGE_REVIEW_PACKAGE_STALE")
    if inventory_head is None or inventory_head["id"] != inv["id"]:
        codes.append("PACKAGE_REVIEW_INVENTORY_STALE")
    if str(current["current_rule_set_id"]) != inv["rule_set_id"]:
        codes.append("PACKAGE_REVIEW_RULE_SET_STALE")
    if not snapshot:
        codes.append("PACKAGE_REVIEW_SOURCE_UNPROVEN")
    if snapshot != inv["source_snapshot"]:
        codes.append("PACKAGE_REVIEW_SOURCE_CHANGED")
    if any(
        row["policy_class"] != "prebid_content"
        or row["status"] != "published"
        or row["known_at"] is None
        or row["valid_from"] is None
        or datetime.fromisoformat(row["known_at"]) > at
        or datetime.fromisoformat(row["valid_from"]) > at
        or (row["valid_until"] is not None and datetime.fromisoformat(row["valid_until"]) <= at)
        for row in snapshot
    ):
        codes.append("PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE")
    if not target_view["storage_eligible"] or not authority_view["storage_eligible"]:
        codes.append("PACKAGE_REVIEW_MEMBERS_UNPROVEN")
    gaps = physical_gaps(target_view["manifest"], "target") + physical_gaps(
        authority_view["manifest"], "authority"
    )
    if gaps:
        codes.append("PACKAGE_REVIEW_PHYSICAL_RANGE_GAP")
    if inv["extraction_binding"] != "exact_frozen_input_result":
        codes.append("PACKAGE_REVIEW_EXTRACTION_UNPROVEN")
    if inv["inventory_complete"] is not True:
        codes.append("PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN")
    if not evidence_matches:
        codes.append("PACKAGE_REVIEW_EVIDENCE_CHANGED")
    # A preview is not an execution adapter, job receipt or formal readiness grant.
    codes.append("PACKAGE_REVIEW_EXECUTOR_NOT_READY")
    return {"blockers": codes, "physical_page_gaps": gaps}
