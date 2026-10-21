"""Opt-in real local Office render of imported Rich content, not sandbox attestation."""

import json
import os
from contextlib import closing
from uuid import uuid4

import pypdfium2 as pdfium
import pytest
import test_authoring_docx_import_parser as cases
import test_authoring_generated as generated_cases

from packages.authoring import docx_import_parser, rich_docx
from packages.authoring.build import render_pdf
from packages.domain.runtime import sha


@pytest.mark.skipif(
    os.environ.get("RUN_AUTHORING_RENDER") != "1",
    reason="Explicit real local LibreOffice and frozen CJK font required",
)
def test_imported_merged_table_and_embedded_image_survive_actual_pdf(tmp_path):
    source = cases.image_package(
        cases.heading("施工组织方案")
        + cases.paragraph("导入前后须保留 Quality 120 与全部单元格正文。")
        + cases.merged_table()
        + cases.image_paragraph()
        + cases.paragraph("末段原文120")
    )
    parsed = docx_import_parser.parse_docx(source)
    assert parsed["can_apply"]
    image = parsed["images"][0]
    binding = {"asset_id": str(uuid4()), "asset_revision": 1, "asset_version_id": str(uuid4())}
    sections = docx_import_parser.materialize_sections(
        docx_import_parser.public_result(parsed), {image["key"]: binding}
    )
    snapshot = generated_cases.snapshot.__wrapped__()
    snapshot["sections"] = [sections[0]["content"]]
    rewritten = rich_docx.assemble(
        snapshot,
        [{**binding, "bytes": image["bytes"], "normalization_proof": image["normalization_proof"]}],
    )
    rendered = render_pdf(
        rewritten,
        executable=os.environ.get("AUTHORING_RENDERER", "soffice"),
        font_path=os.environ.get(
            "AUTHORING_FONT_PATH", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        ),
    )
    assert rendered.state == "succeeded", rendered.gaps
    assert rendered.chain["source_docx_digest"] == sha(rewritten)
    assert rendered.chain["pdf_digest"] == sha(rendered.pdf)
    assert "RENDER_SANDBOX_NOT_ATTESTED" in rendered.gaps
    (tmp_path / "original.docx").write_bytes(source)
    (tmp_path / "imported.docx").write_bytes(rewritten)
    (tmp_path / "imported.pdf").write_bytes(rendered.pdf)
    texts, image_positions = [], []
    with closing(pdfium.PdfDocument(rendered.pdf)) as document:
        for number in range(len(document)):
            with closing(document[number]) as page:
                with closing(page.get_textpage()) as text_page:
                    texts.append(text_page.get_text_range())
                for raster in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=2):
                    left, bottom, right, top = raster.get_pos()
                    assert 0 <= left < right <= page.get_width()
                    assert 0 <= bottom < top <= page.get_height()
                    image_positions.append([number + 1, left, bottom, right, top])
                bitmap = page.render(scale=1.5)
                try:
                    bitmap.to_pil().save(tmp_path / f"page-{number + 1}.png")
                finally:
                    bitmap.close()
    combined = "".join("".join(texts).split())
    for text in ("施工组织方案", "Quality120", "合并单元格120", "工期", "90天", "末段原文120"):
        assert text in combined
    assert len(image_positions) == 1
    (tmp_path / "receipt.json").write_text(
        json.dumps(
            {
                "protocol": "synthetic-word-import-render/1",
                "source_digest": sha(source),
                "method_digest": sha(parsed["method"]),
                "content_digest": parsed["content_digest"],
                "render_chain": rendered.chain,
                "gaps": list(rendered.gaps),
                "image_positions": image_positions,
                "page_count": len(texts),
                "production_sandbox_attested": False,
                "paid_model_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
