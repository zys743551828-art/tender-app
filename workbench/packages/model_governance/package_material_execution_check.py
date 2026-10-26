"""Persist an exact /3 admission refusal, never promote client references to authority."""

from copy import deepcopy

from packages.contracts import package_material_execution_api as contracts
from packages.domain import bid_package_technical_eligibility_service as eligibility
from packages.domain.package_technical_eligibility import distinct, reason
from packages.domain.runtime import Command, DomainError, audit, clean, etag, sha
from packages.model_governance import package_technical_complete_vision as vision

BLOCKERS = (
    (
        "MATERIAL_REFERENCE_UNVERIFIED",
        "材料封印和报价引用尚未通过独立用途复验，不能由输入编号授予资格。",
    ),
    (
        "LIVE_QUALIFICATION_UNAVAILABLE",
        "原生准备任务接受已接通；真实账户发送适配尚未完成，真实调用关闭。",
    ),
    ("LIVE_COST_UNCONFIRMED", "真实账户价格及费用状态未核验，未预留费用。"),
)


def target():
    return {
        "profile": vision.profile(),
        "profile_digest": vision.profile_digest(),
        "serializer_digest": vision.serializer_digest(),
        "judgment_method_digest": vision.judgment_method_digest(),
    }


def context(c, scope, scope_id):
    qualification, _ = eligibility.scoring_context(c, scope, scope_id)
    value = {
        "version": "package-material-execution-context/1",
        "qualification": qualification,
        "target": target(),
        "execution_enabled": False,
        "blockers": distinct(qualification["blockers"] + [reason(k, v) for k, v in BLOCKERS]),
    }
    contracts.validate("PackageMaterialExecutionContext", value)
    stable = deepcopy(value)
    stable["qualification"].pop("observed_at")
    return value, etag("package-material-execution", scope_id, sha(stable))


def check(c, scope, scope_id, actor, body, condition, key):
    contracts.validate("PackageMaterialExecutionCheck", body)
    # Preserve the established governance -> bid -> source lock order before
    # using the shared command ledger. No independent-purpose DSN enters API.
    current, tag = context(c, scope, scope_id)
    command = Command(
        c,
        actor,
        "check-package-material-execution",
        scope_id,
        key,
        {"scope": list(scope), "request": body},
        condition,
    )
    if command.replay is not None:
        return command.replay, True
    if condition is None:
        raise DomainError("PRECONDITION_REQUIRED", "请先读取完整材料执行条件", 428)
    if (
        condition != tag
        or body["scope_digest"] != current["qualification"]["scope"]["scope_digest"]
    ):
        raise DomainError("REVISION_CONFLICT", "范围或执行方法已变化，请保留原请求并重新核对", 412)
    if any(
        body[k] != current["target"][k]
        for k in ("profile_digest", "serializer_digest", "judgment_method_digest")
    ):
        raise DomainError(
            "MATERIAL_EXECUTION_METHOD_CHANGED", "请求模型或方法引用与当前配置不一致", 409
        )
    value = {
        "version": "package-material-execution-receipt/1",
        "command_id": str(command.id),
        "actor_id": str(actor),
        "scope_id": str(scope_id),
        "scope_digest": body["scope_digest"],
        "request_digest": sha(body),
        "request": deepcopy(body),
        "observed_at": current["qualification"]["observed_at"],
        "state": "blocked",
        "reference_status": "unverified",
        "execution_authorized": False,
        "jobs_created": 0,
        "model_requests": 0,
        "fee_reserved": False,
        "blockers": current["blockers"],
    }
    contracts.validate("PackageMaterialExecutionReceipt", value)
    audit(
        c,
        actor,
        scope[0],
        "package.material_execution_refused",
        {"scope_id": scope_id, "request_digest": value["request_digest"]},
        command.id,
    )
    return command.finish(clean(value), headers={"Cache-Control": "private, no-store"}), False
