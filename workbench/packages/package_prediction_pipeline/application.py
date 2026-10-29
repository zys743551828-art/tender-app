"""Resolve one authority-backed candidate; never choose by score or latest model."""

from uuid import UUID, uuid5

from packages.domain.errors import DomainError
from packages.domain.review_identity import digest
from packages.model_governance.common import GovernanceError
from packages.package_prediction_pipeline.policy import VERSION


def identity(actor, scope):
    return str(uuid5(UUID(str(scope)), VERSION + ":" + str(actor)))


class Pipeline:
    def __init__(self, transactions, jobs):
        self.transactions, self.jobs = transactions, jobs

    def read(self, actor, bid, scope):
        with self.transactions(actor, bid, scope) as tx:
            context = tx.context()
            plan = tx.plan()
            state = context["state"]
            if plan is None and state == "ready":
                candidates = tx.candidates()
                state = (
                    "certificate_missing"
                    if not candidates
                    else "awaiting_submission"
                    if len(candidates) == 1
                    else "certificate_ambiguous"
                )
            job = None
            ready = False
            if plan:
                if tx.cancelled(plan):
                    state = "cancelled"
                elif tx.rejected(plan):
                    state = "blocked"
                elif context.get("snapshot") != plan["snapshot"]:
                    state = "context_changed"
                else:
                    job = tx.job(plan)
                    state = job["state"] if job else "accepted"
                    if state == "published":
                        ready = tx.report_ready(plan)
                        state = "ready" if ready else "report_blocked"
            return {
                "schema": VERSION,
                "actor_id": str(actor),
                "bid_id": str(bid),
                "scope_id": str(scope),
                "state": state,
                "command_id": plan["command"] if plan else None,
                "certificate_id": plan["certificate"] if plan else None,
                "review_id": plan["snapshot"]["review_id"] if plan else None,
                "context_digest": digest(plan["snapshot"]) if plan else None,
                "report_ready": ready,
                "provider_requests": 0,
            }

    def advance(self, actor, bid, scope):
        with self.transactions(actor, bid, scope) as tx:
            plan = tx.plan()
            if plan is None:
                context = tx.context()
                if context["state"] != "ready":
                    return self._unplanned(actor, bid, scope, context["state"])
                candidates = tx.candidates()
                if len(candidates) != 1:
                    return self._unplanned(
                        actor,
                        bid,
                        scope,
                        "certificate_missing" if not candidates else "certificate_ambiguous",
                    )
                plan = {
                    "schema": VERSION,
                    "actor": str(actor),
                    "bid": str(bid),
                    "scope": str(scope),
                    "command": identity(actor, scope),
                    "certificate": candidates[0],
                    "snapshot": context["snapshot"],
                }
                tx.save(plan)
            cancelled = tx.cancelled(plan) or tx.rejected(plan)
            changed = tx.context().get("snapshot") != plan["snapshot"]
        if not cancelled and not changed:
            try:
                self.jobs.submit(actor, bid, scope, plan["certificate"], plan["command"])
                self.jobs.advance(actor, bid, scope, plan["command"])
            except (DomainError, GovernanceError) as error:
                if getattr(error, "retryable", False) or getattr(error, "status", 0) >= 500:
                    raise
                with self.transactions(actor, bid, scope) as tx:
                    tx.reject(plan)
        return self.read(actor, bid, scope)

    def cancel(self, actor, bid, scope, command):
        with self.transactions(actor, bid, scope) as tx:
            plan = tx.plan()
            if plan is None or plan["command"] != str(command):
                raise DomainError("PREDICTION_INTENT_CHANGED", "预测意图已变化", 409)
            tx.cancel(plan)
        return self.read(actor, bid, scope)

    @staticmethod
    def _unplanned(actor, bid, scope, state):
        return {
            "schema": VERSION,
            "actor_id": str(actor),
            "bid_id": str(bid),
            "scope_id": str(scope),
            "state": state,
            "command_id": None,
            "certificate_id": None,
            "review_id": None,
            "context_digest": None,
            "report_ready": False,
            "provider_requests": 0,
        }
