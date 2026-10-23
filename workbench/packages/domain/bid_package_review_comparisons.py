"""One read-only snapshot for two exact run/results and their independent human heads."""

from uuid import UUID

from packages.domain import bid_package_review_decision_repository as decisions
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_comparison as policy
from packages.domain.runtime import DomainError, connection, sha
from packages.identity import pagination


def read(bid_id, left_run_id, right_run_id, *, limit=50, cursor=None):
    try:
        valid_ids = all(
            isinstance(value, str) and str(UUID(value)) == value
            for value in (bid_id, left_run_id, right_run_id)
        )
    except (ValueError, TypeError):
        valid_ids = False
    policy.require(
        valid_ids and type(limit) is int and 1 <= limit <= 100,
        "PACKAGE_REVIEW_COMPARISON_REQUEST_INVALID",
        "请明确指定两条核查运行，每页数量须为1至100",
        422,
    )
    policy.require(
        left_run_id != right_run_id,
        "PACKAGE_REVIEW_COMPARISON_SAME_RUN",
        "请明确选择两条不同的已完成核查运行",
        422,
    )
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        records = c.execute(
            runs.SELECT + " WHERE r.bid_id=%s AND r.id IN (%s,%s)",
            (bid_id, left_run_id, right_run_id),
        ).fetchall()
        policy.require(
            len(records) == 2,
            "PACKAGE_REVIEW_COMPARISON_RUN_NOT_FOUND",
            "该标段下没有所选的两条核查运行",
            404,
        )
        sides = {}
        for record in records:
            run = runs.view(record)
            policy.require(
                run["operation"]["state"] == "succeeded" and run["result"] is not None,
                "PACKAGE_REVIEW_COMPARISON_RUN_UNFINISHED",
                "只能对比两条已完成且已发布原结果的核查运行",
            )
            sides[run["id"]] = {
                "run": run,
                "input": {"manifest": record["input_manifest"], "digest": record["input_digest"]},
                "human": decisions.current(c, run),
            }
        compared = policy.compare(bid_id, sides[left_run_id], sides[right_run_id])
        manifest = compared["manifest"]
        marker = sha(
            {"directory": "package-review-comparison/1", "comparison_digest": compared["digest"]}
        )
        try:
            after = pagination.decode(cursor, marker)
            if after and (
                after[0] != ""
                or str(after[-1]) not in {row["requirement_id"] for row in manifest["items"]}
            ):
                raise ValueError("comparison cursor")
        except (DomainError, ValueError) as error:
            raise DomainError(
                "INVALID_CURSOR", "对比游标已过期或不属于这两条核查，请重新加载对比", 422
            ) from error
        remaining = [
            row
            for row in manifest["items"]
            if after is None or row["requirement_id"] > str(after[-1])
        ]
        items, more = remaining[:limit], len(remaining) > limit
        return {
            **{key: value for key, value in manifest.items() if key != "items"},
            "comparison_digest": compared["digest"],
            "items": items,
            "has_more": more,
            "next_cursor": pagination.encode(marker, ["", items[-1]["requirement_id"]])
            if more
            else None,
        }
