from __future__ import annotations

import pytest

from bidwb.parsing import ParseError, parse_pdf, split_chunks
from tests.pdfs import make_pdf


def test_split_chunks_breaks_at_headings_and_keeps_offsets() -> None:
    text = "第一章 工程概况\r\n本工程位于合肥，\r\n工期一百八十天。\r\n1.2 质量标准\r\n合格。"
    spans = split_chunks(text)
    assert [text[a:b].replace("\r\n", "|") for a, b in spans] == [
        "第一章 工程概况|本工程位于合肥，|工期一百八十天。",
        "1.2 质量标准|合格。",
    ]
    assert all(0 <= a < b <= len(text) for a, b in spans)


def test_headings_start_new_chunks() -> None:
    text = "第一章 总则\r\n内容甲。\r\n第二章 施工部署\r\n内容乙。"
    assert len(split_chunks(text)) == 2


def test_parse_extracts_text_pages_and_bbox() -> None:
    doc = parse_pdf(make_pdf([["第一章 工程概况", "本工程工期为一百八十日历天。"], ["第二章 施工部署"]]))
    assert doc.page_count == 2 and doc.coverage == "complete"
    assert [c.physical_page for c in doc.chunks] == [1, 2]
    assert doc.chunks[0].quote.startswith("第一章 工程概况") and "一百八十日历天" in doc.chunks[0].quote  # 标题与正文同块，保留上下文
    box = doc.chunks[0].bbox
    assert box is not None and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
    assert box[1] < 0.2  # 文本在页面上部：归一化 y 以左上为原点


def test_blank_page_reported_as_gap_not_hidden() -> None:
    doc = parse_pdf(make_pdf([["第一章 工程概况，内容充足。"], []]))
    assert doc.coverage == "partial" and doc.gaps == ["page_2:no_text_layer"]


def test_all_blank_is_failed() -> None:
    assert parse_pdf(make_pdf([[], []])).coverage == "failed"


def test_rotated_page_has_no_fake_bbox() -> None:
    doc = parse_pdf(make_pdf([["第一章 横向页面，内容充足。"]], rotate_first=True))
    assert doc.chunks and doc.chunks[0].bbox is None and "page_1:rotated_no_bbox" in doc.gaps


def test_not_a_pdf_raises() -> None:
    with pytest.raises(ParseError):
        parse_pdf(b"this is not a pdf")


def test_join_drops_line_end_hyphen_marker_and_xml_illegal_characters() -> None:
    from bidwb.parsing import _join
    from bidwb.util import xml_safe

    assert _join(["ana\ufffe", "lysis\x0b ok"]) == "analysis ok"
    assert xml_safe("A\x00B\uffffC\n") == "ABC\n"
