"""Deployment/runtime SELECT dependencies; neither grant nor use an owner fallback."""

from packages.domain.runtime import DomainError

COMMON = (
    "design.bids",
    "design.bid_profiles",
    "design.bidders",
    "design.bid_rounds",
    "design.engineering_projects",
    "design.engineering_lots",
    "design.audit_entries",
    "design.bid_packages",
    "design.bid_package_revisions",
    "design.bid_package_heads",
    "design.bid_package_members",
    "design.bid_package_parts",
    "retrieval.source_nodes",
    "retrieval.source_heads",
    "retrieval.source_ancestors",
)
RUN = (
    "design.bid_package_review_runs",
    "design.bid_package_review_results",
    "design.operations",
    "design.step_receipts",
    "design.effect_receipts",
    "design.bid_package_review_inputs",
    "design.bid_package_execution_inputs",
    "design.bid_package_dependency_plans",
    "design.bid_package_dependency_plan_command_receipts",
    "design.bid_package_requirement_inventories",
    "design.bid_package_requirement_heads",
    "design.bid_package_requirement_extraction_runs",
    "design.bid_package_coverage_attempts",
    "design.bid_package_coverage_results",
    "design.bid_package_fact_scopes",
    "design.bid_package_review_decisions",
    "design.bid_package_review_decision_heads",
    "design.fact_heads",
    "design.fact_sets",
    "design.fact_items",
    "design.decisions",
    "design.decision_heads",
    "design.evidence_blocks",
    "design.parse_runs",
    "design.pages",
)
SUBMISSION = (
    "design.submission_records",
    "design.submission_heads",
    "design.bid_package_submission_bindings",
)
BUILD = (
    "design.builds",
    "design.build_inputs",
    "design.draft_snapshots",
    "design.draft_snapshot_sections",
    "design.section_revisions",
    "design.operations",
    "design.build_outputs",
    "design.document_versions",
    "design.document_files",
    "design.document_file_versions",
    "design.blobs",
    "design.document_relations",
    "design.commands",
    "retrieval.lineage_edges",
)
FUNCTIONS = (
    "design.identity_snapshot_v2(uuid)",
    "design.bid_requirement_source_snapshot(uuid,uuid)",
)


def dependencies(kind):
    return sorted(
        set(
            COMMON
            + (BUILD if kind == "relations" else RUN + (SUBMISSION if kind == "submission" else ()))
        )
    )


def inspect(c, kind):
    role = c.execute(
        """SELECT r.rolcanlogin,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolbypassrls,
        pg_has_role(current_user,'tender_api','MEMBER') AS api_capability,
        EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
          WHERE n.nspname IN ('design','retrieval') AND pg_has_role(current_user,t.relowner,'MEMBER')) AS owns,
        current_setting('transaction_isolation') AS isolation,
        current_setting('transaction_read_only') AS read_only
        FROM pg_roles r WHERE r.rolname=current_user"""
    ).fetchone()
    tables = c.execute(
        """SELECT name,to_regclass(name) IS NOT NULL AS installed,
        CASE WHEN to_regclass(name) IS NULL THEN false
          ELSE has_table_privilege(current_user,name,'SELECT') END AS readable
        FROM unnest(%s::text[]) AS name ORDER BY name""",
        (dependencies(kind),),
    ).fetchall()
    functions = c.execute(
        """SELECT name,to_regprocedure(name) IS NOT NULL AS installed,
        CASE WHEN to_regprocedure(name) IS NULL THEN false
          ELSE has_function_privilege(current_user,name,'EXECUTE') END AS readable
        FROM unnest(%s::text[]) AS name ORDER BY name""",
        (list(FUNCTIONS),),
    ).fetchall()
    return {"role": dict(role), "tables": list(tables), "functions": list(functions)}


def require(c, kind):
    result = inspect(c, kind)
    role = result["role"]
    if (
        not role["rolcanlogin"]
        or not role["api_capability"]
        or any(
            role[key]
            for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "owns")
        )
    ):
        raise DomainError(
            "WORK_CONTEXT_ROLE_REJECTED", "工作上下文只能由非所有者 API 运行账号读取", 403
        )
    if role["isolation"] != "repeatable read" or role["read_only"] != "on":
        raise DomainError(
            "WORK_CONTEXT_READ_SNAPSHOT_REQUIRED", "工作上下文需要同一只读重复读取事务", 500
        )
    if not all(
        row["installed"] and row["readable"]
        for key in ("tables", "functions")
        for row in result[key]
    ):
        raise DomainError(
            "WORK_CONTEXT_UNAVAILABLE", "工作上下文所需只读存储或权限尚未完整安装", 503
        )
    return result
