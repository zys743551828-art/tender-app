"""Readonly dependency assessment over exact frozen/prepared packets; no model or writes."""

from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import package_fact_usage as fact_usage
from packages.domain import package_input_dependencies as dependencies
from packages.domain.runtime import DomainError, connection


def observe(
    scope, frozen_id, input_id, prepared_digest, selection_request, request, *, _bind_usage=False
):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = prepared_inputs.load_packet(c, scope, frozen_id, input_id)
        if packet.digest != prepared_digest:
            raise DomainError(
                "PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不一致", 409
            )
        original = frozen_inputs.load_input(c, scope, frozen_id)
        try:
            usage = fact_usage.select(packet, selection_request)
            if _bind_usage:
                request = {**request, "usage_digest": usage.digest}
            return dependencies.assess(original, packet, usage, request)
        except ValueError as error:
            if str(error) in {
                "input_dependency_frozen_binding",
                "input_dependency_projection_corrupt",
                "input_dependency_coverage_changed",
                "input_dependency_duplicate_requirement",
            }:
                raise DomainError(
                    "PACKAGE_EXECUTION_INPUT_CORRUPT", "原准备输入的要求投影无法一致核验", 500
                ) from error
            if str(error) == "input_dependency_usage_changed":
                raise DomainError(
                    "PACKAGE_INPUT_DEPENDENCIES_CHANGED", "事实消费选择与依赖声明引用不一致", 409
                ) from error
            raise DomainError(
                "PACKAGE_INPUT_DEPENDENCIES_INVALID",
                "要求依赖声明的身份、依据或内容不符合协议",
                422,
            ) from error


def check(scope, frozen_id, input_id, body):
    from packages.contracts.bid_package_requirements_api import validate

    validate("CheckPackageInputDependencies", body)
    return observe(
        scope,
        frozen_id,
        input_id,
        body["execution_input_digest"],
        {"purpose": body["purpose"], "fact_ids": body["fact_ids"]},
        {"purpose": body["purpose"], "dependencies": body["dependencies"]},
        _bind_usage=True,
    ).view()
