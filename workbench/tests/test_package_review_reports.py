"""Real OOXML bytes from explicit synthetic reports; no renderer or model claims."""
# ruff: noqa: F401,F811

import io
import os
import zipfile
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
from test_package_review_decisions import case, make, report, request, uid

from packages.contracts.package_review_reports_api import valid
from packages.domain import package_review_reports as reports
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def human_snapshot(run, decision=None):
    value = {key: run[key] for key in ("scope", "frozen_input_id", "execution_input_id")}
    value.update(run_id=run["id"], result_digest=run["result"]["digest"])
    value["items"] = [
        {"requirement_id": row["requirement_id"], "row_digest": digest(row), "current": None}
        for row in sorted(
            run["result"]["manifest"]["matrix"], key=lambda item: item["requirement_id"]
        )
    ]
    if decision:
        manifest = decision["manifest"]
        row = next(
            row for row in value["items"] if row["requirement_id"] == manifest["requirement_id"]
        )
        row["current"] = {
            key: manifest[key]
            for key in ("id", "sequence_no", "actor_id", "created_at", "state", "reason")
        } | {"digest": decision["digest"]}
    return value


def frozen(run, decision=None):
    public, private = reports.context(
        run,
        human_snapshot(run, decision),
        reports.source_profile() | {"pdf_renderer": None},
        "RENDERER_UNAVAILABLE",
    )
    assert valid("PackageReviewReportContext", public)
    return reports.freeze(private, "docx")


def text(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert "[Content_Types].xml" in names
        assert not any("vba" in name.lower() for name in names)
        xml = archive.read("word/document.xml")
        assert b"<!DOCTYPE" not in xml and b"<!ENTITY" not in xml
        return "\n".join(ET.fromstring(xml).itertext())


def render(run, snapshot):
    return reports.document(
        snapshot, run, export_id=uid(700), captured_at="2026-10-21T02:00:00.000000Z"
    )


def test_actual_docx_contains_every_row_evidence_and_separate_human_opinion(report):
    decision = make(
        report,
        request(report, state="rejected")
        | {"reason": "不采用：需重新核对工期适用范围 <复核> & 原文"},
    )
    original = deepcopy(report)
    snapshot = frozen(report, decision)
    raw = render(report, snapshot)
    content = text(raw)
    assert render(report, snapshot) == raw  # Stored inputs produce reproducible OOXML.
    for row in report["result"]["manifest"]["matrix"]:
        assert row["requirement_statement"] in content
        assert row["statement"] in content
        for quote in row["target_quotes"] + row["authority_quotes"]:
            assert quote["quote"] in content
            assert quote["evidence_id"] in content and quote["parse_run_id"] in content
    assert "不采用此项判断" in content and decision["manifest"]["reason"] in content
    assert "当前来源效力未在导出时重新核验" in content
    assert "不是提交正文" in content and "不代表相关风险已解决" in content
    assert report["result"]["digest"] in content and snapshot["context_digest"] in content
    assert "适用范围：适用" in content and "物理页 1-2" in content
    assert "尚未证明要求清单涵盖全部招标语义" in content
    assert "'part_id':" not in content and "'shared_attachment':" not in content
    assert report == original


def test_all_400_rows_are_exported_and_last_quote_cannot_be_filtered_out(report):
    matrix = []
    for index in range(400):
        row = deepcopy(report["result"]["manifest"]["matrix"][0])
        row["requirement_id"] = uid(10000 + index)
        row["requirement_statement"] = f"合成条款 {index + 1} 全部保留"
        matrix.append(row)
    value = deepcopy(report)
    value["result"]["manifest"].update(matrix=matrix, requirement_count=400)
    value["result"]["manifest"]["counts"][matrix[0]["verdict"]] = 400
    value["result"]["digest"] = digest(value["result"]["manifest"])
    content = text(render(value, frozen(value)))
    assert all(row["requirement_statement"] in content for row in matrix)
    assert content.count("条款ID：") == 400


def test_report_preserves_numeric_heading_paths_from_frozen_package_documents(report):
    from packages.domain.package_scope_review import validate_contract

    value = deepcopy(report)
    part = value["result"]["manifest"]["submitted_documents"][0]["parts"][0]
    part["heading_path"] = [1, 2, 11]
    validate_contract("Result", value["result"]["manifest"])
    value["result"]["digest"] = digest(value["result"]["manifest"])
    content = text(render(value, frozen(value)))
    assert "目录 1 / 2 / 11" in content
    assert part["part_id"] in content


def test_400_rows_with_maximum_quotes_do_not_hit_editable_chapter_limits(report):
    from packages.domain.package_scope_review import validate_contract

    value = deepcopy(report)
    rows = []
    for number in range(400):
        row = deepcopy(report["result"]["manifest"]["matrix"][0])
        row["requirement_id"] = uid(10000 + number)
        row["requirement_statement"] = f"完整引用条款 {number + 1}"
        for group in ("target_quotes", "authority_quotes"):
            quote = deepcopy(row[group][0])
            row[group] = [
                quote | {"quote": f"引用 {number + 1}-{index + 1} " + "证据" * 900}
                for index in range(20)
            ]
        rows.append(row)
    value["result"]["manifest"].update(matrix=rows, requirement_count=400)
    value["result"]["manifest"]["counts"][rows[0]["verdict"]] = 400
    validate_contract("Result", value["result"]["manifest"])
    value["result"]["digest"] = digest(value["result"]["manifest"])
    raw = render(value, frozen(value))
    content = text(raw)
    assert content.count("条款ID：") == 400 and content.count("原文：") == 16000
    assert rows[-1]["authority_quotes"][-1]["quote"] in content


@pytest.mark.parametrize(
    "field",
    ["scope", "frozen_input_id", "execution_input_id", "run_id", "input_digest", "result_digest"],
)
def test_rehashed_snapshot_cannot_switch_original_run_identity(report, field):
    snapshot = frozen(report)
    snapshot["context"][field] = (
        {**report["scope"], "bid_id": uid(888)}
        if field == "scope"
        else "b" * 64
        if field.endswith("digest")
        else uid(888)
    )
    snapshot["context_digest"] = digest(snapshot["context"])
    with pytest.raises(DomainError) as error:
        render(report, snapshot)
    assert error.value.code == "PACKAGE_REVIEW_REPORT_CORRUPT"


def test_human_basis_and_qualification_tampering_are_rejected(report):
    snapshot = frozen(report)
    snapshot["context"]["human_decisions"]["items"][0]["row_digest"] = "0" * 64
    snapshot["context_digest"] = digest(snapshot["context"])
    with pytest.raises(DomainError):
        render(report, snapshot)
    snapshot = frozen(report)
    snapshot["submission_eligible"] = True
    with pytest.raises(DomainError):
        render(report, snapshot)


def test_missing_converter_preserves_real_docx_capability_and_refuses_pdf(report, monkeypatch):
    monkeypatch.setenv("AUTHORING_RENDERER", "/definitely-unavailable/scope-report-renderer")
    monkeypatch.setenv("AUTHORING_FONT_PATH", "/definitely-unavailable/scope-report-font")
    profile, unavailable = reports.method_profile()
    public, context = reports.context(report, human_snapshot(report), profile, unavailable)
    assert (
        public["formats"] == ["docx"] and public["pdf_unavailable_code"] == "RENDERER_UNAVAILABLE"
    )
    assert text(render(report, reports.freeze(context, "docx")))
    with pytest.raises(DomainError, match="Word"):
        reports.freeze(context, "pdf")


def test_unfinished_run_has_no_report_context(report):
    report["operation"]["state"] = "running"
    report["result"] = None
    with pytest.raises(DomainError) as error:
        reports.binding(report)
    assert error.value.code == "PACKAGE_REVIEW_REPORT_NOT_READY"


@pytest.mark.skipif(
    os.environ.get("RUN_AUTHORING_RENDER") != "1", reason="需真实LibreOffice及中文字体"
)
def test_real_report_pdf_opens_every_section_and_prints_physical_page_numbers(report):
    import pypdfium2

    from packages.authoring.build import render_pdf

    result = render_pdf(
        render(report, frozen(report)),
        executable=os.environ.get("AUTHORING_RENDERER", "soffice"),
        font_path=os.environ.get(
            "AUTHORING_FONT_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        ),
    )
    assert result.state == "succeeded", result.gaps
    document = pypdfium2.PdfDocument(result.pdf)
    contents = []
    try:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                content = textpage.get_text_bounded()
                assert f"第 {index + 1} 页" in content.replace("\r\n", " ")
                contents.append(content)
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()
    text_content = "\n".join(contents)
    assert "投标文件范围核查报告" in text_content
    assert "版本与复查依据" in text_content
    for row in report["result"]["manifest"]["matrix"]:
        assert row["requirement_statement"] in text_content
        assert row["requirement_id"] in text_content
