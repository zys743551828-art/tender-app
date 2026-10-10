"""报告导出：Word 评审报告，以及在正文 PDF 上批注问题位置的批注版。

批注版使用 PDF 标准的高亮批注（Contents 里是问题说明），在常见阅读器里可直接查看和回复；
页面有旋转、没有坐标的证据只标注在页面左上角，不画虚构的高亮位置。
"""

from __future__ import annotations

import ctypes
import io
from datetime import datetime

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from sqlalchemy import Connection

from bidwb import db
from bidwb.access import Actor, require_project
from bidwb.errors import Conflict, NotFound, Unprocessable
from bidwb.schemas import Calibration, Finding, Report
from bidwb.services import findings as findings_service
from bidwb.services import projects as projects_service
from bidwb.services import report as report_service
from bidwb.storage import ObjectStore
from bidwb.util import xml_safe

MAX_PDF_BYTES = 60 * 1024 * 1024
CATEGORY_LABELS = {
    "disqualification": "废标／否决风险",
    "response": "强制性要求未满足",
    "consistency": "前后矛盾",
    "scope": "范围残留",
    "improvement": "改进建议",
}
VERDICT_LABELS = {"satisfied": "满足", "violated": "违反", "unclear": "无法判断", "failed": "检查失败"}
KIND_LABELS = {
    "disqualification": "否决项",
    "mandatory": "强制性要求",
    "scoring": "评分条款",
    "recommendation": "建议性要求",
    "exception": "例外",
}
STATUS_LABELS = {
    "candidate": "待复核",
    "confirmed": "已确认待修改",
    "rejected": "已驳回",
    "deferred": "暂缓",
    "revision_pending": "修改中",
    "recheck_pending": "待复检",
    "resolved": "已解决",
}
_COLORS = {
    "disqualification": (230, 57, 70),
    "response": (230, 57, 70),
    "consistency": (244, 162, 97),
    "scope": (244, 162, 97),
    "improvement": (255, 214, 10),
}


def _findings(conn: Connection, project_id: str, snapshot_id: str) -> list[Finding]:
    rows = db.all_(
        conn,
        findings_service.SELECT_SQL + "WHERE f.project_id=:p AND f.snapshot_id=:s ORDER BY f.severity, f.created_at, f.id",
        {"p": project_id, "s": snapshot_id},
    )
    order = {c: i for i, c in enumerate(CATEGORY_LABELS)}
    items = [findings_service.finding_from_row(conn, r) for r in rows]
    return sorted(items, key=lambda f: (order[f.category], {"critical": 0, "normal": 1, "improvement": 2}[f.severity]))


# ------------------------------------------------------------------ Word
def _font(doc: DocxDocument) -> None:
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def _table(doc: DocxDocument, header: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    for cell, text in zip(table.rows[0].cells, header, strict=True):
        cell.text = xml_safe(text)
    for row in rows:
        for cell, text in zip(table.add_row().cells, row, strict=True):
            cell.text = xml_safe(text)


_FLAG_LABELS = {"over_max_limit": "超过最高限价", "abnormal_low": "异常低价风险"}


def _calibration_text(cal: Calibration) -> str:
    if cal.state == "calibrated":
        return f"基于 {cal.pairs} 组预测与官方成绩，按百分制平均绝对误差 {cal.mae}，平均偏差 {cal.bias}。"
    if cal.state == "insufficient":
        return f"已有 {cal.pairs}/{cal.needed_pairs} 组预测与官方成绩，样本不足，暂不给误差。"
    return "尚无登记的官方成绩可对照。"


def _qualification_section(doc: DocxDocument, report: Report) -> None:
    doc.add_heading("一、废标／否决与强制性要求", level=1)
    q = report.qualification.qualification
    doc.add_paragraph(f"共 {q.total} 条：满足 {q.satisfied}，违反 {q.violated}，无法判断 {q.unclear}，检查失败 {q.failed}。")
    _table(
        doc,
        ["类型", "条款", "判定", "说明"],
        [
            [
                KIND_LABELS.get(r.kind, r.kind),
                r.statement,
                VERDICT_LABELS[r.verdict] + ("" if r.rule_basis == "confirmed" else "（规则未确认）"),
                r.note,
            ]
            for r in report.qualification.rows
            if r.kind in ("disqualification", "mandatory")
        ],
    )


def _findings_section(doc: DocxDocument, items: list[Finding]) -> None:
    doc.add_heading("二、问题清单", level=1)
    for category, label in CATEGORY_LABELS.items():
        group = [f for f in items if f.category == category]
        if not group:
            continue
        doc.add_heading(f"{label}（{len(group)}）", level=2)
        for finding in group:
            run = doc.add_paragraph(style="List Bullet").add_run(xml_safe(f"[{STATUS_LABELS[finding.status]}] {finding.statement}"))
            if finding.severity == "critical":
                run.font.color.rgb = RGBColor(0xC0, 0x1F, 0x2F)
            for ev in finding.evidence:
                doc.add_paragraph(xml_safe(f"　第 {ev.physical_page} 页：{ev.quote}"))


def _prediction_section(doc: DocxDocument, report: Report, show_score: bool) -> None:
    """关闭“显示分数”时只列失分点，不出现任何分数估计。"""
    p = report.prediction
    doc.add_heading("三、评分预测" if show_score else "三、可能的失分点", level=1)
    if p is None or p.status != "candidate":
        doc.add_paragraph(xml_safe(p.reason) if p else "尚未生成评估。")
    elif show_score:
        if p.validation_status == "validated_in_scope":
            doc.add_paragraph(f"技术标预计 {p.estimated_value} 分（区间 {p.low}–{p.high}，满分 {p.maximum}）。{p.reason}")
        else:
            doc.add_paragraph(
                f"技术标估计（未校准）{p.estimated_value} 分（区间 {p.low}–{p.high}，评分条款合计 {p.maximum} 分）。{p.reason}"
            )
        doc.add_paragraph("在线对照：" + _calibration_text(p.calibration))
        _table(doc, ["评分条款", "估计失分", "评估"], [[t.topic, t.points_lost, t.assessment] for t in p.topics])
    else:
        _table(doc, ["评分条款", "评估"], [[t.topic, t.assessment] for t in p.topics])


def _price_section(doc: DocxDocument, report: Report) -> None:
    doc.add_heading("四、报价", level=1)
    if report.price is None:
        doc.add_paragraph("尚未填写评标价规则。")
        return
    rate = report.price.exchange_rate
    doc.add_paragraph(
        f"报价高于基准价每 1% 扣 {rate.points_per_pct_above} 分"
        + (f"，1 个技术分约相当于 {rate.pct_per_point_above}% 的报价。" if rate.pct_per_point_above else "。")
    )
    _table(
        doc,
        ["候选报价", "相对基准价", "价格分", "提示"],
        [[c.price, f"{c.deviation_pct}%", c.score, "、".join(_FLAG_LABELS[f] for f in c.flags)] for c in report.price.candidates],
    )


def report_docx(conn: Connection, store: ObjectStore, actor: Actor, project_id: str) -> bytes:
    require_project(conn, actor, project_id)
    report: Report = report_service.get_report(conn, store, actor, project_id)
    project = db.one(conn, "SELECT title,tender_number,lot FROM projects WHERE id=:p", {"p": project_id})
    assert project is not None
    settings = projects_service.settings_of(conn, project_id)
    doc = Document()
    _font(doc)
    doc.add_heading(xml_safe(f"{project['title']} 施组评审报告"), level=0)
    doc.add_paragraph(
        f"招标编号：{project['tender_number'] or '—'}　标段：{project['lot'] or '—'}　评审轮次：第 {report.round_no} 轮　"
        f"生成时间：{datetime.now().astimezone():%Y-%m-%d %H:%M}"
    )
    basis = report.basis
    doc.add_paragraph(
        f"评审依据：共 {basis.rules_total} 条招标规则，其中 {basis.rules_confirmed} 条已人工确认，{basis.rules_unconfirmed} 条尚未确认"
        + (
            "（本项目设置为按原文接受未确认的规则）。"
            if settings.accept_rules_as_written
            else "（未确认的规则以模型提取的原文为准，结论供参考）。"
        )
    )
    _qualification_section(doc, report)
    _findings_section(doc, _findings(conn, project_id, report.snapshot_id))
    _prediction_section(doc, report, settings.show_score)
    if settings.price:
        _price_section(doc, report)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ------------------------------------------------------------------ 批注版 PDF
def annotated_pdf(conn: Connection, store: ObjectStore, actor: Actor, project_id: str) -> bytes:
    require_project(conn, actor, project_id)
    last = db.one(
        conn,
        """SELECT s.id,s.body_version_id FROM input_snapshots s WHERE s.project_id=:p
           AND EXISTS (SELECT 1 FROM jobs d WHERE d.snapshot_id=s.id AND d.kind='diagnosis' AND d.state='succeeded')
           ORDER BY s.as_of DESC, s.id DESC LIMIT 1""",
        {"p": project_id},
    )
    if last is None:
        raise NotFound("report_not_ready", "还没有完成的评审")
    source = db.one(
        conn,
        "SELECT a.object_key,a.byte_size,a.media_type FROM file_versions fv JOIN artifacts a ON a.id=fv.artifact_id WHERE fv.id=:v",
        {"v": last["body_version_id"]},
    )
    if source is None:
        raise NotFound("file_not_found")
    if source["media_type"] != "application/pdf":
        raise Conflict("body_not_pdf", "正文不是 PDF，无法生成批注版")
    if source["byte_size"] > MAX_PDF_BYTES:
        raise Unprocessable("body_too_large", "正文过大，无法在线生成批注版")
    items = [f for f in _findings(conn, project_id, last["id"]) if f.status not in ("rejected", "resolved")]
    document = pdfium.PdfDocument(store.get(source["object_key"]))
    try:
        for finding in items:
            text = f"【{CATEGORY_LABELS[finding.category]}】{finding.statement}"
            for ev in finding.evidence:
                if ev.version_id != last["body_version_id"] or not 1 <= ev.physical_page <= len(document):
                    continue
                page = document[ev.physical_page - 1]
                try:
                    _annotate(page, ev.bbox, _COLORS[finding.category], text)
                finally:
                    page.close()
        out = io.BytesIO()
        document.save(out)
        return out.getvalue()
    finally:
        document.close()


def _annotate(page: pdfium.PdfPage, bbox: list[float] | None, color: tuple[int, int, int], text: str) -> None:
    width, height = page.get_size()
    if bbox is None:
        left, right, top, bottom = 12.0, 40.0, height - 12.0, height - 32.0  # 无坐标：页面左上角的标记
    else:
        left, right, top, bottom = bbox[0] * width, bbox[2] * width, (1 - bbox[1]) * height, (1 - bbox[3]) * height
    annot = pdfium_raw.FPDFPage_CreateAnnot(page, pdfium_raw.FPDF_ANNOT_HIGHLIGHT)
    try:
        pdfium_raw.FPDFAnnot_SetRect(annot, pdfium_raw.FS_RECTF(left=left, bottom=bottom, right=right, top=top))
        pdfium_raw.FPDFAnnot_AppendAttachmentPoints(
            annot, pdfium_raw.FS_QUADPOINTSF(x1=left, y1=top, x2=right, y2=top, x3=left, y3=bottom, x4=right, y4=bottom)
        )
        pdfium_raw.FPDFAnnot_SetColor(annot, pdfium_raw.FPDFANNOT_COLORTYPE_Color, *color, 110)
        buffer = (text + "\0").encode("utf-16-le")
        pdfium_raw.FPDFAnnot_SetStringValue(
            annot, b"Contents", ctypes.cast(ctypes.create_string_buffer(buffer), ctypes.POINTER(ctypes.c_ushort))
        )
    finally:
        pdfium_raw.FPDFPage_CloseAnnot(annot)
