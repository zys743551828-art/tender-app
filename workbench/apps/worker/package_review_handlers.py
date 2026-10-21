"""Ordinary fenced worker for an explicit prepared package and saved dependency plan.

The worker has no API credentials. Original/provider IO occurs between closed
transactions; the existing engine owns leases, cancellation, effect receipts and
the final atomic publication transaction.
"""

from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

from packages.domain import bid_package_scope_review as admission
from packages.domain import model_calls
from packages.domain import package_scope_review as policy
from packages.domain.review_identity import digest
from packages.domain.runtime import clean, connection


@dataclass(frozen=True, slots=True)
class PackageReviewOutcome:
    _input_manifest: dict[str, Any] = field(repr=False)
    _verified: admission.VerifiedScopeReview = field(repr=False)
    _responses: list[dict[str, Any]] = field(repr=False)


def _load_run(c, message):
    policy.require(
        message["handler_version"] == policy.HANDLER and message["step_key"] == policy.STEP,
        "PACKAGE_SCOPE_TASK_INVALID",
        "任务不是已注册的整包范围核查阶段",
    )
    row = c.execute(
        """SELECT id,bid_id,execution_input_id,operation_id,input_manifest,input_digest
        FROM design.bid_package_review_runs
        WHERE id=%s AND bid_id=%s AND operation_id=%s""",
        (message["payload_ref"], message["bid_id"], message["operation_id"]),
    ).fetchone()
    policy.require(row is not None, "PACKAGE_REVIEW_RUN_NOT_FOUND", "整包核查运行不存在", 404)
    row = clean(row)
    manifest = row["input_manifest"]
    policy.validate_input(manifest)
    policy.require(
        digest(manifest) == row["input_digest"] == message["input_digest"]
        and row["bid_id"] == manifest["scope"]["bid_id"]
        and row["execution_input_id"] == manifest["execution_input"]["id"],
        "PACKAGE_SCOPE_TASK_BINDING_INVALID",
        "任务与冻结整包输入的精确身份不一致",
    )
    return row


def _new_observation(manifest):
    return admission.observe(
        tuple(
            manifest["scope"][key]
            for key in ("bid_id", "package_id", "revision_id", "inventory_id")
        ),
        manifest["frozen_input"]["id"],
        manifest["execution_input"]["id"],
        {
            "execution_input_digest": manifest["execution_input"]["digest"],
            "dependency_plan_id": manifest["dependency_plan"]["id"],
            "dependency_plan_digest": manifest["dependency_plan"]["digest"],
        },
        worker=True,
    )


def _match(manifest, actual):
    policy.require(
        manifest == actual,
        "PACKAGE_SCOPE_INPUT_CHANGED",
        "本轮已保存核查输入与当前原件、方法或事实条件不同",
    )


def compute(message, lease):
    with connection(True) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = _load_run(c, message)
    manifest = row["input_manifest"]
    verified = admission.verify(_new_observation(manifest))
    _match(manifest, verified._observed.input_manifest())
    payload = verified._observed.model_input()
    policy.require(
        policy.model_digest(payload) == manifest["model_input_digest"],
        "PACKAGE_SCOPE_MODEL_INPUT_CHANGED",
        "完整模型输入与本轮已保存摘要不同",
    )
    prepared_batches = policy.batches(payload)
    responses = []
    for index, batch in enumerate(prepared_batches):
        # Recheck cancellation, lease and all admitted scope before every remote request.
        # The transaction is closed before model_calls starts any provider IO.
        with connection(True) as c:
            model_calls.lock_execution(c, message, lease)
            _match(manifest, admission.recheck(c, verified))
        result, call_id = model_calls.generate(
            message,
            lease,
            logical_key=f"package-scope-judgment-{index + 1}",
            messages=[
                {"role": "system", "content": policy.SYSTEM_PROMPT},
                {"role": "user", "content": policy.model_json(batch)},
            ],
            json_schema=policy.response_schema(),
            max_tokens=policy.OUTPUT_TOKENS,
            purpose="core_review",
        )
        policy.require(
            result["model"] == manifest["executor_method"]["profile"]["model"],
            "PACKAGE_SCOPE_MODEL_CHANGED",
            "模型响应与本轮已保存方法不符",
        )
        policy.validate_batch(batch, result["data"])
        responses.append({"data": result["data"], "call_id": str(call_id)})
    return PackageReviewOutcome(manifest, verified, responses)


def publish(c, message, outcome: PackageReviewOutcome):
    if not isinstance(outcome, PackageReviewOutcome):
        raise TypeError("Scope publication requires the worker's private verified outcome")
    row = _load_run(c, message)
    manifest = row["input_manifest"]
    _match(manifest, outcome._input_manifest)
    _match(manifest, admission.recheck(c, outcome._verified))
    payload = outcome._verified._observed.model_input()
    policy.require(
        policy.model_digest(payload) == manifest["model_input_digest"],
        "PACKAGE_SCOPE_MODEL_INPUT_CHANGED",
        "模型输入与本轮保存摘要不符",
    )
    batches = policy.batches(payload)
    policy.require(
        len(batches) == len(outcome._responses),
        "PACKAGE_SCOPE_RANGE_INCOMPLETE",
        "整包核查批次尚未完整返回",
    )
    matrix = []
    for index, (batch, response) in enumerate(zip(batches, outcome._responses, strict=True)):
        call = c.execute(
            """SELECT mc.id FROM design.model_calls mc JOIN design.operations o ON o.id=mc.operation_id
            WHERE mc.id=%s AND o.bid_id=%s AND mc.operation_id=%s
            AND mc.logical_call_key=%s AND mc.attempt_no=1 AND mc.state='succeeded'""",
            (
                response["call_id"],
                message["bid_id"],
                message["operation_id"],
                f"package-scope-judgment-{index + 1}",
            ),
        ).fetchone()
        policy.require(
            call is not None,
            "PACKAGE_SCOPE_MODEL_RECEIPT_MISSING",
            "本轮核查缺少同一任务的成功模型调用回执",
        )
        matrix.extend(policy.validate_batch(batch, response["data"]))
    result = policy.result_manifest(row["id"], manifest, payload, matrix)
    result_digest = digest(result)
    c.execute(
        """INSERT INTO design.bid_package_review_results
        (run_id,bid_id,operation_id,manifest,digest) VALUES(%s,%s,%s,%s,%s)""",
        (row["id"], row["bid_id"], row["operation_id"], Jsonb(result), result_digest),
    )
    return {
        "result_ref": row["id"],
        "result_digest": result_digest,
        "method_digest": manifest["executor_method"]["digest"],
        "input_digest": row["input_digest"],
        "overall_coverage": "partial",
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }
