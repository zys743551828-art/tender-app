"""One bounded batch and one read snapshot; no implicit current report or selected package."""

from uuid import UUID

from packages.contracts.project_summary_api import validate
from packages.domain import project_summary
from packages.domain.runtime import DomainError, clean

STATEMENT = """
WITH selected AS (
 SELECT bid_id AS id,phase,archived_at FROM design.bid_profiles WHERE bid_id=ANY(%s::uuid[])
), heads AS (
 SELECT p.bid_id,p.kind,
  CASE WHEN r.id IS NULL OR h.revision<>r.revision OR h.digest<>r.digest THEN 1 ELSE 0 END AS invalid,
  coalesce(jsonb_array_length(r.manifest->'members'),0) AS members,
  (SELECT count(*) FROM jsonb_array_elements(r.manifest->'members') m
   WHERE m->'parse'->>'status'='not_frozen') AS not_frozen
 FROM design.bid_packages p LEFT JOIN design.bid_package_heads h ON h.package_id=p.id
 LEFT JOIN design.bid_package_revisions r ON r.package_id=p.id AND r.id=h.revision_id
 WHERE p.bid_id=ANY(%s::uuid[])
), totals AS (
 SELECT bid_id,count(*) FILTER(WHERE kind='authority') AS authority_count,
 count(*) FILTER(WHERE kind='bid') AS bid_count,sum(members) AS member_count,
 sum(not_frozen) AS not_frozen_members,sum(invalid) AS invalid_heads FROM heads GROUP BY bid_id
)
SELECT s.id,s.phase,s.archived_at,
 coalesce(t.authority_count,0)::bigint AS authority_count,coalesce(t.bid_count,0)::bigint AS bid_count,
 coalesce(t.member_count,0)::bigint AS member_count,
 coalesce(t.not_frozen_members,0)::bigint AS not_frozen_members,
 coalesce(t.invalid_heads,0)::bigint AS invalid_heads
FROM selected s LEFT JOIN totals t ON t.bid_id=s.id ORDER BY s.id
"""


def read(c, bid_ids):
    identities = [str(UUID(str(value))) for value in bid_ids]
    if not 1 <= len(identities) <= 20 or len(set(identities)) != len(identities):
        raise DomainError("PROJECT_SUMMARY_BATCH_INVALID", "每次请选择1至20个不同项目", 422)
    rows = c.execute(STATEMENT, (identities, identities)).fetchall()
    found = {str(row["id"]): row for row in rows}
    if set(found) != set(identities):
        raise DomainError("PROJECT_SUMMARY_NOT_FOUND", "所选项目不存在，摘要未完整读取", 404)
    value = {
        "version": "project-work-summary/1",
        "observed_at": clean(c.execute("SELECT transaction_timestamp() AS at").fetchone()["at"]),
        "items": [project_summary.project(found[bid]) for bid in identities],
    }
    validate("ProjectWorkSummaryBatch", value)
    return value
