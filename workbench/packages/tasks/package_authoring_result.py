"""Historical protected exact task/job/publication projection, never admission."""

from psycopg import sql

from packages.assistant import jobs
from packages.authoring import package_generation
from packages.authoring import package_input_repository as inputs
from packages.authoring.package_job_authority import MODE, available
from packages.domain.runtime import DomainError, clean, fetch, sha
from packages.tasks.models import RunView, TaskPackageAuthoringResult

ERROR = "TASK_PACKAGE_AUTHORING_BINDING_INVALID"


def is_exact(row):
    manifest = row["frozen_manifest"]
    return (
        manifest.get("schema") == "task-package-authoring-run/1"
        or manifest.get("configuration", {}).get("source_selection", {}).get("mode")
        == "exact_package_authoring"
    )


def require(valid):
    if not valid:
        raise DomainError(ERROR, "固定整包章节任务与原生历史记录不一致", 409)


def bound(c, row):
    require(available(c))
    binding = fetch(
        c,
        "SELECT * FROM design.authoring_package_job_bindings WHERE task_run_id=%s AND bid_id=%s",
        (row["id"], row["bid_id"]),
    )
    job = jobs.job(c, binding["job_id"])
    input_row = inputs.load(c, row["bid_id"], binding["input_id"])
    version = fetch(
        c,
        "SELECT * FROM design.task_definition_versions WHERE id=%s AND bid_id=%s",
        (row["definition_version_id"], row["bid_id"]),
    )
    plan = fetch(
        c,
        "SELECT * FROM design.writing_plans WHERE id=%s AND bid_id=%s",
        (job["writing_plan_id"], row["bid_id"]),
    )
    operation = fetch(
        c,
        "SELECT * FROM design.operations WHERE id=%s AND bid_id=%s",
        (row["operation_id"], row["bid_id"]),
    )
    command = fetch(c, "SELECT * FROM design.commands WHERE id=%s", (binding["command_id"],))
    frozen, manifest = row["frozen_manifest"], job["input_manifest"]
    expected_plan = package_generation.plan(
        input_row,
        version["config"]["definition"]["instructions"],
        policy_snapshot=manifest["plan"]["execution_policy"],
    )
    require(
        frozen["schema"] == "task-package-authoring-run/1"
        and frozen["configuration"] == version["config"]["definition"]
        and frozen["configuration_digest"] == version["digest"] == sha(version["config"])
        and frozen["configuration"]["source_selection"]["input"]
        == {
            "authoring_input_id": str(input_row["id"]),
            "authoring_input_digest": input_row["digest"],
        }
        and frozen["assistant_job_id"] == str(job["id"])
        and binding["definition_version_id"] == version["id"]
        and binding["job_input_digest"] == job["input_digest"] == sha(manifest)
        and binding["task_manifest_digest"] == sha(frozen)
        and binding["input_digest"] == input_row["digest"]
        and str(command["actor_id"]) == frozen["actor_id"] == str(job["actor_id"])
        and command["target_id"] == version["definition_id"]
        and command["command_kind"] == "task-package-authoring-run"
        and operation["command_id"] == command["id"]
        and job["operation_id"] == operation["id"]
        and manifest["generation_mode"] == MODE
        and manifest["plan"] == plan["plan"] == expected_plan
        and operation["handler_version"] == "authoring-generate/1"
        and operation["input_digest"] == sha({"id": str(job["id"]), "digest": job["input_digest"]})
    )
    return binding, job, operation


def accepted_receipt(c, row, command):
    """Validate the saved ACK; never replace it with a later execution projection."""
    binding, job, operation = bound(c, row)
    response = command["response"]
    try:
        accepted = response["body"]
        RunView.model_validate(accepted)
        result = TaskPackageAuthoringResult.model_validate(accepted["result"]).model_dump(
            mode="json", by_alias=True
        )
        first = binding["command_id"] == command["id"]
        expected = clean(
            {
                "schema": "task-package-authoring-result/1",
                "job_id": job["id"],
                "job_input_digest": job["input_digest"],
                "writing_plan_id": job["writing_plan_id"],
                "operation_id": operation["id"],
                "job_ref": "/api/v1/assistant/jobs/" + str(job["id"]),
                "section_id": job["input_manifest"]["request"]["section_id"],
                "base_section_revision": job["input_manifest"]["request"]["base_section_revision"],
                "authoring_input_id": binding["input_id"],
                "authoring_input_digest": binding["input_digest"],
                "context_digest": job["input_manifest"]["plan"]["input"]["context_digest"],
                "source_scope": "exact_package_context",
                "automatic_apply": False,
                "apply_available": False,
                "build_available": False,
            }
        )
        if first:
            expected.update(
                publication_state="pending", candidate_digest=None, action_id=None, action_ref=None
            )
        require(result == result | expected)
        if result["candidate_digest"] is not None:
            output = fetch(
                c, "SELECT digest FROM design.assistant_outputs WHERE job_id=%s", (job["id"],)
            )
            require(result["candidate_digest"] == output["digest"])
        if result["publication_state"] == "pending":
            require(result["action_id"] is None and result["action_ref"] is None)
        else:
            publication = fetch(
                c, "SELECT * FROM design.assistant_publications WHERE job_id=%s", (job["id"],)
            )
            require(
                result["publication_state"] == publication["state"]
                and result["action_id"] == clean(publication["action_id"])
                and result["action_ref"]
                == (
                    "/api/v1/assistant/actions/" + str(publication["action_id"])
                    if publication["action_id"]
                    else None
                )
                and result["candidate_digest"] is not None
            )
        expected_body = clean(
            {
                "id": row["id"],
                "bid_id": row["bid_id"],
                "definition_version_id": row["definition_version_id"],
                "root_operation_id": operation["id"],
                "final_operation_id": None,
                "state": "queued" if first else accepted["state"],
                "stage": "execution",
                "frozen_manifest": row["frozen_manifest"],
                "result": result,
                "error_code": None if first else accepted["error_code"],
                "formal_decisions_created": False,
                "coverage": "not_formal_score",
            }
        )
        require(
            response
            == {
                "body": expected_body,
                "status": 202,
                "headers": {"Task-Run-Reused": "false" if first else "true"},
            }
            and row["frozen_manifest"]["definition_id"] == str(command["target_id"])
        )
    except (KeyError, TypeError, ValueError):
        raise DomainError(ERROR, "固定整包章节原始回执不完整", 409) from None
    return response


def project(c, row):
    try:
        binding, job, operation = bound(c, row)
        manifest = job["input_manifest"]
        output = c.execute(
            "SELECT * FROM design.assistant_outputs WHERE job_id=%s", (job["id"],)
        ).fetchone()
        if output:
            require(sha(output["payload"]) == output["digest"])
            package_generation.validate(manifest, output["payload"], canonical=True)
            call = fetch(
                c,
                "SELECT * FROM design.model_calls WHERE id=%s AND operation_id=%s",
                (output["project_call_id"], operation["id"]),
            )
            require(
                call["state"] == "succeeded"
                and call["response_ref"] is not None
                and call["logical_call_key"] == "authoring.generate/1"
            )
        publication = c.execute(
            "SELECT * FROM design.assistant_publications WHERE job_id=%s", (job["id"],)
        ).fetchone()
        if publication:
            require(
                output is not None
                and publication["kind"] == "authoring"
                and publication["scope"] == "project"
            )
            if publication["state"] == "published":
                from packages.authoring.package_publication import inspect

                inspect(c, publication["action_id"])
            else:
                require(
                    publication["state"] in {"stale", "failed"}
                    and publication["error_code"]
                    and publication["action_id"] is None
                )
        state, error = operation["state"], None
        if state == "succeeded":
            effect = fetch(
                c,
                "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='authoring-generate'",
                (operation["id"],),
            )
            require(
                output is not None
                and effect["result"]
                == {
                    "job_id": str(job["id"]),
                    "result_ref": "/api/v1/assistant/jobs/" + str(job["id"]),
                    "state": "candidate_ready",
                    "domain_mutated": False,
                }
            )
            state = "awaiting_publication"
            if publication:
                state = {"published": "succeeded", "stale": "superseded", "failed": "failed"}[
                    publication["state"]
                ]
                error = publication["error_code"]
        elif state == "failed":
            effect = c.execute(
                "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='authoring-generate'",
                (operation["id"],),
            ).fetchone()
            error = (effect or {}).get("result", {}).get(
                "error_code"
            ) or "TASK_PACKAGE_AUTHORING_EXECUTION_FAILED"
        if jobs.view(c, job["id"])["requires_billing_reconciliation"]:
            state, error = "reconciliation_required", "MODEL_CALL_REQUIRES_RECONCILIATION"
        result = TaskPackageAuthoringResult.model_validate(
            {
                "schema": "task-package-authoring-result/1",
                "job_id": job["id"],
                "job_input_digest": job["input_digest"],
                "writing_plan_id": job["writing_plan_id"],
                "operation_id": operation["id"],
                "job_ref": "/api/v1/assistant/jobs/" + str(job["id"]),
                "section_id": manifest["request"]["section_id"],
                "base_section_revision": manifest["request"]["base_section_revision"],
                "authoring_input_id": binding["input_id"],
                "authoring_input_digest": binding["input_digest"],
                "context_digest": manifest["plan"]["input"]["context_digest"],
                "publication_state": publication["state"] if publication else "pending",
                "candidate_digest": output["digest"] if output else None,
                "action_id": publication["action_id"] if publication else None,
                "action_ref": "/api/v1/assistant/actions/" + str(publication["action_id"])
                if publication and publication["action_id"]
                else None,
                "source_scope": "exact_package_context",
                "automatic_apply": False,
                "apply_available": False,
                "build_available": False,
            }
        ).model_dump(mode="json", by_alias=True)
        return state, error, result
    except (DomainError, ValueError, KeyError, TypeError, AttributeError):
        return "unknown", ERROR, None


def pending_notifications_sql(c):
    if not available(c):
        return sql.SQL("")
    return sql.SQL(
        """ OR EXISTS(SELECT FROM design.authoring_package_job_bindings binding
        JOIN design.task_runs t ON t.id=binding.task_run_id JOIN design.operations o ON o.id=t.operation_id
        LEFT JOIN design.assistant_publications p ON p.job_id=binding.job_id
        CROSS JOIN LATERAL(SELECT CASE
          WHEN EXISTS(SELECT FROM design.model_calls mc WHERE mc.operation_id=o.id AND mc.state IN('reserved','unknown'))
            OR EXISTS(SELECT FROM design.assistant_budget_reservations hold WHERE hold.job_id=binding.job_id AND hold.state IN('sent','unknown')) THEN 'reconciliation_required'
          WHEN o.state IN('failed','cancelled') THEN o.state::text
          WHEN o.state='succeeded' THEN CASE p.state WHEN 'published' THEN 'succeeded' WHEN 'stale' THEN 'superseded' WHEN 'failed' THEN 'failed' END END AS state) terminal
        WHERE binding.bid_id=b.id AND terminal.state IS NOT NULL AND NOT EXISTS(
          SELECT FROM design.audit_entries a JOIN design.audit_entries bound ON bound.bid_id=a.bid_id
           AND bound.event_type='task.package_authoring_notification_bound' AND bound.payload->>'notification_key'=a.payload->>'key'
          WHERE a.bid_id=b.id AND a.event_type='task.notification' AND a.payload->>'run_id'=t.id::text
           AND a.payload->>'state'=terminal.state AND bound.payload->>'job_id'=binding.job_id::text
           AND bound.payload->>'publication_state'=coalesce(p.state,'pending')
           AND bound.payload->>'action_id' IS NOT DISTINCT FROM p.action_id::text))"""
    )
