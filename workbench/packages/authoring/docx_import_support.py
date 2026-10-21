"""Shared closed Word import vocabulary and bounded, non-evaluating XML helpers."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from packages.domain.runtime import DomainError

PROTOCOL = "authoring-docx-import/1"
LIMITS = {
    "source_bytes": 32 * 1024 * 1024,
    "candidate_json_bytes": 16 * 1024 * 1024,
    "sections": 500,
    "nodes": 100000,
    "issues": 2000,
    "images": 200,
    "image_bytes_total": 64 * 1024 * 1024,
    "image_decoded_pixels_total": 32_000_000,
    "image_placements_pixels_total": 32_000_000,
    "list_levels": 5,
}
W_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
R_NAMESPACES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
}
A_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
WP_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing",
}
PIC_NAMESPACES = {
    "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "http://purl.oclc.org/ooxml/drawingml/picture",
}
REVISION_TAGS = {
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "numberingChange",
    "cellIns",
    "cellDel",
    "cellMerge",
    "numPrChange",
}


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def namespace(tag):
    return tag[1:].split("}", 1)[0] if isinstance(tag, str) and tag.startswith("{") else ""


def is_word(element, name=None):
    return namespace(element.tag) in W_NAMESPACES and (name is None or local(element.tag) == name)


def child(element, name):
    if element is None:
        return None
    return next((item for item in element if is_word(item, name)), None)


def children(element, name):
    return [] if element is None else [item for item in element if is_word(item, name)]


def attr(element, name, default=None):
    if element is None:
        return default
    for ns in W_NAMESPACES:
        if "{" + ns + "}" + name in element.attrib:
            return element.attrib["{" + ns + "}" + name]
    return default


def value(element, name, default=None):
    return attr(child(element, name), "val", default)


def on(element, default=True):
    if element is None:
        return default
    selected = attr(element, "val", "true")
    if selected not in {"1", "0", "true", "false", "on", "off"}:
        raise DomainError("AUTHORING_DOCX_IMPORT_ON_OFF_INVALID", "Word布尔属性无效", 422)
    return selected not in {"0", "false", "off"}


def integer(raw, minimum, maximum):
    try:
        if not isinstance(raw, str) or len(raw) > 16 or raw.strip() != raw:
            return None
        result = int(raw)
    except ValueError:
        return None
    return result if minimum <= result <= maximum else None


def stable(source_digest, path, suffix=""):
    return str(uuid5(NAMESPACE_URL, PROTOCOL + ":" + source_digest + ":" + path + ":" + suffix))


def paths(element, path):
    counts: dict[str, int] = {}
    for item in element:
        name = local(item.tag)
        counts[name] = counts.get(name, 0) + 1
        yield item, f"{path}/{name}[{counts[name]}]"


def limit(message):
    raise DomainError("AUTHORING_DOCX_IMPORT_LIMIT", message, 422)


def empty_paragraph(ctx, path):
    return {"type": "paragraph", "attrs": {"id": ctx.node_id(path)}, "content": []}
