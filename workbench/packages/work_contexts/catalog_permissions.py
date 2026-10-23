"""Additional SELECT-only dependencies for explicit saved authoring contexts."""

from packages.domain.runtime import DomainError

TABLES = (
    "design.drafts",
    "design.authoring_image_assets",
    "design.authoring_image_versions",
)


def require(c):
    rows = c.execute(
        """SELECT name,to_regclass(name) IS NOT NULL AS installed,
        CASE WHEN to_regclass(name) IS NULL THEN false
          ELSE has_table_privilege(current_user,name,'SELECT') END AS readable
        FROM unnest(%s::text[]) AS name ORDER BY name""",
        (list(TABLES),),
    ).fetchall()
    if not all(row["installed"] and row["readable"] for row in rows):
        raise DomainError("WORK_CONTEXT_UNAVAILABLE", "历史正文所需只读表或权限尚未完整安装", 503)
    return list(rows)
