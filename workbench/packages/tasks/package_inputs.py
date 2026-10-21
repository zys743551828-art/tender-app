"""Exact package task references; metadata reads never verify original bytes."""

from copy import deepcopy

from packages.domain import bid_package_dependency_plan_repository as plans
from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import bid_package_scope_review as admission
from packages.domain import package_scope_review as policy
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean, sha
from packages.tasks.models import PackageReviewSelection

SCHEMA = "task-package-run/1"
MODE = "exact_package_review"
SCOPE_KEYS = ("bid_id", "package_id", "revision_id", "inventory_id")


def is_exact(configuration):
    return configuration.get("source_selection", {}).get("mode") == MODE


def selection(configuration):
    try:
        if (
            not is_exact(configuration)
            or configuration["task_kind"] != "denial_check"
            or configuration["trigger"]["mode"] != "manual"
            or configuration["section_id"] is not None
        ):
            raise ValueError("task scope")
        return PackageReviewSelection.model_validate(
            configuration["source_selection"]["input"]
        ).model_dump(mode="json")
    except (KeyError, TypeError, ValueError) as error:
        raise DomainError(
            "TASK_PACKAGE_SELECTION_INVALID",
            "任务必须明确选择同一整包的冻结输入、准备输入与依赖计划",
            422,
        ) from error


def scope(bid, value):
    return (str(bid), *(value[key] for key in SCOPE_KEYS[1:]))


def request(value):
    return {
        key: value[key]
        for key in ("execution_input_digest", "dependency_plan_id", "dependency_plan_digest")
    }


def selected(c, bid, value):
    """Check exact stored references for a new template, with no storage/provider IO."""
    value = PackageReviewSelection.model_validate(value).model_dump(mode="json")
    selected_scope = scope(bid, value)
    frozen = frozen_inputs.load_input(c, selected_scope, value["frozen_input_id"])
    prepared = prepared_inputs.load_packet(
        c, selected_scope, value["frozen_input_id"], value["execution_input_id"]
    )
    plan = plans.load(
        c,
        selected_scope,
        value["frozen_input_id"],
        value["execution_input_id"],
        value["dependency_plan_id"],
    )
    if (
        frozen.digest != value["frozen_input_digest"]
        or prepared.digest != value["execution_input_digest"]
        or plan["digest"] != value["dependency_plan_digest"]
    ):
        raise DomainError(
            "TASK_PACKAGE_SELECTION_CHANGED", "所选整包输入摘要与真实已保存记录不一致", 409
        )
    if value["method_digest"] != digest(policy.method_profile()):
        raise DomainError(
            "TASK_PACKAGE_METHOD_CHANGED", "整包核查方法已变化，请重新读取并确认任务输入", 409
        )
    return value


def verify(bid, value):
    """All object IO is outside the task's publication transaction."""
    verified = admission.verify(
        admission.observe(
            scope(bid, value), value["frozen_input_id"], value["execution_input_id"], request(value)
        )
    )
    manifest = verified._observed.input_manifest()
    if (
        manifest["frozen_input"]["digest"] != value["frozen_input_digest"]
        or manifest["executor_method"]["digest"] != value["method_digest"]
    ):
        raise DomainError(
            "TASK_PACKAGE_SELECTION_CHANGED", "原件核验后的冻结输入或方法与明确选择不同", 409
        )
    policy.batches(verified._observed.model_input())
    return verified


def context(bid, value, manifest):
    if (
        manifest["scope"] != dict(zip(SCOPE_KEYS, scope(bid, value), strict=True))
        or manifest["frozen_input"]["id"] != value["frozen_input_id"]
        or manifest["frozen_input"]["digest"] != value["frozen_input_digest"]
        or manifest["execution_input"]["id"] != value["execution_input_id"]
        or manifest["execution_input"]["digest"] != value["execution_input_digest"]
        or manifest["dependency_plan"]
        != {"id": value["dependency_plan_id"], "digest": value["dependency_plan_digest"]}
        or manifest["executor_method"]["digest"] != value["method_digest"]
    ):
        raise DomainError("TASK_PACKAGE_BINDING_INVALID", "整包任务与真实核查输入无法一致绑定", 409)
    return {
        "subject": {"kind": "bid_package", **deepcopy(manifest["scope"])},
        "selection": deepcopy(value),
        "review_input_digest": digest(manifest),
        "model_input_digest": manifest["model_input_digest"],
        "limitations": deepcopy(manifest["limitations"]),
        "overall_coverage": "partial",
        "formal_scoring_eligible": False,
        "submission_eligible": False,
    }


def input_digest(version, configuration_digest, value):
    return sha(
        clean(
            {
                "schema": SCHEMA,
                "definition_version_id": version,
                "configuration_digest": configuration_digest,
                "context": value,
            }
        )
    )


def fee_scope(value):
    # A changed template, saved navigation record or rerun intent is not a new
    # provider request. Unknown calls for this model payload must be reconciled.
    return sha(
        {
            "schema": "task-package-fee-scope/1",
            "bid_id": value["subject"]["bid_id"],
            "purpose": policy.PURPOSE,
            "model_input_digest": value["model_input_digest"],
        }
    )


def run_ref(value):
    selected_scope = value["scope"]
    return (
        f"/api/v1/bids/{selected_scope['bid_id']}/packages/{selected_scope['package_id']}"
        f"/revisions/{selected_scope['revision_id']}/requirement-inventories/{selected_scope['inventory_id']}"
        f"/frozen-review-inputs/{value['frozen_input_id']}/execution-inputs/{value['execution_input_id']}"
        f"/review-runs/{value['id']}"
    )
