"""Narrow optional v1 saved-plan scope for native exact chapter authoring.

Plans remain manual work. Only authority-backed linkage may be projected to the
provider, and adopting text does not revise, approve, or replace a plan.
"""

from copy import deepcopy
from uuid import UUID

from packages.authoring import format_bindings, planning
from packages.authoring.content import empty_content
from packages.authoring.repository import assert_sources
from packages.domain.runtime import DomainError, clean
from packages.rag.indexing import parse_source_id

INPUT_METHOD = "retained_saved_plan_scope/1"
EXECUTION_METHOD = "retained_saved_plan_projection/1"
DDL = "packages/contracts/sql/authoring-saved-plan-scope.sql"
HELPER = "packages/authoring/saved_chapter_plans.py"


def installed(c):
    return bool(
        c.execute(
            """SELECT count(*)=2 AND coalesce(has_function_privilege(
                    to_regprocedure('design.authoring_saved_plan_assert_current(uuid)'),'EXECUTE'),
                    false) AS ready FROM pg_catalog.pg_trigger
               WHERE tgenabled IN ('O','A') AND NOT tgisinternal AND (
                 (tgrelid=to_regclass('design.authoring_package_inputs')
                   AND tgname='authoring_saved_plan_scope_input')
                 OR (tgrelid=to_regclass('design.authoring_package_job_bindings')
                   AND tgname='authoring_saved_plan_scope_job'))"""
        ).fetchone()["ready"]
    )


def extension(target):
    manifest = target["snapshot_manifest"]
    if not isinstance(manifest, dict):
        raise ValueError("Invalid frozen draft manifest")
    value = manifest.get("authoring_structure")
    if value is not None and not isinstance(value, dict):
        raise ValueError("Invalid frozen draft structure")
    return value


def retained(target):
    return bool((extension(target) or {}).get("plans"))


def selected_plan(structure, section_id):
    return next(
        (plan for plan in structure["plans"].values() if plan["section_id"] == section_id),
        None,
    )


def stale_target(structure, section_id):
    plan = selected_plan(structure, section_id)
    if plan is None:
        return False
    node = next(n for n in structure["nodes"] if n["section_id"] == section_id)
    return plan["base_section_revision"] != node["section_revision"]


def _fail(condition, code, message):
    if not condition:
        raise DomainError(code, message, 409)


def check(c, bid, draft, section, structure, documents, closure, inventory):
    _fail(
        installed(c),
        "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED",
        "本工作台未安装固定编写的章节计划核验；已存计划和正文保持不变",
    )
    _fail(
        not stale_target(structure, section),
        "AUTHORING_SAVED_PLAN_TARGET_STALE",
        "本章计划仍对照旧正文；已保留原计划。请核对当前正文及可用编辑方式",
    )
    frozen = structure["plans"]
    saved = {
        str(row["id"]): clean(row)
        for row in c.execute(
            """SELECT * FROM design.authoring_plan_versions
               WHERE bid_id=%s AND draft_id=%s AND id=ANY(%s::uuid[])""",
            (bid, draft, list(frozen)),
        ).fetchall()
    }
    _fail(saved == frozen, "AUTHORING_SAVED_PLAN_UNVERIFIED", "计划的冻结版本与原记录不一致")
    heads = {row["id"]: row["revision"] for row in closure if row["source_id"] == row["id"]}
    allowed: set[tuple[str, int, str, str]] = set()
    for doc in documents:
        if doc["package_role"] != "authority":
            continue
        source = str(parse_source_id(UUID(doc["parse_id"])))
        if source in heads:
            allowed.update(
                (source, heads[source], doc["document_version_id"], block["id"])
                for block in doc["blocks"]
            )
    rules = {rule["rule_id"] for rule in inventory["record"]["manifest"]["requirements"]}
    for plan in frozen.values():
        payload = plan["payload"]
        _fail(
            set(payload["rule_ids"]) <= rules,
            "AUTHORING_SAVED_PLAN_RULE_OUTSIDE_SELECTION",
            "章节计划包含不在本次已固定要求清单中的条款；请保留计划并重新核对",
        )
        _fail(
            all(
                (
                    ref["source_id"],
                    ref["source_revision"],
                    ref["document_version_id"],
                    ref["evidence_id"],
                )
                in allowed
                for ref in payload["source_refs"]
            ),
            "AUTHORING_SAVED_PLAN_SOURCE_OUTSIDE_SELECTION",
            "章节计划包含不在本次已选依据包内、或版本已变的原页；请保留计划并重新核对",
        )
        content = empty_content("固定章节计划依据", 0)
        content["attrs"]["rule_ids"] = payload["rule_ids"]
        content["attrs"]["source_refs"] = payload["source_refs"]
        # B1's final transaction already holds the project, draft and complete
        # selected source-graph/ancestor locks. Read-only snapshots share this
        # predicate without taking any write lock; B2 matches the same graph.
        assert_sources(c, bid, content, lock_sources=False)
        planning.assert_budget(c, bid, plan, lock_sources=False)
    format_bindings.assert_snapshot(c, bid, structure, lock_sources=False)


def model_projection(frozen):
    """Both snapshot copies are private; send approved linkage, not plan text."""
    projected = deepcopy(frozen)
    target = projected["context"]["target"]
    structure = target["snapshot_manifest"].pop("authoring_structure")
    target["snapshot"].pop("authoring_structure")
    plan = selected_plan(structure, frozen["target"]["section_id"])
    if plan is not None:
        projected["saved_chapter_plan_links"] = {
            "requirement_ids": plan["payload"]["rule_ids"],
            "authority_evidence_ids": [
                ref["evidence_id"] for ref in plan["payload"]["source_refs"]
            ],
        }
    return projected
