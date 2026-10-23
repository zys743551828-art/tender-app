"""Historical task/job/proposal identity and truthful authoring publication state.

This observes the existing section-and-source-version workflow. It never chooses
new sources, claims exact-package scope, publishes a candidate or applies a patch.
"""

from uuid import UUID

from psycopg import sql

from packages.assistant import jobs
from packages.assistant.generation import validate_generation
from packages.domain.runtime import DomainError, clean, sha
from packages.tasks.models import TaskAuthoringResult

ERROR = "TASK_AUTHORING_BINDING_INVALID"


def pending_notifications_sql(c):
    """Discover closed projects with terminal native work, without reopening them.

    The runner still calls ``project`` to establish the result and ``runs.notify``
    to record it. This bounded discovery query does not authorize publication.
    Older installations can have chapter jobs without the optional budget table.
    """
    installed = c.execute(
        "SELECT to_regclass('assistant_jobs') IS NOT NULL AS jobs, "
        "to_regclass('assistant_publications') IS NOT NULL AS publications, "
        "to_regclass('assistant_budget_reservations') IS NOT NULL AS budget"
    ).fetchone()
    if not installed["jobs"] or not installed["publications"]:
        return sql.SQL("")
    unknown_budget = sql.SQL(
        " OR EXISTS(SELECT FROM assistant_budget_reservations hold "
        "WHERE hold.job_id=j.id AND hold.state IN('sent','unknown'))"
        if installed["budget"]
        else ""
    )
    return sql.SQL(
        """ OR EXISTS(
          SELECT FROM task_runs t JOIN operations o ON o.id=t.operation_id AND o.bid_id=t.bid_id
          JOIN assistant_jobs j ON j.operation_id=o.id AND j.bid_id=t.bid_id
            AND j.id::text=t.frozen_manifest->>'assistant_job_id'
          LEFT JOIN assistant_publications pub ON pub.job_id=j.id
          CROSS JOIN LATERAL(SELECT CASE
            WHEN EXISTS(SELECT FROM model_calls call WHERE call.operation_id=o.id
              AND call.state IN('reserved','unknown')){} THEN 'reconciliation_required'
            WHEN o.state IN('failed','cancelled') THEN o.state::text
            WHEN o.state='succeeded' THEN CASE pub.state
              WHEN 'published' THEN 'succeeded' WHEN 'stale' THEN 'superseded'
              WHEN 'failed' THEN 'failed' END END AS state) terminal
          WHERE t.bid_id=b.id AND t.frozen_manifest->>'schema'='task-run/1'
            AND t.frozen_manifest->>'task_kind'='chapter_suggestion' AND terminal.state IS NOT NULL
            AND NOT EXISTS(SELECT FROM audit_entries a WHERE a.bid_id=b.id
              AND a.event_type='task.notification' AND a.payload->>'run_id'=t.id::text
              AND a.payload->>'state'=terminal.state
              AND EXISTS(SELECT FROM audit_entries binding WHERE binding.bid_id=b.id
                AND binding.event_type='task.authoring_notification_bound'
                AND binding.payload->>'notification_key'=a.payload->>'key'
                AND binding.payload->>'run_id'=t.id::text
                AND binding.payload->>'job_id'=j.id::text
                AND binding.payload->>'publication_state'=coalesce(pub.state,'pending')
                AND binding.payload->>'action_id' IS NOT DISTINCT FROM pub.action_id::text)))"""
    ).format(unknown_budget)


def _require(valid):
    if not valid:
        raise DomainError(ERROR, "章节任务与原生输入、候选或提案身份无法一致核验", 409)


def _row(c, query, values):
    value = c.execute(query, values).fetchone()
    _require(value is not None)
    return clean(value)


def _sources(c, bid, context, plan):
    documents = {item["id"]: item for item in context["documents"]}
    blocks = plan["source_blocks"]
    rows = c.execute(
        """SELECT e.id,p.id AS parse_id,p.document_version_id,e.text_content,e.physical_page
        FROM evidence_blocks e JOIN parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id
        WHERE e.bid_id=%s AND e.id=ANY(%s::uuid[])""",
        (bid, [item["evidence_id"] for item in blocks]),
    ).fetchall()
    evidence = {str(item["id"]): clean(item) for item in rows}
    _require(len(evidence) == len(blocks))
    for block in blocks:
        actual = evidence[block["evidence_id"]]
        ref = block["source_ref"]
        _require(
            actual["document_version_id"] in documents
            and documents[actual["document_version_id"]]["parse_id"] == actual["parse_id"]
            and ref["document_version_id"] == actual["document_version_id"]
            and ref["evidence_id"] == actual["id"]
            and block["text"] == actual["text_content"]
            and block["physical_page"] == actual["physical_page"]
        )


def _bound(c, bid, frozen, operation_id):
    """Reconstruct only immutable original records; current heads are irrelevant."""
    bid, operation_id = str(bid), str(operation_id)
    job_id = str(UUID(frozen["assistant_job_id"]))
    job = _row(c, "SELECT * FROM assistant_jobs WHERE bid_id=%s AND id=%s", (bid, job_id))
    manifest = job["input_manifest"]
    config, context = frozen["configuration"], frozen["context"]
    section = context["section"]
    version = _row(
        c,
        "SELECT * FROM task_definition_versions WHERE bid_id=%s AND id=%s",
        (bid, frozen["definition_version_id"]),
    )
    parent = _row(c, "SELECT * FROM commands WHERE id=%s", (frozen["request_id"],))
    operation = _row(c, "SELECT * FROM operations WHERE bid_id=%s AND id=%s", (bid, operation_id))
    command = _row(c, "SELECT * FROM commands WHERE id=%s", (operation["command_id"],))
    plan = _row(
        c, "SELECT * FROM writing_plans WHERE bid_id=%s AND id=%s", (bid, job["writing_plan_id"])
    )
    original = _row(
        c,
        "SELECT * FROM section_revisions WHERE bid_id=%s AND section_id=%s AND revision=%s",
        (bid, section["id"], section["head_revision"]),
    )
    request = manifest["request"]
    expected_request = {
        "section_id": section["id"],
        "base_section_revision": section["head_revision"],
        "instruction": config["instructions"],
        "source_version_ids": [item["id"] for item in context["documents"]],
    }
    expected_context = {
        "rule_set_id": context["rule_set_id"],
        "fact_set_id": (context["fact_head"] or {}).get("fact_set_id"),
        "fact_revision": (context["fact_head"] or {}).get("revision", 0),
    }
    _require(
        frozen["schema"] == "task-run/1"
        and frozen["task_kind"] == config["task_kind"] == "chapter_suggestion"
        and config["source_selection"]["mode"] in {"current_project", "selected_versions"}
        and config["section_id"] == section["id"]
        and version["definition_id"] == frozen["definition_id"]
        and version["config"]["definition"] == config
        and sha(version["config"]) == version["digest"]
        and frozen["purpose"] == "assist"
        and frozen["input_digest"]
        == sha({"version_id": version["id"], "purpose": "assist", "context": context})
        and parent["actor_id"] == frozen["actor_id"]
        and parent["target_id"] == frozen["definition_id"]
        and parent["command_kind"] in {"task-run-manual", "task-trigger"}
        and job["kind"] == "authoring"
        and job["scope"] == "project"
        and job["operation_id"] == operation_id
        and sha(manifest) == job["input_digest"]
        and manifest["kind"] == "authoring"
        and manifest["purpose"] == "authoring"
        and manifest["scope"] == "project"
        and manifest["bid_id"] == bid
        and manifest["actor_id"] == job["actor_id"] == command["actor_id"]
        and manifest["writing_plan_id"] == plan["id"]
        and manifest["plan"] == plan["plan"]
        and manifest.get("selection") is None
        and manifest.get("generation_mode") is None
        and all(request.get(key) == value for key, value in expected_request.items())
        and not any(key in request for key in ("node_id", "selection_start", "selection_end"))
        and plan["section_id"] == section["id"]
        and plan["base_section_revision"] == section["head_revision"]
        and plan["source_version_ids"] == expected_request["source_version_ids"]
        and plan["plan"]["original_content"] == original["content"]
        and plan["plan"]["section_digest"] == original["digest"]
        and original["draft_id"] == section["draft_id"]
        and plan["plan"]["context"] == expected_context
        and operation["kind"] == "authoring-generate"
        and operation["handler_version"] == "authoring-generate/1"
        and operation["input_digest"] == sha({"id": job_id, "digest": job["input_digest"]})
    )
    _sources(c, bid, context, plan["plan"])
    queued = c.execute(
        """SELECT actor_id,command_id,payload FROM audit_entries
        WHERE bid_id=%s AND event_type='authoring.generation_queued'
        AND payload->>'job_id'=%s""",
        (bid, job_id),
    ).fetchall()
    _require(len(queued) == 1)
    queued = clean(queued[0])
    _require(
        queued["actor_id"] == job["actor_id"]
        and queued["command_id"] == operation["command_id"]
        and queued["payload"]
        == {
            "job_id": job_id,
            "writing_plan_id": plan["id"],
            "operation_id": operation_id,
            "applied": False,
        }
    )
    binding = {
        "schema": "task-authoring-binding/1",
        "job_id": job_id,
        "job_input_digest": job["input_digest"],
        "writing_plan_id": plan["id"],
        "writing_plan_digest": sha(plan["plan"]),
        "operation_id": operation_id,
        "native_command_id": operation["command_id"],
        "native_actor_id": job["actor_id"],
    }
    # Older accepted tasks have the original job ID. They must pass all the same
    # immutable joins; no current-section or latest-job fallback is allowed.
    _require(frozen.get("authoring_binding", binding) == binding)
    return binding, job, operation


def bind(c, bid, frozen, operation_id):
    try:
        return _bound(c, bid, clean(frozen), operation_id)[0]
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise DomainError(ERROR, "章节任务的原生输入绑定不完整", 409) from error


def _publication(c, job, candidate):
    publication = c.execute(
        "SELECT * FROM assistant_publications WHERE job_id=%s", (job["id"],)
    ).fetchone()
    if publication is None:
        return None
    publication = clean(publication)
    _require(candidate is not None and publication["scope"] == "project")
    _require(publication["kind"] == "authoring")
    if publication["state"] != "published":
        _require(
            publication["state"] in {"stale", "failed"}
            and publication["error_code"]
            and publication["action_id"] is None
        )
        return publication
    action = _row(
        c,
        """SELECT a.*,l.job_id,l.tool FROM proposed_actions a
        JOIN assistant_action_links l ON l.action_id=a.id
        WHERE a.id=%s AND a.bid_id=%s""",
        (publication["action_id"], job["bid_id"]),
    )
    payload, manifest = action["payload"], job["input_manifest"]
    plan, request = manifest["plan"], manifest["request"]
    _require(
        action["job_id"] == job["id"]
        and action["tool"] == "authoring.apply_patch"
        and sha(payload) == action["request_digest"]
        and payload["kind"] == "authoring_patch"
        and payload["section_id"] == request["section_id"]
        and payload["base_section_revision"] == request["base_section_revision"]
        and payload["before_section_digest"] == plan["section_digest"]
        and payload["context"] == plan["context"]
        and action["base_revision"] == plan["base_draft_revision"]
        and all(
            payload[key] == candidate["payload"][key]
            for key in ("node_id", "before_digest", "replacement")
        )
    )
    return publication


def project(c, row):
    """Return state/error/result only after validating the native historical chain."""
    try:
        frozen = row["frozen_manifest"]
        binding, job, operation = _bound(c, row["bid_id"], frozen, row["operation_id"])
        _require(str(row["definition_version_id"]) == frozen["definition_version_id"])
        output = c.execute(
            """SELECT o.*,m.state AS call_state,m.operation_id,m.response_ref
            FROM assistant_outputs o JOIN model_calls m ON m.id=o.project_call_id
            WHERE o.job_id=%s""",
            (job["id"],),
        ).fetchone()
        if output is not None:
            output = clean(output)
            _require(
                output["digest"] == sha(output["payload"])
                and output["operation_id"] == operation["id"]
                and output["call_state"] == "succeeded"
                and output["response_ref"] is not None
            )
            validate_generation(job["input_manifest"], output["payload"], canonical=True)
        publication = _publication(c, job, output)
        state, error = operation["state"], None
        if state == "succeeded":
            _require(output is not None)
            effect = _row(
                c,
                "SELECT result FROM effect_receipts WHERE operation_id=%s AND effect_key='authoring-generate'",
                (operation["id"],),
            )["result"]
            _require(
                effect
                == {
                    "job_id": job["id"],
                    "result_ref": "/api/v1/assistant/jobs/" + job["id"],
                    "state": "candidate_ready",
                    "domain_mutated": False,
                }
            )
            state = "awaiting_publication"
            if publication is not None:
                state = {"published": "succeeded", "stale": "superseded", "failed": "failed"}[
                    publication["state"]
                ]
                error = publication["error_code"]
        elif state == "failed":
            effect = c.execute(
                "SELECT result FROM effect_receipts WHERE operation_id=%s AND effect_key='authoring-generate'",
                (operation["id"],),
            ).fetchone()
            error = (effect or {}).get("result", {}).get(
                "error_code"
            ) or "TASK_AUTHORING_EXECUTION_FAILED"
        if jobs.view(c, UUID(job["id"]))["requires_billing_reconciliation"]:
            state, error = "reconciliation_required", "MODEL_CALL_REQUIRES_RECONCILIATION"
        result = TaskAuthoringResult.model_validate(
            {
                "schema": "task-authoring-result/1",
                **{
                    key: binding[key]
                    for key in ("job_id", "job_input_digest", "writing_plan_id", "operation_id")
                },
                "job_ref": "/api/v1/assistant/jobs/" + job["id"],
                "section_id": job["input_manifest"]["request"]["section_id"],
                "base_section_revision": job["input_manifest"]["request"]["base_section_revision"],
                "publication_state": publication["state"] if publication else "pending",
                "candidate_digest": output["digest"] if output else None,
                "action_id": publication["action_id"] if publication else None,
                "action_ref": "/api/v1/assistant/actions/" + publication["action_id"]
                if publication and publication["action_id"]
                else None,
                "source_scope": "legacy_section_and_source_versions",
                "automatic_apply": False,
            }
        ).model_dump(mode="json", by_alias=True)
        return state, error, result
    except DomainError as error:
        # A damaged historical link is observable, never a fabricated completed task.
        return "unknown", ERROR if error.code != ERROR else error.code, None
    except (ValueError, KeyError, TypeError, AttributeError):
        return "unknown", ERROR, None
