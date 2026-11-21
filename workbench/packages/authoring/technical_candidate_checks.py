"""Inspect final DOCX bytes without rendering, publishing or approving them."""

from __future__ import annotations

import io
import re
import unicodedata
import warnings
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from xml.etree.ElementTree import Element  # nosec B405

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

from packages.authoring.rich_images import MAX_NORMALIZED_BYTES, MAX_PIXELS
from packages.authoring.structure_schema import FORMAT_BINDING
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
MARGIN_NAMES = {f"margin_{side}_twips": side for side in ("top", "right", "bottom", "left")}
MARGIN_UNINSPECTABLE = "DOCX_PAGE_MARGINS_UNINSPECTABLE"
MARGIN_MISMATCH = "DOCX_PAGE_MARGINS_MISMATCH"
MARGIN_NO_BASIS = "DOCX_PAGE_MARGINS_NO_FROZEN_BASIS"
TEXT_DEFAULT_FIELDS = {
    "font_size_halfpoints": "font_size_halfpoints",
    "paragraph_after_twips": "paragraph_after_twips",
}
TEXT_DEFAULTS_MISMATCH = "DOCX_TEXT_DEFAULTS_MISMATCH"
TEXT_DEFAULTS_UNINSPECTABLE = "DOCX_TEXT_DEFAULTS_UNINSPECTABLE"
TEXT_DEFAULTS_NO_BASIS = "DOCX_TEXT_DEFAULTS_NO_FROZEN_BASIS"
TEXT_DEFAULTS_POLICY = "active-canonical-styles-doc-defaults/2"
TEXT_DEFAULT_CODES = {
    "font_size_halfpoints": "DOCX_DEFAULT_FONT",
    "paragraph_after_twips": "DOCX_DEFAULT_PARAGRAPH_AFTER",
}
TextDefaultState = Literal["RAW_MATCH", "RAW_MISMATCH", "NO_FROZEN_BASIS", "UNINSPECTABLE"]
_OFFICE_REL = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
}
PLACEHOLDER_FOUND = "DOCX_EXPLICIT_PLACEHOLDER"
PLACEHOLDER_POLICY = "literal-markers/1"
_WORD_STORIES = {
    f"{{{ns}}}{part}"
    for ns in inspection.WORD_NS
    for part in ("document", "hdr", "ftr", "footnotes", "endnotes")
}
_PLACEHOLDER_LABELS = r"(?:待填|待填写|待补|待补充|待核实|todo)"
_PLACEHOLDER = re.compile(
    r"\{\{[^{}]{0,80}\}\}" + rf"|\[{_PLACEHOLDER_LABELS}\]" + rf"|【{_PLACEHOLDER_LABELS}】"
)

_HEX = re.compile(r"[a-f0-9]{64}")
_MEASUREMENT = re.compile(r"[+-]?[0-9]{1,10}")
_UNSIGNED = re.compile(r"[0-9]{1,10}")
_FORMAT_BINDING = Draft202012Validator(FORMAT_BINDING, format_checker=FormatChecker())


@dataclass(frozen=True)
class FrozenPageMargins:
    expected_twips: tuple[tuple[str, int], ...] = ()
    malformed_basis: bool = False
    basis_digest: str | None = None


@dataclass(frozen=True)
class FrozenTextDefaults:
    expected: tuple[tuple[str, int], ...] = ()
    malformed_basis: bool = False
    basis_digest: str | None = None
    malformed_fields: tuple[str, ...] = ()
    partial_basis_digests: tuple[tuple[str, str], ...] = ()


def _digest(value: object) -> bool:
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _confirmed_numeric_binding(binding: dict) -> bool:
    body = {key: value for key, value in binding.items() if key not in {"basis", "interpretation"}}
    if not _FORMAT_BINDING.is_valid(body):
        return False
    if binding.get("interpretation") != "human_bound_field_semantics_not_automatically_verified":
        return False
    basis = binding.get("basis")
    if not isinstance(basis, dict) or set(basis) != {
        "rule_id",
        "rule_semantic_digest",
        "decision_id",
        "decision_revision",
        "evidence_basis",
    }:
        return False
    if (
        not _uuid(basis["decision_id"])
        or basis["rule_id"] != body["rule_id"]
        or type(basis["decision_revision"]) is not int
        or basis["decision_revision"] < 1
        or not _digest(basis["rule_semantic_digest"])
    ):
        return False
    evidence = basis["evidence_basis"]
    if not isinstance(evidence, dict) or set(evidence) != {"references", "source_closure_digest"}:
        return False
    refs = evidence["references"]
    return (
        type(body["value"]) is int
        and _digest(evidence["source_closure_digest"])
        and isinstance(refs, list)
        and bool(body["source_refs"])
        and all(ref in refs for ref in body["source_refs"])
    )


def _frozen_numeric_fields(
    snapshot: Mapping[str, object], fields: Mapping[str, str]
) -> tuple[tuple[tuple[str, int], ...], bool, str | None]:
    """Read only human-bound fields from a structurally validated frozen snapshot.

    The repository's capture validates the immutable snapshot digest, extension,
    and template schema. This function validates confirmation metadata shape,
    not today's source effectivity or the correctness of that human decision.
    """
    extension = snapshot.get("authoring_structure")
    if extension is None:
        return (), False, None
    metadata = extension.get("metadata") if isinstance(extension, dict) else None
    if not isinstance(metadata, dict):
        return (), True, None
    frozen = metadata.get("format_binding_manifest", [])
    declared = metadata.get("format_bindings", [])
    if not isinstance(frozen, list) or not isinstance(declared, list):
        return (), True, None

    def matching(rows):
        return [item for item in rows if isinstance(item, dict) and item.get("field") in fields]

    def is_shaped(item):
        return isinstance(item, dict) and isinstance(item.get("field"), str)

    if not all(is_shaped(item) for item in (*frozen, *declared)):
        return (), True, None
    frozen_rows = matching(frozen)
    declared_rows = matching(declared)
    if not frozen_rows and not declared_rows:
        return (), False, None
    effective = metadata.get("effective_style")
    ack = metadata.get("format_review_ack")
    malformed = not _digest(ack) or not isinstance(effective, dict)
    result: dict[str, int] = {}
    for item in frozen_rows:
        field = item["field"]
        selector = fields[field]
        if (
            selector in result
            or not _confirmed_numeric_binding(item)
            or not isinstance(effective, dict)
            or type(effective.get(field)) is not int
            or effective[field] != item["value"]
            or {k: v for k, v in item.items() if k not in {"basis", "interpretation"}}
            not in declared_rows
        ):
            malformed = True
            continue
        result[selector] = item["value"]
    if len(declared_rows) != len(result):
        malformed = True
    # Partial matches never silently validate an incomplete frozen declaration.
    basis_digest = (
        None
        if malformed
        else sha({"review_ack": ack, "binding_rows": sorted(frozen_rows, key=lambda r: r["field"])})
    )
    return tuple(sorted(result.items())), malformed, basis_digest


def frozen_page_margins(snapshot: Mapping[str, object]) -> FrozenPageMargins:
    return FrozenPageMargins(*_frozen_numeric_fields(snapshot, MARGIN_NAMES))


def frozen_text_defaults(snapshot: Mapping[str, object]) -> FrozenTextDefaults:
    """Only sourced, human-acknowledged raw default fields, never template fallback."""
    expected, malformed, basis = _frozen_numeric_fields(snapshot, TEXT_DEFAULT_FIELDS)
    invalid: tuple[str, ...] = ()
    partial_basis: tuple[tuple[str, str], ...] = ()
    if malformed:
        # A malformed binding neither supplies an expected value nor erases a
        # separately verified field. Malformed whole-snapshot metadata affects both.
        fields = {
            name: _frozen_numeric_fields(snapshot, {name: name}) for name in TEXT_DEFAULT_FIELDS
        }
        invalid = tuple(name for name, (_, bad, _) in fields.items() if bad)
        partial_basis = tuple(
            (name, digest) for name, (_, bad, digest) in fields.items() if not bad and digest
        )
    return FrozenTextDefaults(expected, malformed, basis, invalid, partial_basis)


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


def _inspect_page_margins(
    root: Element, expected: tuple[tuple[str, int], ...], blocking: set[str]
) -> None:
    ns = root.tag.rsplit("}", 1)[0] + "}"
    bodies = root.findall(ns + "body")
    final = bodies[0].findall(ns + "sectPr") if len(bodies) == 1 else []
    if len(final) != 1 or bodies[0][-1] is not final[0]:
        blocking.add(MARGIN_UNINSPECTABLE)
        return
    sections = [final[0], *bodies[0].findall(f"{ns}p/{ns}pPr/{ns}sectPr")]
    if set(root.iter(ns + "sectPr")) != set(sections):
        # Do not mistake an alternate/revised/unfamiliar section for known layout.
        blocking.add(MARGIN_UNINSPECTABLE)
    for section in sections:
        margins = section.findall(ns + "pgMar")
        if len(margins) != 1:
            blocking.add(MARGIN_UNINSPECTABLE)
            continue
        for side, twips in expected:
            measured = margins[0].get(ns + side, "")
            if _MEASUREMENT.fullmatch(measured) is None:
                blocking.add(MARGIN_UNINSPECTABLE)
            elif int(measured) != twips:
                blocking.add(MARGIN_MISMATCH)


def _unique_path(node: Element, ns: str, *parts: str) -> Element | None:
    for part in parts:
        children = node.findall(ns + part)
        if len(children) != 1:
            return None
        node = children[0]
    return node


def _inspect_text_defaults(
    archive: zipfile.ZipFile, expected: tuple[tuple[str, int], ...]
) -> dict[str, TextDefaultState]:
    values: dict[str, TextDefaultState] = {field: "UNINSPECTABLE" for field, _ in expected}
    # The writer's canonical stylesheet must be demonstrably active. Do not
    # use an orphan styles.xml or follow unknown alternate/compatibility parts.
    try:
        relationships = inspection._xml(archive.read("word/_rels/document.xml.rels"))
        types = inspection._xml(archive.read("[Content_Types].xml"))
        root = inspection._xml(archive.read("word/styles.xml"))
    except KeyError:
        return values
    styles_types = [
        part.get("ContentType")
        for part in types.findall(f"{{{inspection.CONTENT_NS}}}Override")
        if part.get("PartName") == "/word/styles.xml"
    ]
    style_links = [
        link
        for link in relationships
        if link.get("Type", "").rsplit("/", 1)[-1] in {"styles", "stylesWithEffects"}
    ]
    if (
        styles_types
        != ["application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"]
        or len(style_links) != 1
        or style_links[0].get("Type") not in {base + "/styles" for base in _OFFICE_REL}
        or style_links[0].get("Target") != "styles.xml"
        or style_links[0].get("TargetMode", "Internal") != "Internal"
        or root.tag not in {f"{{{namespace}}}styles" for namespace in inspection.WORD_NS}
    ):
        return values
    ns = root.tag.rsplit("}", 1)[0] + "}"
    defaults = _unique_path(root, ns, "docDefaults")
    if defaults is None or any(_local(node.tag) == "AlternateContent" for node in root.iter()):
        return values
    for field, value in expected:
        if field == "font_size_halfpoints":
            node = _unique_path(defaults, ns, "rPrDefault", "rPr", "sz")
            raw = node.get(ns + "val", "") if node is not None else ""
        elif field == "paragraph_after_twips":
            node = _unique_path(defaults, ns, "pPrDefault", "pPr", "spacing")
            if (
                node is None
                or ns + "afterLines" in node.attrib
                or node.get(ns + "afterAutospacing", "0").casefold() not in {"0", "false", "off"}
            ):
                raw = ""
            else:
                raw = node.get(ns + "after", "")
        else:
            raw = ""
        if _UNSIGNED.fullmatch(raw) is not None:
            values[field] = "RAW_MATCH" if int(raw) == value else "RAW_MISMATCH"
    return values


def _initial_text_defaults(
    frozen: FrozenTextDefaults,
) -> tuple[dict[str, TextDefaultState], tuple[tuple[str, int], ...]]:
    # A field without a binding is never checked against template defaults.
    expected = dict(frozen.expected)
    invalid = (
        set(frozen.malformed_fields) or set(TEXT_DEFAULT_FIELDS)
        if frozen.malformed_basis
        else set()
    )
    if len(expected) != len(frozen.expected) or not set(expected) <= TEXT_DEFAULT_FIELDS.keys():
        invalid = set(TEXT_DEFAULT_FIELDS)
    readings: dict[str, TextDefaultState] = {
        field: "UNINSPECTABLE" if field in expected or field in invalid else "NO_FROZEN_BASIS"
        for field in TEXT_DEFAULT_FIELDS
    }
    return readings, tuple(
        (field, value)
        for field, value in expected.items()
        if field not in invalid and field in readings
    )


def inspect_candidate_docx(
    data: bytes,
    *,
    filename: str,
    prohibited_names: Sequence[str] = (),
    page_margins: FrozenPageMargins | None = None,
    text_defaults: FrozenTextDefaults | None = None,
) -> DocxCandidateCheck:
    """Return blocking signals and outstanding human checks; neither means approval.

    Prohibited names come from an explicitly selected project policy. This lexical
    check does not attest visual/OCR content, style compliance or factual coverage.
    Placeholder checks cover only explicit supported marks in individual readable
    Word paragraphs, not missing values, diagrams, or project semantics.
    Text defaults compare only declared scalars, not real fonts, paragraphs,
    style overrides, text runs or the rendered layout.
    Callers must retain the reviewed basis and compare the hash of delivered bytes.
    """
    names = _names(prohibited_names)
    pattern = re.compile("|".join(map(re.escape, names))) if names else None
    blocking: set[str] = set()
    manual = {"FORMAT_AND_RENDER_REVIEW", "CONTENT_AND_PROJECT_RULE_REVIEW"}
    if page_margins is not None:
        if page_margins.malformed_basis:
            blocking.add(MARGIN_UNINSPECTABLE)
        elif not page_margins.expected_twips:
            manual.add(MARGIN_NO_BASIS)
    default_states, comparable = (
        _initial_text_defaults(text_defaults) if text_defaults is not None else ({}, ())
    )
    defaults_examined = False
    if text_defaults is not None:
        if text_defaults.malformed_basis:
            blocking.add(TEXT_DEFAULTS_UNINSPECTABLE)
        elif not text_defaults.expected:
            manual.add(TEXT_DEFAULTS_NO_BASIS)

    def flagged(value: str) -> bool:
        return pattern is not None and bool(pattern.search(_normalize(value)))

    def result() -> DocxCandidateCheck:
        blocked, human = blocking.copy(), manual.copy()
        for field, state in default_states.items():
            code = TEXT_DEFAULT_CODES[field] + "_" + state
            if state == "RAW_MISMATCH":
                blocked.update((code, TEXT_DEFAULTS_MISMATCH))
            elif state == "UNINSPECTABLE":
                blocked.add(code)
                if defaults_examined:
                    blocked.add(TEXT_DEFAULTS_UNINSPECTABLE)
            else:
                # The unchanged v1 wire has no observations bucket. Neither
                # a raw equality nor a missing binding grants approval.
                human.add(code)
        return DocxCandidateCheck(
            sha(data),
            sha(
                {
                    "filename": filename,
                    "prohibited_names": names,
                    "placeholder_policy": PLACEHOLDER_POLICY,
                }
                | (
                    {
                        "expected_page_margins_twips": page_margins.expected_twips,
                        "malformed_margin_basis": page_margins.malformed_basis,
                        "frozen_margin_basis_sha256": page_margins.basis_digest,
                    }
                    if page_margins is not None
                    else {}
                )
                | (
                    {
                        "text_defaults_policy": TEXT_DEFAULTS_POLICY,
                        "expected_text_defaults": text_defaults.expected,
                        "malformed_text_defaults_basis": text_defaults.malformed_basis,
                        "malformed_text_defaults_fields": text_defaults.malformed_fields,
                        "partial_text_defaults_basis_sha256": text_defaults.partial_basis_digests,
                        "frozen_text_defaults_basis_sha256": text_defaults.basis_digest,
                    }
                    if text_defaults is not None
                    else {}
                )
            ),
            tuple(sorted(blocked)),
            tuple(sorted(human)),
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
        if comparable:
            defaults_examined = True
            default_states.update(_inspect_text_defaults(archive, comparable))
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
            if (
                part == "word/document.xml"
                and page_margins is not None
                and page_margins.expected_twips
            ):
                _inspect_page_margins(root, page_margins.expected_twips, blocking)
            location = (
                "METADATA"
                if folded.startswith("docprops/")
                else "HEADER_FOOTER"
                if _local(root.tag) in {"hdr", "ftr"}
                else "CONTENT"
            )
            is_story = root.tag in _WORD_STORIES
            if pattern or is_story:
                for paragraph in _paragraph_strings(root):
                    normalized = _normalize(paragraph)
                    if pattern and pattern.search(normalized):
                        blocking.add("PROHIBITED_NAME_" + location)
                    if is_story and _PLACEHOLDER.search(normalized):
                        blocking.add(PLACEHOLDER_FOUND)
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
