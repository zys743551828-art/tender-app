"""Atomic human fact confirmation/withdrawal, scoped to an explicit frozen package."""

from copy import deepcopy

from packages.domain import bid_package_review_input_repository as inputs
from packages.domain import package_fact_changes as policy
from packages.domain.bid_package_fact_evidence import read_basis
from packages.domain.bid_package_service import lock_bid
from packages.domain.fact_sets import current_facts, replace_set
from packages.domain.package_fact_validation import decision_basis
from packages.domain.package_review_context import read_decision_basis
from packages.domain.review_data import effective_at
from packages.domain.review_identity import utc
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    clean,
    connection,
    require_read_committed,
    sha,
)
from packages.lifecycle.service import assert_work_writable

KINDS = {"confirmed": "package-fact-confirm", "withdrawn": "package-fact-withdraw"}


def _ack(stored):
    if (
        not isinstance(stored, dict)
        or set(stored) != {"body", "status", "headers"}
        or stored["status"] != 201
        or stored["headers"] != {}
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执格式与原命令不一致", 500)
    return policy.verify(stored["body"])


def _clock(c):
    return utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())


def _head(head):
    return {
        "id": str(head["fact_set_id"]) if head["fact_set_id"] else None,
        "revision": head["revision"],
    }


def _adopt(c, bid, old, decision, at):
    raw = read_decision_basis(c, str(bid), decision, at)
    if raw is None:
        return None
    row = c.execute(
        "SELECT value::text AS value_jsonb_text FROM design.fact_items WHERE bid_id=%s AND id=%s",
        (bid, old["id"]),
    ).fetchone()
    try:
        return decision_basis(
            {
                "fact": clean(old) | {"value_jsonb_text": row["value_jsonb_text"]},
                "decision_basis_jsonb_text": raw,
            }
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _load_record(c, scope, frozen_id, command_id):
    rows = c.execute(
        "SELECT actor_id::text,command_id::text,event_type,payload FROM design.audit_entries WHERE bid_id=%s AND command_id=%s AND event_type IN ('package.fact_confirmed','package.fact_withdrawn') LIMIT 2",
        (scope[0], command_id),
    ).fetchall()
    if not rows:
        raise DomainError("PACKAGE_FACT_CHANGE_NOT_FOUND", "事实操作回执不存在", 404)
    if len(rows) != 1:
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作审计记录不唯一", 500)
    row = rows[0]
    value = policy.verify(row["payload"])
    m = value["manifest"]
    b = m["binding"]
    if (
        tuple(b[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope
        or b["frozen_input_id"] != frozen_id
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_NOT_FOUND", "事实操作回执不存在", 404)
    command = c.execute(
        "SELECT actor_id::text,command_kind,target_id::text,request_digest,response FROM design.commands WHERE id=%s",
        (command_id,),
    ).fetchone()
    ack = _ack(command["response"]) if command is not None else None
    if (
        command is None
        or command["actor_id"] != m["actor_id"]
        or row["actor_id"] != m["actor_id"]
        or row["command_id"] != m["command_id"]
        or m["command_id"] != command_id
        or row["event_type"] != "package.fact_" + m["action"]
        or command["command_kind"] != KINDS[m["action"]]
        or command["target_id"] != frozen_id
        or (
            m["version"] == "package-fact-change/2"
            and m["request_digest"] != command["request_digest"]
        )
        or ack != value
    ):
        raise DomainError(
            "PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执与不可变审计及命令不一致", 500
        )
    packet = inputs.load_input(c, scope, frozen_id)
    if packet.digest != b["frozen_digest"]:
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执与原冻结输入不一致", 500)
    return value


def load(scope, frozen_id, command_id):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _load_record(c, scope, frozen_id, command_id)


def _replay(c, command, actor, scope, frozen_id, body, action):
    stored = deepcopy(command.replay)
    value = _ack(stored)
    m = value["manifest"]
    b = m["binding"]
    if (
        tuple(b[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")) != scope
        or b["frozen_input_id"] != frozen_id
        or b["frozen_digest"] != body["frozen_digest"]
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_NOT_FOUND", "事实操作回执不存在", 404)
    if (
        m["actor_id"] != actor
        or m["command_id"] != str(command.id)
        or m["action"] != action
        or stored["status"] != 201
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执与原命令不一致", 500)
    if m["version"] == "package-fact-change/2" and m["request_digest"] != sha(
        {"body": body, "if_match": None}
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执与原请求内容不一致", 500)
    if value != _load_record(c, scope, frozen_id, str(command.id)):
        raise DomainError("PACKAGE_FACT_CHANGE_CORRUPT", "事实操作回执与原审计不一致", 500)
    return stored, True


def confirm(actor, scope, frozen_id, key, body):
    policy.validate("ConfirmRequest", body)
    return _save(actor, scope, frozen_id, key, deepcopy(body), "confirmed")


def withdraw(actor, scope, frozen_id, key, body):
    policy.validate("WithdrawRequest", body)
    return _save(actor, scope, frozen_id, key, deepcopy(body), "withdrawn")


def _save(actor, scope, frozen_id, key, body, action):
    with connection() as c:
        require_read_committed(c)
        lock_bid(c, scope[0])
        command = Command(c, actor, KINDS[action], frozen_id, key, body)
        if command.replay is not None:
            return _replay(c, command, actor, scope, frozen_id, body, action)
        assert_work_writable(c, scope[0])
        packet = inputs.load_input(c, scope, frozen_id)
        if packet.digest != body["frozen_digest"]:
            raise DomainError(
                "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED", "冻结记录摘要与明确选择不一致", 409
            )
        head, _ = current_facts(c, scope[0])
        previous = _head(head)
        if previous != body["expected_head"]:
            raise DomainError("FACT_HEAD_CHANGED", "事实集已变化，请重读后操作", 409)
        receipt = None
        if action == "confirmed":
            receipt = read_basis(c, scope, frozen_id, packet.digest, body["fact"]["evidence_ids"])
        at = _clock(c)
        removed = body.get("replaces_fact_id") if action == "confirmed" else body["fact_id"]
        reason = body["fact"]["reason"] if action == "confirmed" else body["reason"]

        def evidence_reader(c, bid, ids):
            if receipt is None or ids != body["fact"]["evidence_ids"]:
                raise ValueError("package_fact_evidence_selection_binding")
            return receipt.basis()

        set_id, added_id = replace_set(
            c,
            scope[0],
            actor,
            reason,
            kind="withdraw" if action == "withdrawn" else "replace" if removed else "add",
            removed_id=removed,
            new_fact=body["fact"] if action == "confirmed" else None,
            command_id=command.id,
            evidence_reader=evidence_reader,
            adoption_reader=lambda conn, bid, old, decision: _adopt(conn, bid, old, decision, at),
        )
        current, _ = current_facts(c, scope[0])
        decision = current_decision(c, scope[0], "fact", added_id) if added_id else None
        recorded_at = _clock(c)
        if receipt is not None:
            # Natural expiry can happen without any source revision while cloning.
            effective_at(receipt.closure(), recorded_at)
        manifest = {
            "version": "package-fact-change/2",
            "request_digest": sha({"body": body, "if_match": None}),
            "kind": "package_fact_change",
            "command_id": str(command.id),
            "actor_id": actor,
            "action": action,
            "recorded_at": recorded_at,
            "reason": reason,
            "binding": dict(
                zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)
            )
            | {"frozen_input_id": frozen_id, "frozen_digest": packet.digest},
            "previous_head": previous,
            "head": _head(current),
            "fact_id": str(added_id or removed),
            "replaces_fact_id": body.get("replaces_fact_id") if action == "confirmed" else None,
            "decision_id": str(decision["id"]) if decision else None,
            "evidence_selection_digest": receipt.view()["selection_digest"] if receipt else None,
            "evidence_basis_digest": receipt.view()["basis_digest"] if receipt else None,
            "original_bytes_verified": False,
            "facts_qualified": False,
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        }
        if str(set_id) != manifest["head"]["id"]:
            raise ValueError("package_fact_change_head_binding")
        value = policy.seal(manifest)
        audit(
            c,
            actor,
            scope[0],
            "package.fact_confirmed" if receipt else "package.fact_withdrawn",
            value,
            command.id,
        )
        stored = command.finish(value, 201)
    return stored, False
