"""评审报告、响应矩阵、评分预测、报价与度量，以及报告导出。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Response

from bidwb import db, pricing
from bidwb.api.deps import Body, Ctr, CurrentSession, IdemKey, mutate
from bidwb.schemas import Compliance, Metrics, Prediction, PricePlan, PricePlanRequest, PricePlanWithSimulation, PriceSimulation, Report
from bidwb.services import compliance, export, metrics, predictions, price, report

router = APIRouter(tags=["report"])
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/projects/{project_id}/report", response_model=Report, operation_id="getReport")
def get_report(project_id: str, session: CurrentSession, ctr: Ctr) -> Report:
    with ctr.engine.connect() as conn:
        return report.get_report(conn, ctr.store, session.actor, project_id)


@router.get("/projects/{project_id}/compliance", response_model=Compliance, operation_id="getCompliance")
def get_compliance(project_id: str, session: CurrentSession, ctr: Ctr, snapshot_id: str | None = None) -> Compliance:
    with ctr.engine.connect() as conn:
        return compliance.get_compliance(conn, session.actor, project_id, snapshot_id)


@router.get("/projects/{project_id}/prediction", response_model=Prediction | None, operation_id="getPrediction")
def get_prediction(project_id: str, session: CurrentSession, ctr: Ctr, snapshot_id: str | None = None) -> Prediction | None:
    with ctr.engine.connect() as conn:
        return predictions.latest(conn, ctr.store, session.actor, project_id, snapshot_id)


@router.get("/projects/{project_id}/price", response_model=PricePlanWithSimulation | None, operation_id="getPricePlan")
def get_price(project_id: str, session: CurrentSession, ctr: Ctr) -> PricePlanWithSimulation | None:
    with ctr.engine.connect() as conn:
        return price.get_plan(conn, session.actor, project_id)


@router.put("/projects/{project_id}/price", response_model=PricePlanWithSimulation, operation_id="savePricePlan")
def save_price(project_id: str, body: PricePlanRequest, session: CurrentSession, key: IdemKey, ctr: Ctr) -> Body:
    return mutate(
        ctr,
        session,
        key,
        f"PUT /projects/{project_id}/price",
        body,
        lambda c: price.save_plan(c, session.actor, project_id, body, session.request_id),
    )


@router.post("/projects/{project_id}/price:simulate", response_model=PriceSimulation, operation_id="simulatePrice")
def simulate_price(project_id: str, body: PricePlanRequest, session: CurrentSession, ctr: Ctr) -> PriceSimulation:
    """不保存，只按给定参数计算价格分；用于在页面上边调边看。"""
    with ctr.engine.connect() as conn:
        price.get_plan(conn, session.actor, project_id)  # 校验成员身份
    return pricing.simulate(body.params, body.competitor_prices, body.candidate_prices)


@router.get("/projects/{project_id}/price/history", response_model=list[PricePlan], operation_id="listPricePlans")
def price_history(project_id: str, session: CurrentSession, ctr: Ctr) -> list[PricePlan]:
    with ctr.engine.connect() as conn:
        return price.list_plans(conn, session.actor, project_id)


@router.get("/metrics", response_model=Metrics, operation_id="getMetrics")
def get_metrics(session: CurrentSession, ctr: Ctr) -> Metrics:
    with ctr.engine.connect() as conn:
        return metrics.get_metrics(conn, session.actor)


def _download(data: bytes, media_type: str, filename: str) -> Response:
    return Response(
        data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}", "Cache-Control": "private, no-store"},
    )


def _title(ctr: Ctr, project_id: str) -> str:
    with ctr.engine.connect() as conn:
        row = db.one(conn, "SELECT title FROM projects WHERE id=:p", {"p": project_id})
    return str(row["title"]) if row else project_id


@router.get(
    "/projects/{project_id}/report.docx", operation_id="exportReport", response_class=Response, responses={200: {"content": {_DOCX: {}}}}
)
def export_report(project_id: str, session: CurrentSession, ctr: Ctr) -> Response:
    with ctr.engine.connect() as conn:
        data = export.report_docx(conn, ctr.store, session.actor, project_id)
    return _download(data, _DOCX, f"{_title(ctr, project_id)}-评审报告.docx")


@router.get(
    "/projects/{project_id}/body.annotated.pdf",
    operation_id="exportAnnotatedBody",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def export_annotated(project_id: str, session: CurrentSession, ctr: Ctr) -> Response:
    with ctr.engine.connect() as conn:
        data = export.annotated_pdf(conn, ctr.store, session.actor, project_id)
    return _download(data, "application/pdf", f"{_title(ctr, project_id)}-批注版.pdf")
