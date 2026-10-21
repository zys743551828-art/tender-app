"""Exact package submission observations, without a formal completeness grant.

The repository supplies immutable selections, native current decisions and a bounded
whole-bid history from one database snapshot. This module does no database, storage
or model IO. A human opinion is preserved as an opinion, never a recheck resolution.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import bid_package_requirements_api as requirements
from packages.contracts import package_review_runs_api as runs
from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain import package_inventory_proof as proof_protocol
from packages.domain import package_review_decisions as opinions
from packages.domain.bid_package_review_policy import physical_gaps
from packages.domain.bid_packages import (
    BidScope,
    DocumentPart,
    PackageKind,
    PackageMember,
    PackageRevision,
    ParseIdentity,
)
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import ROOT, DomainError, sha
from packages.identity.contracts import HISTORICAL_SNAPSHOT

VERSION = "package-submission-gate/1"
LIMITS = {
    "history_runs": 1000,
    "history_rows": 400000,
    "rule_decisions": 10000,
    "input_bytes": 64 * 1024 * 1024,
}
CORE_KINDS = {"mandatory", "disqualification"}
VERDICTS = ("satisfied", "violated", "not_found", "unable_to_judge", "not_applicable")
SCOPE_KEYS = ("bid_id", "package_id", "revision_id", "inventory_id")
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
COUNT = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
CODE = {"type": "string", "pattern": "^[A-Z][A-Z0-9_]+$", "maxLength": 200}
NULL = {"type": "null"}
RULE_KIND = {"enum": ["mandatory", "disqualification", "scoring", "advisory"]}
STATE = {"enum": ["blocked", "unknown", "pass"]}
ORIGINAL_STATES = {"enum": ["not_performed", "failed"]}
NATIVE_DECISION = object_schema(
    {
        "id": UUID,
        "bid_id": UUID,
        "object_kind": {"const": "rule"},
        "object_id": UUID,
        "object_revision": COUNT | {"minimum": 1},
        "decision": {"type": "string", "minLength": 1, "maxLength": 200},
        "reason": {"type": "string"},
        "evidence_ids": {"type": "array", "items": UUID},
        "actor_id": UUID,
        "created_at": TIME,
    }
)
LEGACY_FINDING = object_schema(
    {
        **dict.fromkeys(("id", "bid_id", "origin_id", "review_id"), UUID),
        "rule_id": {"anyOf": [UUID, NULL]},
        "rule_kind": {"anyOf": [RULE_KIND, NULL]},
        "severity": {"enum": ["critical", "major", "minor", "info"]},
        "category": {
            "enum": ["disqualification", "response", "consistency", "scope", "improvement"]
        },
        "verdict": {"enum": list(VERDICTS)},
        "lifecycle": {"enum": ["open", "deferred", "dismissed"]},
        "statement": {"type": "string", "minLength": 1},
    }
)


def _nullable(schema):
    return {"anyOf": [schema, NULL]}


def _array(schema, maximum=LIMITS["history_rows"]):
    return {"type": "array", "items": schema, "maxItems": maximum}


def _card(properties):
    return object_schema(
        {
            "state": STATE,
            "codes": _array(CODE, 100) | {"uniqueItems": True},
            **properties,
        }
    )


_OPINION = object_schema(
    {
        "id": UUID,
        "digest": SHA,
        "state": {"enum": ["confirmed", "rejected", "needs_review"]},
        "reason": {"type": "string"},
    }
)
_PACKAGE_RISK = object_schema(
    {
        "kind": {"const": "package_core_requirement"},
        "state": {"enum": ["blocked", "unknown"]},
        "scope": object_schema(dict.fromkeys(SCOPE_KEYS, UUID)),
        "run_id": UUID,
        "frozen_input_id": UUID,
        "execution_input_id": UUID,
        "result_digest": SHA,
        "row_digest": SHA,
        "requirement_id": UUID,
        "rule_digest": SHA,
        "rule_kind": {"enum": sorted(CORE_KINDS)},
        "verdict": {"enum": ["violated", "not_found", "unable_to_judge"]},
        "statement": {"type": "string"},
        "human_decision": _nullable(_OPINION),
        "resolution": {"const": "no_verified_package_recheck_resolution"},
    }
)
_LEGACY_RISK = object_schema(
    {
        "kind": {"const": "legacy_finding"},
        "state": {"const": "blocked"},
        "finding": LEGACY_FINDING,
        "finding_digest": SHA,
        "resolution": {"const": "no_verified_recheck_resolution"},
    }
)
_DEFS = {
    "CurrentInput": _card(
        {
            "scope": {"const": "current_metadata_observation"},
            "observations_digest": _nullable(SHA),
            "current_identity_digest": _nullable(SHA),
            "original_verification": ORIGINAL_STATES,
            "member_count": COUNT,
            "physical_page_gaps": _array(
                object_schema(
                    {
                        "role": {"enum": ["target", "authority"]},
                        "member_id": {"type": "string"},
                        "first_page": COUNT | {"minimum": 1},
                        "last_page": COUNT | {"minimum": 1},
                    }
                )
            ),
        }
    ),
    "CoreCoverage": _card(
        {
            "scope": {"const": "known_inventory_core_rules"},
            "inventory_proof_digest": _nullable(SHA),
            "run_id": _nullable(UUID),
            "active_core_count": COUNT,
            "judged_core_count": COUNT,
            "unknown_core_count": COUNT,
            "unfavorable_core_count": COUNT,
            "human_declared_count": COUNT,
            "extraction_range_proven": {"type": "boolean"},
            "inventory_complete": {"const": False},
            "quality_status": {"const": "not_measured"},
            "overall_coverage": {"enum": ["partial", "unknown"]},
        }
    ),
    "MandatoryConfirmation": _card(
        {
            "scope": {"const": "known_inventory_core_rules"},
            "core_rule_count": COUNT,
            "confirmed_count": COUNT,
            "pending_rule_ids": _array(UUID, LIMITS["rule_decisions"]),
            "inactive_rule_ids": _array(UUID, LIMITS["rule_decisions"]),
            "needs_revalidation_rule_ids": _array(UUID, LIMITS["rule_decisions"]),
            "decisions": _array(
                object_schema(
                    {
                        "rule_id": UUID,
                        "rule_digest": SHA,
                        "decision_id": _nullable(UUID),
                        "decision_digest": _nullable(SHA),
                        "decision": {"type": ["string", "null"]},
                    }
                ),
                LIMITS["rule_decisions"],
            ),
        }
    ),
    "KnownBlockingRisks": _card(
        {
            "scope": {"const": "whole_bid_known_history"},
            "history_digest": _nullable(SHA),
            "history_complete": {"type": "boolean"},
            "runs_read": COUNT,
            "result_rows_read": COUNT,
            "unknown_run_ids": _array(UUID, LIMITS["history_runs"] + 1),
            "blocked_count": COUNT,
            "unknown_count": COUNT,
            "risks": _array({"oneOf": [_PACKAGE_RISK, _LEGACY_RISK]}),
        }
    ),
}
_DEFS["Manifest"] = object_schema(
    {
        "version": {"const": VERSION},
        "kind": {"const": "current_package_submission_observation"},
        "subject": object_schema(
            {
                "kind": {"const": "bid_package"},
                **dict.fromkeys(("bid_id", "package_id", "revision_id"), UUID),
                "package_digest": SHA,
                "identity_digest": SHA,
            }
        ),
        "selection": object_schema(
            {
                "digest": SHA,
                "authority_revision_id": _nullable(UUID),
                "authority_digest": _nullable(SHA),
                "inventory_id": _nullable(UUID),
                "inventory_digest": _nullable(SHA),
                "coverage_attempt_id": _nullable(UUID),
                "coverage_digest": _nullable(SHA),
                "run_id": _nullable(UUID),
                "result_digest": _nullable(SHA),
            }
        ),
        "checked_at": TIME,
        "policy_digest": SHA,
        "gates": object_schema(
            {
                key: {"$ref": "#/$defs/" + name}
                for key, name in (
                    ("current_input", "CurrentInput"),
                    ("core_coverage", "CoreCoverage"),
                    ("mandatory_confirmation", "MandatoryConfirmation"),
                    ("known_blocking_risks", "KnownBlockingRisks"),
                )
            }
        ),
        "state": {"enum": ["blocked", "unknown"]},
        "allowed": {"const": False},
        "inventory_complete": {"const": False},
        "quality_status": {"const": "not_measured"},
        "formal_scoring_eligible": {"const": False},
        "submission_eligible": {"const": False},
        "publication_authorized": {"const": False},
        "platform_submission_verified": {"const": False},
        "limitations": _array(CODE, 10) | {"uniqueItems": True, "minItems": 1},
    }
)
_DEFS["View"] = object_schema({"manifest": {"$ref": "#/$defs/Manifest"}, "digest": SHA})
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:tender:package-submission-gate:1",
    "$ref": "#/$defs/View",
    "$defs": _DEFS,
}


def _relocate(value):
    if isinstance(value, dict):
        return {
            key: item.replace("#/$defs/", "#/components/schemas/PackageSubmissionGate_")
            if key == "$ref"
            else _relocate(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_relocate(item) for item in value]
    return value


SCHEMAS = {"PackageSubmissionGate_" + key: _relocate(value) for key, value in _DEFS.items()}
SCHEMAS["PackageSubmissionGateView"] = {"$ref": "#/components/schemas/PackageSubmissionGate_View"}
POLICY_FILES = (
    "packages/domain/package_submission_gate.py",
    "packages/domain/review_identity.py",
    "packages/domain/bid_package_review_policy.py",
    "packages/domain/bid_packages.py",
    "packages/domain/package_inventory_proof.py",
    "packages/domain/package_review_decisions.py",
    "packages/contracts/bid_package_api.py",
    "packages/contracts/bid_package_requirements_api.py",
    "packages/contracts/package_rule_corrections_api.py",
    "packages/contracts/package_review_runs_api.py",
    "packages/contracts/package_review_decisions_api.py",
    "packages/contracts/schemas/bid-package.schema.json",
    "packages/contracts/schemas/package-scope-review.schema.json",
    "packages/contracts/schemas/package-inventory-proof.schema.json",
    "packages/identity/contracts.py",
)


def policy_identity():
    value = {
        "version": "package-submission-gate-policy/1",
        "limits": deepcopy(LIMITS),
        "sources": {name: sha((ROOT / name).read_bytes()) for name in POLICY_FILES},
    }
    return value | {"digest": digest(value)}


def _require(condition, code="BINDING_MISMATCH", status=409):
    if not condition:
        raise DomainError(
            "PACKAGE_SUBMISSION_GATE_" + code,
            "整包提交观察的范围、历史或原记录无法一致核验；没有推断、截断或补写资格",
            status,
        )


def _valid(schema, value):
    return Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)


def _bounded(value):
    try:
        raw = canonical(value)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        raise DomainError(
            "PACKAGE_SUBMISSION_GATE_INVALID", "提交观察只能包含有界规范 JSON 值", 422
        ) from error
    _require(len(raw) <= LIMITS["input_bytes"], "LIMIT_EXCEEDED", 422)


def _view(value, name):
    schemas = requirements.PACKAGE_SCHEMAS | requirements.SCHEMAS
    _require(
        _valid({"components": {"schemas": schemas}, "allOf": [schemas[name]]}, value),
        "INVALID",
        422,
    )
    _require(value["digest"] == digest(value["manifest"]))


def _package(value):
    """Apply the same pure member/range invariants as immutable package storage."""
    manifest = value["manifest"]
    members = tuple(
        PackageMember(
            **(
                member
                | {
                    "scope": BidScope(**member["scope"]),
                    "purposes": tuple(member["purposes"]),
                    "parse": ParseIdentity(**member["parse"]),
                    "parts": tuple(
                        DocumentPart(**(part | {"heading_path": tuple(part["heading_path"])}))
                        for part in member["parts"]
                    ),
                }
            )
        )
        for member in manifest["members"]
    )
    package = PackageRevision(
        **(
            manifest
            | {
                "scope": BidScope(**manifest["scope"]),
                "kind": PackageKind(manifest["kind"]),
                "members": members,
            }
        )
    )
    _require(package.formal_eligible == value["storage_eligible"])


def _selection(value):
    _require(type(value) is dict, "INVALID", 422)
    if set(value) == {"target", "authority", "inventory", "coverage"}:
        _view(value["target"], "BidPackageStoredView")
    else:
        _require(requirements.valid("PackageReviewInputManifest", value), "INVALID", 422)
        _require(value["bid_id"] == value["target"]["manifest"]["scope"]["bid_id"])
    target = value["target"]
    _view(target, "BidPackageStoredView")
    tm = target["manifest"]
    _require(tm["kind"] == "bid")
    for role in ("target", "authority"):
        item = value[role]
        if item is None:
            continue
        _view(item, "BidPackageStoredView")
        _package(item)
        manifest, identity = item["manifest"], item["identity"]
        _require(manifest["scope"] == tm["scope"])
        _require(
            all(
                manifest["scope"][key] == identity[key]
                for key in ("engineering_project_id", "round_id", "bidder_id")
            )
            and ("lot_id" not in identity or manifest["scope"]["lot_id"] == identity["lot_id"])
            and manifest["scope"]["bidder_status"] == identity["binding_status"]
        )
        _require(manifest["kind"] == ("bid" if role == "target" else "authority"))
        members = manifest["members"]
        _require(len({m["member_id"] for m in members}) == len(members))
        _require(all(m["scope"] == manifest["scope"] for m in members))
    inventory = value["inventory"]
    rows = []
    if inventory is not None:
        _require(value["authority"] is not None)
        _view(inventory, "PackageRequirementInventoryView")
        im = inventory["manifest"]
        authority = value["authority"]
        _require(
            im["bid_id"] == tm["scope"]["bid_id"]
            and im["package_id"] == tm["package_id"]
            and im["target_revision_id"] == tm["revision_id"]
            and im["package_digest"] == target["digest"]
            and im["authority_revision_id"] == authority["manifest"]["revision_id"]
            and im["authority_digest"] == authority["digest"]
            and im["identity_digest"]
            == target["identity"]["digest"]
            == authority["identity"]["digest"]
        )
        rows = im["requirements"]
        _require(len(rows) <= LIMITS["rule_decisions"], "LIMIT_EXCEEDED", 422)
        _require(len({row["rule_id"] for row in rows}) == len(rows))
        for row in rows:
            rule = row["rule_snapshot"]
            _require(
                rule.get("id") == row["rule_id"] == row["requirement"]["requirement_id"]
                and rule.get("bid_id") == im["bid_id"]
                and rule.get("rule_set_id") == im["rule_set_id"]
                and rule.get("kind") in CORE_KINDS | {"advisory", "scoring"}
                and rule.get("provenance_status")
                in {"effective", "superseded", "needs_revalidation"}
                and row["rule_digest"] == digest(rule)
                and row["requirement_digest"] == digest(row["requirement"])
                and row["requirement"]["scope"] == tm["scope"]
                and row["decision_id"]
                == (row["decision_snapshot"]["id"] if row["decision_snapshot"] else None)
            )
    coverage = value["coverage"]
    if coverage is not None:
        _require(inventory is not None)
        _view(coverage, "PackageCoverageAttemptView")
        cm = coverage["manifest"]
        _require(
            cm["bid_id"] == tm["scope"]["bid_id"]
            and cm["inventory_id"] == inventory["manifest"]["id"]
            and cm["inventory_digest"] == inventory["digest"]
            and cm["package_digest"] == cm["assessment"]["package_digest"] == target["digest"]
        )
        by_id = {row["rule_id"]: row for row in rows}
        seen = set()
        for row in cm["results"]:
            result = row["coverage"]
            key = result["requirement_id"]
            _require(key in by_id and key not in seen)
            _require(result["requirement_digest"] == by_id[key]["requirement_digest"])
            _require(result["package_digest"] == target["digest"])
            seen.add(key)
    return rows


def _run(value, bid):
    _require(runs.valid("PackageReviewRunView", value), "INVALID", 422)
    _require(value["scope"]["bid_id"] == bid)
    _require(value["input_digest"] == value["operation"]["input_digest"])
    result = value["result"]
    _require((value["operation"]["state"] == "succeeded") == (result is not None))
    if result is None:
        return
    rm = result["manifest"]
    _require(
        digest(rm) == result["digest"]
        and rm["bid_id"] == bid
        and rm["run_id"] == value["id"]
        and rm["scope"] == value["scope"]
        and all(
            rm[key] == value[key]
            for key in (
                "input_digest",
                "execution_input_id",
                "execution_input_digest",
                "execution_digest",
                "dependency_plan_id",
                "dependency_plan_digest",
                "method_digest",
            )
        )
    )
    matrix = rm["matrix"]
    _require(
        len({row["requirement_id"] for row in matrix}) == len(matrix) == rm["requirement_count"]
    )
    counts = Counter(row["verdict"] for row in matrix)
    _require(rm["counts"] == {key: counts[key] for key in VERDICTS})
    _require(rm["matrix_coverage"] == ("partial" if counts["unable_to_judge"] else "complete"))
    docs = rm["submitted_documents"]
    _require(len({(doc["package_role"], doc["member_id"]) for doc in docs}) == len(docs))
    _require({doc["package_role"] for doc in docs} == {"target", "authority"})


def _selected_run(selection, run, rows):
    if run is None:
        return
    tm = selection["target"]["manifest"]
    _run(run, tm["scope"]["bid_id"])
    inventory = selection["inventory"]
    _require(inventory is not None and selection["authority"] is not None)
    _require(
        run["scope"]
        == {
            "bid_id": tm["scope"]["bid_id"],
            "package_id": tm["package_id"],
            "revision_id": tm["revision_id"],
            "inventory_id": inventory["manifest"]["id"],
        }
    )
    if run["result"] is None:
        return
    result = run["result"]["manifest"]
    by_id = {row["rule_id"]: row for row in rows}
    _require(set(by_id) == {row["requirement_id"] for row in result["matrix"]})
    for row in result["matrix"]:
        expected = by_id[row["requirement_id"]]
        _require(
            row["requirement_digest"] == expected["requirement_digest"]
            and row["rule_digest"] == expected["rule_digest"]
            and row["rule_kind"] == expected["rule_snapshot"]["kind"]
            and row["requirement_statement"] == expected["rule_snapshot"]["statement"]
        )
    expected_docs = {}
    for role in ("target", "authority"):
        for member in selection[role]["manifest"]["members"]:
            _require(member["parse"]["status"] == "frozen")
            expected_docs[(role, member["member_id"])] = {
                "package_role": role,
                "member_id": member["member_id"],
                "document_version_id": member["document_version_id"],
                "parse_run_id": member["parse"]["parse_run_id"],
                "file_digest": member["file_digest"],
                "page_count": member["page_count"],
                "parts": member["parts"],
            }
    actual = result["submitted_documents"]
    _require(set(expected_docs) == {(doc["package_role"], doc["member_id"]) for doc in actual})
    for doc in actual:
        _require(
            {key: field for key, field in doc.items() if key != "evidence_count"}
            == expected_docs[(doc["package_role"], doc["member_id"])]
        )


def _state(blocked, unknown):
    return "blocked" if blocked else "unknown" if unknown else "pass"


def _current(selection, current, at, original_verification, run):
    blocked, unknown = [], []
    gaps, members = [], []
    for role in ("target", "authority"):
        value = selection[role]
        if value is None:
            unknown.append("AUTHORITY_PACKAGE_NOT_SELECTED")
            continue
        package = value["manifest"]
        members.extend(package["members"])
        gaps.extend(physical_gaps(package, role))
        if package["scope"]["bidder_status"] != "confirmed":
            blocked.append("PACKAGE_BIDDER_UNCONFIRMED")
        if not value["storage_eligible"]:
            unknown.append("PACKAGE_MEMBERS_UNPROVEN")
        if any(m["parse"]["status"] != "frozen" for m in package["members"]):
            unknown.append("PACKAGE_PARSE_UNPROVEN")
    if gaps:
        blocked.append("PACKAGE_PHYSICAL_RANGE_GAP")
    identity_digest = None
    if current is None:
        unknown.append("CURRENT_METADATA_NOT_OBSERVED")
    else:
        _require(
            type(current) is dict
            and set(current)
            == {
                "current",
                "lifecycle",
                "package_heads",
                "inventory_head",
                "sources",
                "generated_outputs",
            },
            "INVALID",
            422,
        )
        profile, lifecycle = current["current"], current["lifecycle"]
        _require(
            type(profile) is dict
            and {"identity", "current_rule_set_id", "phase", "archived_at"} <= set(profile)
            and _valid(HISTORICAL_SNAPSHOT, profile["identity"])
            and type(lifecycle) is dict
            and {"bid_id", "phase", "archived_at"} <= set(lifecycle)
            and type(current["package_heads"]) is dict
            and type(current["sources"]) is list
            and type(current["generated_outputs"]) is list,
            "INVALID",
            422,
        )
        _require(lifecycle["bid_id"] == selection["target"]["manifest"]["scope"]["bid_id"])
        identity_digest = profile["identity"]["digest"]
        if lifecycle["archived_at"] is not None or lifecycle["phase"] in {"closed", "terminated"}:
            blocked.append("PROJECT_WORK_CLOSED")
        if profile["identity"]["binding_status"] != "confirmed":
            blocked.append("CURRENT_IDENTITY_UNCONFIRMED")
        for role in ("target", "authority"):
            value = selection[role]
            if value is None:
                continue
            if value["identity"]["digest"] != identity_digest:
                blocked.append("PACKAGE_IDENTITY_STALE")
            manifest = value["manifest"]
            if current["package_heads"].get(manifest["package_id"]) != manifest["revision_id"]:
                blocked.append("PACKAGE_REVISION_STALE")
        inventory = selection["inventory"]
        if inventory is not None:
            im = inventory["manifest"]
            head = current["inventory_head"]
            _require(head is None or type(head) is dict and "id" in head, "INVALID", 422)
            if head is None or head["id"] != im["id"]:
                blocked.append("PACKAGE_INVENTORY_STALE")
            if profile["current_rule_set_id"] != im["rule_set_id"]:
                blocked.append("PACKAGE_RULE_SET_STALE")
            if current["sources"] != im["source_snapshot"]:
                blocked.append("PACKAGE_SOURCES_CHANGED")
        if not current["sources"]:
            unknown.append("PACKAGE_SOURCES_UNPROVEN")
        for row in current["sources"]:
            _require(
                type(row) is dict
                and {"policy_class", "status", "known_at", "valid_from", "valid_until"} <= set(row),
                "INVALID",
                422,
            )
            times = [row[key] for key in ("known_at", "valid_from", "valid_until")]
            _require(all(value is None or _valid(TIME, value) for value in times), "INVALID", 422)
            if (
                row["policy_class"] != "prebid_content"
                or row["status"] != "published"
                or row["known_at"] is None
                or row["valid_from"] is None
                or datetime.fromisoformat(row["known_at"]) > at
                or datetime.fromisoformat(row["valid_from"]) > at
                or row["valid_until"] is not None
                and datetime.fromisoformat(row["valid_until"]) <= at
            ):
                blocked.append("PACKAGE_SOURCE_NOT_EFFECTIVE")
        expected_members = {
            (role, member["member_id"]): member
            for role in ("target", "authority")
            if selection[role] is not None
            for member in selection[role]["manifest"]["members"]
        }
        generated_seen = set()
        for row in current["generated_outputs"]:
            _require(
                type(row) is dict
                and set(row) == {"package_role", "member_id", "document_version_id", "admission"},
                "INVALID",
                422,
            )
            key = (row["package_role"], row["member_id"])
            _require(key in expected_members and key not in generated_seen)
            _require(row["document_version_id"] == expected_members[key]["document_version_id"])
            _require(type(row["admission"]) is dict and "state" in row["admission"], "INVALID", 422)
            if row["admission"]["state"] != "matched":
                blocked.append("PACKAGE_GENERATED_OUTPUT_UNPROVEN")
            generated_seen.add(key)
    if run is not None:
        unknown.append("REVIEW_RUNTIME_DEPENDENCIES_NOT_CHECKED")
    if original_verification == "failed":
        blocked.append("ORIGINAL_BYTES_VERIFICATION_FAILED")
    else:
        unknown.append("ORIGINAL_BYTES_NOT_CHECKED")
    return {
        "state": _state(blocked, unknown),
        "codes": sorted(set(blocked + unknown)),
        "scope": "current_metadata_observation",
        "observations_digest": digest(current) if current is not None else None,
        "current_identity_digest": identity_digest,
        "original_verification": original_verification,
        "member_count": len(members),
        "physical_page_gaps": gaps,
    }


def _proof(selection, proof, run, rows):
    if proof is None:
        return
    _require(_valid(proof_protocol.SCHEMA, proof), "INVALID", 422)
    _require(digest(proof["manifest"]) == proof["digest"])
    im, authority = selection["inventory"], selection["authority"]
    _require(im is not None and authority is not None)
    pm, tm = proof["manifest"], selection["target"]["manifest"]
    prepared = pm["prepared"]
    _require(
        prepared["bid_id"] == tm["scope"]["bid_id"]
        and prepared["package_id"] == tm["package_id"]
        and prepared["revision_id"] == tm["revision_id"]
        and prepared["inventory_id"] == im["manifest"]["id"]
        and pm["inventory_digest"] == im["digest"]
        and pm["authority_revision_id"] == authority["manifest"]["revision_id"]
        and pm["authority_digest"] == authority["digest"]
        and pm["requirement_count"] == len(rows)
        and pm["unbound_requirement_count"] <= len(rows)
    )
    if run is not None:
        _require(
            prepared["frozen_input_id"] == run["frozen_input_id"]
            and pm["frozen_digest"] == run["frozen_input_digest"]
            and prepared["execution_input_id"] == run["execution_input_id"]
            and prepared["execution_input_digest"] == run["execution_input_digest"]
        )
    expected = {m["member_id"]: m for m in authority["manifest"]["members"]}
    docs = pm["documents"]
    _require(len(docs) == len(expected) and {d["member_id"] for d in docs} == set(expected))
    for doc in docs:
        member = expected[doc["member_id"]]
        gaps = physical_gaps({"members": [member]}, "authority")
        missing_pages = sum(gap["last_page"] - gap["first_page"] + 1 for gap in gaps)
        _require(
            doc["document_version_id"] == member["document_version_id"]
            and doc["parse_run_id"] == member["parse"]["parse_run_id"]
            and doc["page_count"] == member["page_count"]
            and doc["declared_page_count"] <= doc["page_count"]
            and doc["declared_page_count"] == doc["page_count"] - missing_pages
            and doc["all_pages_declared"] == (doc["declared_page_count"] == doc["page_count"])
        )
    _require(
        pm["all_declared_pages_bound"]
        == (bool(docs) and all(d["all_pages_declared"] for d in docs))
    )
    _require(
        pm["extraction_range_proven"]
        == (
            pm["extraction_receipt_state"] == "matched"
            and pm["all_declared_pages_bound"]
            and pm["frozen_evidence_count"] > 0
        )
    )
    _require(pm["frozen_evidence_count"] == sum(doc["evidence_count"] for doc in docs))
    if pm["extraction_receipt_state"] == "matched":
        _require(
            pm["receipt_digest"] is not None
            and pm["recorded_read_evidence_ids_digest"] == pm["frozen_evidence_ids_digest"]
        )
    if im["manifest"]["version"] == "bid-package-requirements/3":
        _require(pm["version"] == "package-inventory-proof/2")
        derivation = pm["human_derivation"]
        basis, head = im["manifest"]["extraction_basis"], im["manifest"]["human_derivation"]
        _require(
            derivation["root_inventory_id"] == basis["inventory_id"]
            and derivation["root_rule_set_id"] == basis["rule_set_id"]
            and derivation["head_id"] == head["head_id"]
            and derivation["head_digest"] == head["head_digest"]
            and derivation["length"] == head["length"]
        )
    else:
        _require(pm["version"] == "package-inventory-proof/1")


def _coverage(selection, rows, run, proof):
    blocked, unknown = (
        [],
        ["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED", "PACKAGE_REVIEW_QUALITY_NOT_MEASURED"],
    )
    inventory = selection["inventory"]
    if inventory is None:
        unknown.append("REQUIREMENT_INVENTORY_NOT_SELECTED")
    elif not rows:
        unknown.append("REQUIREMENT_INVENTORY_EMPTY")
    core = [
        row
        for row in rows
        if row["rule_snapshot"]["kind"] in CORE_KINDS
        and row["rule_snapshot"]["provenance_status"] != "superseded"
    ]
    if any(not row["source_bound"] for row in core):
        blocked.append("CORE_REQUIREMENT_SOURCE_UNBOUND")
    if any(row["rule_snapshot"]["provenance_status"] == "needs_revalidation" for row in core):
        blocked.append("CORE_REQUIREMENT_NEEDS_REVALIDATION")
    if any(
        not row["annotation"]["mapped"] or row["requirement"]["applicability"] == "unknown"
        for row in core
    ):
        unknown.append("CORE_REQUIREMENT_SCOPE_UNPROVEN")
    if proof is None:
        unknown.append("INVENTORY_EXTRACTION_PROOF_NOT_OBSERVED")
    else:
        pm = proof["manifest"]
        if pm["extraction_receipt_state"] != "matched":
            unknown.append("INVENTORY_EXTRACTION_RECEIPT_UNPROVEN")
        if not pm["all_declared_pages_bound"]:
            blocked.append("AUTHORITY_DECLARED_PAGE_GAP")
        if pm["extraction_coverage"] in {"partial", "conflict"}:
            blocked.append("INVENTORY_EXTRACTION_INCOMPLETE")
        if pm["frozen_evidence_count"] == 0 or pm["unbound_requirement_count"]:
            blocked.append("INVENTORY_SOURCE_EVIDENCE_INCOMPLETE")
        if pm.get("human_derivation", {}).get("state") == "archive_missing":
            unknown.append("INVENTORY_HUMAN_DERIVATION_UNPROVEN")
    matrix = (
        {}
        if run is None or run["result"] is None
        else {row["requirement_id"]: row for row in run["result"]["manifest"]["matrix"]}
    )
    if run is None:
        unknown.append("PACKAGE_REVIEW_NOT_SELECTED")
    elif run["result"] is None:
        unknown.append("PACKAGE_REVIEW_NOT_SUCCEEDED")
    else:
        unknown.append("PACKAGE_REVIEW_OVERALL_COVERAGE_PARTIAL")
    judged = unfavorable = 0
    for row in core:
        verdict = matrix.get(row["rule_id"], {}).get("verdict")
        if verdict is not None and verdict != "unable_to_judge":
            judged += 1
        if verdict in {"violated", "not_found"}:
            unfavorable += 1
    if judged < len(core):
        unknown.append("KNOWN_CORE_JUDGMENTS_INCOMPLETE")
    coverage = selection["coverage"]
    return {
        "state": _state(blocked, unknown),
        "codes": sorted(set(blocked + unknown)),
        "scope": "known_inventory_core_rules",
        "inventory_proof_digest": proof["digest"] if proof else None,
        "run_id": run["id"] if run else None,
        "active_core_count": len(core),
        "judged_core_count": judged,
        "unknown_core_count": len(core) - judged,
        "unfavorable_core_count": unfavorable,
        "human_declared_count": 0
        if coverage is None
        else sum(
            row["basis_type"] == "human_scope_declaration"
            for row in coverage["manifest"]["results"]
        ),
        "extraction_range_proven": proof["manifest"]["extraction_range_proven"] if proof else False,
        "inventory_complete": False,
        "quality_status": "not_measured",
        "overall_coverage": "partial" if matrix else "unknown",
    }


def _confirmation(selection, rows, rule_decisions):
    _require(type(rule_decisions) in {tuple, list}, "INVALID", 422)
    _require(len(rule_decisions) <= LIMITS["rule_decisions"], "LIMIT_EXCEEDED", 422)
    by_id = {row["rule_id"]: row for row in rows}
    observed = {}
    for item in rule_decisions:
        _require(
            type(item) is dict and set(item) == {"rule_id", "rule_digest", "decision"},
            "INVALID",
            422,
        )
        rid, decision = item["rule_id"], item["decision"]
        _require(
            rid in by_id
            and rid not in observed
            and item["rule_digest"] == by_id[rid]["rule_digest"]
        )
        if decision is not None:
            _require(_valid(NATIVE_DECISION, decision), "INVALID", 422)
            _require(
                decision["bid_id"] == selection["target"]["manifest"]["scope"]["bid_id"]
                and (decision["object_id"] == rid or decision == by_id[rid]["decision_snapshot"])
            )
        observed[rid] = decision
    core = [row for row in rows if row["rule_snapshot"]["kind"] in CORE_KINDS]
    inactive = sorted(
        row["rule_id"] for row in core if row["rule_snapshot"]["provenance_status"] == "superseded"
    )
    revalidate = sorted(
        row["rule_id"]
        for row in core
        if row["rule_snapshot"]["provenance_status"] == "needs_revalidation"
    )
    inactive_ids = set(inactive)
    active = [row for row in core if row["rule_id"] not in inactive_ids]
    pending, output, confirmed = [], [], 0
    blocked, unknown = [], []
    for row in sorted(active, key=lambda item: item["rule_id"]):
        rid, decision = row["rule_id"], observed.get(row["rule_id"])
        if decision is not None and decision["decision"] == "confirmed":
            confirmed += 1
        else:
            pending.append(rid)
            if rid not in observed or decision is None:
                unknown.append("CORE_RULE_CONFIRMATION_NOT_OBSERVED")
            else:
                blocked.append("CORE_RULE_NOT_CONFIRMED")
        output.append(
            {
                "rule_id": rid,
                "rule_digest": row["rule_digest"],
                "decision_id": decision["id"] if decision else None,
                "decision_digest": digest(decision) if decision else None,
                "decision": decision["decision"] if decision else None,
            }
        )
    if selection["inventory"] is None:
        unknown.append("REQUIREMENT_INVENTORY_NOT_SELECTED")
    elif not active:
        unknown.append("ACTIVE_CORE_REQUIREMENTS_NOT_ESTABLISHED")
    if revalidate:
        blocked.append("CORE_REQUIREMENT_NEEDS_REVALIDATION")
    return {
        "state": _state(blocked, unknown),
        "codes": sorted(set(blocked + unknown)),
        "scope": "known_inventory_core_rules",
        "core_rule_count": len(active),
        "confirmed_count": confirmed,
        "pending_rule_ids": pending,
        "inactive_rule_ids": inactive,
        "needs_revalidation_rule_ids": revalidate,
        "decisions": output,
    }


def _history(bid, history, selected_run):
    complete, available = False, history is not None
    all_runs, human, legacy = [], [], []
    if available:
        _require(
            type(history) is dict
            and set(history) == {"complete", "package_runs", "human_decisions", "legacy_findings"},
            "INVALID",
            422,
        )
        _require(
            type(history["complete"]) is bool
            and all(
                type(history[k]) is list
                for k in ("package_runs", "human_decisions", "legacy_findings")
            ),
            "INVALID",
            422,
        )
        complete = history["complete"]
        all_runs, human, legacy = (
            list(history["package_runs"]),
            history["human_decisions"],
            history["legacy_findings"],
        )
    _require(len(all_runs) <= LIMITS["history_runs"], "LIMIT_EXCEEDED", 422)
    _require(len(human) + len(legacy) <= LIMITS["history_rows"], "LIMIT_EXCEEDED", 422)
    by_id = {}
    row_count = 0
    for value in all_runs:
        _run(value, bid)
        _require(value["id"] not in by_id)
        by_id[value["id"]] = value
        row_count += len(value["result"]["manifest"]["matrix"]) if value["result"] else 0
    missing_selected = False
    if selected_run is not None:
        if selected_run["id"] in by_id:
            _require(by_id[selected_run["id"]] == selected_run)
        else:
            missing_selected, complete = True, False
            by_id[selected_run["id"]] = selected_run
            row_count += (
                len(selected_run["result"]["manifest"]["matrix"]) if selected_run["result"] else 0
            )
    _require(row_count + len(legacy) <= LIMITS["history_rows"], "LIMIT_EXCEEDED", 422)
    decisions = {}
    for value in human:
        _require(type(value) is dict and type(value.get("manifest")) is dict, "INVALID", 422)
        m = value["manifest"]
        run_id, requirement_id = m.get("run_id"), m.get("requirement_id")
        _require(run_id in by_id and (run_id, requirement_id) not in decisions)
        opinions.check(value, by_id[run_id], requirement_id)
        decisions[(run_id, requirement_id)] = value
    risk_rows, unknown_runs = [], []
    for run_id, value in sorted(by_id.items()):
        if value["result"] is None:
            unknown_runs.append(run_id)
            continue
        for row in value["result"]["manifest"]["matrix"]:
            if row["rule_kind"] not in CORE_KINDS or row["verdict"] not in {
                "violated",
                "not_found",
                "unable_to_judge",
            }:
                continue
            opinion = decisions.get((run_id, row["requirement_id"]))
            risk_rows.append(
                {
                    "kind": "package_core_requirement",
                    "state": "unknown" if row["verdict"] == "unable_to_judge" else "blocked",
                    "scope": deepcopy(value["scope"]),
                    "run_id": run_id,
                    "frozen_input_id": value["frozen_input_id"],
                    "execution_input_id": value["execution_input_id"],
                    "result_digest": value["result"]["digest"],
                    "row_digest": digest(row),
                    "requirement_id": row["requirement_id"],
                    "rule_digest": row["rule_digest"],
                    "rule_kind": row["rule_kind"],
                    "verdict": row["verdict"],
                    "statement": row["statement"],
                    "human_decision": None
                    if opinion is None
                    else {
                        "id": opinion["manifest"]["id"],
                        "digest": opinion["digest"],
                        "state": opinion["manifest"]["state"],
                        "reason": opinion["manifest"]["reason"],
                    },
                    "resolution": "no_verified_package_recheck_resolution",
                }
            )
    seen = set()
    for row in sorted(legacy, key=lambda item: item.get("origin_id", "")):
        _require(_valid(LEGACY_FINDING, row), "INVALID", 422)
        _require(row["bid_id"] == bid and row["origin_id"] not in seen)
        _require(row["severity"] == "critical" or row["rule_kind"] in CORE_KINDS)
        _require(row["rule_kind"] is None or row["rule_id"] is not None)
        seen.add(row["origin_id"])
        risk_rows.append(
            {
                "kind": "legacy_finding",
                "state": "blocked",
                "finding": deepcopy(row),
                "finding_digest": digest(row),
                "resolution": "no_verified_recheck_resolution",
            }
        )
    blocked = sum(row["state"] == "blocked" for row in risk_rows)
    unknown = sum(row["state"] == "unknown" for row in risk_rows)
    codes = []
    if blocked:
        codes.append("KNOWN_BLOCKING_RISKS_UNRESOLVED")
    if unknown:
        codes.append("HISTORICAL_CORE_JUDGMENTS_UNKNOWN")
    if not available:
        codes.append("RISK_HISTORY_NOT_OBSERVED")
    if not complete:
        codes.append("RISK_HISTORY_INCOMPLETE")
    if missing_selected:
        codes.append("SELECTED_RUN_MISSING_FROM_HISTORY")
    if unknown_runs:
        codes.append("HISTORICAL_RUN_RESULT_UNAVAILABLE")
    return {
        "state": _state(blocked, unknown or not complete or unknown_runs),
        "codes": sorted(codes),
        "scope": "whole_bid_known_history",
        "history_digest": digest(history) if available else None,
        "history_complete": complete,
        "runs_read": len(by_id),
        "result_rows_read": row_count,
        "unknown_run_ids": unknown_runs,
        "blocked_count": blocked,
        "unknown_count": unknown,
        "risks": risk_rows,
    }


def validate_view(value):
    """Read a recorded observation under its recorded policy, never issue a permit."""
    _bounded(value)
    _require(_valid(SCHEMA, value), "INVALID", 422)
    _require(digest(value["manifest"]) == value["digest"])
    return deepcopy(value)


def _assess(
    selection: dict[str, Any],
    *,
    observed_at: str,
    current=None,
    run=None,
    inventory_proof=None,
    rule_decisions=(),
    risk_history=None,
    original_verification="not_performed",
):
    """Observe four independent conditions for one explicit immutable package.

    Native current decisions and whole-bid history must come from the repository;
    omission is unknown. ``original_verification`` cannot be a bare success claim.
    Actual byte IO and its receipt belong to the submission service, outside this
    metadata observer. Existing scope reviews cannot establish semantic completeness.
    """
    _require(type(rule_decisions) in {tuple, list}, "INVALID", 422)
    _bounded(
        {
            "selection": selection,
            "current": current,
            "run": run,
            "inventory_proof": inventory_proof,
            "rule_decisions": list(rule_decisions),
            "risk_history": risk_history,
        }
    )
    _require(
        _valid(TIME, observed_at) and _valid(ORIGINAL_STATES, original_verification), "INVALID", 422
    )
    rows = _selection(selection)
    _selected_run(selection, run, rows)
    _proof(selection, inventory_proof, run, rows)
    tm = selection["target"]["manifest"]
    gates = {
        "current_input": _current(
            selection, current, datetime.fromisoformat(observed_at), original_verification, run
        ),
        "core_coverage": _coverage(selection, rows, run, inventory_proof),
        "mandatory_confirmation": _confirmation(selection, rows, rule_decisions),
        "known_blocking_risks": _history(tm["scope"]["bid_id"], risk_history, run),
    }
    authority, inventory, coverage = (
        selection[key] for key in ("authority", "inventory", "coverage")
    )
    manifest = {
        "version": VERSION,
        "kind": "current_package_submission_observation",
        "subject": {
            "kind": "bid_package",
            "bid_id": tm["scope"]["bid_id"],
            "package_id": tm["package_id"],
            "revision_id": tm["revision_id"],
            "package_digest": selection["target"]["digest"],
            "identity_digest": selection["target"]["identity"]["digest"],
        },
        "selection": {
            "digest": digest(selection),
            "authority_revision_id": authority["manifest"]["revision_id"] if authority else None,
            "authority_digest": authority["digest"] if authority else None,
            "inventory_id": inventory["manifest"]["id"] if inventory else None,
            "inventory_digest": inventory["digest"] if inventory else None,
            "coverage_attempt_id": coverage["manifest"]["id"] if coverage else None,
            "coverage_digest": coverage["digest"] if coverage else None,
            "run_id": run["id"] if run else None,
            "result_digest": run["result"]["digest"] if run and run["result"] else None,
        },
        "checked_at": observed_at,
        "policy_digest": policy_identity()["digest"],
        "gates": gates,
        "state": "blocked"
        if any(card["state"] == "blocked" for card in gates.values())
        else "unknown",
        "allowed": False,
        "inventory_complete": False,
        "quality_status": "not_measured",
        "formal_scoring_eligible": False,
        "submission_eligible": False,
        "publication_authorized": False,
        "platform_submission_verified": False,
        "limitations": [
            "INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED",
            "PACKAGE_REVIEW_QUALITY_NOT_MEASURED",
            "HUMAN_OPINION_IS_NOT_RECHECK_RESOLUTION",
            "METADATA_OBSERVATION_IS_NOT_ORIGINAL_BYTE_VERIFICATION",
            "REGISTRATION_IS_NOT_PLATFORM_SUBMISSION",
        ],
    }
    return validate_view({"manifest": manifest, "digest": digest(manifest)})


def assess(
    selection: dict[str, Any],
    *,
    observed_at: str,
    current=None,
    run=None,
    inventory_proof=None,
    rule_decisions=(),
    risk_history=None,
    original_verification="not_performed",
):
    """Observe exact selected records; malformed or oversized input is never truncated."""
    try:
        return _assess(
            selection,
            observed_at=observed_at,
            current=current,
            run=run,
            inventory_proof=inventory_proof,
            rule_decisions=rule_decisions,
            risk_history=risk_history,
            original_verification=original_verification,
        )
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError) as error:
        raise DomainError(
            "PACKAGE_SUBMISSION_GATE_INVALID", "整包提交观察记录的结构或原记录身份无效", 422
        ) from error
