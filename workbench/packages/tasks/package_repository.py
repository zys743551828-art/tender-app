"""Immutable task-to-native-package-run bindings and historical/current projections."""

from packages.contracts.package_review_runs_api import valid
from packages.domain import bid_package_review_run_repository as native_runs
from packages.domain.runtime import DomainError, clean, fetch, sha
from packages.tasks import package_inputs as inputs
from packages.tasks.models import RunView

COMMAND_KIND = "task-run-manual"


def is_package(row):
    return row["frozen_manifest"].get("schema") == inputs.SCHEMA


def native(c, row):
    row = clean(row)
    frozen = row["frozen_manifest"]
    binding = c.execute(
        "SELECT * FROM design.task_package_review_bindings WHERE bid_id=%s AND task_run_id=%s",
        (row["bid_id"], row["id"]),
    ).fetchone()
    try:
        if binding is None:
            raise ValueError("missing binding")
        binding = clean(binding)
        selected = inputs.selection(frozen["configuration"])
        scope = inputs.scope(row["bid_id"], selected)
        native_row = fetch(
            c,
            native_runs.SELECT + " WHERE r.bid_id=%s AND r.id=%s",
            (row["bid_id"], binding["review_run_id"]),
        )
        run = native_runs.view(native_row)
        native_runs.assert_scope(
            run, scope, selected["frozen_input_id"], selected["execution_input_id"]
        )
        command = fetch(c, "SELECT * FROM commands WHERE id=%s", (binding["start_command_id"],))
        command = clean(command)
        receipt = command["response"]
        details = frozen["package_review"]
        version = clean(
            fetch(
                c,
                "SELECT * FROM task_definition_versions WHERE bid_id=%s AND id=%s",
                (row["bid_id"], row["definition_version_id"]),
            )
        )
        if (
            not is_package(row)
            or binding["manifest_digest"] != sha(frozen)
            or binding["parent_command_id"] != frozen["request_id"]
            or frozen["definition_version_id"] != row["definition_version_id"]
            or frozen["definition_id"] != version["definition_id"]
            or frozen["configuration"] != version["config"]["definition"]
            or frozen["configuration_digest"] != version["digest"]
            or sha(version["config"]) != version["digest"]
            or frozen["input_digest"]
            != inputs.input_digest(version["id"], version["digest"], frozen["context"])
            or frozen["fee_scope"] != inputs.fee_scope(frozen["context"])
            or frozen["context"]["selection"] != selected
            or frozen["context"]
            != inputs.context(row["bid_id"], selected, native_row["input_manifest"])
            or frozen["context"]["review_input_digest"] != run["input_digest"]
            or frozen["context"]["subject"] != {"kind": "bid_package", **run["scope"]}
            or run["operation"]["id"] != row["operation_id"]
            or details
            != {
                "run_id": run["id"],
                "operation_id": row["operation_id"],
                "start_command_id": binding["start_command_id"],
                "input_digest": run["input_digest"],
                "method_digest": run["method_digest"],
                "run_ref": inputs.run_ref(run),
            }
            or command["actor_id"] != frozen["actor_id"]
            or command["command_kind"] != native_runs.KIND
            or command["target_id"] != selected["execution_input_id"]
            or command["request_digest"]
            != sha({"body": inputs.request(selected), "if_match": None})
            or receipt is None
            or receipt["status"] != 202
            or receipt["headers"] != {}
            or not valid("PackageReviewRunView", receipt["body"])
            or any(
                receipt["body"][key] != run[key]
                for key in (
                    "kind",
                    "id",
                    "actor_id",
                    "created_at",
                    "scope",
                    "frozen_input_id",
                    "frozen_input_digest",
                    "execution_input_id",
                    "execution_input_digest",
                    "execution_digest",
                    "dependency_plan_id",
                    "dependency_plan_digest",
                    "input_digest",
                    "method_digest",
                )
            )
            or any(
                receipt["body"]["operation"][key] != run["operation"][key]
                for key in ("id", "kind", "input_digest", "handler_version", "created_at")
            )
            or (receipt["body"]["operation"]["state"] == "succeeded")
            != (receipt["body"]["result"] is not None)
            or (
                receipt["body"]["result"] is not None and receipt["body"]["result"] != run["result"]
            )
        ):
            raise ValueError("binding identity")
        return run
    except (KeyError, TypeError, ValueError) as error:
        raise DomainError(
            "TASK_PACKAGE_BINDING_CORRUPT", "任务与原整包核查、命令或冻结版本无法一致核验", 500
        ) from error


def view(c, row):
    run = native(c, row)
    operation = run["operation"]
    state, error = operation["state"], operation["error_code"]
    if c.execute(
        "SELECT 1 FROM model_calls WHERE operation_id=%s AND state IN('reserved','unknown') LIMIT 1",
        (operation["id"],),
    ).fetchone():
        state, error = "reconciliation_required", "MODEL_CALL_REQUIRES_RECONCILIATION"
    result = None
    if run["result"] is not None:
        result = {
            "kind": "declared_package_scope_review",
            "run_id": run["id"],
            "run_ref": inputs.run_ref(run),
            "input_digest": run["input_digest"],
            "result_digest": run["result"]["digest"],
            "overall_coverage": "partial",
            "formal_scoring_eligible": False,
            "submission_eligible": False,
        }
    value = clean(
        {
            "id": row["id"],
            "bid_id": row["bid_id"],
            "definition_version_id": row["definition_version_id"],
            "root_operation_id": operation["id"],
            "final_operation_id": operation["id"],
            "state": state,
            "stage": "review",
            "frozen_manifest": row["frozen_manifest"],
            "result": result,
            "error_code": error,
            "formal_decisions_created": False,
            "coverage": "not_formal_score",
        }
    )
    RunView.model_validate(value)
    return value


def replay(c, bid, definition, actor, key, body, condition):
    """Recover the exact original ACK before current template/source admission."""
    fetch(c, "SELECT id FROM task_definitions WHERE bid_id=%s AND id=%s", (bid, definition))
    record = c.execute(
        "SELECT request_digest,response FROM commands WHERE actor_id=%s AND command_kind=%s AND target_id=%s AND idempotency_key=%s",
        (actor, COMMAND_KIND, definition, key),
    ).fetchone()
    if record is None:
        return None
    if record["request_digest"] != sha({"body": body, "if_match": condition}):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一任务请求键对应不同请求或条件", 409)
    saved = record["response"]
    if saved is None:
        raise DomainError("COMMAND_INCOMPLETE", "原任务命令尚未完成", 409)
    if saved["body"].get("frozen_manifest", {}).get("schema") != inputs.SCHEMA:
        return None
    row = fetch(
        c,
        "SELECT * FROM task_runs WHERE bid_id=%s AND id=%s",
        (bid, saved["body"]["id"]),
    )
    native(c, row)
    if (
        saved["status"] != 202
        or saved["headers"] not in ({"Task-Run-Reused": "false"}, {"Task-Run-Reused": "true"})
        or saved["body"]["bid_id"] != str(bid)
        or saved["body"]["frozen_manifest"] != row["frozen_manifest"]
        or saved["body"]["root_operation_id"] != str(row["operation_id"])
        or saved["body"]["final_operation_id"] != str(row["operation_id"])
        or saved["body"]["stage"] != "review"
        or saved["body"]["definition_version_id"] != str(row["definition_version_id"])
        or saved["body"]["frozen_manifest"]["definition_id"] != str(definition)
    ):
        raise DomainError("TASK_PACKAGE_BINDING_CORRUPT", "原整包任务回执无法一致核验", 500)
    RunView.model_validate(saved["body"])
    return saved
