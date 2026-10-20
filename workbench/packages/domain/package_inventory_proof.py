"""Frozen authority scope and extraction receipts; never semantic completeness or admission."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.bid_packages import safe_integer
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import ROOT, sha

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/package-inventory-proof.schema.json"
    ).read_text("utf-8")
)
POLICY_FILES = (
    "packages/domain/package_inventory_proof.py",
    "packages/domain/bid_package_inventory_proof.py",
    "packages/contracts/schemas/package-inventory-proof.schema.json",
    "packages/domain/review_identity.py",
)


def _require(condition):
    if not condition:
        raise ValueError("inventory_proof_binding")


def _page_count(parts, total):
    _require(safe_integer(total, 1))
    end = count = 0
    for first, last in sorted((p["first_page"], p["last_page"]) for p in parts):
        _require(safe_integer(first, 1) and safe_integer(last, first) and last <= total)
        if last > end:
            count += last - max(first, end + 1) + 1
            end = last
    return count


@dataclass(frozen=True, slots=True)
class InventoryProof:
    digest: str
    _text: str = field(repr=False)

    def view(self):
        return {"manifest": json.loads(self._text), "digest": self.digest}


def _receipt_matches(receipt, frozen, inventory, expected_members, expected_parts):
    run, operation, effect = (receipt[k] for k in ("run", "operation", "effect"))
    im, result = run["input_manifest"], run["result"]
    authority = frozen["authority"]
    am = authority["manifest"]
    _require(
        run["id"] == inventory["extraction_result_id"]
        and run["bid_id"] == frozen["bid_id"]
        and run["authority_revision_id"] == am["revision_id"]
        and run["authority_digest"] == authority["digest"]
        and run["rule_set_id"] == inventory["rule_set_id"]
        and run["input_digest"] == inventory["extraction_input_digest"] == digest(im)
        and run["result_digest"] == inventory["extraction_result_digest"] == digest(result)
        and im["identity_version"] == "package-rule-extraction-input/1"
        and im["bid_id"] == frozen["bid_id"]
        and im["scope"] == am["scope"]
        and im["authority_package"]
        == {
            "package_id": am["package_id"],
            "revision_id": am["revision_id"],
            "digest": authority["digest"],
            "identity_digest": authority["identity"]["digest"],
            "manifest": am,
            "identity_snapshot": authority["identity"],
        }
        and im["members"] == expected_members
        and im["extraction_scope"]
        == {
            "policy": "all_declared_package_parts",
            "coverage": "all_physical_pages",
            "parts": expected_parts,
        }
        and result["input_digest"] == run["input_digest"]
        and result["rule_set_id"] == inventory["rule_set_id"]
        and result["authority_revision_id"] == am["revision_id"]
        and result["authority_digest"] == authority["digest"]
        and result["method_digest"] == im["method_digest"] == digest(im["method_profile"])
        and result["range_status"]
        == inventory["extraction_range_status"]
        == "all_frozen_evidence_submitted"
        and result["extraction_coverage"] == inventory["extraction_coverage"]
        and result["quality_status"] == inventory["extraction_quality_status"] == "not_measured"
        and operation is not None
        and effect is not None
        and operation["id"] == run["operation_id"]
        and operation["bid_id"] == frozen["bid_id"]
        and operation["input_digest"] == run["operation_input_digest"]
        and operation["handler_version"] == "prepare/1"
        and operation["state"] == "succeeded"
        and effect["result_ref"] == run["rule_set_id"]
        and effect["method_digest"] == result["method_digest"]
        and effect["extraction_input_digest"] == run["input_digest"]
    )
    return result


def assess(original, prepared, receipt=None):
    fm = original.view()["manifest"]
    root = original.evidence()
    selection = root["selection"]
    inv = selection["inventory"]
    im = inv["manifest"]
    authority = selection["authority"]
    am = authority["manifest"]
    b = prepared.view()["manifest"]["identity"]["binding"]
    _require(
        tuple(fm[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id"))
        == prepared.scope
        and prepared.frozen_id == fm["id"] == b["frozen_input_id"]
        and b["frozen_digest"] == original.digest
        and b["input_digest"] == fm["input_digest"] == digest(selection)
        and im["id"] == prepared.scope[3]
        and inv["digest"] == digest(im)
        and authority["digest"] == digest(am)
        and im["authority_revision_id"] == am["revision_id"]
        and im["authority_digest"] == authority["digest"]
    )
    docs = {d["member_id"]: d for d in root["documents"] if d["package_role"] == "authority"}
    _require(len(docs) == len(am["members"]))
    output: list[dict[str, Any]] = []
    expected_members: list[dict[str, Any]] = []
    expected_parts: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for member in am["members"]:
        doc = docs[member["member_id"]]
        parse = member["parse"]
        _require(
            parse["status"] == "frozen"
            and doc["document_version_id"] == member["document_version_id"]
            and doc["parse_id"] == parse["parse_run_id"]
            and doc["digest"] == member["file_digest"]
            and doc["parser_digest"] == parse["parser_digest"]
            and doc["config_digest"] == parse["config_digest"]
            and doc["page_count"] == member["page_count"]
        )
        count = _page_count(member["parts"], doc["page_count"])
        output.append(
            {
                "member_id": member["member_id"],
                "document_version_id": member["document_version_id"],
                "parse_run_id": parse["parse_run_id"],
                "page_count": doc["page_count"],
                "declared_page_count": count,
                "all_pages_declared": count == doc["page_count"],
                "evidence_count": len(doc["blocks"]),
            }
        )
        evidence_ids.update(block["id"] for block in doc["blocks"])
        expected_members.append(
            {
                "member_id": member["member_id"],
                "document_version_id": member["document_version_id"],
                "file_digest": member["file_digest"],
                "parse_run_id": parse["parse_run_id"],
                "parser_digest": parse["parser_digest"],
                "config_digest": parse["config_digest"],
                "evidence_digest": parse["evidence_digest"],
                "page_count": member["page_count"],
                "parts": member["parts"],
            }
        )
        expected_parts.extend(
            {
                "member_id": member["member_id"],
                "document_version_id": member["document_version_id"],
                "parse_run_id": parse["parse_run_id"],
                "part_id": part["part_id"],
                "first_page": part["first_page"],
                "last_page": part["last_page"],
                "shared_attachment": part["shared_attachment"],
            }
            for part in member["parts"]
        )
    all_pages = bool(output) and all(doc["all_pages_declared"] for doc in output)
    read_digest = digest(sorted(evidence_ids))
    blockers = ["INVENTORY_SEMANTIC_COMPLETENESS_UNMEASURED"]
    rows = im["requirements"]
    _require(len({r["rule_id"] for r in rows}) == len(rows))
    for row in rows:
        _require(
            row["rule_id"] == row["requirement"]["requirement_id"] == row["rule_snapshot"]["id"]
            and row["rule_digest"] == digest(row["rule_snapshot"])
            and row["requirement_digest"] == digest(row["requirement"])
        )
    unbound = sum(
        not row["source_bound"]
        or not row["rule_snapshot"]["evidence_ids"]
        or not set(row["rule_snapshot"]["evidence_ids"]) <= evidence_ids
        for row in rows
    )
    state, coverage, receipt_digest = "not_frozen", "unknown", None
    expected_read_digest = None
    if im["version"] == "bid-package-requirements/2":
        _require(im["extraction_binding"] == "exact_frozen_input_result")
        state = "archive_missing"
        if receipt is not None:
            result = _receipt_matches(receipt, selection, im, expected_members, expected_parts)
            receipt_digest = digest(receipt)
            coverage = result["extraction_coverage"]
            expected_read_digest = result["read_evidence_ids_digest"]
            state = "matched" if expected_read_digest == read_digest else "read_set_mismatch"
    else:
        _require(
            im["version"] == "bid-package-requirements/1"
            and im["extraction_binding"] == "unproven_legacy_rule_set"
            and receipt is None
        )
    if state != "matched":
        blockers.append(
            {
                "not_frozen": "INVENTORY_EXTRACTION_NOT_FROZEN",
                "archive_missing": "INVENTORY_EXTRACTION_ARCHIVE_MISSING",
                "read_set_mismatch": "INVENTORY_READ_EVIDENCE_MISMATCH",
            }[state]
        )
    if not all_pages:
        blockers.append("INVENTORY_DECLARED_PAGE_GAP")
    if not evidence_ids:
        blockers.append("INVENTORY_NO_FROZEN_EVIDENCE")
    if coverage in {"partial", "conflict"}:
        blockers.append("INVENTORY_EXTRACTION_" + coverage.upper())
    if not im["requirements"]:
        blockers.append("INVENTORY_EMPTY_REQUIREMENTS")
    if unbound:
        blockers.append("INVENTORY_UNBOUND_REQUIREMENT")
    manifest = {
        "version": "package-inventory-proof/1",
        "kind": "frozen_inventory_scope_observation",
        "scope": "frozen_authority_parse_blocks_only",
        "prepared": {
            **dict(
                zip(
                    ("bid_id", "package_id", "revision_id", "inventory_id"),
                    prepared.scope,
                    strict=True,
                )
            ),
            "frozen_input_id": prepared.frozen_id,
            "execution_input_id": prepared.input_id,
            "execution_input_digest": prepared.digest,
        },
        "frozen_digest": original.digest,
        "inventory_digest": inv["digest"],
        "authority_revision_id": am["revision_id"],
        "authority_digest": authority["digest"],
        "documents": output,
        "all_declared_pages_bound": all_pages,
        "frozen_evidence_count": len(evidence_ids),
        "frozen_evidence_ids_digest": read_digest,
        "extraction_receipt_state": state,
        "receipt_digest": receipt_digest,
        "recorded_read_evidence_ids_digest": expected_read_digest,
        "extraction_coverage": coverage,
        "extraction_range_proven": state == "matched" and all_pages and bool(evidence_ids),
        "requirement_count": len(im["requirements"]),
        "unbound_requirement_count": unbound,
        "quality_status": "not_measured",
        "inventory_complete": False,
        "original_bytes_verified": False,
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
        "blockers": blockers,
        "policy_digest": digest(
            {
                "version": "package-inventory-proof-policy/1",
                "sources": {name: sha((ROOT / name).read_bytes()) for name in POLICY_FILES},
            }
        ),
    }
    _require(
        Draft202012Validator(
            {"$ref": "#/$defs/Manifest", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
        ).is_valid(manifest)
    )
    return InventoryProof(digest(manifest), canonical(manifest).decode("utf-8"))
