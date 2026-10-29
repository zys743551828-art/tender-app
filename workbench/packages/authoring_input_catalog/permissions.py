"""Existing native SELECT dependencies; no SQL installation, grants, or owner fallback."""

from packages.authoring_input_catalog import policy

COMMON = ("design.bids", "design.bid_profiles")
NODES = (
    "design.drafts",
    "design.sections",
    "design.section_revisions",
    "design.draft_snapshots",
    "design.draft_snapshot_sections",
    "design.authoring_structure_versions",
    "design.authoring_image_assets",
    "design.authoring_image_versions",
    "design.blobs",
)
SETS = ("design.fact_sets", "design.fact_heads", "design.fact_items")
FACTS = SETS + (
    "design.bid_packages",
    "design.bid_package_revisions",
    "design.bid_package_members",
    "design.bid_package_parts",
    "design.bidders",
    "design.bid_rounds",
    "design.engineering_projects",
    "design.engineering_lots",
    "design.decisions",
    "design.decision_heads",
    "design.audit_entries",
    "design.evidence_blocks",
    "design.parse_runs",
    "design.pages",
    "retrieval.source_nodes",
    "retrieval.source_heads",
    "retrieval.source_ancestors",
)


def require(c, kind):
    role = c.execute(
        """SELECT r.rolcanlogin,r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolbypassrls,
        pg_has_role(current_user,'tender_api','MEMBER') AS api_capability,
        EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
          WHERE n.nspname IN ('design','retrieval') AND pg_has_role(current_user,t.relowner,'MEMBER')) AS owns,
        current_setting('transaction_isolation') AS isolation,
        current_setting('transaction_read_only') AS read_only
        FROM pg_roles r WHERE r.rolname=current_user"""
    ).fetchone()
    if (
        not role["rolcanlogin"]
        or not role["api_capability"]
        or any(
            role[k] for k in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "owns")
        )
    ):
        policy.fail("ROLE_REJECTED", "采集目录只能由非所有者 API 运行账号读取", 403)
    if role["isolation"] != "repeatable read" or role["read_only"] != "on":
        policy.fail("SNAPSHOT_REQUIRED", "采集目录需要同一只读重复读取事务", 500)
    tables = c.execute(
        """SELECT name,to_regclass(name) IS NOT NULL AS installed,
        CASE WHEN to_regclass(name) IS NULL THEN false
          ELSE has_table_privilege(current_user,name,'SELECT') END AS readable
        FROM unnest(%s::text[]) AS name ORDER BY name""",
        (list(COMMON + {"nodes": NODES, "sets": SETS, "facts": FACTS}[kind]),),
    ).fetchall()
    functions = (
        c.execute(
            """SELECT to_regprocedure('design.identity_snapshot_v2(uuid)') IS NOT NULL AS installed,
            CASE WHEN to_regprocedure('design.identity_snapshot_v2(uuid)') IS NULL THEN false
            ELSE has_function_privilege(current_user,'design.identity_snapshot_v2(uuid)','EXECUTE') END AS readable"""
        ).fetchall()
        if kind == "facts"
        else []
    )
    if not all(row["installed"] and row["readable"] for row in tables + functions):
        policy.fail("UNAVAILABLE", "采集目录所需只读存储或权限尚未完整安装", 503)
    return {"role": dict(role), "tables": list(tables), "functions": list(functions)}
