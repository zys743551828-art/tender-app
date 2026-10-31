"""Actual OOXML and PDFium evidence, including story/page-boundary negatives."""
# ruff: noqa: F811

import io
import zipfile
from copy import deepcopy
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from test_word_prebuilt import docx, runtime  # noqa: F401

from packages.word_intake import prebuilt, static_layout
from packages.word_intake.inspection import inspect_docx


def source(pages=("Synthetic 123",), *, extra="", header="Header 7", footer="Footer 9"):
    with zipfile.ZipFile(io.BytesIO(docx())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    w = static_layout.W
    paragraphs = []
    for index, text in enumerate(pages):
        if index:
            paragraphs.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        paragraphs.append(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
    section = '<w:sectPr><w:headerReference w:type="default" r:id="head"/><w:footerReference w:type="default" r:id="foot"/><w:pgSz w:w="11900" w:h="16840"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr>'
    parts["word/document.xml"] = (
        f'<w:document xmlns:w="{w}" xmlns:r="{static_layout.R}"><w:body>'
        + "".join(paragraphs)
        + extra
        + section
        + "</w:body></w:document>"
    ).encode()
    parts["word/_rels/document.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="{identity}" Target="{kind}.xml" Type="{static_layout.R}/{kind}"/>'
            for identity, kind in (("head", "header"), ("foot", "footer"))
        )
        + "</Relationships>"
    ).encode()
    for kind, name, text in (("header", "hdr", header), ("footer", "ftr", footer)):
        parts[f"word/{kind}.xml"] = (
            f'<w:{name} xmlns:w="{w}"><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:{name}>'.encode()
        )
        parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
            b"</Types>",
            f'<Override PartName="/word/{kind}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/></Types>'.encode(),
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output.getvalue()


def rendered(
    pages=("Synthetic 123",),
    *,
    header="Header 7",
    footer="Footer 9",
    footer_y=30,
    width=595,
    body_mode=0,
    body_white=False,
    cover_body=False,
):
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(width, 842), pageCompression=0)
    for text in pages:
        canvas.drawString(60, 800, header)
        canvas.saveState()
        if body_white:
            canvas.setFillColorRGB(1, 1, 1)
        body = canvas.beginText(60, 750)
        body.setTextRenderMode(body_mode)
        body.textOut(text)
        canvas.drawText(body)
        canvas.restoreState()
        if cover_body:
            canvas.setFillColorRGB(1, 1, 1)
            canvas.rect(50, 735, 300, 30, fill=1, stroke=0)
            canvas.setFillColorRGB(0, 0, 0)
        canvas.drawString(60, footer_y, footer)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def check(original, pdf):
    inspection = inspect_docx(original)
    assert inspection["conversion_eligible"]
    prepared = static_layout.prepare(original)
    assert prepared is not None
    return static_layout.inspect_pdf(pdf, prepared, inspection)


def test_static_stories_are_verified_separately_from_every_body_character():
    result = check(source(), rendered())
    assert result["gaps"] == []
    assert result["stories"] == [
        {
            "physical_page": 1,
            "header_matches": True,
            "footer_matches": True,
            "body_character_count": 12,
        }
    ]


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"header": ""}, "WORD_STATIC_STORY_CORRESPONDENCE_UNVERIFIED"),
        ({"header": "Header 8"}, "WORD_STATIC_STORY_CORRESPONDENCE_UNVERIFIED"),
        ({"footer": "Footer 8"}, "WORD_STATIC_STORY_CORRESPONDENCE_UNVERIFIED"),
        ({"footer_y": 700}, "WORD_STATIC_STORY_CORRESPONDENCE_UNVERIFIED"),
        ({"pages": ("Synthetic 124",)}, "WORD_TEXT_CORRESPONDENCE_UNVERIFIED"),
        ({"pages": ("Header 7 Synthetic 123",)}, "WORD_TEXT_CORRESPONDENCE_UNVERIFIED"),
        ({"pages": ("Synthetic 123 Footer 9",)}, "WORD_TEXT_CORRESPONDENCE_UNVERIFIED"),
        ({"width": 610}, "WORD_PAGE_GEOMETRY_UNVERIFIED"),
    ],
)
def test_missing_changed_misplaced_or_duplicated_story_is_not_globally_stripped(kwargs, expected):
    assert expected in check(source(), rendered(**kwargs))["gaps"]


def test_actual_source_page_break_must_be_an_actual_pdf_boundary():
    original = source(("First 123", "Second 456"))
    assert check(original, rendered(("First 123", "Second 456")))["gaps"] == []
    result = check(original, rendered(("First 123 Second 456",)))
    assert "WORD_EXPLICIT_PAGE_BREAK_UNVERIFIED" in result["gaps"]
    assert "WORD_TEXT_CORRESPONDENCE_UNVERIFIED" not in result["gaps"]


def test_source_construct_outside_static_scope_keeps_a_gap():
    original = source(extra="<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>Hidden</w:t></w:r></w:p>")
    assert (
        "WORD_STATIC_SOURCE_CONSTRUCT_UNSUPPORTED"
        in check(original, rendered(("Synthetic 123 Hidden",)))["gaps"]
    )


@pytest.mark.parametrize("kwargs", [{"body_mode": 3}, {"body_white": True}, {"cover_body": True}])
def test_extractable_but_invisible_or_obscured_body_never_qualifies(kwargs):
    assert "WORD_TEXT_VISIBILITY_UNVERIFIED" in check(source(), rendered(**kwargs))["gaps"]


def test_unhandled_column_break_is_not_collapsed_into_a_supported_paragraph():
    original = source(("First 123", "Second 456"))
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b'w:type="page"', b'w:type="column"'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    assert (
        "WORD_STATIC_SOURCE_CONSTRUCT_UNSUPPORTED"
        in check(output.getvalue(), rendered(("First 123 Second 456",)))["gaps"]
    )


def image_source(transform=""):
    picture = f'''<w:p><w:r><w:drawing><wp:inline xmlns:wp="{static_layout.WP}" xmlns:a="{static_layout.A}" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><wp:extent cx="63500" cy="63500"/><wp:docPr id="1" name="synthetic"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="1" name="synthetic.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="image"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm {transform}><a:off x="0" y="0"/><a:ext cx="63500" cy="63500"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''
    with zipfile.ZipFile(io.BytesIO(source(extra=picture))) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/_rels/document.xml.rels"] = parts["word/_rels/document.xml.rels"].replace(
        b"</Relationships>",
        f'<Relationship Id="image" Target="media/synthetic.png" Type="{static_layout.R}/image"/></Relationships>'.encode(),
    )
    parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
        b"</Types>", b'<Default Extension="png" ContentType="image/png"/></Types>'
    )
    pixels = io.BytesIO()
    with Image.new("RGB", (2, 2), "black") as image:
        image.save(pixels, format="PNG")
    parts["word/media/synthetic.png"] = pixels.getvalue()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize("transform", ['rot="10800000"', 'flipH="1"', 'flipV="1"'])
def test_transformed_inline_source_cannot_reuse_untransformed_pixel_evidence(transform):
    original = image_source(transform)
    assert inspect_docx(original)["conversion_eligible"]
    assert static_layout.prepare(original) is None
    assert static_layout.prepare(image_source()) is not None


def test_original_unsupported_complex_document_still_uses_conservative_path():
    assert static_layout.prepare(docx(complex_layout=True)) is None


def test_worker_render_uses_static_proof_not_a_host_coverage_claim(runtime, monkeypatch, tmp_path):
    monkeypatch.setattr(
        prebuilt,
        "_call",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"200\n" + rendered()),
    )
    result = prebuilt.render(source(), runtime.profile, receipt=tmp_path / "owned.json")
    assert result["coverage"] == "complete"
    assert result["measurements"]["protocol"] == "word-static-correspondence/1"
    assert result["isolation"]["own_job_cleanup_confirmed"]


def test_static_inspector_identity_change_invalidates_the_previous_profile(monkeypatch):
    identity = prebuilt._fixed()
    profile = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    original = static_layout.identity()
    monkeypatch.setattr(static_layout, "identity", lambda: original | {"source_digest": "0" * 64})
    with pytest.raises(prebuilt.PrebuiltError, match="WORD_PREBUILT_PROFILE_CHANGED"):
        prebuilt.validate_profile(profile)


def test_joint_object_order_and_source_break_are_both_required():
    prepared = {
        "snapshot": {
            "sections": [{"content": [{"attrs": {"id": "table"}}, {"attrs": {"id": "image"}}]}]
        },
        "object_chunks": {"table": 0, "image": 1},
    }
    tables = {
        "coverage": "complete",
        "tables": [{"node_id": "table", "physical_page": 1, "bbox": [10, 100, 100, 200]}],
    }
    images = {
        "coverage": "complete",
        "images": [{"node_id": "image", "physical_page": 2, "bbox": [10, 100, 100, 200]}],
    }
    assert static_layout._object_order(prepared, tables, images, {12: [1]}, [12], 2)
    wrong = deepcopy(images)
    wrong["images"][0]["physical_page"] = 1
    assert not static_layout._object_order(prepared, tables, wrong, {12: [1]}, [12], 2)
    assert not static_layout._object_order(prepared, tables, images, {12: [1, 2]}, [12], 2)
