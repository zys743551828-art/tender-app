"""Reuse native result, human-decision and pricing readers; no new record store."""

import json
from contextlib import contextmanager

from packages.domain import bid_package_review_decision_repository as decisions
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import package_review_reports as reports
from packages.domain.bid_package_service import lock_bid
from packages.domain.runtime import DomainError, clean, fetch
from packages.package_prediction.infrastructure import NativeTransaction
from packages.pricing.repository import simulation_view


class NativeUnifiedTransaction(NativeTransaction):
    def components(self, bid, packet, run_id, simulation_id):
        source = packet["authority"]["source"]["current_source"]
        scope = source["scope_manifest"]["preview"]["manifest"]["scope"]
        row = self.c.execute(
            runs.SELECT + " WHERE r.bid_id=%s AND r.id=%s", (bid, run_id)
        ).fetchone()
        if row is None:
            raise DomainError("UNIFIED_REPORT_NOT_READY", "尚无所选完成评审", 404)
        run = runs.view(row)
        if run["scope"] != scope:
            raise DomainError("UNIFIED_REPORT_SCOPE_CHANGED", "核查与预测并非同一冻结范围", 409)
        if run["operation"]["state"] != "succeeded" or run["result"] is None:
            raise DomainError("UNIFIED_REPORT_NOT_READY", "所选评审尚未成功完成", 404)
        reports.binding(run)
        # Latest *completed* review of this exact scope, not a silent latest selection.
        latest = self.c.execute(
            "SELECT r.id FROM design.bid_package_review_runs r JOIN design.operations o ON o.id=r.operation_id "
            "WHERE r.bid_id=%s AND r.input_manifest->'scope'=%s::jsonb AND o.state='succeeded' "
            "ORDER BY o.finished_at DESC NULLS LAST,r.created_at DESC,r.id DESC LIMIT 1",
            (bid, json.dumps(scope)),
        ).fetchone()
        if latest is None or str(latest["id"]) != str(run_id):
            raise DomainError(
                "UNIFIED_REPORT_REVIEW_SUPERSEDED", "请选择该冻结范围最近完成的评审", 409
            )
        settings = clean(fetch(self.c, "SELECT settings FROM design.bids WHERE id=%s", (bid,)))[
            "settings"
        ]
        pricing = None
        if settings.get("pricing", True):
            if simulation_id is not None:
                pricing = simulation_view(self.c, bid=bid, identity=simulation_id)
                if not pricing["current_applicability"]["applicable"]:
                    raise DomainError("UNIFIED_REPORT_PRICE_STALE", "报价依据已失效", 409)
        elif simulation_id is not None:
            raise DomainError(
                "UNIFIED_REPORT_PRICE_DISABLED", "报价模块已关闭，不能组合旧报价", 409
            )
        return {
            "run": run,
            "human": decisions.current(self.c, run),
            "settings": settings,
            "pricing": pricing,
            "simulation_id": str(simulation_id) if simulation_id else None,
        }


class NativeUnifiedTransactions:
    def __init__(self, connections, bid):
        self.connections, self.bid = connections, bid

    @contextmanager
    def __call__(self):
        with self.connections() as c:
            lock_bid(c, self.bid)
            yield NativeUnifiedTransaction(c)
