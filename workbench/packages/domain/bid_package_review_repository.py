"""Read explicit immutable selections and live observations; never decide eligibility."""

from typing import Any

from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_requirement_repository as requirements
from packages.domain.bid_package_service import historical, view
from packages.domain.bid_packages import require
from packages.domain.runtime import fetch
from packages.lifecycle.service import profile


def selected(
    c: Any, bid: str, package: str, revision: str, inventory_id: str, body: dict[str, Any]
):
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
    return manifest


def observations(c: Any, manifest: dict[str, Any]):
    bid = manifest["bid_id"]
    own, authority = manifest["target"]["manifest"], manifest["authority"]["manifest"]
    revision = own["revision_id"]
    current = fetch(
        c,
        "SELECT design.identity_snapshot_v2(%s) AS identity,p.current_rule_set_id,p.phase,p.archived_at FROM design.bid_profiles p WHERE p.bid_id=%s",
        (bid, bid),
    )
    heads = packages._all(
        c,
        "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[])",
        ([own["package_id"], authority["package_id"]],),
    )
    heads_by_package = {row["package_id"]: row["revision_id"] for row in heads}
    inventory_head = requirements.head(c, revision)
    snapshot = requirements._source_snapshot(c, revision, authority["revision_id"])
    at = fetch(c, "SELECT clock_timestamp() AS at")["at"]
    return {
        "current": current,
        "lifecycle": profile(c, bid),
        "package_heads": heads_by_package,
        "inventory_head": inventory_head,
        "sources": snapshot,
        "at": at,
    }
