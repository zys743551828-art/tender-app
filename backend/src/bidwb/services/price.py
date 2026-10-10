"""报价方案：保存评标价规则、竞争对手报价估计与候选报价，并给出价格分模拟。每次保存追加一个版本。"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import Connection

from bidwb import db, pricing
from bidwb.access import Actor, require_project
from bidwb.errors import NotFound
from bidwb.schemas import PriceParams, PricePlan, PricePlanRequest, PricePlanWithSimulation
from bidwb.services import audit
from bidwb.util import decimal_text, new_id, utcnow


def _plan(row: db.Row) -> PricePlan:
    def prices(values: list[str]) -> list[str]:
        return [decimal_text(Decimal(v)) or v for v in values]

    return PricePlan(
        plan_id=row["id"],
        project_id=row["project_id"],
        params=PriceParams.model_validate(row["params_json"]),
        competitor_prices=prices(row["competitor_prices_json"]),
        candidate_prices=prices(row["candidate_prices_json"]),
        note=row["note"],
        supersedes=row["supersedes"],
        created_by=row["actor_id"],
        created_at=row["created_at"],
    )


def _with_simulation(row: db.Row) -> PricePlanWithSimulation:
    plan = _plan(row)
    return PricePlanWithSimulation(plan=plan, simulation=pricing.simulate(plan.params, plan.competitor_prices, plan.candidate_prices))


def get_plan(conn: Connection, actor: Actor, project_id: str) -> PricePlanWithSimulation | None:
    require_project(conn, actor, project_id)
    row = db.one(conn, "SELECT * FROM price_plans WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    return _with_simulation(row) if row else None


def list_plans(conn: Connection, actor: Actor, project_id: str) -> list[PricePlan]:
    require_project(conn, actor, project_id)
    rows = db.all_(conn, "SELECT * FROM price_plans WHERE project_id=:p ORDER BY created_at DESC, id DESC", {"p": project_id})
    return [_plan(r) for r in rows]


def get_version(conn: Connection, actor: Actor, plan_id: str) -> PricePlanWithSimulation:
    row = db.one(conn, "SELECT * FROM price_plans WHERE id=:i", {"i": plan_id})
    if row is None:
        raise NotFound("price_plan_not_found")
    require_project(conn, actor, row["project_id"])
    return _with_simulation(row)


def save_plan(conn: Connection, actor: Actor, project_id: str, req: PricePlanRequest, request_id: str) -> PricePlanWithSimulation:
    require_project(conn, actor, project_id)
    db.one(conn, "SELECT id FROM projects WHERE id=:p FOR UPDATE", {"p": project_id})  # 版本链串行
    previous = db.one(conn, "SELECT id FROM price_plans WHERE project_id=:p ORDER BY created_at DESC, id DESC LIMIT 1", {"p": project_id})
    plan_id = new_id("ppl")
    db.run(
        conn,
        """INSERT INTO price_plans(id,project_id,actor_id,params_json,competitor_prices_json,candidate_prices_json,note,supersedes,created_at)
           VALUES (:i,:p,:a,CAST(:params AS jsonb),CAST(:comp AS jsonb),CAST(:cand AS jsonb),:note,:sup,:now)""",
        {
            "i": plan_id,
            "p": project_id,
            "a": actor.member_id,
            "params": json.dumps(req.params.model_dump(mode="json"), ensure_ascii=False),
            "comp": json.dumps(req.competitor_prices),
            "cand": json.dumps(req.candidate_prices),
            "note": req.note,
            "sup": previous["id"] if previous else None,
            "now": utcnow(),
        },
    )
    audit.record(
        conn,
        actor_id=actor.member_id,
        project_id=project_id,
        action="price.save",
        object_kind="price_plan",
        object_id=plan_id,
        request_id=request_id,
        details={"candidates": len(req.candidate_prices), "competitors": len(req.competitor_prices)},
    )
    row = db.one(conn, "SELECT * FROM price_plans WHERE id=:i", {"i": plan_id})
    assert row is not None
    return _with_simulation(row)
