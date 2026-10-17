"""测试用 PDF 生成（reportlab，内置宋体 CID 字体，无需字体文件）。"""

from __future__ import annotations

import io

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def make_pdf(pages: list[list[str]], *, rotate_first: bool = False, image_first: bool = False) -> bytes:
    """每页一组文本行，自上而下排列；空列表表示一页没有文本层（模拟扫描件）。"""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(595.2756, 841.8898))
    for index, lines in enumerate(pages):
        if image_first and index == 0:
            pdf.drawImage(ImageReader(Image.new("RGB", (16, 16), "white")), 50, 100, width=480, height=600)
        pdf.setFont("STSong-Light", 12)
        for n, line in enumerate(lines):
            pdf.drawString(72, 760 - 20 * n, line)
        if rotate_first and index == 0:
            pdf.setPageRotation(90)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
