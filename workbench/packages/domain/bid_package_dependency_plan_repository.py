"""Append-only dependency plans and exact ACK/audit history, independent of current policy."""

from psycopg.types.json import Jsonb

from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import package_dependency_plan as plans
from packages.domain.runtime import DomainError

KIND = "package-dependency-plan-save"
EVENT = "package.dependency_plan.saved"


def _not_found():
    return DomainError("PACKAGE_DEPENDENCY_PLAN_NOT_FOUND", "依赖计划不存在", 404)


def load(c, scope, frozen_id, input_id, plan_id):
    row = c.execute(
        """SELECT manifest,digest,command_id FROM design.bid_package_dependency_plans
        WHERE bid_id=%s AND execution_input_id=%s AND id=%s""",
        (scope[0], input_id, plan_id),
    ).fetchone()
    if row is None:
        raise _not_found()
    m = row["manifest"]
    p = m["prepared"]
    if (
        tuple(p[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope
        or p["frozen_input_id"] != frozen_id
    ):
        raise _not_found()
    value = {"manifest": m, "digest": row["digest"]}
    command = c.execute(
        "SELECT actor_id,command_kind,target_id,request_digest,response FROM design.bid_package_dependency_plan_command_receipts WHERE id=%s",
        (row["command_id"],),
    ).fetchone()
    audits = c.execute(
        "SELECT actor_id,bid_id,payload FROM design.audit_entries WHERE command_id=%s AND event_type=%s",
        (row["command_id"], EVENT),
    ).fetchall()
    if not (
        command
        and str(row["command_id"]) == m["command_id"]
        and m["id"] == plan_id
        and str(command["actor_id"]) == m["actor_id"]
        and command["command_kind"] == KIND
        and str(command["target_id"]) == input_id
        and command["request_digest"] == m["request_digest"]
        and command["response"] == {"body": value, "status": 201, "headers": {}}
        and len(audits) == 1
        and str(audits[0]["actor_id"]) == m["actor_id"]
        and str(audits[0]["bid_id"]) == scope[0]
        and audits[0]["payload"] == audit_payload(value)
    ):
        raise DomainError("PACKAGE_DEPENDENCY_PLAN_CORRUPT", "依赖计划回执或审计无法一致核验", 500)
    packet = prepared_inputs.load_packet(c, scope, frozen_id, input_id)
    original = frozen_inputs.load_input(c, scope, frozen_id)
    try:
        return plans.read(value, original, packet).view()
    except (ValueError, KeyError, TypeError) as error:
        raise DomainError(
            "PACKAGE_DEPENDENCY_PLAN_CORRUPT", "依赖计划原绑定无法一致核验", 500
        ) from error


def audit_payload(value):
    m = value["manifest"]
    return {
        "plan_id": m["id"],
        "digest": value["digest"],
        "execution_input_id": m["prepared"]["execution_input_id"],
        "assessment_digest": m["assessment"]["digest"],
    }


def append(c, value):
    m = value["manifest"]
    c.execute(
        """INSERT INTO design.bid_package_dependency_plans
        (id,bid_id,execution_input_id,actor_id,command_id,manifest,digest)
        VALUES(%s,%s,%s,%s,%s,%s,%s)""",
        (
            m["id"],
            m["prepared"]["bid_id"],
            m["prepared"]["execution_input_id"],
            m["actor_id"],
            m["command_id"],
            Jsonb(m),
            value["digest"],
        ),
    )
