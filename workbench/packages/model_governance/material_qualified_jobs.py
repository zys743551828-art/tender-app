"""Shared-command intents and native atomic acceptance. No parallel task ledger."""

from psycopg.types.json import Jsonb

from packages.domain.runtime import Command, audit, clean, match, sha
from packages.model_governance import material_judgment_jobs as jobs
from packages.model_governance import material_qualification as policy
from packages.model_governance import material_qualification_guard as guard
from packages.model_governance import material_qualification_registry as registry

VERSION = "material-qualified-job-request/1"


def validate(body):
    policy.closed(
        body,
        {
            "version",
            "scope_digest",
            "qualification_id",
            "qualification_digest",
            "qualification_revision",
            "renewal_id",
            "renewal_digest",
        },
    )
    if (
        body["version"] != VERSION
        or any(not policy.identity(body[k]) for k in ("qualification_id", "renewal_id"))
        or any(
            not policy.is_digest(body[k])
            for k in ("scope_digest", "qualification_digest", "renewal_digest")
        )
        or type(body["qualification_revision"]) is not int
        or not 1 <= body["qualification_revision"] <= 2**53 - 1
    ):
        policy.fail("REQUEST_INVALID")


def current(c, scope_id, body):
    row = registry._row(c, scope_id, body["qualification_id"], lock=True)
    if (
        row["digest"] != body["qualification_digest"]
        or row["revision"] != body["qualification_revision"]
        or row["decision"] != "approved"
    ):
        policy.fail("NOT_CURRENT", "资格版本已变化或未获批准", 409)
    policy.validate(row["document"])
    at = registry._now(c)
    if (
        not policy.timestamp(row["document"]["valid_from"])
        <= at
        < policy.timestamp(row["document"]["valid_until"])
    ):
        policy.fail("EXPIRED", "资格不在有效期内", 409)
    if row["document"]["binding"]["scope_digest"] != body["scope_digest"]:
        policy.fail("SCOPE_CHANGED", "申请与资格输入范围不一致", 409)
    if not c.execute(
        "SELECT active FROM design.members WHERE id=%s", (row["reviewer_id"],)
    ).fetchone()["active"]:
        policy.fail("REVIEWER_INACTIVE", "审核身份已失效", 409)
    registry._evidence(c, row["bid_id"], row["document"])
    return row


def prepare(c, scope, scope_id, actor, body, condition, key):
    saved = registry._scope(c, scope, scope_id)
    validate(body)
    command = Command(
        c,
        actor,
        "accept-qualified-material-job",
        scope_id,
        key,
        {"scope": list(scope), "body": body},
        condition,
    )
    if command.replay is not None:
        return command.replay["body"]["intent_id"]
    guard.audit(c)
    if saved["digest"] != body["scope_digest"]:
        policy.fail("SCOPE_CHANGED", "申请输入范围已变化", 409)
    row = current(c, scope_id, body)
    match(condition, "material-qualification", body["qualification_id"], row["revision"])
    binding = row["document"]["binding"]
    document = {
        "version": "material-qualified-job-intent/1",
        "guard_digest": guard.method_digest(),
        "request_key_digest": sha(key),
        "request": body,
        "command": {
            "version": "material-job-command/1",
            "operation": "start",
            "arguments": {
                "renewal_id": body["renewal_id"],
                "expected_renewal_digest": body["renewal_digest"],
                "profile_id": binding["job_profile_id"],
                "expected_profile_digest": binding["job_profile_digest"],
                "command_id": str(command.id),
                "expected_method_digest": jobs.method_digest(),
            },
        },
    }
    c.execute(
        "INSERT INTO material_qualification.intents(id,actor_id,bid_id,scope_id,qualification_id,qualification_digest,qualification_revision,document,digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            command.id,
            actor,
            scope[0],
            scope_id,
            body["qualification_id"],
            body["qualification_digest"],
            row["revision"],
            Jsonb(document),
            sha(document),
        ),
    )
    audit(
        c,
        actor,
        scope[0],
        "material.qualified_job_requested",
        {
            "intent_id": str(command.id),
            "qualification_id": body["qualification_id"],
            "request_digest": sha(body),
            "request_key_digest": sha(key),
        },
        command.id,
    )
    command.finish({"intent_id": str(command.id)}, 202)
    return str(command.id)


def intent(c, scope, scope_id, actor, intent_id):
    registry._scope(c, scope, scope_id)
    row = c.execute(
        "SELECT * FROM material_qualification.intents WHERE id=%s AND scope_id=%s AND actor_id=%s AND bid_id=%s",
        (intent_id, scope_id, actor, scope[0]),
    ).fetchone()
    if row is None:
        policy.fail("INTENT_NOT_FOUND", "当前成员没有该确切范围的申请", 404)
    if row["digest"] != sha(row["document"]):
        policy.fail("INTENT_CORRUPT", "固定申请摘要异常", 409)
    validate(row["document"]["request"])
    return row


def observe(c, row, *, pending_reason="NATIVE_ACCEPTANCE_PENDING"):
    accepted = c.execute(
        "SELECT * FROM material_qualification.acceptances WHERE intent_id=%s", (row["id"],)
    ).fetchone()
    job = None
    if accepted is not None:
        doc = accepted["document"]
        if (
            accepted["job_digest"] != sha(doc)
            or str(accepted["job_id"]) != doc["job_id"]
            or doc["command_id"] != str(row["id"])
            or doc["bid_id"] != str(row["bid_id"])
            or doc["scope_id"] != str(row["scope_id"])
        ):
            policy.fail("ACCEPTANCE_CORRUPT", "原生接受回执身份或摘要异常", 409)
        job = {
            "job_id": str(accepted["job_id"]),
            "job_digest": accepted["job_digest"],
            "generation": doc["generation"],
        }
    body = row["document"]["request"]
    return clean(
        {
            "version": "material-qualified-job-receipt/1",
            "intent_id": row["id"],
            "actor_id": row["actor_id"],
            "scope_id": row["scope_id"],
            "request": body,
            "request_digest": sha(body),
            "request_key_digest": row["document"]["request_key_digest"],
            "state": "accepted_preparation" if job else "pending",
            "job": job,
            "pending_reason": None if job else pending_reason,
            "send_authorized": False,
            "fee_state": "not_observed",
            "accuracy_verified": False,
            "observed_at": registry._now(c),
        }
    )
