"""PDF 原生解析及渲染也在逐任务文件隔离内进行。"""

import hashlib
import json
import resource
import sys
from pathlib import Path

import pypdfium2 as pdfium
from landlock import abi_version, restrict
from renderer import (
    MAX_PDF,
    font_coverage,
    font_substitutions,
    normalized,
    read_regular,
)

job = Path(sys.argv[1]).resolve()
if job.parent != Path("/work") or not job.name.startswith("word-"):
    raise ValueError("invalid_job_directory")
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
resource.setrlimit(resource.RLIMIT_FSIZE, (2097152, 2097152))
restrict(job)
inspection = json.loads(read_regular(job / "inspection.json", 33554432))
pdf = read_regular(job / "out/source.pdf", MAX_PDF)
points = font_coverage()
result = {"gaps": []}
if not pdf.startswith(b"%PDF-"):
    raise ValueError("word_pdf_invalid")
document = pdfium.PdfDocument(pdf)
text = []
ink_pages = []
try:
    if not 0 < len(document) <= 1000:
        raise ValueError("word_pdf_page_limit")
    pixels_budget = 0
    for number in range(len(document)):
        page = document[number]
        try:
            width, height = page.get_size()
            pixels_budget += int(width * height * 0.25)
            if (
                not 0 < width <= 4000
                or not 0 < height <= 4000
                or pixels_budget > 64000000
            ):
                raise ValueError("word_pdf_render_budget")
            text_page = page.get_textpage()
            try:
                text.append(text_page.get_text_range())
            finally:
                text_page.close()
            bitmap = page.render(scale=0.5)
            try:
                pixels = bytes(bitmap.buffer)
                if pixels.count(b"\xff") != len(pixels):
                    ink_pages.append(number + 1)
            finally:
                bitmap.close()
        finally:
            page.close()
    result["page_count"] = len(document)
finally:
    document.close()
extracted = normalized("\n".join(text))
paragraphs = [
    normalized(value) for value in inspection["paragraphs"] if normalized(value)
]
missing = [value[:120] for value in paragraphs if value not in extracted]
missing_points = sorted(
    {ord(char) for char in "".join(paragraphs) if ord(char) not in points}
)
substitutions = font_substitutions(inspection["requested_fonts"])
features = inspection["unsupported_layout_features"]
if missing:
    result["gaps"].append("text_correspondence_incomplete")
if missing_points:
    result["gaps"].append("font_glyph_coverage_incomplete")
if substitutions:
    result["gaps"].append("font_substitution_requires_review")
if features:
    result["gaps"].append("complex_layout_requires_review")
if not paragraphs or not ink_pages:
    result["gaps"].append("visible_content_unverified")
result.update(
    {
        "state": "converted" if not result["gaps"] else "needs_review",
        "landlock_abi": abi_version(),
        "missing_paragraph_count": len(missing),
        "missing_examples": missing[:5],
        "missing_glyphs": [hex(point) for point in missing_points[:40]],
        "font_substitutions": substitutions,
        "ink_pages": ink_pages,
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "pdf_bytes": len(pdf),
    }
)
(job / "validation.json").write_text(
    json.dumps(result, ensure_ascii=False), encoding="utf-8"
)
