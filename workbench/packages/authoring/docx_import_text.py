"""Word paragraphs, style inheritance and explicit constrained list conversion.

Formatting outside the existing Rich vocabulary is disclosed, never presented as
layout fidelity. Semantic structures that cannot be represented remain blockers.
"""

from __future__ import annotations

import re
from typing import Any

from packages.authoring.docx_import_support import (
    LIMITS,
    REVISION_TAGS,
    attr,
    child,
    children,
    empty_paragraph,
    integer,
    is_word,
    local,
    on,
    paths,
    value,
)

RUN_FORMATTING = {
    "rFonts",
    "color",
    "sz",
    "szCs",
    "u",
    "strike",
    "dstrike",
    "highlight",
    "shd",
    "bdr",
    "spacing",
    "position",
    "kern",
    "w",
    "vertAlign",
    "caps",
    "smallCaps",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "effect",
    "fitText",
    "eastAsianLayout",
}
PARAGRAPH_FORMATTING = {
    "spacing",
    "ind",
    "jc",
    "tabs",
    "pBdr",
    "shd",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "widowControl",
    "contextualSpacing",
    "mirrorIndents",
    "suppressLineNumbers",
    "suppressAutoHyphens",
    "snapToGrid",
    "adjustRightInd",
    "autoSpaceDE",
    "autoSpaceDN",
    "topLinePunct",
    "overflowPunct",
    "kinsoku",
    "wordWrap",
    "textAlignment",
    "suppressOverlap",
    "divId",
    "cnfStyle",
    "outlineLvl",
}
IGNORED_MARKERS = {"bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd"}


class TextReader:
    def __init__(self, ctx, styles=None, numbering=None):
        self.ctx = ctx
        self.styles_path = ctx.related_parts.get("styles", "word/styles.xml")
        self.numbering_path = ctx.related_parts.get("numbering", "word/numbering.xml")
        self.styles: dict[str, Any] = {}
        self.default_style = None
        self.default_run = None
        self.default_paragraph = None
        self.abstract: dict[str, Any] = {}
        self.numbers: dict[str, Any] = {}
        self.ordered_segments = set()
        if styles is not None:
            defaults = child(styles, "docDefaults")
            self.default_run = child(child(defaults, "rPrDefault"), "rPr")
            self.default_paragraph = child(child(defaults, "pPrDefault"), "pPr")
            for style in children(styles, "style"):
                key = attr(style, "styleId")
                if not key or key in self.styles:
                    ctx.issue(
                        "STYLE_DEFINITION_INVALID",
                        "blocker",
                        "word/styles.xml",
                        "样式身份缺失或重复",
                    )
                    continue
                self.styles[key] = style
                if attr(style, "type") == "paragraph" and attr(style, "default") in {
                    "1",
                    "true",
                    "on",
                }:
                    self.default_style = key
        if numbering is not None:
            for node in children(numbering, "abstractNum"):
                key = attr(node, "abstractNumId")
                if key is None or key in self.abstract:
                    ctx.issue(
                        "NUMBERING_DEFINITION_INVALID",
                        "blocker",
                        "word/numbering.xml",
                        "抽象编号身份缺失或重复",
                    )
                else:
                    self.abstract[key] = node
            for node in children(numbering, "num"):
                key = attr(node, "numId")
                if key is None or key in self.numbers:
                    ctx.issue(
                        "NUMBERING_DEFINITION_INVALID",
                        "blocker",
                        "word/numbering.xml",
                        "编号实例身份缺失或重复",
                    )
                else:
                    self.numbers[key] = node

    def chain(self, key, path, expected):
        result: list[Any] = []
        seen: set[str] = set()
        while key:
            if key in seen or len(seen) >= 32:
                self.ctx.issue(
                    "STYLE_INHERITANCE_INVALID", "blocker", path, "样式继承成环或超过32层"
                )
                break
            seen.add(key)
            style = self.styles.get(key)
            if style is None:
                self.ctx.issue(
                    "STYLE_DEFINITION_MISSING", "blocker", path, "引用的Word样式没有定义"
                )
                break
            if attr(style, "type") != expected:
                self.ctx.issue(
                    "STYLE_TYPE_INVALID", "blocker", path, "Word样式类型与使用位置不一致"
                )
                break
            result.append(style)
            key = value(style, "basedOn")
        return list(reversed(result))

    def run_properties(self, props, state, path, *, toggle=False):
        if props is None:
            return
        normalized = set()
        for prop in props:
            name = local(prop.tag)
            if not is_word(prop):
                self.ctx.issue(
                    "RUN_PROPERTY_UNSUPPORTED", "warning", path, "扩展文字样式不进入编辑稿"
                )
            elif name in {"b", "i"}:
                enabled = on(prop)
                state[name] = (not state[name] if enabled else state[name]) if toggle else enabled
            elif name in {"vanish", "webHidden", "specVanish"} and on(prop):
                self.ctx.issue(
                    "HIDDEN_TEXT_UNSUPPORTED",
                    "blocker",
                    path,
                    "原稿含隐藏文字，须先明确处理后再导入",
                )
            elif name in {"bCs", "iCs", "rtl", "cs", "oMath"} and on(prop):
                self.ctx.issue(
                    "COMPLEX_SCRIPT_FORMATTING_UNSUPPORTED",
                    "blocker",
                    path,
                    "复杂文字系统的独立格式或方向尚不能保真映射",
                )
            elif name in REVISION_TAGS:
                self.ctx.issue(
                    "TRACKED_CHANGES_UNSUPPORTED",
                    "blocker",
                    path,
                    "原稿含修订，须在原Word中明确接受或拒绝后导入",
                )
            elif name in RUN_FORMATTING:
                normalized.add(name)
            elif name not in {
                "rStyle",
                "lang",
                "noProof",
                "oMath",
                "vanish",
                "webHidden",
                "specVanish",
                "bCs",
                "iCs",
                "rtl",
                "cs",
            }:
                self.ctx.issue(
                    "RUN_PROPERTY_UNSUPPORTED",
                    "warning",
                    path,
                    "未支持的文字样式不进入编辑稿：" + name,
                )
        if normalized:
            self.ctx.issue(
                "RUN_FORMATTING_NORMALIZED",
                "warning",
                path,
                "文字仅保留粗体和斜体；以下格式由工作台版式重建：" + "、".join(sorted(normalized)),
            )

    def paragraph_properties(self, props, merged, path):
        if props is None:
            return
        normalized = set()
        for prop in props:
            name = local(prop.tag)
            if not is_word(prop):
                self.ctx.issue(
                    "PARAGRAPH_PROPERTY_UNSUPPORTED", "warning", path, "扩展段落格式不进入编辑稿"
                )
            elif name in {"numPr", "outlineLvl"}:
                merged[name] = prop
            elif name in REVISION_TAGS:
                self.ctx.issue(
                    "TRACKED_CHANGES_UNSUPPORTED", "blocker", path, "原稿含段落修订，须先明确处理"
                )
            elif name in {"framePr", "textDirection", "bidi"}:
                self.ctx.issue(
                    "PARAGRAPH_LAYOUT_UNSUPPORTED",
                    "blocker",
                    path,
                    "文本框或段落方向不能映射到当前编辑结构",
                )
            elif name == "sectPr":
                self.ctx.section_properties(prop, path + "/sectPr")
            elif name in PARAGRAPH_FORMATTING:
                normalized.add(name)
            elif name not in {"pStyle", "rPr"}:
                self.ctx.issue(
                    "PARAGRAPH_PROPERTY_UNSUPPORTED",
                    "warning",
                    path,
                    "未支持的段落格式不进入编辑稿：" + name,
                )
        if normalized:
            self.ctx.issue(
                "PARAGRAPH_FORMATTING_NORMALIZED",
                "warning",
                path,
                "段落间距、对齐或分页按工作台版式重建：" + "、".join(sorted(normalized)),
            )

    def paragraph(self, paragraph, path, *, inside_cell=False):
        ppr = child(paragraph, "pPr")
        style_key = value(ppr, "pStyle", self.default_style)
        styles = self.chain(style_key, path, "paragraph") if style_key else []
        props: dict[str, Any] = {}
        self.paragraph_properties(
            self.default_paragraph, props, self.styles_path + "/docDefaults/pPrDefault"
        )
        base_marks = {"b": False, "i": False}
        self.run_properties(
            self.default_run, base_marks, self.styles_path + "/docDefaults/rPrDefault"
        )
        heading = None
        for style in styles:
            style_path = self.styles_path + "/style[" + attr(style, "styleId") + "]"
            self.paragraph_properties(child(style, "pPr"), props, style_path + "/pPr")
            self.run_properties(child(style, "rPr"), base_marks, style_path + "/rPr", toggle=True)
            name = value(style, "name", "")
            match = re.fullmatch(r"(?:heading|标题)[ _-]?([1-6])", name, re.I)
            if match:
                heading = int(match.group(1))
        self.paragraph_properties(ppr, props, path)
        if "outlineLvl" in props:
            level = integer(attr(props["outlineLvl"], "val"), 0, 9)
            if level is None:
                self.ctx.issue("HEADING_LEVEL_INVALID", "blocker", path, "标题层级无效")
            elif level < 6:
                heading = level + 1
            elif level < 9:
                self.ctx.issue("HEADING_LEVEL_UNSUPPORTED", "blocker", path, "当前章节层级最多六层")
            else:
                heading = None
        number = self.numbering(
            props.get("numPr"),
            path,
            inherited=props.get("numPr") is not child(ppr, "numPr"),
            style_ids=[attr(style, "styleId") for style in styles],
        )
        if heading is not None and number is not None:
            self.ctx.issue(
                "HEADING_NUMBERING_NORMALIZED",
                "warning",
                path,
                "原Word标题的自动编号不写入标题文字；导入后按工作台章节版式重新编号",
            )
            if number["type"] == "orderedList":
                self.ordered_segments.add((number["id"], number["level"], None))
            number = None
        if inside_cell and heading is not None:
            self.ctx.issue(
                "CELL_HEADING_NORMALIZED",
                "warning",
                path,
                "单元格内标题按普通段落保存，文字与粗斜体保留",
            )
            heading = None
        segments: list[dict[str, Any]] = []
        inline: list[dict[str, Any]] = []

        def flush(*, force=False):
            if inline or force:
                segments.append(
                    {
                        "type": "paragraph",
                        "attrs": {"id": self.ctx.node_id(path, "paragraph:" + str(len(segments)))},
                        "content": list(inline),
                    }
                )
                inline.clear()

        for item, item_path in paths(paragraph, path):
            name = local(item.tag)
            if is_word(item, "pPr"):
                continue
            if is_word(item) and name in IGNORED_MARKERS:
                if name != "proofErr":
                    self.ctx.issue(
                        "BOOKMARK_OR_EDIT_RANGE_NOT_IMPORTED",
                        "warning",
                        "word/document.xml",
                        "原Word书签和编辑范围标记不复制；正文内容保留，原件仍可查阅",
                    )
                continue
            if not is_word(item, "r"):
                code = (
                    "TRACKED_CHANGES_UNSUPPORTED"
                    if name in REVISION_TAGS
                    else "PARAGRAPH_CONTENT_UNSUPPORTED"
                )
                self.ctx.issue(
                    code, "blocker", item_path, "段落含未支持的结构，不能静默移除：" + name
                )
                continue
            rpr = child(item, "rPr")
            marks = dict(base_marks)
            run_style = value(rpr, "rStyle")
            for style in self.chain(run_style, item_path, "character") if run_style else []:
                self.run_properties(
                    child(style, "rPr"),
                    marks,
                    self.styles_path + "/style[" + attr(style, "styleId") + "]/rPr",
                    toggle=True,
                )
            self.run_properties(rpr, marks, item_path)
            rich_marks = [
                {"type": name} for name, key in (("bold", "b"), ("italic", "i")) if marks[key]
            ]
            for node, node_path in paths(item, item_path):
                name = local(node.tag)
                if not is_word(node):
                    self.ctx.issue(
                        "RUN_CONTENT_UNSUPPORTED", "blocker", node_path, "文字行含未支持的扩展内容"
                    )
                elif name == "rPr":
                    continue
                elif name in {"t", "tab", "noBreakHyphen", "softHyphen"}:
                    text = {"tab": "\t", "noBreakHyphen": "\u2011", "softHyphen": "\u00ad"}.get(
                        name, node.text or ""
                    )
                    if list(node):
                        self.ctx.issue(
                            "TEXT_CHILDREN_UNSUPPORTED",
                            "blocker",
                            node_path,
                            "文字节点包含非文字子结构",
                        )
                    if text:
                        record = {"type": "text", "text": text}
                        if rich_marks:
                            record["marks"] = rich_marks
                        inline.append(record)
                elif name in {"br", "cr"}:
                    if attr(node, "type", "textWrapping") not in {"textWrapping"} or attr(
                        node, "clear"
                    ):
                        self.ctx.issue(
                            "BREAK_LAYOUT_NORMALIZED",
                            "warning",
                            node_path,
                            "原分页、分栏或清除环绕转换为普通换行",
                        )
                    inline.append({"type": "hardBreak"})
                elif name == "lastRenderedPageBreak":
                    self.ctx.issue(
                        "CACHED_PAGE_BREAK_IGNORED",
                        "warning",
                        node_path,
                        "原Word缓存页分界不作为新稿分页依据",
                    )
                elif name == "drawing":
                    if inside_cell or number is not None or heading is not None:
                        self.ctx.issue(
                            "IMAGE_PLACEMENT_UNSUPPORTED",
                            "blocker",
                            node_path,
                            "单元格、列表或标题内图片须先移到独立正文段落",
                        )
                        continue
                    image = self.ctx.picture(node, node_path)
                    if image:
                        if inline:
                            self.ctx.issue(
                                "INLINE_IMAGE_MOVED_TO_BLOCK",
                                "warning",
                                node_path,
                                "行内图片转为独立图片块，前后文字顺序保留",
                            )
                        flush()
                        segments.append(image)
                else:
                    code = (
                        "TRACKED_CHANGES_UNSUPPORTED"
                        if name in REVISION_TAGS
                        else "RUN_CONTENT_UNSUPPORTED"
                    )
                    self.ctx.issue(
                        code, "blocker", node_path, "文字行含未支持的内容，不能静默移除：" + name
                    )
        flush(force=not segments)
        if len(segments) > 1 and any(b["type"] == "image" for b in segments):
            self.ctx.issue(
                "INLINE_IMAGE_MOVED_TO_BLOCK",
                "warning",
                path,
                "含图段落拆为顺序一致的文字与图片块，行内排版不保留",
            )
        return {"blocks": segments, "heading": heading, "number": number, "path": path}

    def numbering(self, numpr, path, *, inherited=False, style_ids=()):
        if numpr is None:
            return None
        key, level_raw = value(numpr, "numId"), value(numpr, "ilvl", "0")
        if key == "0":
            return None
        level = integer(level_raw, 0, LIMITS["list_levels"] - 1)
        instance = self.numbers.get(key)
        definition = self.abstract.get(value(instance, "abstractNumId"))
        if key is None or instance is None or definition is None or level is None:
            self.ctx.issue("NUMBERING_UNSUPPORTED", "blocker", path, "编号定义缺失或列表超过五层")
            return None
        if inherited:
            linked = []
            for style_id in reversed(style_ids):
                linked = [n for n in children(definition, "lvl") if value(n, "pStyle") == style_id]
                if linked:
                    break
            if len(linked) != 1:
                self.ctx.issue(
                    "STYLE_NUMBERING_UNSUPPORTED",
                    "blocker",
                    path,
                    "继承编号没有唯一匹配的样式层级，不能推测编号级别",
                )
                return None
            level = integer(attr(linked[0], "ilvl"), 0, LIMITS["list_levels"] - 1)
            if level is None:
                self.ctx.issue("NUMBERING_UNSUPPORTED", "blocker", path, "样式编号超过支持层级")
                return None
        levels = [n for n in children(definition, "lvl") if attr(n, "ilvl") == str(level)]
        if len(levels) != 1:
            self.ctx.issue("NUMBERING_UNSUPPORTED", "blocker", path, "编号层级定义缺失或重复")
            return None
        definition_level = levels[0]
        start_override = None
        for override in children(instance, "lvlOverride"):
            if attr(override, "ilvl") == str(level):
                replacement = child(override, "lvl")
                if replacement is not None:
                    definition_level = replacement
                start_override = value(override, "startOverride")
        fmt = value(definition_level, "numFmt")
        start = start_override if start_override is not None else value(definition_level, "start")
        label = value(definition_level, "lvlText", "")
        if (
            any(child(definition, p) is not None for p in ("numStyleLink", "styleLink"))
            or child(definition_level, "lvlPicBulletId") is not None
        ):
            self.ctx.issue(
                "NUMBERING_UNSUPPORTED", "blocker", path, "图片项目符号或间接编号样式尚未支持"
            )
        restart = value(definition_level, "lvlRestart")
        if restart is not None and restart != str(level):
            self.ctx.issue(
                "NUMBERING_RESTART_UNSUPPORTED",
                "blocker",
                path,
                "自定义编号重启规则不能映射到当前列表",
            )
        if fmt == "bullet":
            if label not in {"•", "\uf0b7", "·", "●"}:
                self.ctx.issue(
                    "BULLET_MARKER_NORMALIZED", "warning", path, "原项目符号按工作台圆点列表显示"
                )
            return {"id": key, "level": level, "type": "bulletList"}
        if (
            fmt != "decimal"
            or start != "1"
            or not re.fullmatch(r"%" + str(level + 1) + r"[.)、]?", label)
        ):
            self.ctx.issue(
                "NUMBERING_UNSUPPORTED",
                "blocker",
                path,
                "仅支持从1开始的独立十进制编号；组合编号、自定义起点和其他数字格式须先处理",
            )
            return None
        if label != "%" + str(level + 1) + ".":
            self.ctx.issue(
                "LIST_MARKER_NORMALIZED",
                "warning",
                path,
                "编号后缀按工作台小数点样式显示，序号不变",
            )
        return {"id": key, "level": level, "type": "orderedList"}

    def combine(self, records):
        result: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = []
        for record in records:
            number = record.get("number")
            if number is None:
                stack.clear()
                result.extend(record["blocks"])
                continue
            level = number["level"]
            while len(stack) > level + 1:
                stack.pop()
            key = (number["id"], number["type"])
            if len(stack) == level + 1 and stack[-1]["key"] != key:
                stack.pop()
            if len(stack) < level:
                self.ctx.issue(
                    "LIST_LEVEL_GAP",
                    "blocker",
                    record["path"],
                    "列表缺少上级项目，不能推测或补造层级",
                )
                result.extend(record["blocks"])
                stack.clear()
                continue
            if len(stack) == level:
                parent_item = stack[-1]["node"]["content"][-1] if stack else None
                segment = (number["id"], level, parent_item["attrs"]["id"] if parent_item else None)
                if number["type"] == "orderedList":
                    if segment in self.ordered_segments:
                        self.ctx.issue(
                            "LIST_CONTINUATION_UNSUPPORTED",
                            "blocker",
                            record["path"],
                            "原编号跨段落、章节或单元格续号；当前列表不能自动重置为1",
                        )
                    self.ordered_segments.add(segment)
                node: dict[str, Any] = {
                    "type": number["type"],
                    "attrs": {"id": self.ctx.node_id(record["path"], "list")},
                    "content": [],
                }
                (parent_item["content"] if parent_item else result).append(node)
                stack.append({"key": key, "node": node})
            blocks = record["blocks"] or [empty_paragraph(self.ctx, record["path"])]
            item = {
                "type": "listItem",
                "attrs": {"id": self.ctx.node_id(record["path"], "item")},
                "content": blocks,
            }
            stack[-1]["node"]["content"].append(item)
        return result
