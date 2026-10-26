"""Native Word table grid import, retaining horizontal and vertical spans."""

from __future__ import annotations

from typing import Any, cast

from packages.authoring.docx_import_support import (
    REVISION_TAGS,
    attr,
    child,
    children,
    empty_paragraph,
    integer,
    is_word,
    local,
    namespace,
    on,
    paths,
    value,
)
from packages.authoring.rich_content import SCHEMA, table_grid
from packages.domain.runtime import DomainError


def table(ctx, source, path):
    grid = child(source, "tblGrid")
    columns = children(grid, "gridCol")
    widths = [integer(attr(column, "w"), 1, 20000) for column in columns]
    rows = children(source, "tr")
    if (
        not widths
        or len(widths) > 100
        or any(width is None for width in widths)
        or not 1 <= len(rows) <= 200
        or len(widths) * len(rows) > 10000
    ):
        ctx.issue(
            "TABLE_GRID_UNSUPPORTED",
            "blocker",
            path,
            "表格须有明确列宽，且不超过200行、100列和10000网格",
        )
        return None
    properties = child(source, "tblPr")
    layout = child(properties, "tblLayout")
    table_width = child(properties, "tblW")
    if attr(layout, "type") != "fixed" or (
        table_width is not None and attr(table_width, "type") not in {"dxa", "auto"}
    ):
        ctx.issue(
            "TABLE_AUTO_LAYOUT_NORMALIZED",
            "warning",
            path,
            "表格按声明网格列宽转为固定布局；Word自动调整或百分比布局不保留",
        )
    caption = value(properties, "tblCaption", "")
    if len(caption) > 1000 or any(ord(char) < 32 for char in caption):
        ctx.issue("TABLE_CAPTION_UNSUPPORTED", "blocker", path, "表格标题过长或含控制字符")
        return None
    for prop in properties if properties is not None else []:
        name = local(prop.tag)
        if name in REVISION_TAGS:
            ctx.issue("TRACKED_CHANGES_UNSUPPORTED", "blocker", path, "表格属性含未处理修订")
        elif not is_word(prop) or name not in {"tblW", "tblLayout", "tblCaption"}:
            ctx.issue(
                "TABLE_FORMATTING_NORMALIZED",
                "warning",
                path + "/tblPr/" + name,
                "表格颜色、边框、位置或样式按工作台版式重建：" + name,
            )
    if grid is not None and any(not is_word(item, "gridCol") for item in grid):
        ctx.issue("TABLE_GRID_UNSUPPORTED", "blocker", path, "表格网格含修订或未知结构")
    for item in source:
        if not is_word(item) or local(item.tag) not in {"tblPr", "tblGrid", "tr"}:
            ctx.issue(
                "TABLE_CONTENT_UNSUPPORTED", "blocker", path, "表格含未支持的行外内容，不能静默移除"
            )
    output: dict[str, Any] = {
        "type": "table",
        "attrs": {"id": ctx.node_id(path), "column_widths_twips": widths, "caption": caption},
        "content": [],
    }
    repeated_rows = []
    previous: list[Any] = [None] * len(widths)
    for row_index, source_row in enumerate(rows):
        row_path = f"{path}/tr[{row_index + 1}]"
        row_properties = child(source_row, "trPr")
        headers = children(row_properties, "tblHeader")
        if (
            len(children(source_row, "trPr")) > 1
            or len(headers) > 1
            or any(
                list(header)
                or any(key not in {"{" + namespace(header.tag) + "}val"} for key in header.attrib)
                for header in headers
            )
        ):
            ctx.issue(
                "TABLE_HEADER_REPEAT_UNSUPPORTED",
                "blocker",
                row_path,
                "重复表头声明含歧义或未知结构",
            )
            return None
        row_header = bool(headers) and on(headers[0])
        if row_header:
            repeated_rows.append(row_index)
        for prop in row_properties if row_properties is not None else []:
            name = local(prop.tag)
            if name == "tblHeader" and not is_word(prop):
                ctx.issue(
                    "TABLE_HEADER_REPEAT_UNSUPPORTED", "blocker", row_path, "表头命名空间不受支持"
                )
                return None
            if name in {"gridBefore", "gridAfter"} and attr(prop, "val", "0") != "0":
                ctx.issue(
                    "TABLE_GRID_GAP_UNSUPPORTED",
                    "blocker",
                    row_path,
                    "表格行存在前置或尾部空网格，不能补造单元格",
                )
                return None
            if name in REVISION_TAGS:
                ctx.issue("TRACKED_CHANGES_UNSUPPORTED", "blocker", row_path, "表格行包含修订")
            elif name not in {"tblHeader", "gridBefore", "gridAfter"}:
                ctx.issue(
                    "TABLE_ROW_FORMATTING_NORMALIZED",
                    "warning",
                    row_path,
                    "表格行高、分页或样式按新稿重建：" + name,
                )
        row: dict[str, Any] = {
            "type": "tableRow",
            "attrs": {"id": ctx.node_id(row_path)},
            "content": [],
        }
        current: list[Any] = [None] * len(widths)
        column_index = 0
        for source_cell, cell_path in paths(source_row, row_path):
            if is_word(source_cell, "trPr"):
                continue
            if not is_word(source_cell, "tc"):
                ctx.issue(
                    "TABLE_CONTENT_UNSUPPORTED", "blocker", cell_path, "表格行含未支持的单元格结构"
                )
                continue
            cell_properties = child(source_cell, "tcPr")
            span = integer(value(cell_properties, "gridSpan", "1"), 1, 100)
            merge = child(cell_properties, "vMerge")
            merge_kind = attr(merge, "val", "continue") if merge is not None else None
            if (
                span is None
                or column_index + span > len(widths)
                or merge_kind not in {None, "restart", "continue"}
            ):
                ctx.issue(
                    "TABLE_MERGE_INVALID", "blocker", cell_path, "单元格合并超出边界或标记无效"
                )
                return None
            cell_width = child(cell_properties, "tcW")
            if cell_width is not None and (
                attr(cell_width, "type") != "dxa"
                or integer(attr(cell_width, "w"), 1, 2_000_000)
                != sum(widths[column_index : column_index + span])
            ):
                ctx.issue(
                    "TABLE_CELL_WIDTH_NORMALIZED",
                    "warning",
                    cell_path,
                    "单元格偏好宽度与网格不同，导入以声明列网格及合并跨度为准",
                )
            for prop in cell_properties if cell_properties is not None else []:
                name = local(prop.tag)
                if name == "hMerge":
                    ctx.issue(
                        "TABLE_LEGACY_MERGE_UNSUPPORTED",
                        "blocker",
                        cell_path,
                        "旧式水平合并须先由Word保存为gridSpan网格合并",
                    )
                elif name in REVISION_TAGS:
                    ctx.issue(
                        "TRACKED_CHANGES_UNSUPPORTED", "blocker", cell_path, "单元格包含未处理修订"
                    )
                elif name in {"textDirection", "vAlign"} and attr(prop, "val") not in {
                    "lrTb",
                    "top",
                }:
                    ctx.issue(
                        "TABLE_CELL_LAYOUT_NORMALIZED",
                        "warning",
                        cell_path,
                        "单元格文字方向或垂直对齐按工作台默认版式重建",
                    )
                elif not is_word(prop) or name not in {
                    "tcW",
                    "gridSpan",
                    "vMerge",
                    "textDirection",
                    "vAlign",
                }:
                    ctx.issue(
                        "TABLE_CELL_FORMATTING_NORMALIZED",
                        "warning",
                        cell_path + "/tcPr/" + name,
                        "单元格边距、颜色或样式按工作台版式重建：" + name,
                    )
            records = []
            for item, item_path in paths(source_cell, cell_path):
                if is_word(item, "tcPr"):
                    continue
                if not is_word(item, "p"):
                    ctx.issue(
                        "TABLE_CELL_CONTENT_UNSUPPORTED",
                        "blocker",
                        item_path,
                        "单元格仅支持段落和列表；嵌套表格或其他对象须先处理",
                    )
                    continue
                records.append(ctx.text.paragraph(item, item_path, inside_cell=True))
            contents = ctx.text.combine(records) or [empty_paragraph(ctx, cell_path + "/empty")]
            if merge_kind == "continue":
                origin = previous[column_index]
                if (
                    origin is None
                    or any(
                        previous[x] is not origin for x in range(column_index, column_index + span)
                    )
                    or origin["column"] != column_index
                    or origin["cell"]["attrs"]["colspan"] != span
                    or not origin["vertical"]
                ):
                    ctx.issue(
                        "TABLE_MERGE_INVALID",
                        "blocker",
                        cell_path,
                        "纵向合并续行没有相同列跨度的起始单元格",
                    )
                    return None
                if any(block["type"] != "paragraph" or block["content"] for block in contents):
                    ctx.issue(
                        "TABLE_MERGE_CONTINUATION_CONTENT",
                        "blocker",
                        cell_path,
                        "纵向合并续行仍有正文，不能静默删除隐藏内容",
                    )
                origin["cell"]["attrs"]["rowspan"] += 1
            else:
                cell = {
                    "type": "tableCell",
                    "attrs": {
                        "id": ctx.node_id(cell_path),
                        "colspan": span,
                        "rowspan": 1,
                        "header": row_header,
                    },
                    "content": contents,
                }
                row["content"].append(cell)
                origin = {"cell": cell, "column": column_index, "vertical": merge_kind == "restart"}
            for x in range(column_index, column_index + span):
                current[x] = origin
            column_index += span
        if column_index != len(widths):
            ctx.issue(
                "TABLE_GRID_GAP_UNSUPPORTED",
                "blocker",
                row_path,
                "表格行未填满声明网格，不能补造空单元格",
            )
            return None
        output["content"].append(row)
        previous = current
    if repeated_rows:
        if repeated_rows != [0]:
            ctx.issue(
                "TABLE_HEADER_REPEAT_UNSUPPORTED", "blocker", path, "仅支持明确声明的首行重复表头"
            )
            return None
        output["attrs"]["pagination"] = dict(cast(dict[str, Any], SCHEMA["table_pagination"]))
    try:
        table_grid(output)
    except DomainError:
        ctx.issue(
            "TABLE_HEADER_REPEAT_UNSUPPORTED" if repeated_rows else "TABLE_GRID_INVALID",
            "blocker",
            path,
            "转换后表格未通过现有严格网格及分页校验",
        )
        return None
    return output
