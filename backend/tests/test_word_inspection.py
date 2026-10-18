"""Word 转换器的容器核验只读 ZIP；外部关系和动态域不能执行。"""

from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "deploy/word/inspection.py"
SPEC = importlib.util.spec_from_file_location("word_inspection_tested", SOURCE)
assert SPEC is not None and SPEC.loader is not None
inspection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspection)


def make_word(
    text: str = "施工组织设计，工期180日历天，费用15.12‰。", *, body_xml: str | None = None, extra: dict[str, bytes] | None = None
) -> bytes:
    content_types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    if body_xml is None:
        body_xml = f'<w:p><w:r><w:rPr><w:rFonts w:ascii="Noto Sans CJK SC" w:eastAsia="Noto Sans CJK SC"/></w:rPr><w:t>{escape(text)}</w:t></w:r></w:p>'
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body_xml + "</w:body></w:document>"
    )
    parts = {"[Content_Types].xml": content_types.encode(), "_rels/.rels": root_rels.encode(), "word/document.xml": document.encode()}
    parts.update(extra or {})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return stream.getvalue()


def test_plain_word_is_eligible_and_private_text_is_not_public_report() -> None:
    result = inspection.inspect_docx(make_word())
    assert result["conversion_eligible"] and result["container_validated"]
    assert result["requested_fonts"] == ["Noto Sans CJK SC"]
    assert "180" in "".join(result["paragraphs"])
    assert "paragraphs" not in inspection.public_report(result)


def test_external_hyperlink_never_becomes_a_conversion_request() -> None:
    external = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="url" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://invalid.example/word" TargetMode="External"/></Relationships>'
    result = inspection.inspect_docx(make_word(extra={"word/_rels/document.xml.rels": external}))
    assert not result["conversion_eligible"] and "EXTERNAL_RELATIONSHIP" in result["active_content_gaps"]


@pytest.mark.parametrize(
    "field",
    ['<w:fldSimple w:instr="PAGE"/>', "<w:r><w:instrText>DDEAUTO</w:instrText></w:r>", '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'],
)
def test_even_display_fields_are_not_silently_evaluated(field: str) -> None:
    result = inspection.inspect_docx(make_word(body_xml=f"<w:p>{field}</w:p>"))
    assert not result["conversion_eligible"] and "FIELD_EVALUATION_UNSUPPORTED" in result["active_content_gaps"]


def test_archive_path_escape_and_xml_entities_are_rejected() -> None:
    with pytest.raises(inspection.InspectionError):
        inspection.inspect_docx(make_word(extra={"../outside.xml": b"<x/>"}))
    malicious = b'<!DOCTYPE x [<!ENTITY file SYSTEM "file:///etc/passwd">]><x>&file;</x>'
    with pytest.raises(inspection.InspectionError):
        inspection.inspect_docx(make_word(extra={"word/extra.xml": malicious}))


def test_zip_expansion_is_bounded_before_xml_parsing() -> None:
    with pytest.raises(inspection.InspectionError):
        inspection.inspect_docx(make_word(extra={"word/extra.xml": b" " * (inspection.MAX_ENTRY + 1)}))
