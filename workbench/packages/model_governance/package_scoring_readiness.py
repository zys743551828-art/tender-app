"""Public formal checks cannot turn isolated mechanism authority into permission."""

from copy import deepcopy

from packages.contracts import package_technical_execution_api as contracts
from packages.domain import bid_package_technical_eligibility_service as eligibility
from packages.domain.package_technical_eligibility import distinct, reason
from packages.domain.runtime import DomainError, etag, sha
from packages.model_governance import package_scoring_profile as method


def context(c, scope, scope_id, scale_id=None):
    qualification, _ = eligibility.scoring_context(c, scope, scope_id, scale_id)
    installed = c.execute(
        "SELECT to_regprocedure('package_score_execution.owned_input(uuid,bigint,bigint,uuid)') IS NOT NULL AND to_regprocedure('package_score_execution.publish_result(uuid,bigint,bigint,uuid,jsonb)') IS NOT NULL AS ready"
    ).fetchone()["ready"]
    blockers = deepcopy(qualification["blockers"])
    blockers.extend(
        [
            reason(
                "PACKAGE_SCORE_FORMAL_RANGE_AUTHORITY_MISSING",
                "完整必要范围尚无独立权威证明；用户选择技术分册不授予完整读取资格。",
            ),
            reason(
                "PACKAGE_SCORE_VISUAL_AUTHORITY_MISSING",
                "图、表和示意图的原页读取及视觉覆盖尚未由独立执行权威核验。",
            ),
            reason(
                "PACKAGE_SCORE_PROVIDER_NOT_CONFIGURED",
                "当前仅验收隔离软件机制，未配置有资格的真实模型运行端口。",
            ),
            reason(
                "PACKAGE_SCORE_METHOD_NOT_CERTIFIED",
                "整包方法及模型身份尚未通过独立真实验收，不能产生正式分数或训练资格。",
            ),
        ]
    )
    value = {
        "version": "package-technical-execution-context/1",
        "qualification": qualification,
        "producer": {
            "software_foundation": "installed" if installed else "not_installed",
            "real_provider_configured": False,
            "formal_input_authority_configured": False,
            "mechanism_test_publicly_available": False,
        },
        "method": method.descriptor() | {"digest": method.digest()},
        "execution_enabled": False,
        "blockers": distinct(blockers),
    }
    contracts.validate("PackageTechnicalExecutionContext", value)
    stable = deepcopy(value)
    stable["qualification"].pop("observed_at")
    return value, etag("package-technical-execution", scope_id, sha(stable))


def request_execution(c, scope, scope_id, body, condition):
    contracts.validate("CreatePackageTechnicalExecution", body)
    value, tag = context(c, scope, scope_id, body["scale_id"])
    if condition is None:
        raise DomainError("PRECONDITION_REQUIRED", "请先读取此确切范围的执行资格", 428)
    if condition != tag or body["scope_digest"] != value["qualification"]["scope"]["scope_digest"]:
        raise DomainError("REVISION_CONFLICT", "执行依据已变化，请核对原范围和当前资格", 412)
    raise DomainError(
        "PACKAGE_TECHNICAL_EXECUTION_BLOCKED",
        "整包正式执行资格尚未成立，未创建任务、预留费用或发送模型请求",
        409,
        {
            "scope_id": scope_id,
            "scope_digest": body["scope_digest"],
            "method_digest": method.digest(),
            "blockers": value["blockers"],
            "jobs_created": 0,
            "model_requests": 0,
        },
    )
