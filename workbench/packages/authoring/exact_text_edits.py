"""One explicit human text change, bound to the saved exact revision and command.

This path does not enable the ordinary editor, alter citations, replace structure,
or claim that the model generated/reviewed the human's replacement.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID

from psycopg.types.json import Jsonb

from packages.authoring.content import SCHEMA_DIGEST, validate_text_content
from packages.authoring.exact_text_edit_contracts import (
    AuthoringExactManualRevisionView,
    AuthoringExactMultiManualRevisionView,
    AuthoringExactMultiTextEditRequest,
    AuthoringExactTextEditRequest,
)
from packages.domain.runtime import ROOT, DomainError, clean, fetch, sha, uid

KIND = "authoring-exact-text-edit"


def rejected(message="固定来源文字修订与原稿或请求不一致，未保存修改"):
    raise DomainError("AUTHORING_EXACT_TEXT_EDIT_INVALID", message, 409)


def multi(request):
    return request.get("protocol") == "authoring-exact-multi-text-edit/1"


def parse_request(request):
    model = AuthoringExactMultiTextEditRequest if multi(request) else AuthoringExactTextEditRequest
    return clean(model.model_validate(request).model_dump(mode="json"))


def multi_installed(c):
    return c.execute(
        "SELECT to_regprocedure('design.authoring_exact_check_multi_text_record(uuid)') IS NOT NULL AS ready"
    ).fetchone()["ready"]


def policy(is_multi=False):
    paths: tuple[str, ...] = (
        "packages/authoring/exact_text_edits.py",
        "packages/authoring/exact_text_edit_service.py",
        "packages/authoring/exact_text_edit_contracts.py",
        "packages/authoring/exact_sources.py",
        "packages/authoring/repository.py",
        "packages/contracts/sql/authoring-exact-text-edits.sql",
    )
    if is_multi:
        paths += ("packages/contracts/sql/authoring-exact-multi-text-edits.sql",)
    return {
        "protocol": "authoring-exact-text-edit-policy/2"
        if is_multi
        else "authoring-exact-text-edit-policy/1",
        "supported_content": "plain_text_stable_nodes" if is_multi else "plain_text_stable_node",
        "source_sha256": {name: sha((ROOT / name).read_bytes()) for name in paths},
    }


def materialize(original, request):
    """Reconstruct from server content; the request cannot carry any source metadata."""
    from packages.authoring.patches import replace_node

    body = parse_request(request)
    if multi(body):
        edits = body["edits"]
        if len({edit["node_id"] for edit in edits}) != len(edits):
            raise DomainError("INVALID_REQUEST", "同一节点不能重复修订", 422)
        if sum(len(edit["replacement_text"]) for edit in edits) > 20000:
            raise DomainError("INVALID_REQUEST", "本次修订文字合计不能超过20000字符", 422)
        # Validate every node against the immutable parent before constructing a result.
        common = {
            key: body[key] for key in ("base_draft_revision", "section_revision_id", "reason")
        }
        for edit in edits:
            materialize(original, {**common, **edit})
        result = deepcopy(original)
        for edit in edits:
            result = materialize(result, {**common, **edit})
        return result
    if not body["reason"].strip() or any(
        ord(ch) < 32 and ch not in "\t\n" for ch in body["reason"]
    ):
        raise DomainError("INVALID_REQUEST", "请填写有效的文字修订说明", 422)
    validate_text_content(original)
    matches = []

    def visit(node):
        if node.get("attrs", {}).get("id") == body["node_id"]:
            matches.append(node)
        for child in node.get("content", []):
            visit(child)

    visit(original)
    if len(matches) != 1 or sha(matches[0]) != body["before_node_digest"]:
        raise DomainError("SECTION_REVISION_CONFLICT", "文字节点已变化，请保留修改并重新核对", 412)
    node = matches[0]
    if node["type"] not in {"paragraph", "heading"} or any(
        child.get("type") != "text" or child.get("marks") for child in node["content"]
    ):
        raise DomainError(
            "AUTHORING_EXACT_TEXT_NODE_UNSUPPORTED", "请选择无富文本标记的现有纯文字段落或标题", 422
        )
    replacement = deepcopy(node)
    replacement["content"] = (
        [{"type": "text", "text": body["replacement_text"]}] if body["replacement_text"] else []
    )
    result = replace_node(original, body["node_id"], body["before_node_digest"], replacement)
    if result == original:
        raise DomainError("AUTHORING_EXACT_TEXT_NO_CHANGE", "文字未发生变化，无需保存新修订", 422)
    return result


def installed(c):
    return bool(
        c.execute(
            "SELECT to_regclass('design.authoring_exact_manual_revisions') IS NOT NULL "
            "AND to_regclass('design.authoring_exact_revision_records') IS NOT NULL "
            "AND to_regprocedure('design.authoring_exact_check_manual_revision(uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]
    )


def available(c):
    from packages.authoring import exact_builds, exact_sources

    if not installed(c) or not exact_sources.apply_available(c) or not exact_builds.available(c):
        return False
    return all(
        c.execute(
            "SELECT coalesce(has_table_privilege(current_user,to_regclass(%s),%s),false) AS ready",
            (name, privilege),
        ).fetchone()["ready"]
        for name, privilege in (
            ("design.authoring_exact_manual_revisions", "SELECT"),
            ("design.authoring_exact_manual_revisions", "INSERT"),
            ("design.authoring_exact_revision_records", "SELECT"),
        )
    )


def require_available(c):
    if not available(c):
        raise DomainError(
            "AUTHORING_EXACT_TEXT_EDIT_NOT_CONFIGURED",
            "固定来源文字修订及构建所需扩展尚未配置，原稿保持不变",
            503,
        )


@dataclass(frozen=True, slots=True)
class ExactManualEdit:
    command_id: UUID
    actor_id: UUID
    condition: str
    before_action: dict = field(repr=False)
    parent_qualification_id: UUID
    parent_qualification_digest: str
    section_revision_id: UUID = field(default_factory=uid)
    qualification_id: UUID = field(default_factory=uid)


def check(c, admission, bid, draft, actor, body):
    from packages.authoring import exact_sources
    from packages.authoring.repository import draft_etag

    if not isinstance(admission, ExactManualEdit):
        rejected()
    require_available(c)
    request = admission.before_action["request"]
    parent = exact_sources.assert_current(c, bid, UUID(request["section_revision_id"]))
    p = parent["manifest"]
    original = fetch(
        c, "SELECT * FROM design.section_revisions WHERE id=%s", (p["section_revision_id"],)
    )
    expected_content = materialize(original["content"], request)
    command = fetch(c, "SELECT * FROM design.commands WHERE id=%s", (admission.command_id,))
    expected = {
        "base_draft_revision": request["base_draft_revision"],
        "changes": [
            {
                "section_id": p["section_id"],
                "base_section_revision": p["section_revision"],
                "schema_digest": p["schema_digest"],
                "content": expected_content,
            }
        ],
    }
    if (
        str(bid) != p["bid_id"]
        or str(draft) != p["draft_id"]
        or str(actor) != str(admission.actor_id)
        or str(admission.parent_qualification_id) != p["id"]
        or admission.parent_qualification_digest != parent["digest"]
        or p["schema_digest"] != SCHEMA_DIGEST
        or body != expected
        or admission.condition != draft_etag(draft, request["base_draft_revision"])
        or command["actor_id"] != admission.actor_id
        or command["command_kind"] != KIND
        or command["target_id"] != UUID(str(draft))
        or command["response"] is not None
        or command["request_digest"] != sha({"body": request, "if_match": admission.condition})
    ):
        rejected()
    snapshot = fetch(
        c,
        "SELECT * FROM design.draft_snapshots WHERE bid_id=%s AND draft_id=%s AND revision=%s",
        (bid, draft, request["base_draft_revision"]),
    )
    if (
        str(snapshot["id"]) != admission.before_action["base_snapshot_id"]
        or snapshot["digest"] != admission.before_action["base_snapshot_digest"]
        or not c.execute(
            "SELECT 1 FROM design.draft_snapshot_sections WHERE snapshot_id=%s AND section_revision_id=%s",
            (snapshot["id"], p["section_revision_id"]),
        ).fetchone()
    ):
        rejected()
    return parent, expected_content


def append(c, admission, bid, draft, section, revision, content, actor, schema_digest):
    request = admission.before_action["request"]
    return check(
        c,
        admission,
        bid,
        draft,
        actor,
        {
            "base_draft_revision": request["base_draft_revision"],
            "changes": [
                {
                    "section_id": str(section),
                    "base_section_revision": revision - 1,
                    "schema_digest": schema_digest,
                    "content": content,
                }
            ],
        },
    )


def bind(c, admission, parent, expected_content, content, schema_digest):
    from packages.authoring.exact_sources import record_citations

    if content != expected_content:
        rejected()
    p = parent["manifest"]
    if p["origin"]["kind"] == "model_candidate_adoption":
        root_id, root_digest = p["id"], parent["digest"]
    else:
        root_id = p["origin"]["root_qualification_id"]
        root_digest = p["origin"]["root_qualification_digest"]
    request = admission.before_action["request"]
    is_multi = multi(request)
    method = policy(is_multi)
    m = clean(
        {
            "protocol": "authoring-exact-manual-revision/2"
            if is_multi
            else "authoring-exact-manual-revision/1",
            "id": admission.qualification_id,
            "bid_id": p["bid_id"],
            "draft_id": p["draft_id"],
            "draft_revision": request["base_draft_revision"] + 1,
            "section_id": p["section_id"],
            "section_revision_id": admission.section_revision_id,
            "section_revision": p["section_revision"] + 1,
            "section_digest": sha(content),
            "schema_digest": schema_digest,
            "parent_section_revision_id": p["section_revision_id"],
            "parent_section_revision": p["section_revision"],
            "parent_section_digest": p["section_digest"],
            "input": p["input"],
            "origin": {
                "kind": "manual_multi_text_edit" if is_multi else "manual_text_edit",
                "parent_qualification_id": p["id"],
                "parent_qualification_digest": parent["digest"],
                "root_qualification_id": root_id,
                "root_qualification_digest": root_digest,
                "command_id": admission.command_id,
                "actor_id": admission.actor_id,
                "before_action_digest": sha(admission.before_action),
                **(
                    {
                        "edits": [
                            {
                                "node_id": edit["node_id"],
                                "before_node_digest": edit["before_node_digest"],
                                "replacement_text_digest": sha(edit["replacement_text"].encode()),
                            }
                            for edit in request["edits"]
                        ]
                    }
                    if is_multi
                    else {
                        "node_id": request["node_id"],
                        "before_node_digest": request["before_node_digest"],
                        "replacement_text_digest": sha(request["replacement_text"].encode()),
                    }
                ),
                "reason": request["reason"],
            },
            "source_scope": "exact_package_context",
            "source_refs_digest": sha(content["attrs"]["source_refs"]),
            "rule_ids_digest": sha(content["attrs"]["rule_ids"]),
            "method": method,
            "method_digest": sha(method),
            "candidate_adopted": False,
            "content_correctness_certified": False,
        }
    )
    value = {"manifest": m, "digest": sha(m)}
    model = AuthoringExactMultiManualRevisionView if is_multi else AuthoringExactManualRevisionView
    model.model_validate(value)
    c.execute(
        "INSERT INTO design.authoring_exact_manual_revisions "
        "(id,bid_id,draft_id,section_id,section_revision_id,parent_revision_id,parent_qualification_id,"
        "root_qualification_id,input_id,command_id,actor_id,draft_revision,manifest,digest,before_action,request_condition) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            m["id"],
            m["bid_id"],
            m["draft_id"],
            m["section_id"],
            m["section_revision_id"],
            m["parent_section_revision_id"],
            p["id"],
            root_id,
            m["input"]["id"],
            admission.command_id,
            admission.actor_id,
            m["draft_revision"],
            Jsonb(m),
            value["digest"],
            Jsonb(admission.before_action),
            admission.condition,
        ),
    )
    record_citations(c, p["bid_id"], admission.section_revision_id, content)
    return value
