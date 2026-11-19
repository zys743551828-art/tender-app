"""Inspect final DOCX bytes without rendering, publishing or approving them."""

from __future__ import annotations

import io
import re
import unicodedata
import warnings
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from xml.etree.ElementTree import Element  # nosec B405

from PIL import Image

from packages.authoring.rich_images import MAX_NORMALIZED_BYTES, MAX_PIXELS
from packages.domain.runtime import DomainError, sha
from packages.word_intake import inspection

PROTOCOL = "technical-candidate-docx-check/1"
MAX_NAMES = 100
MAX_NAME_LENGTH = 200
TRACKED = {
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "cellIns",
    "cellDel",
    "cellMerge",
    "numberingChange",
    "delText",
}
COMMENT = {"comment", "commentRangeStart", "commentRangeEnd", "commentReference"}
HIDDEN = {"vanish", "webHidden", "specVanish"}
DYNAMIC = {"fldChar", "instrText", "delInstrText", "fldSimple", "fldData"}
PROPERTIES = {"creator", "lastmodifiedby"}


@dataclass(frozen=True)
class DocxCandidateCheck:
    artifact_sha256: str
    policy_sha256: str
    blocking_codes: tuple[str, ...]
    manual_check_codes: tuple[str, ...]
    protocol: str = PROTOCOL


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKC", text).casefold()
        if not char.isspace() and unicodedata.category(char) != "Cf"
    )


def _names(prohibited_names: Sequence[str]) -> tuple[str, ...]:
    if isinstance(prohibited_names, (str, bytes)) or len(prohibited_names) > MAX_NAMES:
        raise DomainError("TECHNICAL_CANDIDATE_NAMES_INVALID", "禁止标识清单无效", 422)
    names = set()
    for name in prohibited_names:
        if not isinstance(name, str) or len(name) > MAX_NAME_LENGTH:
            raise DomainError("TECHNICAL_CANDIDATE_NAMES_INVALID", "禁止标识清单无效", 422)
        normalized = _normalize(name)
        if not normalized or any(unicodedata.category(char) == "Cs" for char in name):
            raise DomainError("TECHNICAL_CANDIDATE_NAMES_INVALID", "禁止标识清单无效", 422)
        names.add(normalized)
    return tuple(sorted(names))


def _safe_page_field(node: Element, part: str) -> bool:
    # Exact simple PAGE shape produced by generated_docx; no compound fields or instructions.
    if not re.fullmatch(r"word/footer[0-9]*\.xml", part):
        return False
    for ns in inspection.WORD_NS:
        tag = "{" + ns + "}"
        if (
            node.tag == tag + "fldSimple"
            and node.attrib == {tag + "instr": " PAGE "}
            and len(node) == 1
            and node[0].tag == tag + "r"
            and not node[0].attrib
            and len(node[0]) == 1
            and node[0][0].tag == tag + "t"
            and not node[0][0].attrib
            and not len(node[0][0])
            and node[0][0].text == "1"
        ):
            return True
    return False


def _check_embedded_image(data: bytes, blocking: set[str]) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
                width, height = image.size
                if (
                    image.format != "PNG"
                    or image.mode not in {"RGB", "RGBA"}
                    or not 1 <= width <= 10000
                    or not 1 <= height <= 10000
                    or width * height > MAX_PIXELS
                    or getattr(image, "n_frames", 1) != 1
                ):
                    blocking.add("EMBEDDED_IMAGE_UNSUPPORTED")
                    return
                if image.info:
                    blocking.add("EMBEDDED_IMAGE_METADATA")
                image.verify()
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        blocking.add("EMBEDDED_IMAGE_INVALID")


def _paragraph_strings(node: Element) -> Iterator[str]:
    # Visit each run once; do not concatenate separate paragraphs (including nested text boxes).
    for paragraph in node.iter():
        if _local(paragraph.tag) != "p":
            continue
        texts = []
        pending = list(reversed(paragraph))
        while pending:
            item = pending.pop()
            tag = _local(item.tag)
            if tag == "p":
                continue
            if tag in {"t", "delText"}:
                texts.append(item.text or "")
            pending.extend(reversed(item))
        yield "".join(texts)


def inspect_candidate_docx(
    data: bytes, *, filename: str, prohibited_names: Sequence[str] = ()
) -> DocxCandidateCheck:
    """Return blocking signals and outstanding human checks; neither means approval.

    Prohibited names come from an explicitly selected project policy. This lexical
    check does not attest visual/OCR content, style compliance or factual coverage.
    Callers must retain the reviewed basis and compare the hash of delivered bytes.
    """
    names = _names(prohibited_names)
    pattern = re.compile("|".join(map(re.escape, names))) if names else None
    blocking: set[str] = set()
    manual = {"FORMAT_AND_RENDER_REVIEW", "CONTENT_AND_PROJECT_RULE_REVIEW"}

    def flagged(value: str) -> bool:
        return pattern is not None and bool(pattern.search(_normalize(value)))

    def result() -> DocxCandidateCheck:
        return DocxCandidateCheck(
            sha(data),
            sha({"filename": filename, "prohibited_names": names}),
            tuple(sorted(blocking)),
            tuple(sorted(manual)),
        )

    try:
        if inspection.filename_type(filename) != inspection.DOCX:
            blocking.add("CANDIDATE_FILENAME_INVALID")
    except DomainError:
        blocking.add("CANDIDATE_FILENAME_INVALID")
    if flagged(filename):
        blocking.add("PROHIBITED_NAME_FILENAME")
    if not data or len(data) > inspection.MAX_BYTES or not data.startswith(b"PK\x03\x04"):
        blocking.add("CANDIDATE_DOCX_INVALID")
        return result()
    try:
        checked = inspection.inspect_docx(data)
    except DomainError:
        blocking.add("CANDIDATE_DOCX_INVALID")
        return result()
    flags = set(checked["active_content_gaps"])
    # Intake conservatively rejects all fields for generic rendering. For candidate
    # bytes, only a generated PAGE in the footer can be excluded from that flag.
    blocking.update(flags - {"FIELD_EVALUATION_UNSUPPORTED"})
    found_field = False
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.comment:
            blocking.add("ARCHIVE_METADATA")
        for item in archive.infolist():
            if item.comment or item.extra:
                blocking.add("ARCHIVE_METADATA")
            if item.is_dir():
                continue
            part = item.filename
            folded = part.casefold()
            if flagged(part):
                blocking.add("PROHIBITED_NAME_PART")
            if folded.startswith(("word/comments", "word/people")):
                blocking.add("COMMENT_CONTENT")
            if folded.startswith("customxml/"):
                blocking.add("CUSTOM_XML_CONTENT")
            if not folded.endswith((".xml", ".rels")):
                if folded.startswith("word/media/") and folded.endswith(".png"):
                    manual.add("IMAGE_VISUAL_AND_METADATA_REVIEW")
                    if item.file_size > MAX_NORMALIZED_BYTES:
                        blocking.add("EMBEDDED_IMAGE_UNSUPPORTED")
                    else:
                        _check_embedded_image(archive.read(item), blocking)
                else:
                    blocking.add("UNSUPPORTED_BINARY_PART")
                continue
            # The first pass validated ZIP bounds, CRC, and XML parser limits.
            root = inspection._xml(archive.read(item))
            location = (
                "METADATA"
                if folded.startswith("docprops/")
                else "HEADER_FOOTER"
                if _local(root.tag) in {"hdr", "ftr"}
                else "CONTENT"
            )
            if any(flagged(text) for text in _paragraph_strings(root)):
                blocking.add("PROHIBITED_NAME_" + location)
            for node in root.iter():
                tag = _local(node.tag)
                text = node.text or ""
                if flagged(text) or flagged(node.tail or ""):
                    blocking.add("PROHIBITED_NAME_" + location)
                for attr, value in node.attrib.items():
                    if flagged(value):
                        suffix = (
                            "ALT_TEXT" if _local(attr) in {"alt", "descr", "title"} else location
                        )
                        blocking.add("PROHIBITED_NAME_" + suffix)
                if location == "METADATA" and tag.casefold() in PROPERTIES and text.strip():
                    blocking.add("AUTHOR_METADATA")
                if tag in HIDDEN and not any(
                    _local(attr) == "val" and value.casefold() in {"0", "false", "off"}
                    for attr, value in node.attrib.items()
                ):
                    blocking.add("HIDDEN_CONTENT")
                if tag in COMMENT:
                    blocking.add("COMMENT_CONTENT")
                if (
                    tag in TRACKED
                    or tag in {"trackRevisions", "tblGridChange"}
                    or tag.endswith("PrChange")
                ):
                    blocking.add("TRACKED_CHANGES")
                if tag in DYNAMIC:
                    found_field = True
                    if not _safe_page_field(node, part):
                        blocking.add("FIELD_EVALUATION_UNSUPPORTED")
    if "FIELD_EVALUATION_UNSUPPORTED" in flags and not found_field:
        blocking.add("FIELD_EVALUATION_UNSUPPORTED")
    return result()
