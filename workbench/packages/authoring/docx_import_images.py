"""Closed embedded raster drawing import, with no relationship or network IO."""

from __future__ import annotations

from pathlib import PurePosixPath

from packages.authoring import rich_images
from packages.authoring.docx_import_support import (
    A_NAMESPACES,
    LIMITS,
    PIC_NAMESPACES,
    R_NAMESPACES,
    WP_NAMESPACES,
    integer,
    limit,
    local,
    namespace,
    stable,
)
from packages.domain.runtime import DomainError, sha


def matching(parent, namespaces, name):
    return [
        item for item in parent if namespace(item.tag) in namespaces and local(item.tag) == name
    ]


def one(parent, namespaces, name):
    matches = matching(parent, namespaces, name)
    return matches[0] if len(matches) == 1 else None


def picture(ctx, drawing, path):
    before = ctx.blocker_count
    inline = one(drawing, WP_NAMESPACES, "inline")
    if inline is None or len(drawing) != 1:
        ctx.issue(
            "FLOATING_DRAWING_UNSUPPORTED",
            "blocker",
            path,
            "仅支持单张行内图片；浮动图片、形状或组合绘图须先转换为独立图片",
        )
        return None
    allowed = {
        **{
            ns: {"inline", "extent", "effectExtent", "docPr", "cNvGraphicFramePr"}
            for ns in WP_NAMESPACES
        },
        **{
            ns: {
                "graphic",
                "graphicData",
                "graphicFrameLocks",
                "picLocks",
                "blip",
                "stretch",
                "fillRect",
                "srcRect",
                "xfrm",
                "off",
                "ext",
                "prstGeom",
                "avLst",
            }
            for ns in A_NAMESPACES
        },
        **{
            ns: {"pic", "nvPicPr", "cNvPr", "cNvPicPr", "blipFill", "spPr"} for ns in PIC_NAMESPACES
        },
    }
    for nested in inline.iter():
        if local(nested.tag) not in allowed.get(namespace(nested.tag), set()):
            ctx.issue(
                "DRAWING_CONTENT_UNSUPPORTED",
                "blocker",
                path,
                "图片含未支持的绘图节点：" + local(nested.tag),
            )
    padding = one(inline, WP_NAMESPACES, "effectExtent")
    if any(inline.get(k, "0") != "0" for k in ("distT", "distB", "distL", "distR")) or (
        padding is not None and any(v != "0" for v in padding.attrib.values())
    ):
        ctx.issue("IMAGE_PADDING_NORMALIZED", "warning", path, "原图周围间距按工作台图片块重新排版")
    for item in inline:
        if not (
            namespace(item.tag) in WP_NAMESPACES
            and local(item.tag) in {"extent", "effectExtent", "docPr", "cNvGraphicFramePr"}
        ) and not (namespace(item.tag) in A_NAMESPACES and local(item.tag) == "graphic"):
            ctx.issue("DRAWING_CONTENT_UNSUPPORTED", "blocker", path, "图片包含未支持的扩展结构")
    extent = one(inline, WP_NAMESPACES, "extent")
    raw_width = extent.get("cx") if extent is not None else None
    raw_height = extent.get("cy") if extent is not None else None
    width = integer(raw_width, 1, 20000 * 635)
    height = integer(raw_height, 1, 20000 * 635)
    if width is None or height is None:
        ctx.issue(
            "IMAGE_GEOMETRY_UNSUPPORTED", "blocker", path, "图片必须有明确且不超过20000 twips的宽高"
        )
        return None
    if width % 635 or height % 635:
        ctx.issue(
            "IMAGE_GEOMETRY_ROUNDED",
            "warning",
            path,
            "图片尺寸从EMU取整到最接近的twip，误差不超过半个twip",
        )
    width_twips, height_twips = max(1, (width + 317) // 635), max(1, (height + 317) // 635)
    graphic = one(inline, A_NAMESPACES, "graphic")
    payload = one(graphic, A_NAMESPACES, "graphicData") if graphic is not None else None
    pic = one(payload, PIC_NAMESPACES, "pic") if payload is not None else None
    if (
        payload is None
        or payload.get("uri") not in PIC_NAMESPACES
        or pic is None
        or len(payload) != 1
    ):
        ctx.issue("DRAWING_CONTENT_UNSUPPORTED", "blocker", path, "绘图不是单个PNG/JPEG图片对象")
        return None
    fill = one(pic, PIC_NAMESPACES, "blipFill")
    shape = one(pic, PIC_NAMESPACES, "spPr")
    blip = one(fill, A_NAMESPACES, "blip") if fill is not None else None
    relationship = None
    if blip is not None:
        for ns in R_NAMESPACES:
            relationship = blip.get("{" + ns + "}embed") or relationship
            if blip.get("{" + ns + "}link"):
                ctx.issue(
                    "LINKED_IMAGE_UNSUPPORTED", "blocker", path, "外链图片不能作为内嵌原件导入"
                )
        if list(blip):
            ctx.issue(
                "IMAGE_EFFECT_UNSUPPORTED",
                "blocker",
                path,
                "图片含颜色效果、扩展图像或替代数据，不能忽略后导入",
            )
    if not relationship or relationship not in ctx.relationships:
        ctx.issue("IMAGE_RELATIONSHIP_INVALID", "blocker", path, "图片没有唯一有效的内嵌关系")
        return None
    relation = ctx.relationships[relationship]
    if relation["external"] or relation["type"].rsplit("/", 1)[-1] != "image":
        ctx.issue("IMAGE_RELATIONSHIP_INVALID", "blocker", path, "图片关系不是内嵌图片类型")
        return None
    for item in fill:
        name = local(item.tag)
        if namespace(item.tag) not in A_NAMESPACES or name not in {"blip", "srcRect", "stretch"}:
            ctx.issue(
                "IMAGE_FILL_UNSUPPORTED", "blocker", path, "图片平铺或未知填充不能映射为单张图片"
            )
        elif name == "srcRect" and any(v not in {"0", "0%"} for v in item.attrib.values()):
            ctx.issue(
                "IMAGE_CROP_UNSUPPORTED",
                "blocker",
                path,
                "图片带裁剪，须先在原Word中保存裁剪结果，不能恢复被裁去内容",
            )
        elif name == "stretch":
            rectangle = one(item, A_NAMESPACES, "fillRect")
            if (
                rectangle is None
                or len(item) != 1
                or any(v not in {"0", "0%"} for v in rectangle.attrib.values())
            ):
                ctx.issue("IMAGE_FILL_UNSUPPORTED", "blocker", path, "非完整矩形拉伸尚不能映射")
    if shape is None:
        ctx.issue("IMAGE_GEOMETRY_UNSUPPORTED", "blocker", path, "图片缺少形状几何")
        return None
    for item in shape:
        name = local(item.tag)
        if namespace(item.tag) not in A_NAMESPACES:
            ctx.issue("IMAGE_EFFECT_UNSUPPORTED", "blocker", path, "图片包含未支持的形状扩展")
        elif name == "xfrm":
            if any(
                item.get(k, "0") not in {"0", "false", "off"} for k in ("rot", "flipH", "flipV")
            ):
                ctx.issue(
                    "IMAGE_TRANSFORM_UNSUPPORTED",
                    "blocker",
                    path,
                    "旋转或翻转图片须先固化像素后导入",
                )
            offset = one(item, A_NAMESPACES, "off")
            if offset is not None and any(offset.get(k, "0") != "0" for k in ("x", "y")):
                ctx.issue(
                    "IMAGE_TRANSFORM_UNSUPPORTED",
                    "blocker",
                    path,
                    "图片内部有偏移，须先固化像素后导入",
                )
            transform_extent = one(item, A_NAMESPACES, "ext")
            if transform_extent is not None and (
                transform_extent.get("cx"),
                transform_extent.get("cy"),
            ) != (raw_width, raw_height):
                ctx.issue(
                    "IMAGE_TRANSFORM_UNSUPPORTED",
                    "blocker",
                    path,
                    "图片内部与外部尺寸不同，不能猜测变换结果",
                )
        elif name == "prstGeom":
            if item.get("prst") != "rect" or any(
                local(desc.tag) != "avLst" or list(desc) for desc in item
            ):
                ctx.issue("IMAGE_SHAPE_UNSUPPORTED", "blocker", path, "仅支持未调整的矩形图片形状")
        else:
            ctx.issue(
                "IMAGE_EFFECT_UNSUPPORTED",
                "blocker",
                path,
                "图片边框、效果或未知几何尚不能保真导入：" + name,
            )
    for item in pic:
        if namespace(item.tag) not in PIC_NAMESPACES or local(item.tag) not in {
            "nvPicPr",
            "blipFill",
            "spPr",
        }:
            ctx.issue("DRAWING_CONTENT_UNSUPPORTED", "blocker", path, "图片含未支持的内部结构")
    docpr = one(inline, WP_NAMESPACES, "docPr")
    if docpr is not None and list(docpr):
        ctx.issue("IMAGE_ACTION_UNSUPPORTED", "blocker", path, "图片含动作或链接，不能静默删除")
    nv = one(pic, PIC_NAMESPACES, "nvPicPr")
    nonvisual = one(nv, PIC_NAMESPACES, "cNvPr") if nv is not None else None
    if nonvisual is not None and list(nonvisual):
        ctx.issue("IMAGE_ACTION_UNSUPPORTED", "blocker", path, "图片含动作或链接，不能静默删除")
    if ctx.blocker_count != before:
        return None
    source_part = relation["resolved"]
    media_type = ctx.part_types.get(source_part)
    if media_type not in {"image/png", "image/jpeg"}:
        ctx.issue(
            "IMAGE_FORMAT_UNSUPPORTED",
            "blocker",
            path,
            "仅支持内嵌PNG/JPEG原图；其他格式须先明确转换",
        )
        return None
    key = stable(ctx.source_digest, source_part, "image-asset")
    if key not in ctx.images:
        if len(ctx.images) >= LIMITS["images"]:
            limit("Word内嵌图片超过200份，请拆分原件")
        original = ctx.archive.read(source_part)
        try:
            normalized = rich_images.normalize(original, media_type)
        except DomainError as error:
            ctx.issue(
                "IMAGE_DECODE_UNSUPPORTED",
                "blocker",
                path,
                "内嵌图片未通过现有单帧图片核验：" + error.code,
            )
            return None
        proof = normalized["proof"]
        ctx.image_bytes += len(original) + len(normalized["bytes"])
        ctx.image_pixels += proof["width_px"] * proof["height_px"]
        if (
            ctx.image_bytes > LIMITS["image_bytes_total"]
            or ctx.image_pixels > LIMITS["image_decoded_pixels_total"]
        ):
            limit("Word图片累计超过64MiB或3200万解码像素，请拆分或压缩原件")
        ctx.images[key] = {
            "key": key,
            "source_part": source_part,
            "filename": PurePosixPath(source_part).name,
            "media_type": media_type,
            "source_media_type": media_type,
            "source_digest": sha(original),
            "source_byte_size": len(original),
            "original_bytes": original,
            "bytes": normalized["bytes"],
            "normalization_proof": proof,
        }
        ctx.issue(
            "IMAGE_METADATA_NORMALIZED",
            "warning",
            source_part,
            "图片按现有规范转换为PNG，应用EXIF方向并移除元数据；原始内嵌图片字节另行保留",
        )
    asset = ctx.images[key]
    ctx.image_placement_pixels += (
        asset["normalization_proof"]["width_px"] * asset["normalization_proof"]["height_px"]
    )
    if ctx.image_placement_pixels > LIMITS["image_placements_pixels_total"]:
        limit("Word图片按出现次数累计超过3200万像素，请压缩图片或拆分原件")
    alt = ""
    for properties in (docpr, nonvisual):
        if properties is not None:
            if properties.get("hidden", "0") not in {"0", "false", "off"}:
                ctx.issue(
                    "IMAGE_HIDDEN_UNSUPPORTED",
                    "blocker",
                    path,
                    "图片标记为隐藏，不能直接显示到编辑稿",
                )
                return None
            alt = properties.get("descr") or properties.get("title") or alt
            if alt:
                break
    if not alt.strip():
        alt = "导入图片 " + str(list(ctx.images).index(key) + 1)
        ctx.issue(
            "IMAGE_ALT_GENERATED",
            "warning",
            path,
            "原图没有替代文字，已生成占位说明，请在导入后补充",
        )
    if len(alt) > 1000 or any(ord(char) < 32 for char in alt):
        ctx.issue(
            "IMAGE_ALT_UNSUPPORTED",
            "blocker",
            path,
            "原图说明超过1000字符或含控制字符，请在原Word中修正",
        )
        return None
    return {
        "type": "image",
        "attrs": {
            "id": ctx.node_id(path),
            "asset_id": key,
            "asset_revision": 1,
            "asset_version_id": stable(ctx.source_digest, source_part, "image-version-placeholder"),
            "width_twips": width_twips,
            "height_twips": height_twips,
            "alt": alt,
            "caption": "",
        },
    }
