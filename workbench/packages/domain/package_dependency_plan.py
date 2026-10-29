"""Immutable human dependency plans; historical integrity is separate from new assessment."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain import package_fact_usage as facts
from packages.domain import package_input_dependencies as dependencies
from packages.domain.review_identity import canonical, digest

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/package-dependency-plan.schema.json"
    ).read_text("utf-8")
)


def validate(name, value):
    if not Draft202012Validator(
        {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
    ).is_valid(value):
        raise ValueError("dependency_plan_contract")


def _require(condition):
    if not condition:
        raise ValueError("dependency_plan_binding")


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    digest: str
    _text: str = field(repr=False)

    def view(self):
        return {"manifest": json.loads(self._text), "digest": self.digest}


def build(frozen, prepared, usage, assessment, *, record_id, actor_id, command_id, saved_at, body):
    validate("Save", body)
    _require(body["execution_input_digest"] == prepared.digest)
    _require(body["assessment_digest"] == assessment.digest)
    _require(
        facts.select(prepared, {"purpose": body["purpose"], "fact_ids": body["fact_ids"]}).view()
        == usage.view()
    )
    requested = dependencies.assess(
        frozen,
        prepared,
        usage,
        {
            "purpose": body["purpose"],
            "usage_digest": usage.digest,
            "dependencies": body["dependencies"],
        },
    )
    _require(requested.view() == assessment.view())
    manifest = {
        "version": "package-dependency-plan/1",
        "kind": "human_dependency_plan",
        "id": record_id,
        "actor_id": actor_id,
        "command_id": command_id,
        "saved_at": saved_at,
        "reason": body["reason"],
        "request_digest": digest({"body": body, "if_match": None}),
        "prepared": usage.view()["manifest"]["prepared"],
        "assessment": assessment.view(),
        "usage": usage.view(),
        "inventory_complete": False,
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    return read({"manifest": manifest, "digest": digest(manifest)}, frozen, prepared)


def read(record, frozen, prepared):
    """Read a trusted saved receipt without invoking today's dependency policy or current heads.

    The repository additionally requires the exact immutable command ACK and audit.
    This function checks original binding/integrity, never renews qualification.
    """
    validate("View", record)
    m = record["manifest"]
    _require(record["digest"] == digest(m))
    usage = facts.verify(m["usage"], prepared)
    um = usage.view()["manifest"]
    assessment = m["assessment"]
    am = assessment["manifest"]
    _require(assessment["digest"] == digest(am))
    _require(m["prepared"] == um["prepared"] == am["prepared"])
    _require(am["usage_digest"] == usage.digest)
    _require(am["selected_fact_count"] == len(um["selected"]))
    _require(am["frozen_digest"] == frozen.digest)
    binding = prepared.view()["manifest"]["identity"]["binding"]
    _require(binding["frozen_digest"] == frozen.digest)
    inventory = frozen.evidence()["selection"]["inventory"]
    _require(am["inventory_digest"] == inventory["digest"])
    _require(am["requirement_count"] == len(inventory["manifest"]["requirements"]))
    return DependencyPlan(record["digest"], canonical(m).decode("utf-8"))
