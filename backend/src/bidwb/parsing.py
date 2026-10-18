"""PDF 解析：文本层提取、按语义单元切分为证据块、计算页面坐标。

只依赖 pypdfium2（Apache-2.0/BSD）。刻意不用 PyMuPDF：它是 AGPL，作为公司内部网络服务使用时的许可风险需要法务确认，
而本阶段没有它才能做到的能力。

诚实边界（写进 ``gaps``，不静默略过）：
* 没有文本层的页（扫描件、整页图片）不会产生证据，标记 ``page_N:no_text_layer``，需要 OCR 才能覆盖，当前不含 OCR；
* 表格目前按文本块处理，不识别表格结构；
* 图片对象无论是否伴有文字，都标记 ``page_N:raster_images_unread``；装饰背景也可能触发，不猜测图片用途；
* 页面有旋转时坐标需要变换，当前不输出坐标（``bbox`` 为 ``None``，前端只显示整页，不画虚构高亮）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import pypdfium2 as pdfium

from bidwb.util import xml_safe

PARSER_VERSION = "pdfium-1.4"
MAX_CHUNK_CHARS = 400
MIN_PAGE_CHARS = 3  # 文字层为空的低字符阈值；有页码或标题不能证明业务内容已覆盖。

# 标题与条款起始：第X章/节/条、1.2.3、（一）、一、
HEADING = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零〇\d]+[章节条款篇部]|\d+(?:\.\d+){0,4}[\s、.．]|[（(][一二三四五六七八九十\d]+[）)]|[一二三四五六七八九十]+[、.．])"
)
_CJK = re.compile(r"[㐀-鿿豈-﫿，。；：！？、）】》]")

Coverage = Literal["complete", "partial", "failed"]


class ParseError(Exception):
    """文件无法作为 PDF 打开（损坏、加密、类型不符）。"""


@dataclass(frozen=True)
class Chunk:
    physical_page: int
    quote: str
    bbox: list[float] | None
    kind: Literal["text", "table", "visual_observation"] = "text"
    source: Literal["native", "ocr", "native_table", "raster_grid"] = "native"
    confidence: float | None = None
    numeric_review_required: bool = False


@dataclass
class PageCoverage:
    physical_page: int
    text_layer: Literal["extracted", "empty", "failed"] = "failed"
    text_chars: int = 0
    raster_images: int | None = None
    issues: list[str] = field(default_factory=list)
    table_structure: Literal["not_evaluated"] = "not_evaluated"
    figure_semantics: Literal["not_evaluated"] = "not_evaluated"


@dataclass
class ParsedDocument:
    page_count: int
    chunks: list[Chunk] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    page_text_chars: list[int] = field(default_factory=list)
    pages: list[PageCoverage] = field(default_factory=list)

    @property
    def coverage(self) -> Coverage:
        if self.page_count == 0 or not self.chunks:
            return "failed"
        return "partial" if self.gaps else "complete"


def _join(lines: list[str]) -> str:
    """合并折行：中文之间不加空格，西文之间补一个空格；行末连字符（pdfium 标为 U+FFFE）处直接接上。"""
    out = ""
    hyphenated = False
    for line in lines:
        piece = xml_safe(line).strip()  # 控制字符与 U+FFFE 不能进入证据原文
        if not piece:
            continue
        if out and not hyphenated and not (_CJK.match(out[-1]) or _CJK.match(piece[0])):
            out += " "
        out += piece
        hyphenated = line.rstrip().endswith("\ufffe")
    return out


def chunk_text(lines: list[str]) -> str:
    """一个证据块的文字。块以标题行开头时，标题单独成第一行（其后接换行），正文从第二行起：
    章节结构（``ai.sections``）据此取标题；证据落地校验忽略空白，不受影响。"""
    pieces = [line for line in lines if xml_safe(line).strip()]
    if len(pieces) > 1 and HEADING.match(pieces[0]):
        return _join(pieces[:1]) + "\n" + _join(pieces[1:])
    return _join(pieces)


def split_chunks(text: str) -> list[tuple[int, int]]:
    """把页文本切成语义块，返回每块在 ``text`` 中的 ``(起, 止)`` 字符区间（半开）。

    规则：遇到标题/条款起始行，或当前块已超过 ``MAX_CHUNK_CHARS`` 且行末是句末标点，就另起一块。
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    start: int | None = None
    length = 0
    last_end = 0
    previous_ends_sentence = False
    for raw in text.splitlines(keepends=True):
        line_start, line_end = pos, pos + len(raw)
        pos = line_end
        stripped = raw.strip()
        if not stripped:
            continue
        if start is not None and (HEADING.match(stripped) or (length >= MAX_CHUNK_CHARS and previous_ends_sentence)):
            spans.append((start, last_end))
            start, length = None, 0
        if start is None:
            start = line_start
        length += len(stripped)
        last_end = line_start + len(raw.rstrip())
        previous_ends_sentence = stripped[-1] in "。；！？.;!?"
    if start is not None:
        spans.append((start, last_end))
    return spans


def _bbox(textpage: pdfium.PdfTextPage, start: int, end: int, width: float, height: float) -> list[float] | None:
    left = bottom = float("inf")
    right = top = float("-inf")
    for index in range(start, end):
        char_left, char_bottom, char_right, char_top = textpage.get_charbox(index)
        if char_right - char_left <= 0 or char_top - char_bottom <= 0:
            continue  # 空白与换行符的盒子没有意义
        left, bottom = min(left, char_left), min(bottom, char_bottom)
        right, top = max(right, char_right), max(top, char_top)
    if right < left or top < bottom or width <= 0 or height <= 0:
        return None
    # PDF 坐标原点在左下，输出归一化坐标 [x0, y0, x1, y1]，原点在左上。
    box = [left / width, 1 - top / height, right / width, 1 - bottom / height]
    return [round(min(max(v, 0.0), 1.0), 5) for v in box]


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise ParseError("无法打开 PDF（文件损坏、已加密或类型不符）") from exc
    try:
        result = ParsedDocument(page_count=len(document))
        for number in range(1, len(document) + 1):
            coverage = PageCoverage(number)
            result.pages.append(coverage)
            result.page_text_chars.append(0)
            try:
                page = document[number - 1]
                try:
                    _parse_page(page, number, result, coverage)
                finally:
                    page.close()
            except pdfium.PdfiumError:
                # 读取故障只影响本物理页；之前提取的文字保留，但本页不得标作已覆盖。
                coverage.text_layer = "failed"
                coverage.issues.append("page_read_failed")
            result.gaps.extend(f"page_{number}:{issue}" for issue in coverage.issues)
        return result
    finally:
        document.close()


def _parse_page(page: pdfium.PdfPage, number: int, result: ParsedDocument, coverage: PageCoverage) -> None:
    coverage.raster_images = sum(1 for _ in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]))
    if coverage.raster_images:
        coverage.issues.append("raster_images_unread")
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_range()
        meaningful = len(text.strip())
        result.page_text_chars[number - 1] = meaningful
        coverage.text_chars = meaningful
        if meaningful < MIN_PAGE_CHARS:
            coverage.text_layer = "empty"
            coverage.issues.append("no_text_layer")
            return
        coverage.text_layer = "extracted"
        rotated = page.get_rotation() % 360 != 0
        if rotated:
            coverage.issues.append("rotated_no_bbox")
        width, height = page.get_size()
        for start, end in split_chunks(text):
            quote = chunk_text(text[start:end].splitlines())
            if not quote:
                continue
            result.chunks.append(Chunk(number, quote, None if rotated else _bbox(textpage, start, end, width, height)))
    finally:
        textpage.close()
