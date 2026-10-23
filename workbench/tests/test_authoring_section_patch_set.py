"""Real Rich interpretation and offline provider protocol, with no paid network calls."""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import httpx
import pytest

from packages.assistant import actions, generation, jobs
from packages.authoring import patches
from packages.authoring import section_patch_set as patch_set
from packages.authoring.content import schema_digest_for, validate_content
from packages.domain.runtime import DomainError, now, sha


def identity(value):
    return str(UUID(int=value))


def paragraph(node_id, text):
    return {
        "type": "paragraph",
        "attrs": {"id": node_id},
        "content": [{"type": "text", "text": text}],
    }


def reference(value):
    return {
        "source_id": identity(value),
        "source_revision": 2,
        "evidence_id": identity(value + 1),
        "document_version_id": identity(value + 2),
    }


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("A pure patch-set test attempted real HTTP")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject)


@pytest.fixture
def rich_plan():
    table = {
        "type": "table",
        "attrs": {"id": "table", "column_widths_twips": [2000, 2200], "caption": "原合并表"},
        "content": [
            {
                "type": "tableRow",
                "attrs": {"id": "row1"},
                "content": [
                    {
                        "type": "tableCell",
                        "attrs": {"id": "cell1", "colspan": 1, "rowspan": 2, "header": True},
                        "content": [paragraph("cell-p1", "格内原件内容必须保留")],
                    },
                    {
                        "type": "tableCell",
                        "attrs": {"id": "cell2", "colspan": 1, "rowspan": 1, "header": True},
                        "content": [paragraph("cell-p2", "原数值123")],
                    },
                ],
            },
            {
                "type": "tableRow",
                "attrs": {"id": "row2"},
                "content": [
                    {
                        "type": "tableCell",
                        "attrs": {"id": "cell3", "colspan": 1, "rowspan": 1, "header": False},
                        "content": [paragraph("cell-p3", "原表续行")],
                    }
                ],
            },
        ],
    }
    image = {
        "type": "image",
        "attrs": {
            "id": "image",
            "asset_id": identity(20),
            "asset_revision": 3,
            "asset_version_id": identity(21),
            "width_twips": 2400,
            "height_twips": 1800,
            "alt": "原现场图片",
            "caption": "原图注",
        },
    }
    original = {
        "type": "doc",
        "attrs": {
            "title": "施工组织",
            "ordinal": 3,
            "rule_ids": [identity(30)],
            "source_refs": [reference(40)],
        },
        "content": [
            {
                "type": "heading",
                "attrs": {"id": "heading", "level": 2},
                "content": [{"type": "text", "text": "原小标题"}],
            },
            paragraph("p1", "原正文一"),
            table,
            image,
            {
                "type": "bulletList",
                "attrs": {"id": "list"},
                "content": [
                    {
                        "type": "listItem",
                        "attrs": {"id": "item1"},
                        "content": [paragraph("list-p1", "原列表一")],
                    },
                    {
                        "type": "listItem",
                        "attrs": {"id": "item2"},
                        "content": [paragraph("list-p2", "原列表二")],
                    },
                ],
            },
            paragraph("p2", "未选结尾不改"),
        ],
    }
    return plan_for(original)


def plan_for(original, selected=None):
    validate_content(original)
    return {
        "generation_mode": patch_set.MODE,
        "patch_scope": patch_set.freeze_scope(original, selected),
        "section_digest": sha(original),
        "original_content": original,
        "instruction": "根据实际证据补充施工安排，缺失事实明确待补",
        "source_blocks": [
            {
                "evidence_id": reference(value)["evidence_id"],
                "physical_page": index + 1,
                "text": "合成证据正文",
                "source_ref": reference(value),
            }
            for index, value in enumerate((50, 60))
        ],
    }


def replace(plan, node_id="p1", text="已核验的新正文"):
    target = next(
        item for item in plan["patch_scope"]["replacement_targets"] if item["node_id"] == node_id
    )
    return target | {"inline": [{"type": "text", "text": text, "marks": [{"type": "bold"}]}]}


def insert(plan, after=None, texts=("新增正文一", "新增正文二")):
    target = next(
        item for item in plan["patch_scope"]["insertion_targets"] if item["after_node_id"] == after
    )
    return target | {"paragraphs": [{"inline": [{"type": "text", "text": text}]} for text in texts]}


def output(plan):
    return {
        "replacements": [replace(plan), replace(plan, "list-p1", "改进的列表安排")],
        "insertions": [insert(plan), insert(plan, "table", ("表后新增说明",))],
        "evidence_ids": [identity(51)],
    }


def manifest(plan):
    return {
        "kind": "authoring",
        "generation_mode": patch_set.MODE,
        "batch_context": {"batch_id": identity(100), "section_id": identity(101), "attempt": 1},
        "writing_plan_id": identity(102),
        "selection": None,
        "request": {"section_id": identity(101), "base_section_revision": 4},
        "plan": plan,
        "project_memory": {
            "confirmed": "已确认的合成信息",
            "source_authorities": [{"private": "guard"}],
        },
    }


def by_id(doc):
    result = {}

    def walk(node):
        if "id" in node.get("attrs", {}):
            result[node["attrs"]["id"]] = node
        for child in node.get("content", []):
            walk(child)

    walk(doc)
    return result


def test_real_multi_paragraph_candidate_preserves_merges_images_metadata_and_unselected_bytes(
    rich_plan,
):
    original = deepcopy(rich_plan)
    raw = output(rich_plan)
    untouched_raw = deepcopy(raw)
    candidate = patch_set.canonicalize(rich_plan, identity(102), raw)
    assert candidate == patch_set.canonicalize(rich_plan, identity(102), raw)
    preview = patch_set.materialize(rich_plan, identity(102), candidate)
    before, after = by_id(preview["before"]), by_id(preview["after"])
    assert raw == untouched_raw and rich_plan == original
    assert candidate["before_digest"] == sha(preview["before"])
    assert candidate["after_digest"] == sha(preview["after"])
    assert preview["schema_digest"] == schema_digest_for(rich_plan["original_content"])
    for node_id in ("table", "image", "p2", "heading", "list-p2", "cell-p1", "cell-p2", "cell-p3"):
        assert sha(before[node_id]) == sha(after[node_id])
    assert after["p1"]["attrs"] == before["p1"]["attrs"]
    assert after["list"]["attrs"] == before["list"]["attrs"]
    assert after["list-p1"]["content"][0]["text"] == "改进的列表安排"
    assert preview["changes"]["replaced_node_ids"] == ["p1", "list-p1"]
    assert preview["changes"]["added_paragraphs"] == 3
    assert preview["after"]["attrs"] == original["original_content"]["attrs"] | {
        "source_refs": [reference(40), reference(50)]
    }
    assert [
        item["attrs"]["id"] for item in preview["after"]["content"] if item["attrs"]["id"] in before
    ] == [item["attrs"]["id"] for item in preview["before"]["content"]]
    new_ids = [node_id for item in preview["changes"]["insertions"] for node_id in item["node_ids"]]
    assert len(set(new_ids)) == 3 and all(str(UUID(node_id)) == node_id for node_id in new_ids)
    assert set(new_ids).isdisjoint(before)
    validate_content(preview["after"])


def test_model_record_order_normalizes_without_changing_paragraph_order(rich_plan):
    raw = output(rich_plan)
    raw["evidence_ids"] = [identity(61), identity(51)]
    permuted = deepcopy(raw)
    permuted["replacements"].reverse()
    permuted["insertions"].reverse()
    permuted["evidence_ids"].reverse()
    assert patch_set.canonicalize(rich_plan, identity(102), raw) == patch_set.canonicalize(
        rich_plan, identity(102), permuted
    )


def test_explicit_scope_preserves_other_inline_marks_and_only_allows_selected_gap(rich_plan):
    scoped = plan_for(rich_plan["original_content"], ["p1"])
    assert [item["after_node_id"] for item in scoped["patch_scope"]["insertion_targets"]] == ["p1"]
    raw = {
        "replacements": [replace(scoped)],
        "insertions": [insert(scoped, "p1")],
        "evidence_ids": [],
    }
    preview = patch_set.materialize(
        scoped, identity(102), patch_set.canonicalize(scoped, identity(102), raw)
    )
    old, new = by_id(preview["before"]), by_id(preview["after"])
    assert all(sha(new[key]) == sha(node) for key, node in old.items() if key != "p1")
    for anchor in (None, "table", "image", "p2"):
        bad = deepcopy(raw)
        bad["insertions"] = [insert(rich_plan, anchor)]
        with pytest.raises(DomainError) as error:
            patch_set.canonicalize(scoped, identity(102), bad)
        assert error.value.code == "AUTHORING_PATCH_RANGE_CHANGED"


def test_list_insertion_gap_requires_entire_top_level_list_selected(rich_plan):
    partial = plan_for(rich_plan["original_content"], ["list-p1"])
    assert partial["patch_scope"]["insertion_targets"] == []
    full = plan_for(rich_plan["original_content"], ["list-p2", "list-p1"])
    assert full["patch_scope"]["selected_node_ids"] == ["list-p1", "list-p2"]
    assert [item["after_node_id"] for item in full["patch_scope"]["insertion_targets"]] == ["list"]


@pytest.mark.parametrize(
    "selected",
    [[], ["table"], ["image"], ["cell-p1"], ["list"], ["missing"], ["p1", "p1"], [False], "p1"],
)
def test_invalid_or_structural_scope_is_rejected(rich_plan, selected):
    with pytest.raises(DomainError) as error:
        patch_set.freeze_scope(rich_plan["original_content"], selected)
    assert error.value.code == "AUTHORING_PATCH_SCOPE_INVALID"


@pytest.mark.parametrize("node_id", ["table", "image", "cell-p1", "cell-p2", "list", "item1"])
def test_actual_protected_node_digest_does_not_grant_edit_authority(rich_plan, node_id):
    node = by_id(rich_plan["original_content"])[node_id]
    raw = {
        "replacements": [
            {
                "node_id": node_id,
                "before_digest": sha(node),
                "inline": [{"type": "text", "text": "试图改表图"}],
            }
        ],
        "insertions": [],
        "evidence_ids": [],
    }
    with pytest.raises(DomainError) as error:
        patch_set.canonicalize(rich_plan, identity(102), raw)
    assert error.value.code == "AUTHORING_PATCH_RANGE_CHANGED"


@pytest.mark.parametrize(
    "tamper",
    [
        "source_refs",
        "new_id",
        "asset",
        "link",
        "unknown_mark",
        "duplicate_mark",
        "wrong_digest",
        "wrong_anchor",
        "duplicate_target",
        "duplicate_anchor",
        "unknown_evidence",
        "duplicate_evidence",
        "empty",
        "unchanged",
    ],
)
def test_model_cannot_inject_identity_sources_assets_or_ambiguous_changes(rich_plan, tamper):
    raw = output(rich_plan)
    if tamper == "source_refs":
        raw["source_refs"] = [reference(50)]
    elif tamper == "new_id":
        raw["insertions"][0]["paragraphs"][0]["attrs"] = {"id": "model-created"}
    elif tamper == "asset":
        raw["replacements"][0]["inline"] = [{"type": "image", "attrs": {"asset_id": identity(99)}}]
    elif tamper == "link":
        raw["replacements"][0]["inline"][0]["url"] = "https://example.invalid"
    elif tamper == "unknown_mark":
        raw["replacements"][0]["inline"][0]["marks"] = [{"type": "underline"}]
    elif tamper == "duplicate_mark":
        raw["replacements"][0]["inline"][0]["marks"] *= 2
    elif tamper == "wrong_digest":
        raw["replacements"][0]["before_digest"] = "0" * 64
    elif tamper == "wrong_anchor":
        raw["insertions"][0]["anchor_digest"] = "0" * 64
    elif tamper == "duplicate_target":
        raw["replacements"].append(deepcopy(raw["replacements"][0]))
    elif tamper == "duplicate_anchor":
        raw["insertions"].append(deepcopy(raw["insertions"][0]))
    elif tamper == "unknown_evidence":
        raw["evidence_ids"] = [identity(999)]
    elif tamper == "duplicate_evidence":
        raw["evidence_ids"] *= 2
    elif tamper == "empty":
        raw["replacements"], raw["insertions"] = [], []
    elif tamper == "unchanged":
        raw["replacements"][0]["inline"] = deepcopy(
            by_id(rich_plan["original_content"])["p1"]["content"]
        )
    with pytest.raises(DomainError):
        patch_set.canonicalize(rich_plan, identity(102), raw)


@pytest.mark.parametrize("text", ["不允许\x00", "不允许\r", "\ud800"])
def test_unpersistable_text_is_rejected(rich_plan, text):
    raw = output(rich_plan)
    raw["replacements"][0]["inline"][0]["text"] = text
    with pytest.raises(DomainError):
        patch_set.canonicalize(rich_plan, identity(102), raw)


def test_hard_break_and_allowed_emphasis_are_actual_inline_nodes(rich_plan):
    raw = {"replacements": [replace(rich_plan)], "insertions": [], "evidence_ids": []}
    inline = [
        {"type": "text", "text": "前\t文", "marks": [{"type": "bold"}, {"type": "italic"}]},
        {"type": "hardBreak"},
        {"type": "text", "text": "后文"},
    ]
    raw["replacements"][0]["inline"] = inline
    candidate = patch_set.canonicalize(rich_plan, identity(102), raw)
    assert (
        by_id(patch_set.materialize(rich_plan, identity(102), candidate)["after"])["p1"]["content"]
        == inline
    )


@pytest.mark.parametrize(
    "key", ["mode", "writing_plan_id", "scope_digest", "before_digest", "after_digest", "patch_set"]
)
def test_canonical_tampering_is_rejected_on_materialization(rich_plan, key):
    candidate = patch_set.canonicalize(rich_plan, identity(102), output(rich_plan))
    candidate[key] = {} if key == "patch_set" else "changed"
    with pytest.raises(DomainError):
        patch_set.materialize(rich_plan, identity(102), candidate)


@pytest.mark.parametrize(
    "tamper", ["scope", "original", "section_digest", "mode", "duplicate_source", "false_source_id"]
)
def test_frozen_plan_cannot_silently_change(rich_plan, tamper):
    raw = output(rich_plan)
    if tamper == "scope":
        rich_plan["patch_scope"]["selected_node_ids"] = ["p1"]
    elif tamper == "original":
        rich_plan["original_content"]["attrs"]["title"] = "被换掉的章"
    elif tamper == "section_digest":
        rich_plan["section_digest"] = "0" * 64
    elif tamper == "mode":
        rich_plan["generation_mode"] = "arbitrary"
    elif tamper == "duplicate_source":
        rich_plan["source_blocks"].append(deepcopy(rich_plan["source_blocks"][0]))
    else:
        rich_plan["source_blocks"][0]["source_ref"]["evidence_id"] = identity(999)
    with pytest.raises(DomainError):
        patch_set.canonicalize(rich_plan, identity(102), raw)


def test_existing_source_refs_keep_exact_order_and_only_selected_evidence_is_added(rich_plan):
    original = rich_plan["original_content"]
    original["attrs"]["source_refs"] = [reference(40), reference(40)]
    plan = plan_for(original)
    candidate = patch_set.canonicalize(plan, identity(102), output(plan))
    assert patch_set.materialize(plan, identity(102), candidate)["after"]["attrs"][
        "source_refs"
    ] == [reference(40), reference(40), reference(50)]


@pytest.mark.parametrize("tamper", ["page", "text", "reference", "instruction", "batch_id"])
def test_malformed_frozen_sources_or_identity_fail_before_provider_request(rich_plan, tamper):
    frozen = manifest(rich_plan)
    if tamper == "page":
        rich_plan["source_blocks"][0]["physical_page"] = True
    elif tamper == "text":
        rich_plan["source_blocks"][0]["text"] = "\ud800"
    elif tamper == "reference":
        rich_plan["source_blocks"][0]["source_ref"]["source_revision"] = False
    elif tamper == "instruction":
        rich_plan["instruction"] = None
    else:
        frozen["batch_context"]["batch_id"] = "not-a-real-batch"
    with pytest.raises(DomainError):
        generation.request_for(frozen)


def test_empty_chapter_can_get_multiple_new_server_identified_paragraphs(rich_plan):
    original = deepcopy(rich_plan["original_content"])
    original["content"] = []
    plan = plan_for(original)
    raw = {"replacements": [], "insertions": [insert(plan)], "evidence_ids": []}
    candidate = patch_set.canonicalize(plan, identity(102), raw)
    result = patch_set.materialize(plan, identity(102), candidate)
    assert len(result["after"]["content"]) == 2
    with pytest.raises(DomainError):
        patch_set.materialize(plan, identity(103), candidate)


def test_explicit_new_node_collision_refuses_overwrite(rich_plan, monkeypatch):
    original = rich_plan["original_content"]
    original["content"][1]["attrs"]["id"] = identity(500)
    plan = plan_for(original)
    monkeypatch.setattr(patch_set, "uuid5", lambda *_: UUID(int=500))
    raw = {"replacements": [], "insertions": [insert(plan)], "evidence_ids": []}
    with pytest.raises(DomainError) as error:
        patch_set.canonicalize(plan, identity(102), raw)
    assert error.value.code == "AUTHORING_PATCH_NODE_COLLISION"


@pytest.mark.parametrize(
    "limit,value", [("patch_bytes", 100), ("added_paragraphs", 2), ("text_characters", 3)]
)
def test_whole_candidate_limits_refuse_without_truncation(rich_plan, monkeypatch, limit, value):
    raw = output(rich_plan)
    before = deepcopy(raw)
    monkeypatch.setitem(patch_set.LIMITS, limit, value)
    with pytest.raises(DomainError) as error:
        patch_set.canonicalize(rich_plan, identity(102), raw)
    assert error.value.code == "AUTHORING_PATCH_SET_LIMIT"
    assert raw == before


def test_result_retains_existing_one_megabyte_section_limit(rich_plan):
    original = deepcopy(rich_plan["original_content"])
    original["content"] = [paragraph("large", "x" * 950000)]
    plan = plan_for(original)
    raw = {
        "replacements": [],
        "insertions": [insert(plan, "large", ("y" * 20000,) * 4)],
        "evidence_ids": [],
    }
    with pytest.raises(DomainError):
        patch_set.canonicalize(plan, identity(102), raw)


def test_result_retains_existing_ten_thousand_node_limit(rich_plan):
    original = deepcopy(rich_plan["original_content"])
    original["content"] = [paragraph(f"p-{index}", "x") for index in range(4999)]
    with pytest.raises(DomainError) as error:
        patch_set.freeze_scope(original)
    assert error.value.code == "AUTHORING_PATCH_SET_LIMIT"
    plan = plan_for(original, ["p-0"])
    raw = {"replacements": [], "insertions": [insert(plan, "p-0")], "evidence_ids": []}
    with pytest.raises(DomainError):
        patch_set.canonicalize(plan, identity(102), raw)


def test_actual_prompt_and_offline_provider_roundtrip_return_canonical_full_preview(rich_plan):
    import json

    from packages.domain.providers.deepseek import DeepSeekClient

    frozen = manifest(rich_plan)
    messages, schema = generation.request_for(frozen)
    payload = json.loads(messages[1]["content"])
    assert payload["plan"]["original_content"] == rich_plan["original_content"]
    assert payload["plan"]["patch_scope"] == rich_plan["patch_scope"]
    assert "source_ref" not in payload["plan"]["source_blocks"][0]
    assert "source_authorities" not in payload["project_memory"]
    calls = []

    def transport(request):
        submitted = json.loads(request.content)
        assert submitted["max_tokens"] == 2048
        assert submitted["response_format"] == {"type": "json_object"}
        calls.append(request.url.path)
        return httpx.Response(
            200,
            headers={"x-request-id": "offline-patch-set"},
            json={
                "id": "offline-result",
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(output(rich_plan), ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    client = DeepSeekClient(
        api_key="explicit-offline-only", transport=httpx.MockTransport(transport)
    )
    result = client.generate(messages=messages, json_schema=schema, max_tokens=2048)
    candidate = generation.validate_generation(frozen, result.data)
    assert generation.validate_generation(frozen, candidate, canonical=True) == candidate
    assert (
        patch_set.materialize(rich_plan, frozen["writing_plan_id"], candidate)["changes"][
            "added_paragraphs"
        ]
        == 3
    )
    assert calls == ["/v1/chat/completions"]


@pytest.mark.parametrize(
    "tamper", ["mode", "plan_mode", "selection", "batch_section", "batch_attempt", "missing_batch"]
)
def test_mode_or_batch_mismatch_is_rejected_before_prompt(rich_plan, tamper):
    frozen = manifest(rich_plan)
    if tamper == "mode":
        frozen["generation_mode"] = "unchecked"
    elif tamper == "plan_mode":
        frozen["plan"]["generation_mode"] = None
    elif tamper == "selection":
        frozen["selection"] = {"node_id": "p1"}
    elif tamper == "batch_section":
        frozen["batch_context"]["section_id"] = identity(999)
    elif tamper == "batch_attempt":
        frozen["batch_context"]["attempt"] = True
    else:
        frozen.pop("batch_context")
    with pytest.raises(DomainError) as error:
        generation.request_for(frozen)
    assert error.value.code == "AUTHORING_GENERATION_MODE_INVALID"


def test_prompt_never_silently_truncates_large_chapter(rich_plan):
    original = deepcopy(rich_plan["original_content"])
    original["content"] = [paragraph("large", "x" * 200000)]
    with pytest.raises(DomainError) as error:
        generation.request_for(manifest(plan_for(original)))
    assert error.value.code == "ASSISTANT_INPUT_TOO_LARGE"


@pytest.mark.parametrize("total_characters", [200000, 200001, 262145])
def test_actual_full_message_size_counts_rich_sources_memory_and_system(
    rich_plan, total_characters
):
    import json

    frozen = manifest(rich_plan)
    for block in frozen["plan"]["source_blocks"]:
        block["text"] = "证" * 50000
    frozen["project_memory"]["summary"] = ""
    initial_messages, _ = generation.request_for(frozen)
    initial_size = sum(len(message["content"]) for message in initial_messages)
    frozen["project_memory"]["summary"] = "事" * (total_characters - initial_size)
    if total_characters > 200000:
        with pytest.raises(DomainError) as error:
            generation.request_for(frozen)
        assert error.value.code == "ASSISTANT_INPUT_TOO_LARGE"
        return
    messages, _ = generation.request_for(frozen)
    assert sum(len(message["content"]) for message in messages) == total_characters
    payload = json.loads(messages[1]["content"])
    assert payload["plan"]["original_content"] == rich_plan["original_content"]
    assert sum(len(block["text"]) for block in payload["plan"]["source_blocks"]) == 100000
    assert payload["project_memory"]["summary"] == frozen["project_memory"]["summary"]


class EmptyCursor:
    def fetchone(self):
        return None


class ReadOnlyPort:
    def __init__(self):
        self.queries = []

    def execute(self, query, arguments=()):
        assert str(query).startswith("SELECT ")
        self.queries.append(str(query))
        return EmptyCursor()


@pytest.mark.parametrize("decision", ["confirm", "reject"])
def test_single_action_resolution_cannot_consume_or_stale_batch_leaf(monkeypatch, decision):
    proposed = {"payload": {"kind": "authoring_patch_set"}}
    monkeypatch.setattr(actions, "lock", lambda *_: (({}, proposed), {}))
    monkeypatch.setattr(
        actions, "view", lambda *_: pytest.fail("batch leaf reached normal action view")
    )
    c = ReadOnlyPort()
    with pytest.raises(DomainError) as error:
        actions.resolve(c, UUID(int=1), UUID(int=2), decision, UUID(int=3), None)
    assert error.value.code == "AUTHORING_BATCH_CONFIRM_REQUIRED"
    assert len(c.queries) == 1 and "action_consumptions" in c.queries[0]


def test_native_patch_route_also_refuses_batch_leaf_without_writes(monkeypatch):
    row = {"expires_at": now() + timedelta(hours=1), "payload": {"kind": "authoring_patch_set"}}
    monkeypatch.setattr(
        patches,
        "fetch",
        lambda _c, query, args: row if "proposed_actions" in query else {"id": args[0]},
    )
    c = ReadOnlyPort()
    with pytest.raises(DomainError) as error:
        patches.apply_proposal(c, UUID(int=1), UUID(int=2), UUID(int=3), UUID(int=4), None)
    assert error.value.code == "AUTHORING_BATCH_CONFIRM_REQUIRED"


def test_existing_action_view_exposes_complete_verified_patch_set_preview(rich_plan, monkeypatch):
    frozen = manifest(rich_plan)
    candidate = generation.validate_generation(frozen, output(rich_plan))
    payload = {
        "kind": "authoring_patch_set",
        "job_id": identity(103),
        "writing_plan_id": identity(102),
        "batch_context": frozen["batch_context"],
        "section_id": identity(101),
        "base_section_revision": 4,
        "candidate": candidate,
    }
    link = {
        "job_id": UUID(int=103),
        "tool": "authoring.apply_patch",
        "state": "pending",
        "revision": 1,
        "resolved_by": None,
        "error_code": None,
    }
    action = {
        "payload": payload,
        "bid_id": UUID(int=104),
        "request_digest": sha(payload),
        "base_revision": 10,
        "expires_at": now() + timedelta(hours=1),
    }
    source = {
        "id": UUID(int=103),
        "kind": "authoring",
        "writing_plan_id": UUID(int=102),
        "input_manifest": frozen,
    }
    monkeypatch.setattr(actions, "records", lambda *_: (link, action))
    monkeypatch.setattr(jobs, "job", lambda *_: source)
    result = actions.view(ReadOnlyPort(), UUID(int=105))
    assert result["preview"]["before"] == rich_plan["original_content"]
    assert result["preview"]["kind"] == "authoring_patch_set"
    assert result["preview"]["changes"]["added_paragraphs"] == 3
    assert result["state"] == "pending"
    payload["job_id"] = identity(999)
    with pytest.raises(DomainError) as error:
        actions.view(ReadOnlyPort(), UUID(int=105))
    assert error.value.code == "ACTION_IDENTITY_INVALID"


def test_new_public_request_cannot_inject_trusted_mode_and_tokens_keep_real_port_bound():
    from packages.assistant.protocol import validate

    body = {
        "section_id": identity(1),
        "base_section_revision": 1,
        "instruction": "补充实际方案",
        "source_version_ids": [],
    }
    assert validate("AssistantGenerationRequest", body | {"max_tokens": 8192})
    for extra in (
        {"generation_mode": patch_set.MODE},
        {"batch_context": {}},
        {"max_tokens": 8193},
        {"max_tokens": True},
    ):
        with pytest.raises(DomainError):
            validate("AssistantGenerationRequest", body | extra)


@pytest.mark.parametrize("mode", [None, patch_set.MODE])
def test_plan_freezing_keeps_current_word_source_authority_and_old_mode_compatibility(
    rich_plan, monkeypatch, mode
):
    from packages.authoring import generation as authoring_generation
    from packages.authoring import snapshot_structure

    content = rich_plan["original_content"]
    checked = []
    persisted = []

    class Port:
        def execute(self, query, arguments=None):
            if (
                query
                == "SELECT to_regclass('design.authoring_exact_revisions') IS NOT NULL AS present"
            ):
                return self
            assert str(query).startswith("INSERT INTO writing_plans")
            persisted.append(arguments[-1].obj)

        def fetchone(self):
            return {"present": False}

    monkeypatch.setattr(
        authoring_generation,
        "fetch",
        lambda _c, query, args: {"draft_id": UUID(int=104)}
        if "SELECT * FROM sections " in query
        else {"revision": 4, "content": content, "digest": sha(content)},
    )
    monkeypatch.setattr(authoring_generation, "lock_draft", lambda *_: {"revision": 10})
    monkeypatch.setattr(
        snapshot_structure,
        "assert_active",
        lambda *_: {"metadata": {"word_import_sources": ["actual-proof-port"]}},
    )
    monkeypatch.setattr(
        authoring_generation,
        "assert_sources",
        lambda _c, bid, value: checked.append((bid, deepcopy(value))),
    )
    monkeypatch.setattr(authoring_generation, "proposal_context", lambda *_: {"fact_set_id": None})

    def authority(_c, bid, draft, section, value, *, additional_refs, extension):
        assert bid == UUID(int=103) and section == UUID(int=101)
        assert value == content and additional_refs == []
        assert extension["metadata"]["word_import_sources"] == ["actual-proof-port"]
        return [{"source_id": identity(900), "revision": 1, "word_original_guard": True}]

    monkeypatch.setattr(authoring_generation.section_sources, "authority", authority)
    result = authoring_generation.freeze_generation_plan(
        Port(),
        UUID(int=103),
        {
            "section_id": identity(101),
            "base_section_revision": 4,
            "instruction": "补充实际施工方案",
            "source_version_ids": [],
        },
        generation_mode=mode,
        generation_scope=["p1"] if mode else None,
    )
    assert len(checked) == 1 and checked[0][1] == content
    assert len(persisted) == 1 and result["plan"] == persisted[0]
    assert result["plan"]["authority_manifest"][0]["word_original_guard"]
    assert result["input_digest"] == sha(result["plan"])
    if mode:
        assert result["plan"]["generation_mode"] == patch_set.MODE
        assert result["plan"]["patch_scope"] == patch_set.freeze_scope(content, ["p1"])
    else:
        assert "generation_mode" not in result["plan"] and "patch_scope" not in result["plan"]


def queue_port(rich_plan, monkeypatch):
    from packages.assistant import budget
    from packages.authoring import generation as authoring_generation
    from packages.lifecycle import service

    events = []
    saved = []

    class Port:
        def execute(self, query, arguments):
            assert str(query).startswith("INSERT INTO assistant_jobs")
            saved.append(arguments[6].obj)

    monkeypatch.setattr(jobs, "require_schema", lambda *_: None)
    monkeypatch.setattr(service, "assert_work_writable", lambda *_: events.append("writable"))
    monkeypatch.setattr(jobs.context, "lock_scope", lambda *_: events.append("source_graph"))
    monkeypatch.setattr(
        jobs.context,
        "project_memory",
        lambda *_: {"source_authorities": [{"word_original_guard": True}]},
    )

    def prepare(*_, **kwargs):
        assert events == ["writable", "source_graph"]
        assert kwargs["generation"] and kwargs["explicit_send"]
        events.append("budget_prepare")
        return {"anti_resend_key": "a" * 64}

    monkeypatch.setattr(budget, "prepare", prepare)
    monkeypatch.setattr(budget, "bind", lambda *_: events.append("budget_bind"))

    def freeze(*_, **kwargs):
        assert kwargs == {"generation_mode": patch_set.MODE, "generation_scope": None}
        events.append("freeze_sources")
        return {"writing_plan_id": identity(102), "plan": rich_plan}

    monkeypatch.setattr(authoring_generation, "freeze_generation_plan", freeze)

    def enqueue(*_, **kwargs):
        assert kwargs["handler_version"] == "authoring-generate/1"
        assert kwargs["topic"] == "tender.task.assistant.v1"
        events.append("enqueue")
        return {"id": identity(105)}

    monkeypatch.setattr(jobs, "enqueue_plan", enqueue)
    monkeypatch.setattr(jobs, "audit", lambda *_: None)
    monkeypatch.setattr(jobs, "view", lambda _c, job_id, actor: {"id": str(job_id)})
    body = {
        "section_id": identity(101),
        "base_section_revision": 4,
        "instruction": "实际编写要求",
        "source_version_ids": [],
        "max_tokens": 4096,
    }
    options = {
        "explicit_send": True,
        "generation_mode": patch_set.MODE,
        "batch_context": {"batch_id": identity(100), "section_id": identity(101), "attempt": 1},
    }
    return Port(), body, options, events, saved


def test_trusted_batch_queue_binds_existing_budget_and_original_worker_with_exact_manifest(
    rich_plan, monkeypatch
):
    port, body, options, events, saved = queue_port(rich_plan, monkeypatch)
    result = jobs.queue_generation(
        port, UUID(int=103), UUID(int=104), body, UUID(int=106), **options
    )
    assert UUID(result["id"])
    assert events == [
        "writable",
        "source_graph",
        "budget_prepare",
        "freeze_sources",
        "enqueue",
        "budget_bind",
    ]
    assert len(saved) == 1
    assert saved[0]["generation_mode"] == patch_set.MODE
    assert saved[0]["batch_context"] == options["batch_context"]
    assert saved[0]["plan"] == rich_plan
    assert saved[0]["request"]["max_tokens"] == 4096
    assert saved[0]["project_memory"]["source_authorities"] == [{"word_original_guard": True}]
    assert saved[0]["selection"] is None and saved[0]["formal_scoring_input"] is False


@pytest.mark.parametrize(
    "reason", ["ASSISTANT_CALL_REQUIRES_RECONCILIATION", "ASSISTANT_BUDGET_EXHAUSTED"]
)
def test_batch_mode_never_bypasses_existing_unknown_cost_or_budget_gate(
    rich_plan, monkeypatch, reason
):
    from packages.assistant import budget

    port, body, options, events, saved = queue_port(rich_plan, monkeypatch)

    def blocked(*_, **__):
        raise DomainError(reason, "合成账本阻断", 409)

    monkeypatch.setattr(budget, "prepare", blocked)
    with pytest.raises(DomainError) as error:
        jobs.queue_generation(port, UUID(int=103), UUID(int=104), body, UUID(int=106), **options)
    assert error.value.code == reason
    assert events == ["writable", "source_graph"] and saved == []


def test_batch_mode_never_queues_after_word_original_authority_fails(rich_plan, monkeypatch):
    from packages.authoring import generation as authoring_generation

    port, body, options, events, saved = queue_port(rich_plan, monkeypatch)

    def withdrawn(*_, **__):
        raise DomainError("SOURCE_WITHDRAWN", "原Word已撤回", 409)

    monkeypatch.setattr(authoring_generation, "freeze_generation_plan", withdrawn)
    with pytest.raises(DomainError) as error:
        jobs.queue_generation(port, UUID(int=103), UUID(int=104), body, UUID(int=106), **options)
    assert error.value.code == "SOURCE_WITHDRAWN"
    assert events == ["writable", "source_graph", "budget_prepare"] and saved == []


@pytest.mark.parametrize(
    "tamper", ["mode", "batch_id", "section_id", "attempt", "extra", "selection"]
)
def test_invalid_trusted_batch_parameters_never_reach_budget(rich_plan, monkeypatch, tamper):
    port, body, options, events, saved = queue_port(rich_plan, monkeypatch)
    if tamper == "mode":
        options["generation_mode"] = "uncontrolled"
    elif tamper == "batch_id":
        options["batch_context"]["batch_id"] = "not-a-batch"
    elif tamper == "section_id":
        options["batch_context"]["section_id"] = identity(999)
    elif tamper == "attempt":
        options["batch_context"]["attempt"] = True
    elif tamper == "extra":
        options["batch_context"]["job_id"] = identity(999)
    else:
        body.update(node_id="p1", selection_start=0, selection_end=1)
    with pytest.raises(DomainError) as error:
        jobs.queue_generation(port, UUID(int=103), UUID(int=104), body, UUID(int=106), **options)
    assert error.value.code == "AUTHORING_GENERATION_MODE_INVALID"
    assert events == [] and saved == []
