"""Read-only explicit package inputs; never schedules or authorizes a review."""

from datetime import datetime
from typing import Any

from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_requirement_repository as requirements
from packages.domain.bid_package_service import historical, view
from packages.domain.bid_packages import require
from packages.domain.review_identity import digest
from packages.domain.runtime import fetch
from packages.lifecycle.service import profile


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


def preview(c: Any, bid: str, package: str, revision: str, inventory_id: str, body: dict[str, Any]):
    inventory = requirements.load_inventory(c, bid, package, revision, inventory_id)
    inv = inventory["manifest"]
    own = historical(c, bid, package, revision)
    authority = packages.load_revision(c, bid, inv["authority_revision_id"])
    require(
        own.kind.value == "bid" and authority.kind.value == "authority",
        "PACKAGE_REVIEW_KIND_MISMATCH",
    )
    require(own.scope == authority.scope, "PACKAGE_REVIEW_SCOPE_MISMATCH")
    require(
        body["package_digest"] == own.manifest_digest
        and body["inventory_digest"] == inventory["digest"],
        "PACKAGE_REVIEW_INPUT_DIGEST_MISMATCH",
    )
    coverage = None
    if body["coverage_attempt_id"] is not None:
        coverage = requirements.load_attempt(
            c, bid, package, revision, inventory_id, body["coverage_attempt_id"]
        )
        require(
            coverage["digest"] == body["coverage_digest"], "PACKAGE_REVIEW_COVERAGE_DIGEST_MISMATCH"
        )
    else:
        require(body["coverage_digest"] is None, "PACKAGE_REVIEW_COVERAGE_DIGEST_MISMATCH")

    target_view, authority_view = view(c, own), view(c, authority)
    require(
        inv["package_digest"] == target_view["digest"]
        and inv["authority_digest"] == authority_view["digest"]
        and inv["identity_digest"] == target_view["identity"]["digest"],
        "PACKAGE_REVIEW_FROZEN_INPUT_CORRUPT",
    )
    # This digest identifies only the explicitly selected immutable records.
    # Mutable readiness observations below never rewrite the selected input.
    manifest = {
        "version": "bid-package-review-input/1",
        "kind": "preview",
        "bid_id": bid,
        "target": target_view,
        "authority": authority_view,
        "inventory": inventory,
        "coverage": coverage,
    }
    current = fetch(
        c,
        "SELECT design.identity_snapshot_v2(%s) AS identity,p.current_rule_set_id,p.phase,p.archived_at FROM design.bid_profiles p WHERE p.bid_id=%s",
        (bid, bid),
    )
    heads = packages._all(
        c,
        "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[])",
        ([own.package_id, authority.package_id],),
    )
    heads_by_package = {row["package_id"]: row["revision_id"] for row in heads}
    inventory_head = requirements.head(c, revision)
    snapshot = requirements._source_snapshot(c, revision, authority.revision_id)
    at = fetch(c, "SELECT clock_timestamp() AS at")["at"]
    codes = []
    state = profile(c, bid)
    if state["archived_at"] is not None or state["phase"] in {"closed", "terminated"}:
        codes.append("PROJECT_WORK_CLOSED")
    if own.scope.bidder_status != "confirmed":
        codes.append("PACKAGE_BIDDER_UNCONFIRMED")
    if any(
        v["identity"]["digest"] != current["identity"]["digest"]
        for v in (target_view, authority_view)
    ):
        codes.append("PACKAGE_REVIEW_IDENTITY_STALE")
    if (
        heads_by_package.get(own.package_id) != revision
        or heads_by_package.get(authority.package_id) != authority.revision_id
    ):
        codes.append("PACKAGE_REVIEW_PACKAGE_STALE")
    if inventory_head is None or inventory_head["id"] != inventory_id:
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
    if not own.formal_eligible or not authority.formal_eligible:
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
    # A preview is not an execution adapter, job receipt or formal readiness grant.
    codes.append("PACKAGE_REVIEW_EXECUTOR_NOT_READY")
    return {
        "manifest": manifest,
        "digest": digest(manifest),
        "review_ready": False,
        "launch_available": False,
        "blockers": codes,
        "physical_page_gaps": gaps,
    }
