"""Closed, deterministic OOXML report writer, independent of editable chapter limits."""

import io
import zipfile
from pathlib import Path

# Serialization only: this module never parses source XML.
from xml.etree import ElementTree as ET  # nosec B405

from packages.domain.runtime import sha

WRITER_DIGEST = sha(Path(__file__).read_bytes())
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _element(parent, name, text=None, **attrs):
    node = ET.SubElement(
        parent,
        "{" + W + "}" + name,
        {"{" + W + "}" + key: str(value) for key, value in attrs.items()},
    )
    node.text = text
    return node


def _text(parent, value):
    node = _element(_element(parent, "r"), "t", value)
    node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def _xml(element):
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def assemble_report(sections: list[tuple[str, list[str]]]) -> bytes:
    """Write all report text literally; no images, links, fields from source, or macros."""
    document = ET.Element("{" + W + "}document")
    body = _element(document, "body")
    for index, (title, lines) in enumerate(sections):
        heading = _element(body, "p")
        properties = _element(heading, "pPr")
        _element(properties, "pStyle", val="Title" if index == 0 else "Heading1")
        _element(properties, "keepNext")
        _text(heading, title)
        for line in lines:
            # Splitting long paragraphs changes neither report scope nor section count.
            for start in range(0, max(1, len(line)), 4000):
                paragraph = _element(body, "p")
                _text(paragraph, line[start : start + 4000])
    page = _element(body, "sectPr")
    footer_ref = _element(page, "footerReference", type="default")
    footer_ref.set("{" + R + "}id", "rFooter")
    _element(page, "pgSz", w=11906, h=16838)
    _element(
        page,
        "pgMar",
        top=1200,
        right=1200,
        bottom=1200,
        left=1200,
        header=567,
        footer=567,
        gutter=0,
    )

    styles = ET.Element("{" + W + "}styles")
    defaults = _element(styles, "docDefaults")
    run_properties = _element(_element(defaults, "rPrDefault"), "rPr")
    _element(
        run_properties, "rFonts", ascii="Calibri", hAnsi="Calibri", eastAsia="Noto Sans CJK SC"
    )
    _element(run_properties, "sz", val=22)
    _element(run_properties, "lang", val="zh-CN", eastAsia="zh-CN")
    paragraph_properties = _element(_element(defaults, "pPrDefault"), "pPr")
    _element(paragraph_properties, "spacing", after=120, line=300, lineRule="auto")
    for style_id, name, size in (
        ("Normal", "Normal", 22),
        ("Title", "Title", 36),
        ("Heading1", "heading 1", 28),
    ):
        style = _element(styles, "style", type="paragraph", styleId=style_id)
        _element(style, "name", val=name)
        if style_id != "Normal":
            _element(style, "basedOn", val="Normal")
            _element(style, "next", val="Normal")
            properties = _element(style, "pPr")
            _element(properties, "keepNext")
            _element(properties, "spacing", before=240, after=160)
            if style_id == "Heading1":
                _element(properties, "outlineLvl", val=0)
        properties = _element(style, "rPr")
        _element(properties, "sz", val=size)
        if style_id != "Normal":
            _element(properties, "b")

    footer = ET.Element("{" + W + "}ftr")
    paragraph = _element(footer, "p")
    _element(_element(paragraph, "pPr"), "jc", val="center")
    _text(paragraph, "范围核查报告 · 第 ")
    field = _element(paragraph, "fldSimple", instr="PAGE")
    _text(field, "1")
    _text(paragraph, " 页")

    # OPC package detection in real office readers requires the default namespace.
    # Declare it on each metadata root without mutating ElementTree's global registry.
    content_types = ET.Element("Types", xmlns=CT)
    for extension, media in (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
    ):
        ET.SubElement(content_types, "Default", Extension=extension, ContentType=media)
    for part, kind in (("document", "document.main"), ("styles", "styles"), ("footer1", "footer")):
        ET.SubElement(
            content_types,
            "Override",
            PartName="/word/" + part + ".xml",
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml."
            + kind
            + "+xml",
        )
    root_rels = ET.Element("Relationships", xmlns=PKG)
    ET.SubElement(
        root_rels,
        "Relationship",
        Id="rDocument",
        Type=R + "/officeDocument",
        Target="word/document.xml",
    )
    document_rels = ET.Element("Relationships", xmlns=PKG)
    for identifier, kind, target in (
        ("rStyles", "styles", "styles.xml"),
        ("rFooter", "footer", "footer1.xml"),
    ):
        ET.SubElement(
            document_rels,
            "Relationship",
            Id=identifier,
            Type=R + "/" + kind,
            Target=target,
        )
    parts = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/footer1.xml": footer,
        "word/_rels/document.xml.rels": document_rels,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, _xml(value))
    return output.getvalue()
