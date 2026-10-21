"""Pure, bounded multi-paragraph candidates for an explicitly frozen chapter.

The model can supply inline text and insertion positions, never document metadata,
node identities, assets or source objects. Existing tables/images and every node
outside the selected text scope are retained byte-for-byte in canonical JSON.
No function performs storage, model calls or draft mutations.
"""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from packages.authoring.content import schema_digest_for, validate_content
from packages.domain.runtime import DomainError, sha

MODE = "section_patch_set/1"
LIMITS = {
    "editable_nodes": 1000,
    "replacements": 500,
    "insertion_positions": 200,
    "added_paragraphs": 500,
    "inline_nodes": 2000,
    "text_characters": 200000,
    "patch_bytes": 1000000,
    "evidence_ids": 500,
    "source_text_characters": 100000,
}


def _object(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _array(items, maximum, *, minimum=0, unique=False):
    return {
        "type": "array",
        "items": items,
        "minItems": minimum,
        "maxItems": maximum,
        "uniqueItems": unique,
    }


_NODE_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_INLINE = _array(
    {
        "oneOf": [
            _object(
                {
                    "type": {"const": "text"},
                    "text": {"type": "string", "minLength": 1, "maxLength": 20000},
                    "marks": _array(
                        _object({"type": {"enum": ["bold", "italic"]}}), 2, unique=True
                    ),
                },
                ["type", "text"],
            ),
            _object({"type": {"const": "hardBreak"}}),
        ]
    },
    LIMITS["inline_nodes"],
)
_SCHEMA = _object(
    {
        "replacements": _array(
            _object({"node_id": _NODE_ID, "before_digest": _HASH, "inline": _INLINE}),
            LIMITS["replacements"],
        ),
        "insertions": _array(
            _object(
                {
                    "after_node_id": {"oneOf": [_NODE_ID, {"type": "null"}]},
                    "anchor_digest": _HASH,
                    "paragraphs": _array(
                        _object({"inline": _INLINE}), LIMITS["added_paragraphs"], minimum=1
                    ),
                }
            ),
            LIMITS["insertion_positions"],
        ),
        "evidence_ids": _array(
            {"type": "string", "format": "uuid"}, LIMITS["evidence_ids"], unique=True
        ),
    }
)
SCHEMA_DIGEST = sha(_SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


def model_schema():
    return deepcopy(_SCHEMA)


def _invalid(code="MODEL_PATCH_SET_INVALID", message="章节候选不符合冻结的多段落编写范围"):
    raise DomainError(code, message, 422)


def _bounded_json(value):
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (UnicodeError, ValueError, TypeError, RecursionError):
        _invalid(message="章节候选必须是可保存的有限UTF-8 JSON")
    if size > LIMITS["patch_bytes"]:
        _invalid("AUTHORING_PATCH_SET_LIMIT", "章节候选超过完整处理范围，未截断或应用")


def _nodes(node):
    for item in node.get("content", []):
        if "id" in item.get("attrs", {}):
            yield item
        yield from _nodes(item)


def _editable(node):
    for item in node.get("content", []):
        if item["type"] in {"table", "image"}:
            continue
        if item["type"] in {"paragraph", "heading"}:
            yield item
        else:
            yield from _editable(item)


def freeze_scope(original_content, selected_node_ids=None):
    """Freeze actual editable nodes and insertion gaps, without flattening Rich.

    Whole-chapter mode permits text nodes outside tables and all top-level gaps.
    Explicit node scope permits only those nodes and gaps after entirely selected
    top-level text/list blocks. It cannot insert before an unselected first block.
    """
    validate_content(original_content)
    editable = list(_editable(original_content))
    allowed = {item["attrs"]["id"]: item for item in editable}
    whole = selected_node_ids is None
    if whole:
        selected = set(allowed)
    else:
        if (
            not isinstance(selected_node_ids, list)
            or not selected_node_ids
            or any(not isinstance(value, str) for value in selected_node_ids)
            or len(selected_node_ids) != len(set(selected_node_ids))
            or not set(selected_node_ids) <= set(allowed)
        ):
            _invalid(
                "AUTHORING_PATCH_SCOPE_INVALID", "编写范围必须是实际文字节点且不能包含表格或图片"
            )
        selected = set(selected_node_ids)
    if len(selected) > LIMITS["editable_nodes"]:
        _invalid("AUTHORING_PATCH_SET_LIMIT", "所选文字节点超过完整编写范围，请缩小范围")
    before_digest = sha(original_content)
    targets = [
        {"node_id": item["attrs"]["id"], "before_digest": sha(item)}
        for item in editable
        if item["attrs"]["id"] in selected
    ]
    anchors = []
    if whole:
        anchors.append(
            {
                "after_node_id": None,
                "anchor_digest": sha({"position": "start", "before_digest": before_digest}),
            }
        )
    for item in original_content["content"]:
        contained = {node["attrs"]["id"] for node in _editable({"content": [item]})}
        if whole or contained and contained <= selected:
            anchors.append({"after_node_id": item["attrs"]["id"], "anchor_digest": sha(item)})
    scope = {
        "mode": MODE,
        "schema_digest": SCHEMA_DIGEST,
        "selection": "section" if whole else "nodes",
        "before_digest": before_digest,
        "selected_node_ids": [item["node_id"] for item in targets],
        "replacement_targets": targets,
        "insertion_targets": anchors,
    }
    return scope | {"digest": sha(scope)}


def _checked_plan(plan):
    if (
        not isinstance(plan, dict)
        or plan.get("generation_mode") != MODE
        or not isinstance(plan.get("patch_scope"), dict)
        or not isinstance(plan.get("instruction"), str)
        or not 1 <= len(plan["instruction"].strip()) <= 8000
    ):
        _invalid("AUTHORING_PATCH_SCOPE_INVALID", "缺少服务端冻结的章节编写范围")
    scope = plan["patch_scope"]
    original = plan.get("original_content")
    if scope.get("selection") not in {"section", "nodes"}:
        _invalid("AUTHORING_PATCH_SCOPE_INVALID")
    expected = freeze_scope(
        original,
        None if scope["selection"] == "section" else scope.get("selected_node_ids"),
    )
    if scope != expected or plan.get("section_digest") != sha(original):
        _invalid("AUTHORING_PATCH_SCOPE_CHANGED", "冻结章节或编写范围摘要不一致，未应用候选")
    return original, scope


def _identity(writing_plan_id):
    try:
        identity = UUID(str(writing_plan_id))
    except (ValueError, TypeError, AttributeError):
        _invalid("AUTHORING_PATCH_SCOPE_INVALID", "编写计划身份无效")
    return identity


def _checked_raw(value):
    _bounded_json(value)
    if not _VALIDATOR.is_valid(value):
        _invalid()
    if not value["replacements"] and not value["insertions"]:
        _invalid("MODEL_PATCH_NO_CHANGE", "模型未提出正文修改或新增段落")
    paragraphs = sum(len(item["paragraphs"]) for item in value["insertions"])
    if paragraphs > LIMITS["added_paragraphs"]:
        _invalid("AUTHORING_PATCH_SET_LIMIT", "新增正文段落超过完整处理范围，未截断")
    inline = [item["inline"] for item in value["replacements"]] + [
        paragraph["inline"] for item in value["insertions"] for paragraph in item["paragraphs"]
    ]
    text = [node["text"] for nodes in inline for node in nodes if node["type"] == "text"]
    if sum(map(len, text)) > LIMITS["text_characters"]:
        _invalid("AUTHORING_PATCH_SET_LIMIT", "候选正文超过完整处理范围，未截断")
    if any(any(ord(char) < 32 and char not in "\t\n" for char in item) for item in text):
        _invalid(message="候选正文包含不能保存的控制字符")
    return deepcopy(value)


def _source_refs(plan, evidence_ids):
    blocks = plan.get("source_blocks")
    if not isinstance(blocks, list) or len(blocks) > LIMITS["evidence_ids"]:
        _invalid("AUTHORING_PATCH_SCOPE_INVALID", "冻结来源范围无效")
    allowed = {}
    text_size = 0
    for block in blocks:
        if (
            not isinstance(block, dict)
            or not isinstance(block.get("evidence_id"), str)
            or not isinstance(block.get("source_ref"), dict)
            or block["source_ref"].get("evidence_id") != block["evidence_id"]
            or block["evidence_id"] in allowed
            or type(block.get("physical_page")) is not int
            or block["physical_page"] < 1
            or not isinstance(block.get("text"), str)
        ):
            _invalid("AUTHORING_PATCH_SCOPE_INVALID", "冻结证据身份不唯一或与来源不符")
        ref = block["source_ref"]
        try:
            if (
                set(ref) != {"source_id", "source_revision", "evidence_id", "document_version_id"}
                or type(ref["source_revision"]) is not int
                or ref["source_revision"] < 1
            ):
                raise ValueError
            for field in ("source_id", "evidence_id", "document_version_id"):
                if not isinstance(ref[field], str):
                    raise ValueError
                UUID(ref[field])
            block["text"].encode("utf-8", errors="strict")
        except (ValueError, TypeError, AttributeError, UnicodeError):
            _invalid("AUTHORING_PATCH_SCOPE_INVALID", "冻结来源对象或证据文字无效")
        text_size += len(block["text"])
        allowed[block["evidence_id"]] = block["source_ref"]
    if text_size > LIMITS["source_text_characters"]:
        _invalid("AUTHORING_PATCH_SET_LIMIT", "冻结来源超过完整编写范围，未截断")
    if any(identity not in allowed for identity in evidence_ids):
        _invalid("MODEL_CITATION_INVALID", "候选引用了未实际提供的证据")
    return [deepcopy(allowed[identity]) for identity in evidence_ids]


def request_context(plan):
    """The model receives the complete selected chapter and explicit edit authority."""
    original, scope = _checked_plan(plan)
    _source_refs(plan, [])
    return {
        "instruction": plan["instruction"],
        "original_content": deepcopy(original),
        "patch_scope": deepcopy(scope),
        "source_blocks": [
            {key: block[key] for key in ("evidence_id", "physical_page", "text")}
            for block in plan["source_blocks"]
        ],
        "output_policy": "inline_text_and_existing_anchor_ids_only_no_asset_or_source_objects",
    }


def _build(plan, writing_plan_id, raw):
    original, scope = _checked_plan(plan)
    identity = _identity(writing_plan_id)
    patch = _checked_raw(raw)
    replacements = {item["node_id"]: item for item in patch["replacements"]}
    insertions = {item["after_node_id"]: item for item in patch["insertions"]}
    if len(replacements) != len(patch["replacements"]) or len(insertions) != len(
        patch["insertions"]
    ):
        _invalid(message="同一文字节点或插入位置不能重复提交")
    target_digests = {
        item["node_id"]: item["before_digest"] for item in scope["replacement_targets"]
    }
    anchor_digests = {
        item["after_node_id"]: item["anchor_digest"] for item in scope["insertion_targets"]
    }
    if any(target_digests.get(key) != item["before_digest"] for key, item in replacements.items()):
        _invalid("AUTHORING_PATCH_RANGE_CHANGED", "替换目标不在冻结范围或原文摘要不符")
    if any(anchor_digests.get(key) != item["anchor_digest"] for key, item in insertions.items()):
        _invalid("AUTHORING_PATCH_RANGE_CHANGED", "新增正文的锚点不在冻结范围或原文摘要不符")
    patch["replacements"] = [replacements[key] for key in target_digests if key in replacements]
    patch["insertions"] = [insertions[key] for key in anchor_digests if key in insertions]
    patch["evidence_ids"] = sorted(patch["evidence_ids"])
    refs = _source_refs(plan, patch["evidence_ids"])
    updated = deepcopy(original)
    for node in _editable(updated):
        replacement = replacements.get(node["attrs"]["id"])
        if replacement is not None:
            if node["content"] == replacement["inline"]:
                _invalid("MODEL_PATCH_NO_CHANGE", "候选包含与原文完全相同的替换")
            node["content"] = deepcopy(replacement["inline"])
    existing_ids = {node["attrs"]["id"] for node in _nodes(original)}
    added = []

    def paragraphs_after(anchor):
        item = insertions.get(anchor)
        if item is None:
            return []
        nodes = []
        for index, paragraph in enumerate(item["paragraphs"]):
            node_id = str(uuid5(identity, MODE + ":" + json.dumps([anchor, index])))
            if node_id in existing_ids:
                _invalid("AUTHORING_PATCH_NODE_COLLISION", "新增节点与现有身份冲突，未覆盖原节点")
            existing_ids.add(node_id)
            nodes.append(
                {
                    "type": "paragraph",
                    "attrs": {"id": node_id},
                    "content": deepcopy(paragraph["inline"]),
                }
            )
        added.append({"after_node_id": anchor, "node_ids": [node["attrs"]["id"] for node in nodes]})
        return nodes

    content = paragraphs_after(None)
    for node in updated["content"]:
        content.append(node)
        content.extend(paragraphs_after(node["attrs"]["id"]))
    updated["content"] = content
    known_refs = {sha(ref) for ref in updated["attrs"]["source_refs"]}
    for ref in refs:
        if sha(ref) not in known_refs:
            updated["attrs"]["source_refs"].append(ref)
            known_refs.add(sha(ref))
    validate_content(updated)
    # This explicit postcondition also guards future edits to the interpreter.
    after_nodes = {node["attrs"]["id"]: node for node in _nodes(updated)}
    for node in _nodes(original):
        node_id = node["attrs"]["id"]
        after = after_nodes.get(node_id)
        if after is None or node["type"] != after["type"] or node["attrs"] != after["attrs"]:
            _invalid("AUTHORING_PATCH_PRESERVATION_FAILED", "候选改变了原有结构或节点身份")
        if node["type"] in {"table", "image"} or (
            node["type"] in {"paragraph", "heading"} and node_id not in replacements
        ):
            if sha(node) != sha(after):
                _invalid("AUTHORING_PATCH_PRESERVATION_FAILED", "候选改变了表图或未选正文")
    canonical = {
        "mode": MODE,
        "writing_plan_id": str(identity),
        "scope_digest": scope["digest"],
        "before_digest": sha(original),
        "after_digest": sha(updated),
        "patch_set": patch,
    }
    _bounded_json(canonical)
    preview = {
        "before": deepcopy(original),
        "after": updated,
        "schema_digest": schema_digest_for(updated),
        "changes": {
            "replaced_node_ids": [item["node_id"] for item in patch["replacements"]],
            "insertions": added,
            "added_paragraphs": sum(len(item["node_ids"]) for item in added),
        },
    }
    return canonical, preview


def canonicalize(plan, writing_plan_id, raw):
    """Validate provider data and bind deterministic before/after identities."""
    return _build(plan, writing_plan_id, raw)[0]


def _checked_canonical(plan, writing_plan_id, candidate):
    _bounded_json(candidate)
    if not isinstance(candidate, dict) or set(candidate) != {
        "mode",
        "writing_plan_id",
        "scope_digest",
        "before_digest",
        "after_digest",
        "patch_set",
    }:
        _invalid("AUTHORING_PATCH_CANDIDATE_INVALID", "规范候选身份不完整")
    canonical, preview = _build(plan, writing_plan_id, candidate["patch_set"])
    if canonical != candidate:
        _invalid("AUTHORING_PATCH_CANDIDATE_INVALID", "候选与实际冻结输入或正文摘要不符")
    return canonical, preview


def validate_canonical(plan, writing_plan_id, candidate):
    return _checked_canonical(plan, writing_plan_id, candidate)[0]


def materialize(plan, writing_plan_id, candidate):
    """Return full, verified before/after Rich and concrete change locations."""
    return _checked_canonical(plan, writing_plan_id, candidate)[1]
