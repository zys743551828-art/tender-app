"""Assess explicit per-requirement fact dependencies, never semantic completeness or dispatch.

Inputs are already consumed immutable packets. Human annotations describe intended
dependencies; they cannot certify extraction quality, fact authority or compliance.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain import package_fact_usage as fact_usage
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import ROOT, sha

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/package-input-dependencies.schema.json"
    ).read_text("utf-8")
)
POLICY_FILES = (
    "packages/domain/package_input_dependencies.py",
    "packages/contracts/schemas/package-input-dependencies.schema.json",
    "packages/domain/package_fact_usage.py",
    "packages/domain/review_identity.py",
    "packages/domain/package_rule_corrections.py",
    "packages/contracts/package_rule_corrections_api.py",
    "packages/contracts/bid_package_requirements_api.py",
)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _validate(name, value):
    _require(
        Draft202012Validator(
            {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
        ).is_valid(value),
        "input_dependency_contract",
    )


@dataclass(frozen=True, slots=True)
class InputDependencyAssessment:
    digest: str
    _text: str = field(repr=False)

    def view(self):
        return {"manifest": json.loads(self._text), "digest": self.digest}


def assess(frozen, prepared, usage, request):
    _validate("Request", request)
    fact_usage.verify(usage.view(), prepared)
    um = usage.view()["manifest"]
    _require(request["usage_digest"] == usage.digest, "input_dependency_usage_changed")
    fm = frozen.view()["manifest"]
    root = frozen.evidence()
    selection = root["selection"]
    inventory = selection["inventory"]
    inv = inventory["manifest"]
    derived = inv.get("version") == "bid-package-requirements/3"
    if derived:
        from packages.domain import package_rule_corrections as corrections

        corrections.verify_inventory_header(inventory)
    binding = prepared.view()["manifest"]["identity"]["binding"]
    _require(
        prepared.frozen_id == fm["id"] == um["prepared"]["frozen_input_id"]
        and tuple(fm[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id"))
        == prepared.scope
        and binding["frozen_digest"] == frozen.digest
        and fm["input_digest"] == binding["input_digest"] == digest(selection)
        and inv["id"] == prepared.scope[3]
        and inventory["digest"] == digest(inv),
        "input_dependency_frozen_binding",
    )
    rows = inv["requirements"]
    by_id = {row["rule_id"]: row for row in rows}
    _require(len(by_id) == len(rows), "input_dependency_duplicate_requirement")
    facts = prepared.snapshot()["context"]["manifest"]["facts"]["items"]
    pool = {item["fact"]["id"] for item in facts}
    chosen = {item["fact_id"] for item in um["selected"]}
    authority = {
        block["id"]
        for doc in root["documents"]
        if doc["package_role"] == "authority"
        for block in doc["blocks"]
    }
    declarations = {}
    for declaration in request["dependencies"]:
        rid = declaration["requirement_id"]
        _require(rid in by_id and rid not in declarations, "input_dependency_requirement_scope")
        row = by_id[rid]
        _require(
            declaration["requirement_digest"] == row["requirement_digest"],
            "input_dependency_requirement_changed",
        )
        _require(set(declaration["fact_ids"]) <= pool, "input_dependency_fact_not_prepared")
        _require(
            declaration["state"] == "required" or not declaration["fact_ids"],
            "input_dependency_nonrequired_facts",
        )
        _require(
            set(declaration["evidence_ids"])
            <= authority.intersection(row["rule_snapshot"]["evidence_ids"]),
            "input_dependency_rule_evidence",
        )
        declarations[rid] = {
            **declaration,
            "fact_ids": sorted(declaration["fact_ids"]),
            "evidence_ids": sorted(declaration["evidence_ids"]),
        }
    coverage = selection["coverage"]
    states = {}
    if coverage:
        cm = coverage["manifest"]
        _require(
            coverage["digest"] == digest(cm) and cm["inventory_digest"] == inventory["digest"],
            "input_dependency_coverage_changed",
        )
        states = cm["assessment"]["requirement_states"]
    output = []
    for rid, row in sorted(by_id.items()):
        _require(
            row["requirement_digest"] == digest(row["requirement"])
            and row["rule_digest"] == digest(row["rule_snapshot"])
            and row["requirement"]["requirement_id"] == rid
            and row["rule_snapshot"]["id"] == rid,
            "input_dependency_projection_corrupt",
        )
        declaration = declarations.get(rid)
        missing = sorted(set(declaration["fact_ids"]) - chosen) if declaration else []
        if declaration is None or declaration["state"] == "unknown" or not row["source_bound"]:
            status = "unknown"
        elif declaration["state"] == "not_needed":
            status = "not_used"
        elif not declaration["fact_ids"] or missing:
            status = "missing"
        else:
            status = "selected_unvalidated"
        output.append(
            {
                "requirement_id": rid,
                "requirement_digest": row["requirement_digest"],
                "declaration": declaration,
                "fact_status": status,
                "unselected_fact_ids": missing,
                "coverage_state": states.get(rid, "not_provided"),
                "source_bound": row["source_bound"],
                "applicability": row["requirement"]["applicability"],
            }
        )
        if derived:
            output[-1]["rule_status"] = corrections.rule_state(row["rule_snapshot"])
    statuses = {row["fact_status"] for row in output}
    overall = (
        next(
            (
                value
                for value in ("missing", "unknown", "selected_unvalidated")
                if value in statuses
            ),
            "not_used",
        )
        if output
        else "unknown"
    )
    manifest = {
        "policy_digest": digest(
            {
                "version": "package-input-dependency-policy/1",
                "sources": {name: sha((ROOT / name).read_bytes()) for name in POLICY_FILES},
            }
        ),
        "version": "package-input-dependencies/1",
        "kind": "input_dependency_assessment",
        "purpose": "prebid_compliance",
        "prepared": um["prepared"],
        "frozen_digest": frozen.digest,
        "inventory_digest": inventory["digest"],
        "usage_digest": usage.digest,
        "selected_fact_count": len(chosen),
        "requirement_count": len(rows),
        "dependency_review_status": "declared"
        if output
        and all(
            x["declaration"] is not None and x["declaration"]["state"] != "unknown" for x in output
        )
        else "incomplete",
        "required_facts_assessment": overall,
        "requirements": output,
        "inventory_status": "range_submitted_quality_unmeasured"
        if inv["extraction_binding"] == "exact_frozen_input_result"
        else "unproven",
        "declaration_kind": "human_dependency_annotation",
        "inventory_complete": False,
        "original_bytes_verified": False,
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    if derived:
        manifest.update(
            version="package-input-dependencies/2",
            inventory_status="human_derivation_range_quality_unmeasured",
            rule_state_counts=corrections.rule_counts([row["rule_snapshot"] for row in rows]),
        )
    _validate("Manifest", manifest)
    return InputDependencyAssessment(digest(manifest), canonical(manifest).decode("utf-8"))


def verify(record, frozen, prepared, usage):
    _validate("View", record)
    m = record["manifest"]
    rebuilt = assess(
        frozen,
        prepared,
        usage,
        {
            "purpose": m["purpose"],
            "usage_digest": m["usage_digest"],
            "dependencies": [
                row["declaration"] for row in m["requirements"] if row["declaration"] is not None
            ],
        },
    )
    _require(rebuilt.view() == record, "input_dependency_record_changed")
    return rebuilt
