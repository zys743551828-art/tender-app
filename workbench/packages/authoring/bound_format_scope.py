"""Narrow optional scope for human-bound numeric project layout on saved drafts."""

from copy import deepcopy
from uuid import UUID

from packages.authoring import format_bindings
from packages.domain.runtime import DomainError, sha
from packages.rag.indexing import parse_source_id

INPUT_METHOD = "retained_numeric_project_format/1"
EXECUTION_METHOD = "retained_numeric_project_format_projection/1"
DDL = "packages/contracts/sql/authoring-bound-format-scope.sql"
HELPER = "packages/authoring/bound_format_scope.py"
FIELDS = frozenset(
    (
        "font_size_halfpoints",
        "paragraph_after_twips",
        "margin_top_twips",
        "margin_right_twips",
        "margin_bottom_twips",
        "margin_left_twips",
    )
)


def present(structure):
    metadata = (structure or {}).get("metadata", {})
    return bool(metadata.get("format_bindings") or metadata.get("format_binding_manifest"))


def installed(c):
    return bool(
        c.execute(
            """SELECT count(*)=2 AND
                    to_regprocedure('design.authoring_bound_format_assert_current(uuid)') IS NOT NULL AS ready FROM pg_catalog.pg_trigger
               WHERE tgenabled IN ('O','A') AND NOT tgisinternal AND (
                 (tgrelid=to_regclass('design.authoring_package_inputs')
                   AND tgname='authoring_bound_format_input')
                 OR (tgrelid=to_regclass('design.authoring_package_job_bindings')
                   AND tgname='authoring_bound_format_job'))"""
        ).fetchone()["ready"]
    )


def supported(structure, *, saved_plans=False):
    metadata = (structure or {}).get("metadata", {})
    bindings = metadata.get("format_bindings")
    if (
        not structure
        or bool(structure["plans"]) != saved_plans
        or metadata.get("word_import_sources")
        or not isinstance(bindings, list)
        or not 0 < len(bindings) <= len(FIELDS)
        or not all(
            isinstance(row, dict)
            and isinstance(row.get("field"), str)
            and row["field"] in FIELDS
            and type(row.get("value")) is int
            for row in bindings
        )
    ):
        return False
    return len({row["field"] for row in bindings}) == len(bindings)


def ready(c, structure, *, saved_plans=False):
    return supported(structure, saved_plans=saved_plans) and installed(c)


def _claim(ref):
    return (
        ref["source_id"],
        ref["source_revision"],
        ref["document_version_id"],
        ref["evidence_id"],
    )


def check(c, bid, structure, documents, closure, inventory, *, saved_plans=False):
    if not ready(c, structure, saved_plans=saved_plans):
        raise DomainError(
            "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED",
            "此固定编写暂不支持该项目版式范围或缺少可选约束；原稿和版式保持不变",
            409,
        )
    report = format_bindings.assert_snapshot(c, bid, structure, lock_sources=False)
    revisions = {row["id"]: row["revision"] for row in closure if row["id"] == row["source_id"]}
    claims = {
        (source, revisions[source], doc["document_version_id"], block["id"])
        for doc in documents
        if doc["package_role"] == "authority"
        for source in [str(parse_source_id(UUID(doc["parse_id"])))]
        if source in revisions
        for block in doc["blocks"]
    }
    requirements = {row["rule_id"]: row for row in inventory["record"]["manifest"]["requirements"]}
    for binding in report["binding_manifest"]:
        rule_id, basis = binding["rule_id"], binding["basis"]
        requirement = requirements.get(rule_id)
        evidence_basis = basis["evidence_basis"]
        refs = evidence_basis["references"]
        source_ids = {ref["source_id"] for ref in refs}
        if (
            not requirement
            or requirement["decision_id"] != basis["decision_id"]
            or requirement["decision_snapshot"]["object_id"] != rule_id
            or not refs
            or {ref["evidence_id"] for ref in refs}
            != set(requirement["rule_snapshot"]["evidence_ids"])
            or len(refs) != len({ref["evidence_id"] for ref in refs})
            or not all(_claim(ref) in claims for ref in refs)
            or not all(ref in refs for ref in binding["source_refs"])
            or evidence_basis["source_closure_digest"]
            != sha([row for row in closure if row["source_id"] in source_ids])
        ):
            raise DomainError(
                "AUTHORING_PACKAGE_BOUND_FORMAT_OUTSIDE_SELECTION",
                "有据版式必须使用本次已选依据包及当前要求的原确认；请核对原页和规则",
                409,
            )


def model_projection(frozen):
    """Layout is a renderer decision; no private styling metadata enters the prompt."""
    projected = deepcopy(frozen)
    target = projected["context"]["target"]
    target["snapshot_manifest"].pop("authoring_structure")
    target["snapshot"].pop("authoring_structure")
    return projected
