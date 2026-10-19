"""Requirement projection/coverage persistence; caller owns the transaction."""

from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from packages.domain import bid_package_extraction as extraction
from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_requirements as domain
from packages.domain.bid_package_service import historical, lock_bid
from packages.domain.bid_packages import PackageError, PackageRevision, require
from packages.domain.review_identity import digest
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import DomainError, clean, fetch, require_read_committed, sha
from packages.identity import pagination
from packages.knowledge import sources
from packages.lifecycle.service import assert_work_writable


def _source_snapshot(c: Any, target: str, authority: str) -> list[dict[str, Any]]:
    return fetch(
        c, "SELECT design.bid_requirement_source_snapshot(%s,%s) AS value", (target, authority)
    )["value"]


def _context(
    c: Any, bid_id: str, package_id: str, target_id: str, authority_id: str, rule_set_id: str
):
    require_read_committed(c)
    lock_bid(c, bid_id)
    assert_work_writable(c, bid_id)
    sources.lock_graph(c)
    target = historical(c, bid_id, package_id, target_id)
    authority = packages.load_revision(c, bid_id, authority_id)
    require(
        target.kind.value == "bid" and authority.kind.value == "authority",
        "PACKAGE_REQUIREMENT_KIND_MISMATCH",
    )
    require(target.scope == authority.scope, "PACKAGE_REQUIREMENT_SCOPE_MISMATCH")
    current = packages.identity_snapshot(c, target.scope)
    for value in (target, authority):
        frozen = packages.load_frozen_identity(c, bid_id, value.revision_id)
        require(current["digest"] == frozen["digest"], "PACKAGE_REQUIREMENT_IDENTITY_STALE")
        head = fetch(
            c,
            "SELECT revision_id::text FROM design.bid_package_heads WHERE package_id=%s FOR SHARE",
            (value.package_id,),
        )
        require(head["revision_id"] == value.revision_id, "PACKAGE_REQUIREMENT_PACKAGE_STALE")
    rule_set = fetch(
        c,
        "SELECT r.* FROM design.rule_sets r JOIN design.bid_profiles p ON p.bid_id=r.bid_id AND p.current_rule_set_id=r.id WHERE r.id=%s AND r.bid_id=%s",
        (rule_set_id, bid_id),
    )
    snapshot = _source_snapshot(c, target_id, authority_id)
    at = fetch(c, "SELECT clock_timestamp() AS at")["at"]
    require(
        all(
            row["policy_class"] == "prebid_content"
            and row["status"] == "published"
            and row["known_at"] is not None
            and row["valid_from"] is not None
            and datetime.fromisoformat(row["known_at"]) <= at
            and datetime.fromisoformat(row["valid_from"]) <= at
            and (row["valid_until"] is None or at < datetime.fromisoformat(row["valid_until"]))
            for row in snapshot
        ),
        "PACKAGE_REQUIREMENT_SOURCE_NOT_EFFECTIVE",
    )
    return target, authority, current, clean(rule_set), snapshot


def head(c: Any, target_id: str, *, lock: bool = False):
    return packages._one(
        c,
        (
            "SELECT inventory_id::text AS id,revision,digest FROM design.bid_package_requirement_heads WHERE target_revision_id=%s FOR UPDATE"
            if lock
            else "SELECT inventory_id::text AS id,revision,digest FROM design.bid_package_requirement_heads WHERE target_revision_id=%s"
        ),
        (target_id,),
    )


def _evidence(c: Any, package: PackageRevision) -> dict[str, dict[str, Any]]:
    rows = packages._all(
        c,
        """SELECT DISTINCT e.id,e.parse_id,e.physical_page,p.part_id
    FROM design.evidence_blocks e JOIN design.bid_package_members m ON m.bid_id=e.bid_id AND m.parse_run_id=e.parse_id
    JOIN design.bid_package_parts p ON p.revision_id=m.revision_id AND p.member_id=m.member_id
    AND e.physical_page BETWEEN p.first_page AND p.last_page WHERE m.revision_id=%s""",
        (package.revision_id,),
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = result.setdefault(
            str(row["id"]),
            {"parse_id": row["parse_id"], "physical_page": row["physical_page"], "part_ids": set()},
        )
        item["part_ids"].add(row["part_id"])
    return result


def create_inventory(
    c: Any,
    bid_id: str,
    package_id: str,
    target_id: str,
    body: dict[str, Any],
    *,
    expected_digest: str | None,
):
    with c.transaction():
        target, authority, current, rule_set, snapshot = _context(
            c, bid_id, package_id, target_id, body["authority_revision_id"], body["rule_set_id"]
        )
        previous = head(c, target_id, lock=True)
        require(
            (previous["digest"] if previous else None) == expected_digest,
            "PACKAGE_REQUIREMENT_CAS_MISMATCH",
        )
        mappings = {row["rule_id"]: row for row in body["mappings"]}
        require(len(mappings) == len(body["mappings"]), "PACKAGE_REQUIREMENT_MAPPING_DUPLICATE")
        rules = packages._all(
            c,
            "SELECT to_jsonb(r)||jsonb_build_object('max_points',r.max_points::text) AS value FROM design.rule_items r WHERE rule_set_id=%s ORDER BY kind,id",
            (rule_set["id"],),
        )
        require(
            set(mappings) <= {row["value"]["id"] for row in rules}, "PACKAGE_REQUIREMENT_UNKNOWN"
        )
        authority_evidence = _evidence(c, authority)
        bindings = []
        for row in rules:
            rule = row["value"]
            counts = fetch(
                c,
                "SELECT count(*) AS n FROM design.evidence_blocks WHERE bid_id=%s AND id=ANY(%s::uuid[])",
                (bid_id, rule["evidence_ids"]),
            )
            require(
                counts["n"] == len(rule["evidence_ids"]),
                "PACKAGE_REQUIREMENT_RULE_EVIDENCE_INVALID",
            )
            mapping = mappings.get(rule["id"])
            if mapping:
                require(
                    set(mapping["basis_evidence_ids"] + mapping["applicability_evidence_ids"])
                    <= authority_evidence.keys(),
                    "PACKAGE_REQUIREMENT_EVIDENCE_OUTSIDE_AUTHORITY",
                )
            decision = current_decision(c, bid_id, "rule", rule["id"])
            frozen_decision = (
                fetch(
                    c,
                    "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE id=%s",
                    (decision["id"],),
                )["value"]
                if decision
                else None
            )
            bindings.append(
                domain.project_requirement(
                    target,
                    rule,
                    frozen_decision,
                    mapping,
                    source_bound=bool(rule["evidence_ids"])
                    and set(rule["evidence_ids"]) <= authority_evidence.keys(),
                )
            )
        extracted = extraction.completion_for_rule_set(
            c,
            bid_id,
            str(rule_set["id"]),
            authority.revision_id,
            authority.manifest_digest,
        )
        manifest = {
            "version": "bid-package-requirements/2" if extracted else "bid-package-requirements/1",
            "id": str(uuid4()),
            "bid_id": bid_id,
            "package_id": package_id,
            "target_revision_id": target_id,
            "package_digest": target.manifest_digest,
            "authority_revision_id": authority.revision_id,
            "authority_digest": authority.manifest_digest,
            "rule_set_id": str(rule_set["id"]),
            "rule_set_digest": rule_set["digest"],
            "revision": previous["revision"] + 1 if previous else 1,
            "predecessor_digest": expected_digest,
            "identity_digest": current["digest"],
            "source_snapshot": snapshot,
            "requirements": bindings,
            "inventory_complete": False,
            "extraction_binding": (
                "exact_frozen_input_result" if extracted else "unproven_legacy_rule_set"
            ),
            "review_ready": False,
            "actor_id": body["actor_id"],
        }
        if extracted:
            manifest.update(
                {
                    "extraction_input_digest": extracted["input_digest"],
                    "extraction_result_digest": extracted["result_digest"],
                    "extraction_result_id": str(extracted["id"]),
                    "extraction_range_status": extracted["result"]["range_status"],
                    "extraction_coverage": extracted["result"]["extraction_coverage"],
                    "extraction_quality_status": extracted["result"]["quality_status"],
                }
            )
        identity = manifest["id"]
        frozen_digest = digest(manifest)
        c.execute(
            """INSERT INTO design.bid_package_requirement_inventories
        (id,bid_id,package_id,target_revision_id,authority_revision_id,rule_set_id,revision,predecessor_digest,digest,manifest,actor_id)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                identity,
                bid_id,
                package_id,
                target_id,
                authority.revision_id,
                rule_set["id"],
                manifest["revision"],
                expected_digest,
                frozen_digest,
                Jsonb(manifest),
                body["actor_id"],
            ),
        )
        for ordinal, binding in enumerate(bindings):
            c.execute(
                "INSERT INTO design.bid_package_requirements(inventory_id,bid_id,ordinal,rule_id,decision_id,requirement_digest,payload) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    identity,
                    bid_id,
                    ordinal,
                    binding["rule_id"],
                    binding["decision_id"],
                    binding["requirement_digest"],
                    Jsonb(binding),
                ),
            )
        if previous:
            c.execute(
                "UPDATE design.bid_package_requirement_heads SET inventory_id=%s,revision=%s,digest=%s WHERE target_revision_id=%s",
                (identity, manifest["revision"], frozen_digest, target_id),
            )
        else:
            c.execute(
                "INSERT INTO design.bid_package_requirement_heads(target_revision_id,inventory_id,revision,digest) VALUES(%s,%s,%s,%s)",
                (target_id, identity, manifest["revision"], frozen_digest),
            )
        return {"manifest": manifest, "digest": frozen_digest}


def load_inventory(c: Any, bid_id: str, package_id: str, target_id: str, inventory_id: str):
    row = packages._one(
        c,
        "SELECT manifest,digest FROM design.bid_package_requirement_inventories WHERE bid_id=%s AND package_id=%s AND target_revision_id=%s AND id=%s",
        (bid_id, package_id, target_id, inventory_id),
    )
    if not row:
        raise PackageError("PACKAGE_REQUIREMENT_INVENTORY_NOT_FOUND")
    try:
        from packages.contracts.bid_package_requirements_api import valid

        value = row["manifest"]
        require(
            valid("PackageRequirementInventoryManifest", value) and digest(value) == row["digest"],
            "PACKAGE_REQUIREMENT_STORED_CORRUPT",
        )
        if value["version"] == "bid-package-requirements/2":
            result = extraction.completion_for_rule_set(
                c,
                bid_id,
                value["rule_set_id"],
                value["authority_revision_id"],
                value["authority_digest"],
            )
            require(
                result is not None
                and value["extraction_input_digest"] == result["input_digest"]
                and value["extraction_result_digest"] == result["result_digest"]
                and value["extraction_result_id"] == str(result["id"])
                and value["extraction_range_status"] == result["result"]["range_status"]
                and value["extraction_coverage"] == result["result"]["extraction_coverage"]
                and value["extraction_quality_status"] == result["result"]["quality_status"],
                "PACKAGE_REQUIREMENT_STORED_CORRUPT",
            )
        require(
            all(
                binding["requirement_digest"] == digest(binding["requirement"])
                and binding["rule_digest"] == digest(binding["rule_snapshot"])
                and binding["rule_id"] == binding["requirement"]["requirement_id"]
                and binding["decision_id"]
                == (binding["decision_snapshot"]["id"] if binding["decision_snapshot"] else None)
                for binding in value["requirements"]
            ),
            "PACKAGE_REQUIREMENT_STORED_CORRUPT",
        )
        target = packages.load_revision(c, bid_id, target_id)
        authority = packages.load_revision(c, bid_id, value["authority_revision_id"])
        require(
            value["package_digest"] == target.manifest_digest
            and value["authority_digest"] == authority.manifest_digest
            and target.scope == authority.scope,
            "PACKAGE_REQUIREMENT_STORED_CORRUPT",
        )
        domain.assess_records(target, row["manifest"]["requirements"], [])
        return row
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise PackageError("PACKAGE_REQUIREMENT_STORED_CORRUPT") from error


def create_attempt(
    c: Any, bid_id: str, package_id: str, target_id: str, inventory_id: str, body: dict[str, Any]
):
    with c.transaction():
        row = load_inventory(c, bid_id, package_id, target_id, inventory_id)
        inv = row["manifest"]
        target, authority, _, _, snapshot = _context(
            c, bid_id, package_id, target_id, inv["authority_revision_id"], inv["rule_set_id"]
        )
        require(
            body["package_digest"] == target.manifest_digest
            and body["inventory_digest"] == row["digest"],
            "PACKAGE_REQUIREMENT_ATTEMPT_STALE",
        )
        current = head(c, target_id, lock=True)
        require(
            current is not None and current["id"] == inventory_id,
            "PACKAGE_REQUIREMENT_INVENTORY_STALE",
        )
        require(snapshot == inv["source_snapshot"], "PACKAGE_REQUIREMENT_SOURCE_STALE")
        own_evidence = _evidence(c, target)
        authority_evidence = _evidence(c, authority)
        bindings = {r["rule_id"]: r for r in inv["requirements"]}
        for binding in bindings.values():
            decision = current_decision(c, bid_id, "rule", binding["rule_id"])
            require(
                (str(decision["id"]) if decision else None) == binding["decision_id"],
                "PACKAGE_REQUIREMENT_DECISION_STALE",
            )
        require(
            len({r["rule_id"] for r in body["results"]}) == len(body["results"]),
            "PACKAGE_COVERAGE_DUPLICATE",
        )
        records = []
        for item in body["results"]:
            binding = bindings.get(item["rule_id"])
            require(binding is not None, "PACKAGE_REQUIREMENT_UNKNOWN")
            if binding is None:
                raise PackageError("PACKAGE_REQUIREMENT_UNKNOWN")
            decision = current_decision(c, bid_id, "rule", binding["rule_id"])
            require(
                (str(decision["id"]) if decision else None) == binding["decision_id"],
                "PACKAGE_REQUIREMENT_DECISION_STALE",
            )
            if item["state"] in {"verified", "not_applicable"}:
                require(
                    binding["source_bound"]
                    and decision is not None
                    and decision["decision"] == "confirmed"
                    and binding["rule_snapshot"]["provenance_status"] == "effective",
                    "PACKAGE_REQUIREMENT_NOT_CONFIRMED",
                )
                require(bool(snapshot), "PACKAGE_REQUIREMENT_SOURCE_UNPROVEN")
                require(
                    {m.document_version_id for p in (target, authority) for m in p.members}
                    <= {str(s["document_version_id"]) for s in snapshot},
                    "PACKAGE_REQUIREMENT_SOURCE_UNPROVEN",
                )
                at = fetch(c, "SELECT clock_timestamp() AS at")["at"]
                require(
                    all(
                        s["status"] == "published"
                        and datetime.fromisoformat(s["known_at"]) <= at
                        and datetime.fromisoformat(s["valid_from"]) <= at
                        and (
                            s["valid_until"] is None
                            or at < datetime.fromisoformat(s["valid_until"])
                        )
                        for s in snapshot
                    ),
                    "PACKAGE_REQUIREMENT_SOURCE_UNPROVEN",
                )
            if item["state"] == "verified":
                require(
                    set(item["evidence_ids"]) <= own_evidence.keys(),
                    "PACKAGE_COVERAGE_EVIDENCE_OUTSIDE_SCOPE",
                )
                for identity in item["evidence_ids"]:
                    evidence = own_evidence[identity]
                    require(
                        any(
                            r["part_id"] in evidence["part_ids"]
                            and r["first_page"] <= evidence["physical_page"] <= r["last_page"]
                            for r in item["inspected"]
                        ),
                        "PACKAGE_COVERAGE_EVIDENCE_OUTSIDE_SCOPE",
                    )
            else:
                require(
                    set(item["evidence_ids"]) <= (own_evidence.keys() | authority_evidence.keys()),
                    "PACKAGE_COVERAGE_EVIDENCE_OUTSIDE_SCOPE",
                )
            records.append(domain.coverage_record(target, binding, item))
        assessment = domain.assess_records(target, inv["requirements"], records)
        identity = str(uuid4())
        manifest = {
            "version": "bid-package-coverage/1",
            "id": identity,
            "bid_id": bid_id,
            "inventory_id": inventory_id,
            "inventory_digest": row["digest"],
            "package_digest": target.manifest_digest,
            "actor_id": body["actor_id"],
            "results": records,
            "assessment": assessment,
            "review_ready": False,
        }
        frozen_digest = digest(manifest)
        c.execute(
            "INSERT INTO design.bid_package_coverage_attempts(id,bid_id,inventory_id,digest,manifest,actor_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (identity, bid_id, inventory_id, frozen_digest, Jsonb(manifest), body["actor_id"]),
        )
        for ordinal, result in enumerate(records):
            value = result["coverage"]
            c.execute(
                "INSERT INTO design.bid_package_coverage_results(attempt_id,inventory_id,rule_id,ordinal,requirement_digest,payload) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    identity,
                    inventory_id,
                    value["requirement_id"],
                    ordinal,
                    value["requirement_digest"],
                    Jsonb(result),
                ),
            )
        return {"manifest": manifest, "digest": frozen_digest}


def load_attempt(
    c: Any, bid_id: str, package_id: str, target_id: str, inventory_id: str, attempt_id: str
):
    inventory = load_inventory(c, bid_id, package_id, target_id, inventory_id)
    row = packages._one(
        c,
        "SELECT manifest,digest FROM design.bid_package_coverage_attempts WHERE bid_id=%s AND inventory_id=%s AND id=%s",
        (bid_id, inventory_id, attempt_id),
    )
    if row is None:
        raise PackageError("PACKAGE_COVERAGE_ATTEMPT_NOT_FOUND")
    try:
        from packages.contracts.bid_package_requirements_api import valid

        target = packages.load_revision(c, bid_id, target_id)
        value = row["manifest"]
        require(
            valid("PackageCoverageAttemptManifest", value)
            and digest(value) == row["digest"]
            and value["inventory_digest"] == inventory["digest"]
            and value["assessment"]
            == domain.assess_records(
                target, inventory["manifest"]["requirements"], value["results"]
            ),
            "PACKAGE_COVERAGE_STORED_CORRUPT",
        )
        require(
            all(
                result["coverage"]["state"] not in {"verified", "not_applicable"}
                or (
                    result["basis_type"] == "human_scope_declaration"
                    and bool(result["coverage"]["reason"])
                    and bool(result["evidence_ids"])
                )
                for result in value["results"]
            ),
            "PACKAGE_COVERAGE_STORED_CORRUPT",
        )
        return row
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise PackageError("PACKAGE_COVERAGE_STORED_CORRUPT") from error


def storage_error(error: psycopg.Error):
    # The route's outer error boundary must include connection.__exit__/COMMIT.
    # A deferred authority rejection rolls back the command ACK and all child rows.
    primary = getattr(error.diag, "message_primary", "") or ""
    codes = {
        "requirement_source_not_effective": "PACKAGE_REQUIREMENT_SOURCE_NOT_EFFECTIVE",
        "requirement_source_snapshot_stale": "PACKAGE_REQUIREMENT_SOURCE_STALE",
        "requirement_source_unproven": "PACKAGE_REQUIREMENT_SOURCE_UNPROVEN",
        "requirement_decision_stale": "PACKAGE_REQUIREMENT_DECISION_STALE",
        "requirement_identity_stale": "PACKAGE_REQUIREMENT_IDENTITY_STALE",
        "requirement_package_stale": "PACKAGE_REQUIREMENT_PACKAGE_STALE",
        "requirement_inventory_stale": "PACKAGE_REQUIREMENT_INVENTORY_STALE",
    }
    shape = bool(error.sqlstate and error.sqlstate.startswith("22")) or any(
        fragment in primary
        for fragment in ("_shape", "_invalid", "assessment_mismatch", "unmapped_must_stay_unknown")
    )
    return DomainError(
        codes.get(
            primary,
            "PACKAGE_REQUIREMENT_STORAGE_SHAPE_REJECTED"
            if shape
            else "PACKAGE_REQUIREMENT_STORAGE_REJECTED",
        ),
        "要求或人工范围声明不符合协议"
        if shape
        else "冻结依据、人工决定或来源时效已变化，请重新核对",
        422 if shape else 409,
        retryable=False,
    )


def directory(
    c: Any,
    bid_id: str,
    package_id: str,
    target_id: str,
    *,
    inventory_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
):
    historical(c, bid_id, package_id, target_id)
    if inventory_id:
        load_inventory(c, bid_id, package_id, target_id, inventory_id)
    scope = sha(
        {
            "directory": "bid-package-requirement-history/1",
            "bid_id": bid_id,
            "package_id": package_id,
            "target_id": target_id,
            "inventory_id": inventory_id,
        }
    )
    after = pagination.decode(cursor, scope)
    last = after[-1] if after else None
    if inventory_id:
        rows = packages._all(
            c,
            "SELECT id,digest,created_at FROM design.bid_package_coverage_attempts WHERE bid_id=%s AND inventory_id=%s AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
            (bid_id, inventory_id, last, last, limit + 1),
        )
    else:
        rows = packages._all(
            c,
            "SELECT id,digest,created_at FROM design.bid_package_requirement_inventories WHERE bid_id=%s AND package_id=%s AND target_revision_id=%s AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT %s",
            (bid_id, package_id, target_id, last, last, limit + 1),
        )
    items = clean(rows[:limit])
    value = {
        "items": items,
        "has_more": len(rows) > limit,
        "next_cursor": pagination.encode(scope, ["", items[-1]["id"]])
        if len(rows) > limit
        else None,
    }
    if not inventory_id:
        current = head(c, target_id)
        value["current_inventory_id"] = current["id"] if current else None
    return value
