"""Bounded, deterministic external DOCX to the existing editable Rich subset.

This module never reads business storage or evaluates Word fields. Candidate
creation does not apply a draft. Image identities below are placeholders until
the service atomically registers assets and calls ``materialize_sections``.
"""

from __future__ import annotations

import io
import json
import platform
import posixpath
import pyexpat
import re
import zipfile
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import UUID

from PIL import __version__ as PILLOW_VERSION
from PIL import features as pillow_features

from packages.authoring import content, docx_import_images, docx_import_tables, rich_content
from packages.authoring.docx_import_support import (
    LIMITS,
    PROTOCOL,
    R_NAMESPACES,
    REVISION_TAGS,
    child,
    is_word,
    limit,
    local,
    paths,
    stable,
)
from packages.authoring.docx_import_text import TextReader
from packages.domain.runtime import DomainError, sha
from packages.word_intake import inspection

SOURCE_FILES = (
    "packages/authoring/docx_import_parser.py",
    "packages/authoring/docx_import_support.py",
    "packages/authoring/docx_import_text.py",
    "packages/authoring/docx_import_tables.py",
    "packages/authoring/docx_import_images.py",
    "packages/authoring/content.py",
    "packages/authoring/rich_content.py",
    "packages/authoring/rich_images.py",
    "packages/word_intake/inspection.py",
    "packages/domain/runtime.py",
    "packages/platform_runtime/__init__.py",
    "packages/platform_runtime/configuration.py",
    "packages/platform_runtime/database.py",
)
DOCUMENT_PATH = "word/document.xml/body"


def _source_digests():
    root = Path(__file__).resolve().parents[2]
    return {name: sha((root / name).read_bytes()) for name in SOURCE_FILES}


_LOADED_SOURCE_DIGESTS = _source_digests()


def method_identity():
    """Bind every parser/helper/schema/normalizer input, without runtime secrets."""
    if _source_digests() != _LOADED_SOURCE_DIGESTS:
        raise DomainError(
            "AUTHORING_DOCX_IMPORT_RESTART_REQUIRED",
            "导入实现文件已变化，请重启API进程后重新读取能力",
            409,
        )
    return {
        "protocol": PROTOCOL,
        "source_digests": dict(_LOADED_SOURCE_DIGESTS),
        "text_schema_digest": content.SCHEMA_DIGEST,
        "rich_schema_digest": rich_content.SCHEMA_DIGEST,
        "pillow_version": PILLOW_VERSION,
        "runtime": {
            "python_version": platform.python_version(),
            "xml_expat_version": pyexpat.EXPAT_VERSION,
            "zlib_version": zlib.ZLIB_RUNTIME_VERSION,
            "pillow_codecs": {
                name: pillow_features.version(name) for name in ("jpg", "zlib", "libjpeg_turbo")
            },
        },
        "limits": dict(LIMITS),
        "supported": [
            "heading_sections_1_to_6",
            "paragraph_text_breaks_bold_italic",
            "decimal_from_1_and_bullet_lists_up_to_5_levels",
            "explicit_table_grid_horizontal_and_vertical_spans",
            "table_header_rows_and_caption",
            "explicit_single_repeated_header_unmerged_2_to_12_rows",
            "embedded_untransformed_inline_png_jpeg",
        ],
        "layout_policy": "editable_subset_explicit_losses_original_retained",
        "revision_policy": "block_until_resolved_in_original",
        "field_policy": "never_evaluate_block",
        "external_relationship_policy": "never_fetch_block",
        "heading_policy": "map_heading_to_section_title_without_duplicate_body_heading",
    }


def public_result(result):
    """Remove image bytes from a private candidate, retaining all proofs/identity."""
    return {
        key: (
            [
                {k: deepcopy(v) for k, v in image.items() if k not in {"bytes", "original_bytes"}}
                for image in value
            ]
            if key == "images"
            else deepcopy(value)
        )
        for key, value in result.items()
    }


def result_digest(result):
    value = public_result(result)
    value.pop("content_digest", None)
    return sha(value)


def materialize_sections(result, image_bindings):
    """Replace *all* placeholder images with registered immutable asset identities.

    Accepts the persisted public result. It deliberately does not require image
    bytes or regenerate their normalization; publication owns byte verification.
    """
    if (
        not isinstance(result, dict)
        or result.get("protocol") != PROTOCOL
        or result.get("content_digest") != result_digest(result)
        or result.get("can_apply") is not True
    ):
        raise DomainError(
            "AUTHORING_DOCX_IMPORT_CANDIDATE_INVALID", "导入候选摘要无效或仍有阻断项", 409
        )
    images = result.get("images")
    if not isinstance(images, list) or not isinstance(image_bindings, dict):
        raise DomainError("AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID", "导入图片身份不完整", 422)
    keys = [image["key"] for image in images]
    if len(keys) != len(set(keys)) or set(keys) != set(image_bindings):
        raise DomainError(
            "AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID", "必须精确绑定本次候选的全部图片", 422
        )
    for binding in image_bindings.values():
        try:
            if not isinstance(binding, dict) or set(binding) != {
                "asset_id",
                "asset_revision",
                "asset_version_id",
            }:
                raise ValueError
            if (
                str(UUID(binding["asset_id"])) != binding["asset_id"]
                or str(UUID(binding["asset_version_id"])) != binding["asset_version_id"]
                or type(binding["asset_revision"]) is not int
                or not 1 <= binding["asset_revision"] <= 2**63 - 1
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise DomainError(
                "AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID",
                "图片必须绑定真实且规范的资产版本",
                422,
            ) from None
    sections = deepcopy(result["sections"])
    seen = set()
    for section in sections:
        for block in section["content"]["content"]:
            if block["type"] == "image":
                attrs = block["attrs"]
                key = attrs["asset_id"]
                if key not in image_bindings:
                    raise DomainError(
                        "AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID", "图片占位身份不属于候选", 422
                    )
                attrs.update(image_bindings[key])
                seen.add(key)
        content.validate_content(section["content"])
    if seen != set(keys):
        raise DomainError(
            "AUTHORING_DOCX_IMPORT_IMAGE_BINDING_INVALID", "候选包含没有对应节点的图片", 422
        )
    return sections


class _Context:
    def __init__(self, source_digest, archive, part_types, xml):
        self.source_digest = source_digest
        self.archive = archive
        self.part_types = part_types
        self.xml = xml
        self.issues = {}
        self.blocker_count = 0
        self.node_paths = {}
        self.images = {}
        self.image_bytes = 0
        self.image_pixels = 0
        self.image_placement_pixels = 0
        self.relationships = {}
        self.related_parts = {}
        rels = xml.get("word/_rels/document.xml.rels")
        if rels is not None:
            for item in rels:
                target = item.get("Target", "")
                external = item.get("TargetMode", "Internal") != "Internal" or bool(
                    re.match(r"(?:[a-z][a-z0-9+.-]*:|//)", target, re.I)
                )
                relation_type = item.get("Type", "")
                if relation_type.rsplit("/", 1)[0] not in R_NAMESPACES:
                    self.issue(
                        "IMPORT_RELATIONSHIP_TYPE_UNSUPPORTED",
                        "blocker",
                        "word/_rels/document.xml.rels",
                        "正文关系使用未支持的类型命名空间",
                    )
                self.relationships[item.get("Id")] = {
                    "type": relation_type,
                    "external": external,
                    "resolved": None
                    if external
                    else posixpath.normpath(
                        posixpath.join("word", unquote(target).split("#", 1)[0])
                    ),
                }
        self.text = TextReader(self, self.related_xml("styles"), self.related_xml("numbering"))

    def related_xml(self, kind):
        matches = [
            r["resolved"]
            for r in self.relationships.values()
            if r["type"].rsplit("/", 1)[-1] == kind and not r["external"]
        ]
        if len(matches) > 1:
            self.issue(
                "IMPORT_RELATIONSHIP_AMBIGUOUS",
                "blocker",
                "word/_rels/document.xml.rels",
                "正文包含多份同类型关系：" + kind,
            )
        if len(matches) == 1:
            self.related_parts[kind] = matches[0]
            return self.xml.get(matches[0])
        return None

    def issue(self, code, severity, path, message):
        record = {"code": code, "severity": severity, "source_path": path, "message": message}
        identity = sha(record)
        if identity not in self.issues:
            if len(self.issues) >= LIMITS["issues"]:
                limit("Word导入问题超过2000项，请拆分或先规范原件")
            self.issues[identity] = {"id": identity, **record}
            self.blocker_count += severity == "blocker"

    def node_id(self, path, suffix=""):
        identity = stable(self.source_digest, path, suffix)
        self.node_paths[identity] = path
        if len(self.node_paths) > LIMITS["nodes"]:
            limit("Word导入节点超过100000项，请拆分原件")
        return identity

    def picture(self, drawing, path):
        return docx_import_images.picture(self, drawing, path)

    def section_properties(self, properties, path):
        if len(properties):
            self.issue(
                "DOCUMENT_LAYOUT_NORMALIZED",
                "warning",
                path,
                "原Word页面尺寸、边距、分栏和分节布局不复制，新稿按工作台版式生成",
            )
        for item in properties:
            if local(item.tag) in REVISION_TAGS:
                self.issue("TRACKED_CHANGES_UNSUPPORTED", "blocker", path, "分节属性包含未处理修订")
            elif is_word(item) and local(item.tag) in {"headerReference", "footerReference"}:
                self.issue(
                    "HEADER_FOOTER_NOT_IMPORTED",
                    "warning",
                    path,
                    "原Word页眉页脚不进入可编辑正文，原件保留，新稿使用工作台版式",
                )


def _global_issues(ctx, report):
    for flag in report["active_content_gaps"]:
        ctx.issue(
            "WORD_INTAKE_" + flag,
            "blocker",
            "word/document.xml",
            "原件接收核验发现不可导入内容：" + flag,
        )
    for name, root in ctx.xml.items():
        for element in root.iter():
            if is_word(element) and local(element.tag) in REVISION_TAGS:
                ctx.issue(
                    "TRACKED_CHANGES_UNSUPPORTED",
                    "blocker",
                    name,
                    "原稿含修订，须在原Word中明确接受或拒绝后导入",
                )
        suffixes = {
            r["type"].rsplit("/", 1)[-1]
            for r in ctx.relationships.values()
            if r["resolved"] == name
        }
        if suffixes & {
            "footnotes",
            "endnotes",
            "comments",
            "commentsExtended",
            "commentsIds",
            "people",
        }:
            ctx.issue(
                "ANNOTATIONS_NOT_IMPORTED",
                "blocker",
                name,
                "原Word脚注、尾注或批注未映射，须明确处理后导入",
            )
        if suffixes & {"header", "footer"}:
            ctx.issue(
                "HEADER_FOOTER_NOT_IMPORTED",
                "warning",
                name,
                "原Word页眉页脚不进入可编辑正文，原件仍完整保留",
            )
        if suffixes & {"customXml", "glossaryDocument"}:
            ctx.issue(
                "CUSTOM_CONTENT_UNSUPPORTED",
                "blocker",
                name,
                "原Word自定义XML或文档构件不能静默移除",
            )
    ctx.issue(
        "EDITABLE_LAYOUT_NORMALIZED",
        "warning",
        "word/document.xml",
        "导入保留支持的正文结构，不复制原Word整页版式；章节标题、字体、分页和样式按工作台编辑与构建规则生成",
    )


def _document_structure(ctx):
    """Reject ambiguous XML rather than selecting the first conflicting value."""
    root = ctx.xml["word/document.xml"]
    bodies = [node for node in root if is_word(node, "body")]
    if len(bodies) != 1:
        raise DomainError("AUTHORING_DOCX_IMPORT_BODY_INVALID", "Word必须有唯一正文容器", 422)
    unique_children = {
        "p": {"pPr"},
        "r": {"rPr"},
        "tbl": {"tblPr", "tblGrid"},
        "tr": {"trPr"},
        "tc": {"tcPr"},
        "pPr": {"pStyle", "outlineLvl", "numPr", "rPr", "sectPr"},
        "rPr": {"b", "i", "rStyle", "vanish", "webHidden", "specVanish"},
        "numPr": {"numId", "ilvl"},
        "tcPr": {"gridSpan", "vMerge", "hMerge", "tcW"},
        "tblPr": {"tblCaption", "tblDescription", "tblW", "tblLayout"},
    }
    for node in root:
        if not is_word(node, "body"):
            ctx.issue(
                "DOCUMENT_DECORATION_NOT_IMPORTED",
                "warning",
                "word/document.xml",
                "正文外背景或装饰不进入编辑稿",
            )
    for node in root.iter():
        if node.text and node.text.strip() and not is_word(node, "t"):
            ctx.issue(
                "UNMAPPED_XML_TEXT",
                "blocker",
                "word/document.xml/" + local(node.tag),
                "文字位于不受支持的XML位置，不能静默删除",
            )
        if node.tail and node.tail.strip():
            ctx.issue(
                "UNMAPPED_XML_TEXT",
                "blocker",
                "word/document.xml/" + local(node.tag),
                "XML尾部含未映射文字，不能静默删除",
            )
        seen = set()
        for nested in node:
            if is_word(nested, "t") and not is_word(node, "r"):
                ctx.issue(
                    "UNMAPPED_XML_TEXT",
                    "blocker",
                    "word/document.xml/" + local(node.tag),
                    "文字节点位于文字行之外，不能静默删除",
                )
            name = local(nested.tag)
            if (
                is_word(node)
                and is_word(nested)
                and name in unique_children.get(local(node.tag), set())
            ):
                if name in seen:
                    ctx.issue(
                        "AMBIGUOUS_WORD_STRUCTURE",
                        "blocker",
                        "word/document.xml/" + local(node.tag),
                        "Word结构或属性重复，不能选择其中一项后忽略其他项：" + name,
                    )
                seen.add(name)


def _sections(ctx, body):
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    pending: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def create(title, path, level=None):
        nonlocal current
        if len(sections) >= LIMITS["sections"]:
            limit("Word标题超过500个章节，请拆分原件")
        if level is None:
            stack.clear()
        else:
            while stack and stack[-1][0] >= level:
                stack.pop()
            if (not stack and level > 1) or (stack and level > stack[-1][0] + 1):
                ctx.issue(
                    "HEADING_LEVEL_GAP",
                    "warning",
                    path,
                    "标题层级有跳级，保留已有父子关系，不补造空章节",
                )
        key = stable(ctx.source_digest, path, "section")
        current = {
            "key": key,
            "parent_key": stack[-1][1] if stack else None,
            "ordinal": len(sections),
            "title": title,
            "source_path": path,
            "content": {
                "type": "doc",
                "attrs": {
                    "title": title,
                    "ordinal": len(sections),
                    "rule_ids": [],
                    "source_refs": [],
                },
                "content": [],
            },
        }
        sections.append(current)
        if level is not None:
            stack.append((level, key))

    def ensure():
        if current is None:
            create("导入正文", DOCUMENT_PATH + "/preamble")
            ctx.issue(
                "SECTION_TITLE_GENERATED",
                "warning",
                DOCUMENT_PATH,
                "无标题的前置正文放入“导入正文”章节，可在导入后重命名",
            )
        if current is None:
            raise DomainError("AUTHORING_DOCX_IMPORT_RESULT_INVALID", "导入章节未建立", 422)
        return current

    def flush():
        if pending:
            section = ensure()
            section["content"]["content"].extend(ctx.text.combine(pending))
            pending.clear()

    for node, path in paths(body, DOCUMENT_PATH):
        if is_word(node, "sectPr"):
            ctx.section_properties(node, path)
            continue
        if is_word(node, "p"):
            record = ctx.text.paragraph(node, path)
            title = "".join(
                part.get("text", " ")
                for block in record["blocks"]
                if block["type"] == "paragraph"
                for part in block["content"]
            ).strip()
            if (
                record["heading"] is not None
                and title
                and all(block["type"] == "paragraph" for block in record["blocks"])
            ):
                if len(title) > 200 or any(ord(char) < 32 for char in title):
                    ctx.issue(
                        "HEADING_TITLE_UNSUPPORTED",
                        "blocker",
                        path,
                        "章节标题超过200字符或含控制字符，须先修正",
                    )
                else:
                    flush()
                    create(title, path, record["heading"])
                    continue
            pending.append(record)
        elif is_word(node, "tbl"):
            flush()
            section = ensure()
            table = docx_import_tables.table(ctx, node, path)
            if table is not None:
                section["content"]["content"].append(table)
        else:
            flush()
            ctx.issue(
                "DOCUMENT_CONTENT_UNSUPPORTED",
                "blocker",
                path,
                "正文包含未支持的内容，不能静默移除：" + local(node.tag),
            )
    flush()
    if not sections:
        create("导入正文", DOCUMENT_PATH + "/empty")
        ctx.issue("EMPTY_DOCUMENT", "blocker", DOCUMENT_PATH, "原件没有可导入的正文或标题")
    for section in sections:
        try:
            content.validate_content(section["content"])
        except DomainError as error:
            if len(json.dumps(section["content"], ensure_ascii=False).encode()) > 1_000_000:
                limit("单个导入章节超过1MiB，请在原Word中补充标题或拆分章节")
            raise DomainError(
                "AUTHORING_DOCX_IMPORT_RESULT_INVALID",
                "导入结构未通过现有编辑器校验：" + error.code,
                422,
            ) from None
    return sections


def _mapping(ctx, sections):
    result = []

    def walk(node, section):
        identity = node.get("attrs", {}).get("id")
        if identity is not None:
            result.append(
                {
                    "source_path": ctx.node_paths[identity],
                    "section_key": section["key"],
                    "node_id": identity,
                    "kind": node["type"],
                }
            )
        for nested in node.get("content", []):
            walk(nested, section)

    for section in sections:
        result.append(
            {
                "source_path": section["source_path"],
                "section_key": section["key"],
                "node_id": section["key"],
                "kind": "section_title",
            }
        )
        walk(section["content"], section)
    return result


def parse_docx(data):
    """Read exact in-memory DOCX bytes into a previewable, un-applied candidate."""
    if not isinstance(data, bytes) or not 0 < len(data) <= LIMITS["source_bytes"]:
        limit("Word导入原件须为1字节到32MiB")
    report = inspection.inspect_docx(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        manifest = inspection._xml(archive.read("[Content_Types].xml"))
        part_types = inspection._content_types(manifest, names)
        xml = {
            name: inspection._xml(archive.read(name))
            for name, media in part_types.items()
            if inspection._xml_type(media) or name.casefold().endswith((".xml", ".rels"))
        }
        ctx = _Context(sha(data), archive, part_types, xml)
        _global_issues(ctx, report)
        _document_structure(ctx)
        body = child(xml["word/document.xml"], "body")
        if body is None:
            raise DomainError("AUTHORING_DOCX_IMPORT_BODY_MISSING", "Word原件缺少正文容器", 422)
        sections = _sections(ctx, body)
        result = {
            "protocol": PROTOCOL,
            "source_digest": ctx.source_digest,
            "source_byte_size": len(data),
            "method": method_identity(),
            "sections": sections,
            "images": list(ctx.images.values()),
            "mapping": _mapping(ctx, sections),
            "issues": list(ctx.issues.values()),
            "can_apply": ctx.blocker_count == 0,
        }
        if (
            len(json.dumps(public_result(result), ensure_ascii=False, allow_nan=False).encode())
            > LIMITS["candidate_json_bytes"]
        ):
            limit("导入候选超过16MiB，请拆分原Word")
        result["content_digest"] = result_digest(result)
        return result
