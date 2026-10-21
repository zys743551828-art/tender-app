"""Actual bounded OOXML import; no storage, HTTP, model, database, or renderer."""

from __future__ import annotations

import copy
import io
import json
import zipfile
from html import escape
from uuid import uuid4
from xml.etree import ElementTree as ET

import httpx
import pytest
import requests
from PIL import Image, PngImagePlugin

from packages.authoring import content, rich_content, rich_docx, rich_images
from packages.authoring import docx_import_parser as parser
from packages.authoring.docx_import_support import LIMITS
from packages.domain.runtime import DomainError, sha

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DEFAULT_STYLES = "".join(
    f'<w:style w:type="paragraph" w:styleId="Heading{i}"><w:name w:val="Heading {i}"/>'
    f'<w:pPr><w:outlineLvl w:val="{i - 1}"/></w:pPr></w:style>'
    for i in range(1, 7)
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("DOCX import must not invoke HTTP or model services")

    async def forbidden_async(*_args, **_kwargs):
        forbidden()

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async)


def package(
    body, *, styles=DEFAULT_STYLES, numbering="", parts=None, relations=(), extra_types=None
):
    entries = dict(parts or {})
    entries["word/document.xml"] = (
        f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    ).encode()
    linked = []
    if styles is not None:
        entries["word/styles.xml"] = f'<w:styles xmlns:w="{W}">{styles}</w:styles>'.encode()
        linked.append(("styles", R + "/styles", "styles.xml", "Internal"))
    if numbering:
        entries["word/numbering.xml"] = (
            f'<w:numbering xmlns:w="{W}">{numbering}</w:numbering>'.encode()
        )
        linked.append(("numbering", R + "/numbering", "numbering.xml", "Internal"))
    linked.extend(relations)
    entries["_rels/.rels"] = (
        f'<Relationships xmlns="{REL}"><Relationship Id="office" Type="{R}/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    ).encode()
    entries["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{REL}">'
        + "".join(
            f'<Relationship Id="{escape(identity)}" Type="{escape(kind)}" Target="{escape(target)}" TargetMode="{mode}"/>'
            for identity, kind, target, mode in linked
        )
        + "</Relationships>"
    ).encode()
    types = {"word/document.xml": DOCX + ".main+xml", **(extra_types or {})}
    entries["[Content_Types].xml"] = (
        f'<Types xmlns="{CT}"><Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="png" ContentType="image/png"/><Default Extension="jpg" ContentType="image/jpeg"/>'
        + "".join(
            f'<Override PartName="/{name}" ContentType="{media}"/>' for name, media in types.items()
        )
        + "</Types>"
    ).encode()
    return archive(entries)


def archive(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    return output.getvalue()


def parts(data):
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


def paragraph(text="", *, props="", runs=None):
    body = (
        runs if runs is not None else f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    )
    return f"<w:p><w:pPr>{props}</w:pPr>{body}</w:p>"


def heading(text, level=1):
    return paragraph(text, props=f'<w:pStyle w:val="Heading{level}"/>')


def numbered(text, number=1, level=0):
    return paragraph(
        text, props=f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{number}"/></w:numPr>'
    )


def numbering(*, start=1, label=None, fmt="decimal"):
    abstract = "".join(
        f'<w:abstractNum w:abstractNumId="{number}">'
        + "".join(
            f'<w:lvl w:ilvl="{level}"><w:start w:val="{start}"/><w:numFmt w:val="{kind}"/>'
            f'<w:lvlText w:val="{label or ("•" if kind == "bullet" else "%" + str(level + 1) + ".")}"/></w:lvl>'
            for level in range(5)
        )
        + "</w:abstractNum>"
        for number, kind in ((1, fmt), (2, "bullet"))
    )
    return abstract + "".join(
        f'<w:num w:numId="{number}"><w:abstractNumId w:val="{number}"/></w:num>'
        for number in (1, 2)
    )


def merged_table(*, continuation="", first_width=1800):
    return (
        '<w:tbl><w:tblPr><w:tblLayout w:type="fixed"/><w:tblCaption w:val="工程量表"/></w:tblPr>'
        f'<w:tblGrid><w:gridCol w:w="{first_width}"/><w:gridCol w:w="2100"/><w:gridCol w:w="900"/></w:tblGrid>'
        '<w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr>'
        + paragraph("合并单元格 120")
        + "</w:tc><w:tc><w:tcPr/>"
        + paragraph("工期")
        + '</w:tc></w:tr><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr>'
        + paragraph(continuation)
        + "</w:tc><w:tc><w:tcPr/>"
        + paragraph("90 天")
        + "</w:tc></w:tr></w:tbl>"
    )


def raster(fmt="PNG"):
    output = io.BytesIO()
    image = Image.new("RGB", (12, 8), (71, 110, 180))
    if fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("comment", "synthetic private test metadata")
        image.save(output, fmt, pnginfo=info)
    else:
        image.save(output, fmt)
    return output.getvalue()


def image_paragraph(*, before="", after=""):
    image = rich_docx.picture(
        {"width_twips": 2400, "height_twips": 1600, "alt": "施工示意图"}, "picture", 1
    )
    if before:
        run = ET.Element("{" + W + "}r")
        ET.SubElement(run, "{" + W + "}t").text = before
        image.insert(0, run)
    if after:
        run = ET.SubElement(image, "{" + W + "}r")
        ET.SubElement(run, "{" + W + "}t").text = after
    return ET.tostring(image, encoding="unicode")


def image_package(body=None, *, fmt="PNG"):
    suffix = "png" if fmt == "PNG" else "jpg"
    return package(
        body or heading("施工方法") + image_paragraph(),
        parts={"word/media/figure." + suffix: raster(fmt)},
        relations=[("picture", R + "/image", "media/figure." + suffix, "Internal")],
    )


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def text_of(node):
    return node.get("text", "") + "".join(text_of(item) for item in node.get("content", []))


def test_exact_bytes_deterministic_hierarchy_titles_and_node_mapping():
    data = package(
        paragraph("前言")
        + heading("施工方法")
        + paragraph("原文 120")
        + heading("安全措施", 2)
        + paragraph("保留末段")
        + heading("进度计划")
    )
    first, second = parser.parse_docx(data), parser.parse_docx(data)
    assert first == second
    assert first["can_apply"]
    assert first["source_digest"] == sha(data) and first["source_byte_size"] == len(data)
    assert first["method"] == parser.method_identity()
    assert first["content_digest"] == parser.result_digest(first)
    sections = first["sections"]
    assert [s["title"] for s in sections] == ["导入正文", "施工方法", "安全措施", "进度计划"]
    assert [s["parent_key"] for s in sections] == [None, None, sections[1]["key"], None]
    assert [s["ordinal"] for s in sections] == [0, 1, 2, 3]
    assert text_of(sections[1]["content"]) == "原文 120"
    assert not any(n["type"] == "heading" for s in sections for n in s["content"]["content"])
    for section in sections:
        content.validate_content(section["content"])
    assert len({m["node_id"] for m in first["mapping"]}) == len(first["mapping"])
    assert all(m["source_path"].startswith("word/document.xml/body/") for m in first["mapping"])
    assert "SECTION_TITLE_GENERATED" in codes(first)


def test_style_inheritance_toggle_direct_override_whitespace_and_breaks():
    styles = DEFAULT_STYLES + (
        '<w:style w:type="paragraph" w:styleId="Base"><w:rPr><w:b/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Child"><w:basedOn w:val="Base"/><w:rPr><w:b/><w:i/></w:rPr></w:style>'
    )
    data = package(
        heading("Title")
        + paragraph(
            props='<w:pStyle w:val="Child"/>',
            runs='<w:r><w:t xml:space="preserve">  A  </w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r><w:r><w:rPr><w:b/><w:i w:val="0"/></w:rPr><w:t>D</w:t></w:r>',
        ),
        styles=styles,
    )
    result = parser.parse_docx(data)
    assert result["can_apply"]
    nodes = result["sections"][0]["content"]["content"][0]["content"]
    assert nodes[0] == {"type": "text", "text": "  A  ", "marks": [{"type": "italic"}]}
    assert nodes[1]["text"] == "\t" and nodes[3] == {"type": "hardBreak"}
    assert nodes[-1]["marks"] == [{"type": "bold"}]
    assert text_of(result["sections"][0]["content"]) == "  A  \tBCD"


def test_supported_nested_lists_keep_item_structure_and_order():
    data = package(
        heading("施工步骤")
        + numbered("第一项")
        + numbered("第一项的子项", level=1)
        + numbered("第二项")
        + paragraph("结束")
        + numbered("项目符号", number=2),
        numbering=numbering(),
    )
    result = parser.parse_docx(data)
    assert result["can_apply"]
    blocks = result["sections"][0]["content"]["content"]
    assert [n["type"] for n in blocks] == ["orderedList", "paragraph", "bulletList"]
    assert len(blocks[0]["content"]) == 2
    assert blocks[0]["content"][0]["content"][1]["type"] == "orderedList"
    assert text_of(blocks[0]) == "第一项第一项的子项第二项"


@pytest.mark.parametrize("variant", ["resume", "start", "composite", "format", "gap"])
def test_numbering_that_would_change_values_is_blocked(variant):
    definition = numbering(
        start=5 if variant == "start" else 1,
        label="%1.%2." if variant == "composite" else None,
        fmt="upperRoman" if variant == "format" else "decimal",
    )
    body = numbered("项目", level=2 if variant == "gap" else 0)
    if variant == "resume":
        body += paragraph("中断") + numbered("应续号2")
    result = parser.parse_docx(package(heading("编号") + body, numbering=definition))
    assert not result["can_apply"]
    assert codes(result) & {
        "NUMBERING_UNSUPPORTED",
        "LIST_CONTINUATION_UNSUPPORTED",
        "LIST_LEVEL_GAP",
    }


def test_actual_table_grid_combined_spans_widths_header_caption_and_cell_text():
    result = parser.parse_docx(package(heading("施工组织") + merged_table()))
    assert result["can_apply"]
    table = result["sections"][0]["content"]["content"][0]
    grid = rich_content.table_grid(table)
    assert table["attrs"]["column_widths_twips"] == [1800, 2100, 900]
    assert table["attrs"]["caption"] == "工程量表"
    assert table["content"][0]["content"][0]["attrs"] | {"id": "ignored"} == {
        "id": "ignored",
        "colspan": 2,
        "rowspan": 2,
        "header": True,
    }
    assert len(table["content"][1]["content"]) == 1
    assert grid["grid"][0][0] is grid["grid"][1][1]
    assert text_of(table) == "合并单元格 120工期90 天"


@pytest.mark.parametrize(
    "variant", ["width", "continuation_text", "orphan", "mismatch", "nested", "legacy"]
)
def test_malformed_or_unrepresented_table_content_never_silently_disappears(variant):
    body = merged_table(
        continuation="续行隐藏的120" if variant == "continuation_text" else "",
        first_width=0 if variant == "width" else 1800,
    )
    if variant == "orphan":
        body = body.replace('<w:vMerge w:val="restart"/>', "")
    elif variant == "mismatch":
        body = body.replace(
            '<w:gridSpan w:val="2"/><w:vMerge/>', '<w:gridSpan w:val="1"/><w:vMerge/>'
        )
    elif variant == "nested":
        body = body.replace(paragraph("工期"), merged_table())
    elif variant == "legacy":
        body = body.replace('<w:gridSpan w:val="2"/>', '<w:hMerge w:val="restart"/>')
    result = parser.parse_docx(package(heading("Table") + body))
    assert not result["can_apply"]
    assert any(
        issue["severity"] == "blocker" and issue["code"].startswith("TABLE_")
        for issue in result["issues"]
    )


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_embedded_image_original_bytes_normalized_proof_and_geometry_are_bound(fmt):
    data = image_package(fmt=fmt)
    result = parser.parse_docx(data)
    assert result["can_apply"]
    assert len(result["images"]) == 1
    source = result["images"][0]
    original = parts(data)[source["source_part"]]
    assert source["original_bytes"] == original
    assert source["source_digest"] == sha(original)
    rich_images.verify_normalized(source["bytes"], source["normalization_proof"])
    block = result["sections"][0]["content"]["content"][0]
    assert block["type"] == "image" and block["attrs"]["asset_id"] == source["key"]
    assert block["attrs"]["width_twips"] == 2400 and block["attrs"]["height_twips"] == 1600
    assert block["attrs"]["alt"] == "施工示意图"
    public = parser.public_result(result)
    assert not {"bytes", "original_bytes"} & public["images"][0].keys()
    json.dumps(public, ensure_ascii=False)
    assert parser.result_digest(public) == result["content_digest"]


def test_inline_picture_splits_preserving_reading_order_with_explicit_loss():
    result = parser.parse_docx(
        image_package(heading("顺序") + image_paragraph(before="图前文字120", after="图后文字90"))
    )
    assert result["can_apply"]
    blocks = result["sections"][0]["content"]["content"]
    assert [b["type"] for b in blocks] == ["paragraph", "image", "paragraph"]
    assert text_of(blocks[0]) == "图前文字120" and text_of(blocks[2]) == "图后文字90"
    assert "INLINE_IMAGE_MOVED_TO_BLOCK" in codes(result)


@pytest.mark.parametrize(
    "variant", ["floating", "crop", "rotate", "hyperlink", "unknown_effect", "table"]
)
def test_image_layout_or_actions_not_representable_are_blocked(variant):
    source = image_paragraph()
    root = ET.fromstring(source)
    if variant == "floating":
        node = root.find(".//{" + rich_docx.WP + "}inline")
        node.tag = "{" + rich_docx.WP + "}anchor"
    elif variant == "crop":
        fill = root.find(".//{" + rich_docx.PIC + "}blipFill")
        ET.SubElement(fill, "{" + rich_docx.A + "}srcRect", {"l": "10000"})
    elif variant == "rotate":
        root.find(".//{" + rich_docx.A + "}xfrm").set("rot", "60000")
    elif variant == "hyperlink":
        ET.SubElement(
            root.find(".//{" + rich_docx.WP + "}docPr"), "{" + rich_docx.A + "}hlinkClick"
        )
    elif variant == "unknown_effect":
        ET.SubElement(root.find(".//{" + rich_docx.A + "}blip"), "{" + rich_docx.A + "}grayscl")
    body = ET.tostring(root, encoding="unicode")
    if variant == "table":
        body = merged_table().replace(paragraph("工期"), body)
    result = parser.parse_docx(image_package(heading("Images") + body))
    assert not result["can_apply"]


def test_all_image_bindings_are_required_and_only_registered_versions_are_written():
    result = parser.parse_docx(image_package())
    original = copy.deepcopy(result["sections"])
    identity = result["images"][0]["key"]
    binding = {"asset_id": str(uuid4()), "asset_revision": 1, "asset_version_id": str(uuid4())}
    materialized = parser.materialize_sections(parser.public_result(result), {identity: binding})
    block = materialized[0]["content"]["content"][0]
    assert all(block["attrs"][key] == val for key, val in binding.items())
    assert result["sections"] == original
    for bad in (
        {},
        {identity: binding, str(uuid4()): binding},
        {identity: binding | {"asset_revision": True}},
        {identity: binding | {"asset_version_id": "not-a-uuid"}},
    ):
        with pytest.raises(DomainError) as error:
            parser.materialize_sections(result, bad)
        assert error.value.code == "AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID"


def test_candidate_tamper_or_blocker_cannot_be_materialized():
    result = parser.parse_docx(package(heading("Title") + paragraph("Original")))
    changed = copy.deepcopy(result)
    changed["sections"][0]["content"]["content"][0]["content"][0]["text"] = "Replaced"
    with pytest.raises(DomainError) as error:
        parser.materialize_sections(changed, {})
    assert error.value.code == "AUTHORING_DOCX_IMPORT_CANDIDATE_INVALID"
    blocked = parser.parse_docx(
        package(
            heading("Title")
            + "<w:sdt><w:sdtContent>"
            + paragraph("Not silently dropped")
            + "</w:sdtContent></w:sdt>"
        )
    )
    assert not blocked["can_apply"]
    with pytest.raises(DomainError):
        parser.materialize_sections(blocked, {})


@pytest.mark.parametrize(
    "body,expected",
    [
        ('<w:ins w:id="1">' + paragraph("Inserted") + "</w:ins>", "TRACKED_CHANGES_UNSUPPORTED"),
        (
            paragraph(
                runs='<w:r><w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText><w:fldChar w:fldCharType="end"/></w:r>'
            ),
            "WORD_INTAKE_FIELD_EVALUATION_UNSUPPORTED",
        ),
        (
            paragraph(runs="<w:r><w:rPr><w:vanish/></w:rPr><w:t>Hidden price 120</w:t></w:r>"),
            "HIDDEN_TEXT_UNSUPPORTED",
        ),
        (
            paragraph(runs='<w:r><w:sym w:font="Symbol" w:char="F0A3"/></w:r>'),
            "RUN_CONTENT_UNSUPPORTED",
        ),
    ],
)
def test_unresolved_revisions_fields_hidden_text_and_symbols_block(body, expected):
    result = parser.parse_docx(package(heading("Title") + body))
    assert not result["can_apply"]
    assert expected in codes(result)


def test_external_relationship_is_disclosed_and_never_fetched():
    result = parser.parse_docx(
        package(
            heading("Title") + paragraph("Keep"),
            relations=[
                ("outside", R + "/hyperlink", "https://invalid.example/private.docx", "External")
            ],
        )
    )
    assert not result["can_apply"]
    assert "WORD_INTAKE_EXTERNAL_RELATIONSHIP" in codes(result)


def test_internal_mode_does_not_allow_absolute_external_image_target():
    data = parts(image_package())
    data["word/_rels/document.xml.rels"] = data["word/_rels/document.xml.rels"].replace(
        b'Target="media/figure.png"', b'Target="https://invalid.example/private.png"'
    )
    result = parser.parse_docx(archive(data))
    assert not result["can_apply"]
    assert "WORD_INTAKE_EXTERNAL_RELATIONSHIP" in codes(result)


def test_omitted_numbering_start_is_not_silently_rewritten_from_zero_to_one():
    definition = numbering().replace('<w:start w:val="1"/>', "")
    result = parser.parse_docx(package(heading("Number") + numbered("first"), numbering=definition))
    assert not result["can_apply"] and "NUMBERING_UNSUPPORTED" in codes(result)


def test_image_nonzero_internal_offset_and_hidden_flag_are_blocked():
    for variant in ("offset", "hidden"):
        xml = ET.fromstring(image_paragraph())
        if variant == "offset":
            xml.find(".//{" + rich_docx.A + "}off").set("x", "635")
        else:
            xml.find(".//{" + rich_docx.WP + "}docPr").set("hidden", "true")
        result = parser.parse_docx(
            image_package(heading("Image") + ET.tostring(xml, encoding="unicode"))
        )
        assert not result["can_apply"]


def test_running_process_cannot_label_old_loaded_code_with_new_source_digest(monkeypatch):
    current = parser.method_identity()
    monkeypatch.setattr(
        parser,
        "_source_digests",
        lambda: current["source_digests"] | {"packages/authoring/docx_import_tables.py": "0" * 64},
    )
    with pytest.raises(DomainError) as error:
        parser.method_identity()
    assert error.value.code == "AUTHORING_DOCX_IMPORT_RESTART_REQUIRED"


@pytest.mark.parametrize(
    "body",
    [
        "<w:p>unmapped<w:r><w:t>visible</w:t></w:r></w:p>",
        "<w:p><w:r><w:t>visible</w:t>unmapped</w:r></w:p>",
        '<w:p><w:pPr/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>content</w:t></w:r></w:p>',
        '<w:p><w:r><w:rPr><w:color w:val="000000"><w:t>unmapped</w:t></w:color></w:rPr><w:t>visible</w:t></w:r></w:p>',
    ],
)
def test_invalid_ambiguous_structure_is_disclosed_instead_of_silently_dropped(body):
    result = parser.parse_docx(package(heading("Title") + body))
    assert not result["can_apply"]
    assert codes(result) & {"UNMAPPED_XML_TEXT", "AMBIGUOUS_WORD_STRUCTURE"}


def test_repeated_style_losses_are_reported_at_style_definition_not_every_paragraph():
    styles = (
        DEFAULT_STYLES
        + '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Example"/><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>'
    )
    result = parser.parse_docx(
        package(heading("Title") + "".join(paragraph(str(i)) for i in range(2100)), styles=styles)
    )
    assert result["can_apply"]
    assert len(result["issues"]) < 10
    assert len(result["sections"][0]["content"]["content"]) == 2100


def test_header_footer_loss_and_annotation_blocker_are_not_hidden():
    header = f'<w:hdr xmlns:w="{W}">{paragraph("企业页眉")}</w:hdr>'.encode()
    result = parser.parse_docx(
        package(
            heading("Title") + paragraph("Body"),
            parts={"word/header1.xml": header},
            relations=[("header", R + "/header", "header1.xml", "Internal")],
        )
    )
    assert result["can_apply"] and "HEADER_FOOTER_NOT_IMPORTED" in codes(result)
    notes = f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1">{paragraph("重要脚注")}</w:footnote></w:footnotes>'.encode()
    result = parser.parse_docx(
        package(
            heading("Title"),
            parts={"word/footnotes.xml": notes},
            relations=[("notes", R + "/footnotes", "footnotes.xml", "Internal")],
        )
    )
    assert not result["can_apply"] and "ANNOTATIONS_NOT_IMPORTED" in codes(result)


def test_reuses_existing_container_gate_for_entity_and_archive_escapes():
    valid = parts(package(heading("Title")))
    malicious = dict(valid)
    malicious["word/document.xml"] = (
        b'<!DOCTYPE x [<!ENTITY injected "injected">]>' + valid["word/document.xml"]
    )
    with pytest.raises(DomainError) as error:
        parser.parse_docx(archive(malicious))
    assert error.value.code == "WORD_XML_DECLARATION_BLOCKED"
    malicious = valid | {"../outside.xml": b"<x/>"}
    with pytest.raises(DomainError) as error:
        parser.parse_docx(archive(malicious))
    assert error.value.code == "WORD_ARCHIVE_PATH_INVALID"


@pytest.mark.parametrize(
    "limit_name,new_limit",
    [("source_bytes", 10), ("sections", 1), ("candidate_json_bytes", 100), ("nodes", 1)],
)
def test_import_budgets_reject_whole_candidate_without_truncating(
    monkeypatch, limit_name, new_limit
):
    data = package(heading("One") + paragraph("first") + heading("Two") + paragraph("last"))
    monkeypatch.setitem(LIMITS, limit_name, new_limit)
    with pytest.raises(DomainError) as error:
        parser.parse_docx(data)
    assert error.value.code == "AUTHORING_DOCX_IMPORT_LIMIT"


def test_strict_word_namespace_retains_same_supported_text_and_heading():
    data = parts(package(heading("Strict") + paragraph("120")))
    for name in ("word/document.xml", "word/styles.xml"):
        data[name] = data[name].replace(
            W.encode(), b"http://purl.oclc.org/ooxml/wordprocessingml/main"
        )
    result = parser.parse_docx(archive(data))
    assert result["can_apply"]
    assert (
        result["sections"][0]["title"] == "Strict"
        and text_of(result["sections"][0]["content"]) == "120"
    )


def test_imported_table_image_and_text_build_into_actual_existing_rich_docx():
    import test_authoring_generated as generated_cases

    data = image_package(
        heading("导入章节") + merged_table() + image_paragraph() + paragraph("末段原文120")
    )
    result = parser.parse_docx(data)
    assert result["can_apply"]
    asset = result["images"][0]
    binding = {"asset_id": str(uuid4()), "asset_revision": 1, "asset_version_id": str(uuid4())}
    sections = parser.materialize_sections(parser.public_result(result), {asset["key"]: binding})
    snapshot = generated_cases.snapshot.__wrapped__()
    snapshot["sections"][0] = sections[0]["content"]
    output = rich_docx.assemble(
        snapshot,
        [{**binding, "bytes": asset["bytes"], "normalization_proof": asset["normalization_proof"]}],
    )
    entries = parts(output)
    xml = ET.fromstring(entries["word/document.xml"])
    assert len(xml.findall(".//{" + W + "}tbl")) == 1
    assert len(xml.findall(".//{" + W + "}vMerge")) == 2
    assert len(xml.findall(".//{" + W + "}drawing")) == 1
    assert "末段原文120" in "".join(t.text or "" for t in xml.iter("{" + W + "}t"))
    assert (
        entries["word/media/" + asset["normalization_proof"]["output_digest"] + ".png"]
        == asset["bytes"]
    )
