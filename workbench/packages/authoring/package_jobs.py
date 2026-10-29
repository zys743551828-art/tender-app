"""Atomic fixed-input task/native job producer over the existing paid call port."""

import json
from uuid import UUID

from psycopg.types.json import Jsonb

from packages.assistant import budget, jobs
from packages.assistant.generation import request_for
from packages.authoring import package_generation as generation
from packages.authoring.package_job_authority import MODE, require_schema
from packages.domain.runtime import DomainError, audit, clean, enqueue_plan, fetch, sha, uid


def prior_semantic(c, bid, input_row, instruction, policy_digest):
    return c.execute(
        "SELECT b.* FROM design.authoring_package_job_bindings b "
        "JOIN design.authoring_package_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id "
        "JOIN design.assistant_jobs j ON j.id=b.job_id AND j.bid_id=b.bid_id "
        "WHERE b.bid_id=%s AND i.context_digest=%s "
        "AND design.assistant_normalize_question(j.input_manifest#>>'{request,instruction}')=design.assistant_normalize_question(%s) "
        "AND j.input_manifest#>>'{plan,execution_policy_digest}'=%s ORDER BY j.id LIMIT 1",
        (bid, input_row["context_digest"], instruction, policy_digest),
    ).fetchone()


def original_required(job, binding=None):
    raise DomainError(
        "AUTHORING_PACKAGE_ORIGINAL_JOB_REQUIRED",
        "同一输入已有原任务，请打开原任务核对；未把已有运行包装为本次受理",
        409,
        {
            "bid_id": str(job["bid_id"]),
            "job_id": str(job["id"]),
            "task_run_id": str(binding["task_run_id"]) if binding else None,
            "new_attempt_authorized": False,
        },
    )


def queue(c, bid, actor, template, input_row, command_id):
    """Caller has verified originals out of transaction and rechecked under locks."""
    require_schema(c)
    jobs.require_schema(c)
    config = template["config"]["definition"]
    selected = input_row["manifest"]["selection"]["target_section"]
    body = {
        "section_id": selected["section_id"],
        "base_section_revision": selected["base_section_revision"],
        "instruction": config["instructions"],
        "authoring_input_id": str(input_row["id"]),
        "authoring_input_digest": input_row["digest"],
        "max_tokens": 2048,
    }
    execution_policy = generation.policy()
    semantic = prior_semantic(c, bid, input_row, config["instructions"], sha(execution_policy))
    if semantic:
        if (
            semantic["definition_version_id"] == template["version_id"]
            and semantic["input_id"] == input_row["id"]
            and semantic["input_digest"] == input_row["digest"]
        ):
            return semantic["task_run_id"], True
        original_required(jobs.job(c, semantic["job_id"]), semantic)
    prepared = budget.prepare_package(c, actor, body, bid, input_row["id"], input_row["digest"])
    if "reuse_id" in prepared:
        previous = c.execute(
            "SELECT task_run_id,bid_id,input_id,input_digest,definition_version_id "
            "FROM design.authoring_package_job_bindings WHERE job_id=%s",
            (prepared["reuse_id"],),
        ).fetchone()
        old = jobs.job(c, prepared["reuse_id"])
        if (
            previous
            and previous["bid_id"] == bid
            and previous["input_id"] == input_row["id"]
            and previous["input_digest"] == input_row["digest"]
            and previous["definition_version_id"] == template["version_id"]
            and old["input_manifest"].get("request") == body
        ):
            return previous["task_run_id"], True
        original_required(old, previous)
    plan = generation.plan(input_row, config["instructions"], policy_snapshot=execution_policy)
    plan_id, job_id, run_id = uid(), uid(), uid()
    c.execute(
        "INSERT INTO design.writing_plans(id,bid_id,section_id,base_section_revision,rule_ids,fact_set_id,source_version_ids,plan) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            plan_id,
            bid,
            selected["section_id"],
            selected["base_section_revision"],
            [UUID(v) for v in plan["original_content"]["attrs"]["rule_ids"]],
            input_row["manifest"]["selection"]["facts"]["fact_set_id"],
            sorted({UUID(d["document_version_id"]) for d in plan["context"]["documents"]}),
            Jsonb(plan),
        ),
    )
    manifest = clean(
        {
            "schema_version": 1,
            "kind": "authoring",
            "purpose": "authoring",
            "scope": "project",
            "generation_mode": MODE,
            "job_id": job_id,
            "bid_id": bid,
            "actor_id": actor,
            "writing_plan_id": plan_id,
            "plan": plan,
            "request": body,
            "formal_scoring_input": False,
            "logical_intent": prepared,
        }
    )
    messages, schema = request_for(manifest)
    # Fail before committing any job/hold when the COMPLETE request exceeds the
    # verified hard input ceiling. UTF-8 bytes conservatively bound tokenizer input.
    request = {
        "messages": messages,
        "json_schema": schema,
        "max_tokens": 2048,
        "temperature": 0,
        "thinking": "disabled",
    }
    price = fetch(
        c,
        "SELECT input_hard_ceiling FROM design.assistant_price_versions WHERE id=%s",
        (prepared["price_version_id"],),
    )
    if len(json.dumps(request, ensure_ascii=False).encode()) > price["input_hard_ceiling"]:
        raise DomainError(
            "ASSISTANT_INPUT_TOO_LARGE", "完整整包超过冻结输入硬上界，未截断或创建调用", 422
        )
    digest = sha(manifest)
    operation = enqueue_plan(
        c,
        bid,
        command_id,
        "authoring-generate",
        {"id": str(job_id), "digest": digest},
        stages=[{"key": "authoring-generate", "depends_on": []}],
        handler_version="authoring-generate/1",
        topic="tender.task.assistant.v1",
    )
    c.execute(
        "INSERT INTO design.assistant_jobs(id,kind,scope,bid_id,writing_plan_id,operation_id,actor_id,input_manifest,input_digest,intent_digest) "
        "VALUES(%s,'authoring','project',%s,%s,%s,%s,%s,%s,%s)",
        (
            job_id,
            bid,
            plan_id,
            operation["id"],
            actor,
            Jsonb(manifest),
            digest,
            prepared["anti_resend_key"],
        ),
    )
    input_identity = {
        "authoring_input_id": str(input_row["id"]),
        "authoring_input_digest": input_row["digest"],
    }
    context = {
        "input": input_identity,
        "context_digest": input_row["context_digest"],
        "target": selected,
        "scope": input_row["manifest"]["scope"],
        "source_scope": "exact_package_context",
    }
    run_digest = sha(
        {
            "schema": "task-package-authoring-run/1",
            "definition_version_id": str(template["version_id"]),
            "configuration_digest": template["digest"],
            "context": context,
        }
    )
    frozen = clean(
        {
            "schema": "task-package-authoring-run/1",
            "definition_id": template["id"],
            "definition_version_id": template["version_id"],
            "configuration_digest": template["digest"],
            "configuration": config,
            "task_kind": "chapter_suggestion",
            "purpose": "assist",
            "actor_id": actor,
            "request_id": command_id,
            "context": context,
            "input_digest": run_digest,
            "fee_scope": prepared["coarse_key"],
            "trigger": "manual",
            "trigger_event_id": None,
            "scheduled_at": None,
            "accepted_at": fetch(c, "SELECT clock_timestamp() AS at")["at"],
            "formal_decisions_allowed": False,
            "assistant_job_id": job_id,
            "authoring_binding": {
                "job_input_digest": digest,
                "writing_plan_id": plan_id,
                "writing_plan_digest": sha(plan),
                "operation_id": operation["id"],
            },
        }
    )
    c.execute(
        "INSERT INTO design.task_runs(id,bid_id,definition_version_id,operation_id,frozen_manifest) VALUES(%s,%s,%s,%s,%s)",
        (run_id, bid, template["version_id"], operation["id"], Jsonb(frozen)),
    )
    c.execute(
        "INSERT INTO design.authoring_package_job_bindings(job_id,task_run_id,bid_id,input_id,input_digest,actor_id,command_id,definition_version_id,writing_plan_id,job_input_digest,task_manifest_digest) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            job_id,
            run_id,
            bid,
            input_row["id"],
            input_row["digest"],
            actor,
            command_id,
            template["version_id"],
            plan_id,
            digest,
            sha(frozen),
        ),
    )
    budget.bind(c, job_id, actor, prepared)
    audit(
        c,
        actor,
        bid,
        "authoring.package_generation_queued",
        {
            "job_id": job_id,
            "task_run_id": run_id,
            "input_id": input_row["id"],
            "input_digest": input_row["digest"],
            "operation_id": operation["id"],
            "applied": False,
        },
        command_id,
    )
    audit(
        c,
        actor,
        bid,
        "task.run_created",
        {
            "run_id": run_id,
            "definition_version_id": template["version_id"],
            "operation_id": operation["id"],
            "input_digest": run_digest,
        },
        command_id,
    )
    return run_id, False
