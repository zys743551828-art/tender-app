"""Existing intent/run/audit authority; fixed task transactions gain an intent guard."""

import json
from contextlib import contextmanager

from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_reports as reports
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, audit, clean, fetch
from packages.lifecycle.service import assert_work_writable
from packages.model_governance.common import GovernanceError
from packages.package_model_certification.policy import method_digest as cm
from packages.package_prediction.application import method_digest as pm
from packages.package_prediction_pipeline.policy import VERSION, method_digest, same_documents
from packages.package_prediction_reports.application import Reports
from packages.package_prediction_tasks.application import authorize
from packages.package_prediction_tasks.native import Transaction as TaskTransaction
from packages.package_prediction_tasks.native import Transactions as TaskTransactions
from packages.package_unified_reports.infrastructure import NativeUnifiedTransaction

EVENT = "package.prediction.pipeline_planned"
CANCEL = "package.prediction.pipeline_cancelled"
REJECT = "package.prediction.pipeline_rejected"


class Transaction:
    def __init__(self, c, actor, bid, scope):
        self.c, self.actor, self.bid, self.scope = c, str(actor), str(bid), str(scope)

    def context(self):
        s = clean(
            fetch(
                self.c,
                "SELECT * FROM design.bid_package_technical_scopes WHERE bid_id=%s AND id=%s",
                (self.bid, self.scope),
            )
        )
        if (
            s["actor_id"] != self.actor
            or not self.c.execute(
                "SELECT id FROM design.members WHERE id=%s AND active", (self.actor,)
            ).fetchone()
        ):
            raise DomainError(
                "PREDICTION_INTENT_ACTOR_DENIED", "不能消费其他成员的自动预测意图", 403
            )
        assert_work_writable(self.c, self.bid)
        settings = fetch(self.c, "SELECT settings FROM design.bids WHERE id=%s", (self.bid,))[
            "settings"
        ]
        scope = s["manifest"]["preview"]["manifest"]["scope"]
        row = self.c.execute(
            runs.SELECT
            + " WHERE r.bid_id=%s AND r.actor_id=%s AND r.input_manifest->'scope'=%s::jsonb ORDER BY r.created_at DESC,r.id DESC LIMIT 1",
            (self.bid, self.actor, json.dumps(scope)),
        ).fetchone()
        if row is None:
            return {
                "state": "waiting_review" if settings.get("auto_review", False) else "waiting_start"
            }
        if row["operation_state"] != "succeeded" or row["result_manifest"] is None:
            return {
                "state": "review_failed"
                if row["operation_state"] in {"failed", "cancelled", "cancel_requested"}
                else "waiting_review"
            }
        if digest(row["result_manifest"]) != row["result_digest"] or not same_documents(
            s["manifest"]["preview"]["manifest"].get("documents"),
            row["result_manifest"].get("submitted_documents"),
        ):
            return {"state": "review_context_mismatch"}
        run = runs.view(row)
        reports.binding(run)
        return {
            "state": "ready",
            "snapshot": {
                "method_digest": method_digest(),
                "scope_digest": s["digest"],
                "review_id": str(row["id"]),
                "review_input_digest": row["input_digest"],
                "review_result_digest": row["result_digest"],
                "trigger_id": str(
                    s["command_id"] if settings.get("auto_review", False) else row["command_id"]
                ),
                "trigger": "materials_ready"
                if settings.get("auto_review", False)
                else "start_review",
            },
        }

    def plan(self):
        rows = self.c.execute(
            "SELECT payload FROM design.audit_entries WHERE event_type=%s AND bid_id=%s AND actor_id=%s AND payload->>'scope'=%s",
            (EVENT, self.bid, self.actor, self.scope),
        ).fetchall()
        if len(rows) > 1:
            raise DomainError("PREDICTION_INTENT_CORRUPT", "预测意图身份冲突", 409)
        plan = rows[0]["payload"] if rows else None
        if plan and plan.get("schema") != VERSION:
            raise DomainError("PREDICTION_INTENT_VERSION", "预测意图协议版本不符", 409)
        return plan

    def marker(self, event, plan):
        return (
            self.c.execute(
                "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'command'=%s",
                (event, plan["command"]),
            ).fetchone()
            is not None
        )

    def cancelled(self, plan):
        return self.marker(CANCEL, plan)

    def rejected(self, plan):
        return self.marker(REJECT, plan)

    def candidates(self):
        if not self.c.execute(
            "SELECT to_regprocedure('package_prediction.eligible_certificates(uuid,uuid,uuid,text,text)') IS NOT NULL AS ready"
        ).fetchone()["ready"]:
            raise DomainError("PREDICTION_SELECTION_UNAVAILABLE", "预测认证选择适配尚未安装", 503)
        ids = self.c.execute(
            "SELECT package_prediction.eligible_certificates(%s,%s,%s,%s,%s) AS value",
            (self.actor, self.bid, self.scope, pm(), cm()),
        ).fetchone()["value"]
        eligible = []
        for certificate in ids:
            try:
                authorize(TaskTransaction(self.c), self.actor, self.bid, self.scope, certificate)
            except GovernanceError:
                continue
            eligible.append(certificate)
        return eligible

    def save(self, plan):
        if self.plan() is not None:
            raise DomainError("PREDICTION_INTENT_CONFLICT", "预测意图已固定", 409)
        audit(self.c, self.actor, self.bid, EVENT, plan)

    def job(self, plan):
        tx = TaskTransaction(self.c)
        job = tx.job({k: plan[k] for k in ("actor", "bid", "scope", "command", "certificate")})
        return tx.view(job) if job else None

    def cancel(self, plan):
        if self.cancelled(plan):
            return
        tx = TaskTransaction(self.c)
        job = tx.job({k: plan[k] for k in ("actor", "bid", "scope", "command", "certificate")})
        if job:
            tx.cancel(job)
        audit(self.c, self.actor, self.bid, CANCEL, {"command": plan["command"]})

    def reject(self, plan):
        if not self.rejected(plan):
            audit(self.c, self.actor, self.bid, REJECT, {"command": plan["command"]})

    def report_ready(self, plan):
        try:
            tx = NativeUnifiedTransaction(self.c)
            _, packet = Reports.snapshot(tx, self.actor, self.bid, self.scope, plan["command"])
            tx.components(self.bid, packet, plan["snapshot"]["review_id"], None)
            return True
        except (DomainError, GovernanceError):
            return False

    def guard(self, command, certificate=None):
        plan = self.plan()
        if plan and plan["command"] == command:
            if (
                (certificate is not None and str(certificate) != plan["certificate"])
                or self.cancelled(plan)
                or self.rejected(plan)
                or self.context().get("snapshot") != plan["snapshot"]
            ):
                raise DomainError(
                    "PREDICTION_INTENT_CHANGED", "启动意图已取消或固定上下文变化", 409
                )


class GuardedTransaction(TaskTransaction):
    intent: Transaction
    command: str

    def prepare(self, *args):
        self.intent.guard(self.command, args[3])
        return super().prepare(*args)

    def enqueue(self, *args):
        self.intent.guard(self.command)
        return super().enqueue(*args)

    def commit(self, *args):
        self.intent.guard(self.command)
        return super().commit(*args)


class Transactions:
    def __init__(self, connections):
        self.base = TaskTransactions(connections)

    @contextmanager
    def __call__(self, actor, bid, scope):
        with self.base({"actor": str(actor), "bid": str(bid), "scope": str(scope)}) as tx:
            yield Transaction(tx.c, actor, bid, scope)

    def tasks(self, body, publishing=None):
        @contextmanager
        def transaction():
            context = self.base(body, publishing=publishing)
            with context() if publishing else context as base:
                tx = GuardedTransaction(base.c)
                tx.publishing = publishing
                tx.intent = Transaction(base.c, body["actor"], body["bid"], body["scope"])
                tx.command = body["command"]
                yield tx

        return transaction if publishing else transaction()
