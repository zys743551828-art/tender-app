"""OCR chapter hints tolerate token spacing without changing evidence."""

import pytest

from packages.parsing.core import HEADING


@pytest.mark.parametrize(
    "text",
    [
        "第一章施工方案",
        "第 一 章 施工方案",
        "第 十 二 章 质量要求",
        "第 12 章 风险",
        "第\t三\t篇 说明",
        "1. Scope",
        "1.2 Details",
    ],
)
def test_heading_prefix_accepts_horizontal_ocr_token_spacing(text):
    assert HEADING.match(text)


@pytest.mark.parametrize(
    "text",
    ["第 一 条合同要求", "第\n一章", "第一\n章", "正文提到第一章", "第安全章", "第一", "施工方案"],
)
def test_heading_prefix_does_not_merge_lines_or_invent_a_chapter(text):
    assert not HEADING.match(text)
