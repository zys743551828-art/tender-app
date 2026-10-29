"""Bounded history discovery from immutable receipts, without copying full plans or fact pools."""

from packages.domain import bid_package_dependency_plan_repository as repository
from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain.review_identity import utc
from packages.domain.runtime import DomainError, connection, sha
from packages.identity import pagination


def directory(scope, frozen_id, input_id, limit=10, cursor=None):
    from packages.contracts.bid_package_requirements_api import valid

    if type(limit) is not int or not 1 <= limit <= 20:
        raise DomainError("INVALID_REQUEST", "每页计划数量须为1至20", 422)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = prepared_inputs.load_packet(c, scope, frozen_id, input_id)
        prepared = dict(
            zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
        ) | {
            "frozen_input_id": frozen_id,
            "execution_input_id": input_id,
            "execution_input_digest": packet.digest,
        }
        marker = sha({"directory": "package-dependency-plans/1", "prepared": prepared})
        after = pagination.decode(cursor, marker)
        if after:
            try:
                if utc(after[0]) != after[0]:
                    raise ValueError("noncanonical_time")
            except (ValueError, OverflowError) as error:
                raise DomainError("INVALID_CURSOR", "计划游标时间不符合协议", 422) from error
        rows = c.execute(
            """SELECT p.manifest->'prepared' AS prepared,
            jsonb_build_object('id',p.id,'digest',p.digest,'actor_id',p.actor_id,
              'saved_at',p.manifest->'saved_at','reason',p.manifest->'reason',
              'assessment_digest',p.manifest#>'{assessment,digest}',
              'required_facts_assessment',p.manifest#>'{assessment,manifest,required_facts_assessment}',
              'dependency_review_status',p.manifest#>'{assessment,manifest,dependency_review_status}',
              'selected_fact_count',p.manifest#>'{assessment,manifest,selected_fact_count}',
              'requirement_count',p.manifest#>'{assessment,manifest,requirement_count}') AS summary,
            (cmd.actor_id=p.actor_id AND cmd.command_kind=%s AND cmd.target_id=p.execution_input_id
              AND cmd.request_digest=p.manifest->>'request_digest'
              AND cmd.response=jsonb_build_object('body',jsonb_build_object('manifest',p.manifest,'digest',p.digest),'status',201,'headers','{}'::jsonb)) AS ack_valid,
            (SELECT count(*) FROM design.audit_entries a WHERE a.command_id=p.command_id AND a.event_type=%s) AS audits,
            (SELECT count(*) FROM design.audit_entries a WHERE a.command_id=p.command_id AND a.event_type=%s
              AND a.actor_id=p.actor_id AND a.bid_id=p.bid_id
              AND a.payload=jsonb_build_object('plan_id',p.id,'digest',p.digest,'execution_input_id',p.execution_input_id,'assessment_digest',p.manifest#>'{assessment,digest}')) AS valid_audits
            FROM design.bid_package_dependency_plans p LEFT JOIN design.commands cmd ON cmd.id=p.command_id
            WHERE p.bid_id=%s AND p.execution_input_id=%s
              AND (%s::text IS NULL OR (p.manifest->>'saved_at',p.id)>(%s::text,%s::uuid))
            ORDER BY p.manifest->>'saved_at',p.id LIMIT %s""",
            (
                repository.KIND,
                repository.EVENT,
                repository.EVENT,
                scope[0],
                input_id,
                after[0] if after else None,
                after[0] if after else None,
                after[-1] if after else None,
                limit + 1,
            ),
        ).fetchall()
        for row in rows:
            if not (
                row["prepared"] == prepared
                and row["ack_valid"] is True
                and row["audits"] == row["valid_audits"] == 1
                and valid("PackageDependencyPlanSummary", row["summary"])
            ):
                raise DomainError(
                    "PACKAGE_DEPENDENCY_PLAN_CORRUPT", "计划历史摘要与原回执无法一致核验", 500
                )
        items = [row["summary"] for row in rows[:limit]]
        more = len(rows) > limit
        return {
            "prepared": prepared,
            "items": items,
            "has_more": more,
            "next_cursor": pagination.encode(marker, [items[-1]["saved_at"], items[-1]["id"]])
            if more
            else None,
            "inventory_complete": False,
            "facts_qualified": False,
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        }
