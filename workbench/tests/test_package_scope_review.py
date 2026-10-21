"""Synthetic frozen vectors verify scope/protocol mechanics, not model judgment quality."""

import json
import math
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.domain import package_scope_review as review
from packages.domain.package_review_execution_identity import identify
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha


def uid(value):
    return str(UUID(int=value))


def part(part_id, first=1, last=2):
    return {
        "part_id": part_id,
        "category": "技术" if part_id == "technical" else "商务",
        "first_page": first,
        "last_page": last,
        "shared_attachment": False,
        "heading_path": [],
    }


def document(index, member_id, role, parts, text):
    blocks = [
        {
            "id": uid(index + number),
            "physical_page": number,
            "ordinal": 0,
            "kind": "paragraph",
            "text_content": value,
            "bbox": None,
            "structure": {},
            "digest": sha(value.encode()),
        }
        for number, value in enumerate((text, "此页为完整读取范围的第二页"), 1)
    ]
    doc = {
        "package_role": role,
        "member_id": member_id,
        "document_version_id": uid(index + 10),
        "parse_id": uid(index + 20),
        "digest": sha(member_id.encode()),
        "page_count": 2,
        "pages": [{"physical_page": page, "quality": "usable", "gaps": []} for page in (1, 2)],
        "blocks": blocks,
    }
    return {"member_id": member_id, "parts": parts}, doc


@pytest.fixture
def case(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    target, target_doc = document(
        100, "main-bid", "target", [part("technical")], "本投标项目计划工期为 120 日历天"
    )
    business, business_doc = document(
        200, "business-bid", "target", [part("business")], "项目负责人为张三"
    )
    authority, authority_doc = document(
        300, "authority", "authority", [part("authority")], "本项目要求工期不超过 120 日历天"
    )
    rule = {
        "id": uid(1000),
        "kind": "mandatory",
        "statement": "本项目要求工期不超过 120 日历天",
        "evidence_ids": [uid(301)],
        "conditions": [],
        "exceptions": [],
        "provenance_status": "effective",
    }
    requirement = {
        "requirement_id": rule["id"],
        "applicability": "applicable",
        "target_part_ids": ["technical", "business"],
        "applicability_evidence": [],
        "checks": ["text"],
    }
    row = {
        "rule_id": rule["id"],
        "rule_snapshot": rule,
        "rule_digest": digest(rule),
        "requirement": requirement,
        "requirement_digest": digest(requirement),
        "source_bound": True,
    }
    root = {
        "selection": {
            "target": {"manifest": {"members": [target, business]}},
            "authority": {"manifest": {"members": [authority]}},
            "inventory": {"manifest": {"requirements": [row]}},
        },
        "documents": [target_doc, business_doc, authority_doc],
        "context": {"facts": {"unused-private": "never sent to a provider"}},
    }
    scope = tuple(uid(i) for i in range(1, 5))
    frozen_digest, prepared_digest = "a" * 64, "b" * 64
    frozen_manifest = {
        "input_digest": digest(root["selection"]),
        "evidence_digest": digest(root),
    }
    binding = {
        **dict(zip(("bid_id", "package_id", "revision_id", "inventory_id"), scope, strict=True)),
        "identity_digest": "c" * 64,
        "frozen_input_id": uid(5),
        "frozen_digest": frozen_digest,
        **frozen_manifest,
        "context_digest": "d" * 64,
        "method_digest": "e" * 64,
        "policy_digest": "f" * 64,
        "purpose": "prebid_compliance",
    }
    prepared = SimpleNamespace(
        scope=scope,
        frozen_id=uid(5),
        input_id=uid(6),
        digest=prepared_digest,
        view=lambda: {"manifest": {"identity": identify(binding)}},
    )
    frozen = SimpleNamespace(
        digest=frozen_digest,
        view=lambda: {"manifest": deepcopy(frozen_manifest)},
        evidence=lambda: deepcopy(root),
    )
    declaration = {
        "requirement_id": uid(1000),
        "state": "not_needed",
        "fact_ids": [],
        "evidence_ids": [uid(301)],
    }
    plan = {
        "manifest": {
            "id": uid(7),
            "assessment": {
                "manifest": {
                    "requirements": [{"requirement_id": uid(1000), "declaration": declaration}]
                }
            },
        },
        "digest": "1" * 64,
    }
    admission = SimpleNamespace(
        selected_items=lambda: [],
        view=lambda: {
            "manifest": {
                "usage_digest": "2" * 64,
                "selected_facts_digest": digest([]),
                "content_digest": "3" * 64,
                "proofs_digest": "4" * 64,
                "policy_digest": "5" * 64,
                "fact_declarations": [],
            }
        },
        _proof_text="private-proof",
    )
    proof = {"digest": "6" * 64}
    payload = review.model_input(root, plan, admission)
    manifest = review.input_manifest(
        prepared, frozen, plan, admission, proof, review.method_profile()
    )
    return locals()


def response(batch, verdict="satisfied"):
    return {
        "scope_digest": batch["scope_digest"],
        "judgments": [
            {
                "requirement_id": row["requirement_id"],
                "verdict": verdict,
                "statement": "投标承诺与本项已声明要求一致，待人工核对。",
                "target_quotes": [
                    {"member_id": "main-bid", "evidence_id": uid(101), "quote": "工期为 120 日历天"}
                ],
                "authority_quotes": [
                    {
                        "member_id": "authority",
                        "evidence_id": uid(301),
                        "quote": "工期不超过 120 日历天",
                    }
                ],
                "used_fact_ids": [],
            }
            for row in batch["requirements"]
        ],
    }


def test_all_frozen_members_and_only_selected_facts_are_submitted(case):
    payload = case["payload"]
    assert [d["member_id"] for d in payload["documents"]] == [
        "main-bid",
        "business-bid",
        "authority",
    ]
    assert all(len(d["pages"]) == len(d["blocks"]) == 2 for d in payload["documents"])
    assert "unused-private" not in json.dumps(payload)
    assert "object_key" not in json.dumps(payload)
    assert payload["selected_facts"] == []
    batch = review.batches(payload)[0]
    matrix = review.validate_batch(batch, response(batch))
    result = review.result_manifest(uid(50), case["manifest"], payload, matrix)
    assert result["matrix_coverage"] == "complete"
    assert result["overall_coverage"] == "partial"
    assert result["limitations"] == [review.LIMITATION]
    assert not any(
        result[key]
        for key in ("inventory_complete", "formal_scoring_eligible", "submission_eligible")
    )
    quote = result["matrix"][0]["target_quotes"][0]
    assert quote["document_version_id"] == uid(110)
    assert quote["parse_run_id"] == uid(120)
    assert quote["physical_page"] == 1 and quote["part_ids"] == ["technical"]
    assert result["matrix"][0]["human_review_state"] == "unreviewed"


def test_real_parse_float_geometry_is_preserved_in_model_input(case):
    block = case["root"]["documents"][0]["blocks"][0]
    block["bbox"] = [0.0, -0.0, 17.125, 841.8897637795277]
    block["structure"] = {
        "table": {
            "cells": [
                {
                    "row": 0,
                    "column": 1,
                    "bbox": [1.25e-12, 12.000000000000002, 10.0, 21.875],
                    "value": "金额 1.000 元",
                    "row_span": 1,
                }
            ],
            "rotation": -0.0,
        }
    }
    payload = review.model_input(case["root"], case["plan"], case["admission"])
    batch = review.batches(payload)[0]
    submitted = json.loads(review.model_json(batch))
    actual = submitted["documents"][0]["blocks"][0]
    assert actual == block
    assert isinstance(actual["bbox"][0], float)
    assert math.copysign(1, actual["bbox"][1]) == -1
    assert isinstance(actual["structure"]["table"]["cells"][0]["row"], int)
    assert submitted["scope_digest"] == review.model_digest(submitted["documents"])
    manifest = review.input_manifest(
        case["prepared"],
        case["frozen"],
        case["plan"],
        case["admission"],
        case["proof"],
        review.method_profile(),
    )
    assert manifest["model_input_digest"] == review.model_digest(payload)
    assert manifest["executor_method"]["profile"]["model_json_encoding"] == "finite-json-numbers/1"


def test_model_json_binds_exact_numeric_values_and_is_stable_for_key_order():
    value = {"z": -0.0, "a": [9007199254740993, 1.0, 12.000000000000002, "1.00"]}
    text = review.model_json(value)
    assert text == '{"a":[9007199254740993,1.0,12.000000000000002,"1.00"],"z":-0.0}'
    assert review.model_digest(value) == sha(text.encode("utf-8"))
    assert review.model_digest(dict(reversed(list(value.items())))) == review.model_digest(value)
    assert json.loads(text) == value
    assert review.model_digest(value | {"z": 0.0}) != review.model_digest(value)
    assert review.model_digest(value | {"z": "-0.0"}) != review.model_digest(value)
    assert review.model_digest(value | {"a": [9007199254740993, 1.0, 12.0, "1.00"]}) != (
        review.model_digest(value)
    )
    # The existing immutable review protocol is intentionally unchanged.
    with pytest.raises(ValueError, match="float_forbidden"):
        digest(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_geometry_is_rejected_before_any_model_batch(case, value):
    case["payload"]["documents"][0]["blocks"][0]["structure"] = {"cells": [{"x": value}]}
    with pytest.raises(DomainError) as error:
        review.batches(case["payload"])
    assert error.value.code == "PACKAGE_SCOPE_MODEL_JSON_INVALID"


@pytest.mark.parametrize("value", [{1: "not a string key"}, {"value": (1, 2)}, {"value": "\ud800"}])
def test_model_json_does_not_silently_coerce_non_json_values(value):
    with pytest.raises(DomainError) as error:
        review.model_json(value)
    assert error.value.code == "PACKAGE_SCOPE_MODEL_JSON_INVALID"


@pytest.mark.parametrize(
    "name,value",
    [
        ("DEEPSEEK_MODEL", "unsupported-model"),
        ("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1?token=synthetic-secret"),
        ("DEEPSEEK_BASE_URL", "https://private.example/model"),
        ("DEEPSEEK_BASE_URL", "https://synthetic-secret@api.deepseek.com/v1"),
    ],
)
def test_method_profile_rejects_unapproved_or_secret_endpoint_without_credentials(
    monkeypatch, name, value
):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv(name, value)
    with pytest.raises(DomainError) as error:
        review.method_profile()
    assert error.value.code == "MODEL_CONFIG_INVALID"
    assert value not in str(error.value)


def test_method_profile_validates_public_configuration_without_api_credentials(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/")
    profile = review.method_profile()
    assert profile["model"] == "deepseek-v4-pro"
    assert profile["endpoint"] == "https://api.deepseek.com/v1"
    review.validate_contract("MethodProfile", profile)


def test_one_pdf_and_shared_logical_members_keep_exact_member_identity(case):
    root = case["root"]
    # Two declared members deliberately share the same physical parse and evidence IDs.
    root["documents"][1] = deepcopy(root["documents"][0]) | {"member_id": "business-bid"}
    payload = review.model_input(root, case["plan"], case["admission"])
    batch = review.batches(payload)[0]
    value = response(batch)
    value["judgments"][0]["target_quotes"][0]["member_id"] = "business-bid"
    quote = review.validate_batch(batch, value)[0]["target_quotes"][0]
    assert quote["member_id"] == "business-bid" and quote["part_ids"] == ["business"]
    assert quote["document_version_id"] == uid(110) and quote["parse_run_id"] == uid(120)
    payload["documents"] = [payload["documents"][0], payload["documents"][2]]
    batch = review.batches(payload)[0]
    assert len(review.validate_batch(batch, response(batch))) == 1


@pytest.mark.parametrize("case_kind", ["missing", "duplicate", "foreign", "scope"])
def test_missing_duplicate_foreign_requirement_or_scope_ack_cannot_publish(case, case_kind):
    batch = review.batches(case["payload"])[0]
    value = response(batch)
    if case_kind == "missing":
        value["judgments"] = []
    elif case_kind == "duplicate":
        value["judgments"] *= 2
    elif case_kind == "foreign":
        value["judgments"][0]["requirement_id"] = uid(999)
    else:
        value["scope_digest"] = "0" * 64
    with pytest.raises(DomainError) as error:
        review.validate_batch(batch, value)
    assert error.value.code == "PACKAGE_SCOPE_RANGE_INCOMPLETE"


@pytest.mark.parametrize(
    "case_kind",
    [
        "foreign_member",
        "foreign_parse",
        "quote",
        "authority_as_target",
        "wrong_part",
        "foreign_authority",
    ],
)
def test_quotes_cannot_cross_members_parse_pages_roles_or_declared_parts(case, case_kind):
    batch = review.batches(case["payload"])[0]
    value = response(batch)
    quote = value["judgments"][0]["target_quotes"][0]
    if case_kind == "foreign_member":
        quote["member_id"] = "another-bid"
    elif case_kind == "foreign_parse":
        quote["evidence_id"] = uid(999)
    elif case_kind == "quote":
        quote["quote"] = "工期为 95 日历天"
    elif case_kind == "authority_as_target":
        quote.update(member_id="authority", evidence_id=uid(301), quote="工期不超过")
    elif case_kind == "wrong_part":
        batch["requirements"][0]["requirement"]["target_part_ids"] = ["business"]
    else:
        value["judgments"][0]["authority_quotes"][0].update(evidence_id=uid(302), quote="完整读取")
    with pytest.raises(DomainError):
        review.validate_batch(batch, value)


@pytest.mark.parametrize(
    "case_kind", ["unknown_applicability", "unsupported", "scoring", "source_effectivity"]
)
def test_unproven_or_unsupported_rows_never_become_satisfied(case, case_kind):
    batch = review.batches(case["payload"])[0]
    row = batch["requirements"][0]
    if case_kind == "unknown_applicability":
        row["requirement"]["applicability"] = "unknown"
    elif case_kind == "unsupported":
        row["requirement"]["checks"] = ["signature", "platform_acceptance"]
    elif case_kind == "scoring":
        row["rule"]["kind"] = "scoring"
    else:
        row["rule"]["provenance_status"] = "needs_revalidation"
    matrix = review.validate_batch(batch, response(batch))
    assert matrix[0]["verdict"] == "unable_to_judge" and matrix[0]["limitations"]
    result = review.result_manifest(uid(50), case["manifest"], case["payload"], matrix)
    assert result["matrix_coverage"] == result["overall_coverage"] == "partial"


def test_not_applicable_needs_frozen_applicability_and_exact_evidence(case):
    batch = review.batches(case["payload"])[0]
    with pytest.raises(DomainError):
        review.validate_batch(batch, response(batch, "not_applicable"))
    row = batch["requirements"][0]
    row["requirement"].update(
        applicability="not_applicable", applicability_evidence=["evidence:" + uid(302)]
    )
    with pytest.raises(DomainError) as error:
        review.validate_batch(batch, response(batch, "not_applicable"))
    assert error.value.code == "PACKAGE_SCOPE_APPLICABILITY_UNPROVEN"
    row["requirement"]["applicability_evidence"] = ["evidence:" + uid(301)]
    assert (
        review.validate_batch(batch, response(batch, "not_applicable"))[0]["verdict"]
        == "not_applicable"
    )


@pytest.mark.parametrize("verdict", ["satisfied", "violated", "not_found", "not_applicable"])
def test_facts_are_per_requirement_and_required_facts_must_be_used(case, verdict):
    batch = review.batches(case["payload"])[0]
    if verdict == "not_applicable":
        batch["requirements"][0]["requirement"].update(
            applicability="not_applicable", applicability_evidence=["evidence:" + uid(301)]
        )
    value = response(batch, verdict)
    value["judgments"][0]["used_fact_ids"] = [uid(800)]
    with pytest.raises(DomainError) as error:
        review.validate_batch(batch, value)
    assert error.value.code == "PACKAGE_SCOPE_FACT_NOT_ADMITTED"
    batch["requirements"][0]["dependency"].update(state="required", fact_ids=[uid(800)])
    with pytest.raises(DomainError) as error:
        review.validate_batch(batch, response(batch, verdict))
    assert error.value.code == "PACKAGE_SCOPE_REQUIRED_FACTS_UNUSED"
    assert review.validate_batch(batch, value)[0]["used_fact_ids"] == [uid(800)]


@pytest.mark.parametrize(
    ("check", "field", "limit", "known"),
    [
        ("expiry", "valid_at", "REQUIREMENT_VALIDITY_TIME_UNDECLARED", "2026-10-20T00:00:00Z"),
        ("quantity", "minimum_count", "REQUIREMENT_MINIMUM_COUNT_UNKNOWN", 20),
    ],
)
def test_unknown_quantity_or_validity_time_cannot_be_guessed_by_model(
    case, check, field, limit, known
):
    batch = review.batches(case["payload"])[0]
    requirement = batch["requirements"][0]["requirement"]
    requirement.update(checks=[check], **{field: None})
    row = review.validate_batch(batch, response(batch))[0]
    assert row["verdict"] == "unable_to_judge" and limit in row["limitations"]
    requirement[field] = known
    row = review.validate_batch(batch, response(batch))[0]
    assert row["verdict"] == "satisfied" and limit not in row["limitations"]


def test_determinate_results_need_frozen_quotes_and_model_cannot_emit_scores(case):
    batch = review.batches(case["payload"])[0]
    for key in ("target_quotes", "authority_quotes"):
        value = response(batch)
        value["judgments"][0][key] = []
        with pytest.raises(DomainError) as error:
            review.validate_batch(batch, value)
        assert error.value.code == "PACKAGE_SCOPE_EVIDENCE_REQUIRED"
    value = response(batch)
    value["judgments"][0]["score"] = 100
    with pytest.raises(DomainError) as error:
        review.validate_batch(batch, value)
    assert error.value.code == "PACKAGE_SCOPE_RESPONSE_INVALID"


def test_all_batch_and_character_limits_are_checked_without_truncation(case):
    payload = deepcopy(case["payload"])
    original = payload["requirements"][0]
    payload["requirements"] = [
        deepcopy(original) | {"requirement_id": uid(10000 + i)} for i in range(400)
    ]
    ready = review.batches(payload)
    assert len(ready) == 4 and all(len(batch["requirements"]) == 100 for batch in ready)
    assert all(batch["documents"] == payload["documents"] for batch in ready)
    payload["requirements"].append(deepcopy(original) | {"requirement_id": uid(11000)})
    with pytest.raises(DomainError) as error:
        review.batches(payload)
    assert error.value.code == "PACKAGE_SCOPE_REQUIREMENT_LIMIT"
    assert len(payload["requirements"]) == 401
    payload = deepcopy(case["payload"])
    payload["documents"][0]["blocks"][0]["text_content"] = "字" * 240000
    with pytest.raises(DomainError) as error:
        review.batches(payload)
    assert error.value.code == "PACKAGE_SCOPE_INPUT_LIMIT"
    assert len(payload["documents"][0]["blocks"][0]["text_content"]) == 240000


@pytest.mark.parametrize("field", ["scope", "frozen", "method", "execution_digest"])
def test_input_schema_and_full_binding_reject_cross_identity_replay(case, field):
    manifest = deepcopy(case["manifest"])
    if field == "scope":
        manifest["scope"]["bid_id"] = uid(999)
    elif field == "frozen":
        manifest["frozen_input"]["digest"] = "0" * 64
    elif field == "method":
        manifest["executor_method"]["profile"]["model"] = "deepseek-v4-pro"
    else:
        manifest["execution_input"]["identity"]["execution_digest"] = "0" * 64
    with pytest.raises(DomainError) as error:
        review.validate_input(manifest)
    assert error.value.code == "PACKAGE_SCOPE_INPUT_BINDING_INVALID"


def test_observation_flags_are_never_added_to_historical_inputs(case):
    manifest = deepcopy(case["manifest"])
    manifest["review_ready"] = True
    with pytest.raises(DomainError) as error:
        review.validate_input(manifest)
    assert error.value.code == "PACKAGE_SCOPE_CONTRACT_INVALID"


def test_original_fact_declarations_are_frozen_in_identity_and_cannot_be_reused(case):
    manifest = deepcopy(case["manifest"])
    declaration = {
        "fact_id": uid(800),
        "declaration_id": uid(801),
        "declaration_digest": "0" * 64,
    }
    manifest["fact_admission"]["fact_declarations"] = [declaration]
    review.validate_input(manifest)
    changed = deepcopy(manifest)
    changed["fact_admission"]["fact_declarations"][0]["declaration_id"] = uid(802)
    assert digest(manifest) != digest(changed)
    for extra in (
        declaration | {"fact_id": uid(803)},
        declaration | {"declaration_id": uid(804)},
    ):
        changed["fact_admission"]["fact_declarations"] = [declaration, extra]
        with pytest.raises(DomainError) as error:
            review.validate_input(changed)
        assert error.value.code == "PACKAGE_SCOPE_INPUT_BINDING_INVALID"
