"""正文结构：标题分级、目录行、跨页章节、没有标题时按篇幅切片段；解析时标题单独成行。"""

from __future__ import annotations

from bidwb.ai.sections import SEGMENT_CHARS, build_sections, heading_of
from bidwb.checks import Passage
from bidwb.parsing import chunk_text, parse_pdf
from tests.pdfs import make_pdf


def _p(n: int, text: str, page: int = 1) -> Passage:
    return Passage(f"e{n}", page, text)


def test_chapter_and_cn_numbering_are_levels_one_and_two_deeper_merge() -> None:
    passages = [
        _p(1, "施工组织设计\n某道路工程"),
        _p(2, "第一章 施工部署\n本工程分三个施工段。"),
        _p(3, "一、施工段划分\n按桩号划分为三段。"),
        _p(4, "（一）第一施工段\nK0+000～K1+200。", page=2),
        _p(5, "二、施工顺序\n先管线后路基。", page=2),
        _p(6, "第二章 施工进度计划\n总工期一百八十日历天。", page=3),
        _p(7, "一、关键线路\n路基—基层—面层。", page=3),
    ]
    sections = build_sections(passages)
    assert [s.level for s in sections] == [1, 1, 2, 3, 2, 1, 2]
    assert sections[1].evidence_ids == ("e2", "e3", "e4", "e5")
    assert sections[2].evidence_ids == ("e3", "e4")
    assert sections[3].parent_id == sections[2].id
    assert sections[3].label == "第一章 施工部署 › 一、施工段划分 › （一）第一施工段"
    assert sections[3].first_page == 2


def test_numeric_outline_keeps_deep_nodes_and_single_chapter() -> None:
    passages = [
        _p(1, "1 工程概况\n概况"),
        _p(2, "1.1 范围\n含排水"),
        _p(3, "1.1.1 管网\n雨污分流"),
        _p(4, "1.1.1.1 雨水\n开挖"),
        _p(5, "1.1.1.1.1 支护\n钢板桩"),
    ]
    sections = build_sections(passages)
    assert [s.level for s in sections] == [1, 2, 3, 4, 5]
    assert sections[0].evidence_ids == tuple(f"e{n}" for n in range(1, 6))
    assert sections[-1].parent_id == sections[-2].id
    many = build_sections([_p(i, f"第{i}章 施工方法\n内容") for i in range(1, 82)])
    assert len(many) == 81 and many[-1].title.startswith("第81章")


def test_toc_lines_and_long_numbered_paragraphs_are_not_headings() -> None:
    assert heading_of("第一章 施工部署……………………3") is None
    assert heading_of("第一章 施工部署        3") is None
    assert heading_of("1. 本工程采用的施工方法经过了多个同类项目的验证，能够满足工期与质量的要求，并且具有成本优势。") is None
    assert heading_of("第一章 施工部署\n正文") is not None


def test_documents_without_headings_fall_back_to_segments() -> None:
    passages = [_p(i, "路基施工采用分层填筑、分层压实的方法。" * 30, page=i) for i in range(1, 9)]
    sections = build_sections(passages)
    assert [s.title for s in sections][:2] == ["片段 1", "片段 2"] and len(sections) > 1
    assert all(s.chars >= SEGMENT_CHARS for s in sections[:-1])
    assert sum(len(s.evidence_ids) for s in sections) == len(passages)
    assert build_sections([]) == []


def test_parser_keeps_heading_line_separate() -> None:
    assert chunk_text(["第一章 工程概况", "本工程位于合肥，", "工期一百八十天。"]) == "第一章 工程概况\n本工程位于合肥，工期一百八十天。"
    assert chunk_text(["本工程位于合肥，", "工期一百八十天。"]) == "本工程位于合肥，工期一百八十天。"
    doc = parse_pdf(make_pdf([["第一章 施工进度计划", "本工程计划总工期为二百四十日历天。"]]))
    assert doc.chunks[0].quote == "第一章 施工进度计划\n本工程计划总工期为二百四十日历天。"
