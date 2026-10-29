"""Minimal native read dependencies; no grants or owner fallback."""

from packages.domain.runtime import DomainError

TABLES = ("design.drafts", "design.sections", "design.section_revisions")
IMAGE_TABLES = (
    "design.authoring_image_assets",
    "design.authoring_image_versions",
    "design.blobs",
)


def tables(c, names):
    result = c.execute(
        """SELECT name,to_regclass(name) IS NOT NULL AS installed,
        CASE WHEN to_regclass(name) IS NULL THEN false
          ELSE has_table_privilege(current_user,name,'SELECT') END AS readable
        FROM unnest(%s::text[]) AS name ORDER BY name""",
        (list(names),),
    ).fetchall()
    if not all(item["installed"] and item["readable"] for item in result):
        raise DomainError(
            "AUTHORING_HISTORY_UNAVAILABLE", "历史章节所需只读表或权限尚未完整安装", 503
        )
    return list(result)


def require(c):
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
            role[key]
            for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolbypassrls", "owns")
        )
    ):
        raise DomainError(
            "AUTHORING_HISTORY_ROLE_REJECTED", "历史章节只能由非所有者 API 运行账号读取", 403
        )
    if role["isolation"] != "repeatable read" or role["read_only"] != "on":
        raise DomainError(
            "AUTHORING_HISTORY_SNAPSHOT_REQUIRED", "历史章节需要同一只读重复读取事务", 500
        )
    return {"role": dict(role), "tables": tables(c, TABLES)}
