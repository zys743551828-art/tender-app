"""Opt-in orchestration of the retained saved-plan and numeric-format contracts."""

from packages.authoring import bound_format_scope, saved_chapter_plans
from packages.domain.runtime import DomainError

INPUT_METHOD = "retained_plan_and_numeric_format/1"
EXECUTION_METHOD = "retained_plan_and_numeric_format_projection/1"
DDL = "packages/contracts/sql/authoring-combined-plan-format-scope.sql"
HELPER = "packages/authoring/combined_authoring_scope.py"


def installed(c):
    marker = c.execute(
        "SELECT to_regprocedure('design.authoring_combined_scope_installed()') IS NOT NULL AS ready"
    ).fetchone()["ready"]
    return bool(marker and saved_chapter_plans.installed(c) and bound_format_scope.installed(c))


def ready(c, structure):
    if not bound_format_scope.present(structure):
        return True
    if structure["plans"]:
        return bound_format_scope.supported(structure, saved_plans=True) and installed(c)
    return bound_format_scope.ready(c, structure)


def require_schema(c):
    if not installed(c):
        raise DomainError(
            "AUTHORING_PACKAGE_STRUCTURE_BASIS_UNSUPPORTED",
            "同稿同时保留章节计划与项目数字版式需要单独启用联合约束；原稿与依据保持不变",
            409,
        )
