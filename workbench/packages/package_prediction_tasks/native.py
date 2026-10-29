"""Existing commands, audit, operations and effects; no new queue or SQL privilege."""

from contextlib import contextmanager

from packages.domain.runtime import Command, DomainError, audit, clean, enqueue_plan, fetch
from packages.lifecycle.service import assert_work_writable, lock
from packages.package_model_registry.artifact import fail
from packages.package_prediction.infrastructure import NativeTransaction
from packages.package_prediction_tasks.application import HANDLER, STEP

EVENT = "package.prediction.task_accepted"
PUBLISHED = "package.prediction.task_published"
CANCELLED = "package.prediction.task_cancelled"
BLOCKED = "package.prediction.task_blocked"


class Transaction(NativeTransaction):
    publishing: dict

    def job(self, body):
        rows = self.c.execute(
            "SELECT payload FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
            (EVENT, body["command"]),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            fail()
        job = rows[0]["payload"]
        if any(job["body"].get(k) != v for k, v in body.items()):
            fail()
        return job

    def enqueue(self, body, reference, authority):
        assert_work_writable(self.c, body["bid"])
        competing = self.c.execute(
            "SELECT a.payload FROM design.audit_entries a JOIN design.operations o ON o.id=(a.payload->>'operation_id')::uuid "
            "WHERE a.event_type=%s AND a.payload#>>'{body,scope}'=%s "
            "AND o.state NOT IN('failed','cancelled') AND NOT EXISTS(SELECT FROM design.audit_entries x "
            "WHERE x.event_type=ANY(%s) AND x.payload->>'request_id'=a.payload->>'request_id') LIMIT 1",
            (EVENT, body["scope"], [CANCELLED, BLOCKED]),
        ).fetchone()
        if competing:
            raise DomainError(
                "PREDICTION_TASK_SCOPE_FIXED", "此冻结范围已有预测任务，请恢复原请求", 409
            )
        cmd = Command(self.c, body["actor"], HANDLER, body["scope"], body["command"], body)
        if cmd.replay:
            fail()
        operation = enqueue_plan(
            self.c,
            body["bid"],
            cmd.id,
            "package-prediction",
            {"id": body["command"]},
            stages=[{"key": STEP, "depends_on": [], "required": True}],
            handler_version=HANDLER,
            topic="tender.task.review.v1",
            input_digest=reference,
        )
        job = {
            "body": body,
            "request_id": body["command"],
            "operation_id": operation["id"],
            "input_ref": reference,
            "authority_digest": authority,
        }
        audit(self.c, body["actor"], body["bid"], EVENT, job, cmd.id)
        view = self.view(job)
        cmd.finish(view, 202)
        return view

    def operation(self, job):
        row = clean(
            fetch(
                self.c,
                "SELECT * FROM design.operations WHERE id=%s AND bid_id=%s FOR UPDATE",
                (job["operation_id"], job["body"]["bid"]),
            )
        )
        if row["handler_version"] != HANDLER or row["input_digest"] != job["input_ref"]:
            fail()
        return row

    def view(self, job):
        state = self.operation(job)["state"]
        published = self.c.execute(
            "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
            (PUBLISHED, job["request_id"]),
        ).fetchone()
        if published:
            b = job["body"]
            from packages.package_model_certification.policy import method_digest as cm
            from packages.package_prediction.application import method_digest

            value = self.read(b["actor"], b["bid"], b["scope"], b["command"], method_digest(), cm())
            state = "published" if value and value["state"] in {"valid", "hidden"} else "stale"
        elif self.cancelled(job):
            state = "cancelled"
        elif self.c.execute(
            "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
            (BLOCKED, job["request_id"]),
        ).fetchone():
            state = "blocked"
        elif state == "succeeded":
            state = "awaiting_publication"
        elif state == "running":
            row = self.c.execute(
                "SELECT state FROM design.step_receipts WHERE operation_id=%s AND step_key=%s",
                (job["operation_id"], STEP),
            ).fetchone()
            if row and row["state"] == "failed":
                state = "retrying"
        return {
            "schema": HANDLER,
            "command_id": job["request_id"],
            "bid_id": job["body"]["bid"],
            "scope_id": job["body"]["scope"],
            "certificate_id": job["body"]["certificate"],
            "operation_id": job["operation_id"],
            "state": state,
            "actor_id": job["body"]["actor"],
            "prediction_ready": state == "published",
            "unified_report_state": "selection_required"
            if state == "published"
            else "prediction_pending",
            "provider_requests": 0,
        }

    def publishable(self, job):
        assert_work_writable(self.c, job["body"]["bid"])
        blocked = self.c.execute(
            "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
            (BLOCKED, job["request_id"]),
        ).fetchone()
        if self.operation(job)["state"] != "succeeded" or self.cancelled(job) or blocked:
            fail()
        row = fetch(
            self.c,
            "SELECT s.state,s.lease_until,s.input_digest,p.handler_version,p.dispatch_generation,s.fence FROM design.step_receipts s JOIN design.operation_steps p USING(operation_id,step_key,input_digest) WHERE s.operation_id=%s AND s.step_key=%s",
            (job["operation_id"], STEP),
        )
        if (
            row["state"] != "succeeded"
            or row["lease_until"] is not None
            or row["input_digest"] != job["input_ref"]
            or row["handler_version"] != HANDLER
        ):
            fail()

    def output(self, job):
        self.publishable(job)
        value = fetch(
            self.c,
            "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key=%s",
            (job["operation_id"], STEP),
        )["result"]
        if set(value) != {"input_ref", "result_ref"} or value["input_ref"] != job["input_ref"]:
            fail()
        return value

    def commit(self, *args):
        job = self.publishing
        self.publishable(job)
        result = super().commit(*args)
        self.mark_published(job)
        return result

    def block(self, job):
        if self.view(job)["state"] == "awaiting_publication":
            audit(
                self.c,
                job["body"]["actor"],
                job["body"]["bid"],
                BLOCKED,
                {
                    "request_id": job["request_id"],
                    "operation_id": job["operation_id"],
                    "reason": "AUTHORITY_CHANGED",
                },
            )
        return self.view(job)

    def cancelled(self, job):
        return (
            self.c.execute(
                "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
                (CANCELLED, job["request_id"]),
            ).fetchone()
            is not None
        )

    def cancel(self, job):
        state = self.view(job)["state"]
        if state in {"published", "stale"}:
            raise DomainError(
                "PREDICTION_ALREADY_PUBLISHED", "结果已发布，取消不能撤销认证或删除历史", 409
            )
        if not self.cancelled(job):
            op = self.operation(job)
            if op["state"] not in {"succeeded", "failed", "cancelled"}:
                self.c.execute(
                    "UPDATE design.operations SET state='cancel_requested',cancel_requested_at=clock_timestamp() WHERE id=%s",
                    (job["operation_id"],),
                )
                self.c.execute(
                    "UPDATE design.step_receipts SET lease_until=clock_timestamp() WHERE operation_id=%s AND state='running'",
                    (job["operation_id"],),
                )
            audit(
                self.c,
                job["body"]["actor"],
                job["body"]["bid"],
                CANCELLED,
                {"request_id": job["request_id"], "operation_id": job["operation_id"]},
            )
        return self.view(job)

    def mark_published(self, job):
        from packages.domain.review_identity import digest
        from packages.package_model_certification.policy import method_digest as cm
        from packages.package_prediction.application import method_digest
        from packages.package_prediction_tasks.application import authorize

        self.publishable(job)
        b = job["body"]
        if (
            digest(authorize(self, b["actor"], b["bid"], b["scope"], b["certificate"]))
            != job["authority_digest"]
        ):
            fail()
        value = self.read(b["actor"], b["bid"], b["scope"], b["command"], method_digest(), cm())
        if (
            not value
            or value["state"] not in {"valid", "hidden"}
            or value["certificate_id"] != b["certificate"]
        ):
            fail()
        if not self.c.execute(
            "SELECT 1 FROM design.audit_entries WHERE event_type=%s AND payload->>'request_id'=%s",
            (PUBLISHED, job["request_id"]),
        ).fetchone():
            audit(
                self.c,
                b["actor"],
                b["bid"],
                PUBLISHED,
                {"request_id": job["request_id"], "operation_id": job["operation_id"]},
            )


class Transactions:
    def __init__(self, connections):
        self.connections = connections

    def __call__(self, body, publishing=None):
        @contextmanager
        def transaction():
            with self.connections() as c:
                lock(c, body["bid"])
                c.execute("SELECT pg_advisory_xact_lock(91143,1)")
                tx = Transaction(c)
                tx.publishing = publishing
                if publishing is not None:
                    tx.publishable(publishing)
                yield tx

        return transaction if publishing is not None else transaction()
