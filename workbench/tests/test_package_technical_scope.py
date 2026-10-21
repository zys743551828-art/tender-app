"""Synthetic exact scope proofs, with no database, object IO or model invocation."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from package_rule_correction_cases import uid
from package_submission_gate_cases import case

from packages.contracts import package_technical_scope_api as contract
from packages.contracts.openapi_dependencies import schema_closure, schema_references
from packages.domain import package_technical_scope as policy
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha
from packages.rag.indexing import original_source_id, parse_source_id


def test_empty_application_publishes_no_technical_scope_contract_or_components():
    actual = {"paths": {}}
    contract.extend_openapi(actual)
    assert actual == {"paths": {}}


@pytest.mark.parametrize(
    ("suffix", "method", "expected"),
    [
        ("/technical-scope-context", "get", {"PackageTechnicalScopeContext"}),
        (
            "/technical-scope-previews",
            "post",
            {"PackageTechnicalScopeRequest", "PackageTechnicalScopePreview"},
        ),
        (
            "/technical-scopes",
            "post",
            {"FreezePackageTechnicalScope", "PackageTechnicalScopeApplied"},
        ),
        ("/technical-scopes", "get", {"PackageTechnicalScopePage"}),
        ("/technical-scopes/{scope_id}", "get", {"PackageTechnicalScopeView"}),
    ],
)
def test_partial_technical_scope_application_has_only_reachable_closed_schemas(
    suffix, method, expected
):
    path = "/api/v1/bids/{bid_id}/packages/{package_id}/revisions/{revision_id}" + suffix
    actual = {"paths": {path: {method: {"parameters": []}}}}
    contract.extend_openapi(actual)
    schemas = actual["components"]["schemas"]
    assert set(schemas) & contract.SCHEMAS.keys() == expected
    assert schema_closure(schemas, schema_references(actual["paths"])) == schemas
    before = deepcopy(actual)
    contract.extend_openapi(actual)
    assert actual == before


def synthetic_scope():
    selected = case()["selection"]
    target, authority, inventory = (
        deepcopy(selected[key]) for key in ("target", "authority", "inventory")
    )
    member = target["manifest"]["members"][0]
    member["parts"][0]["last_page"] = 1
    member["parts"].append(
        {
            "part_id": "appendix/table",
            "category": "technical-attachment",
            "first_page": 2,
            "last_page": 2,
            "shared_attachment": False,
            "heading_path": [1, 2],
        }
    )
    target["digest"] = digest(target["manifest"])
    im = inventory["manifest"]
    im["package_digest"] = target["digest"]
    for binding in im["requirements"]:
        rule = binding["rule_snapshot"]
        rule["kind"] = "scoring"
        rule["max_points"] = "10"
        rule["bands"] = [{"label": "完整", "description": "全部适用范围有据覆盖", "points": "10"}]
        binding["rule_digest"] = digest(rule)
        binding["requirement"]["target_part_ids"] = ["body", "appendix/table"]
        binding["requirement_digest"] = digest(binding["requirement"])
    im["rule_set_digest"] = digest([r["rule_snapshot"] for r in im["requirements"]])
    inventory["digest"] = digest(im)
    documents, sources, originals = [], [], []
    for role, value in (("target", target), ("authority", authority)):
        m = value["manifest"]["members"][0]
        blocks = []
        for page, kind, text in (
            (1, "text", "完整原页文字；技术范围必须覆盖附表。"),
            (2, "table", "参数：30 天；备选：45 天。"),
        ):
            blocks.append(
                {
                    "id": uid(30 if page == 1 else 32) if role == "authority" else uid(300 + page),
                    "physical_page": page,
                    "ordinal": 0,
                    "kind": kind,
                    "text_content": text,
                    "digest": sha(text.encode()),
                    "bbox_json": "[0, 1.25, 100, 200]",
                    "structure_json": '{"tables": [{"cells": [["30 天", "45 天"]]}]}'
                    if kind == "table"
                    else None,
                }
            )
        documents.append(
            {
                "package_role": role,
                "member_id": m["member_id"],
                "document_version_id": m["document_version_id"],
                "file_digest": m["file_digest"],
                "byte_size": 1234,
                "parse": deepcopy(m["parse"]),
                "page_count": m["page_count"],
                "pages": [{"physical_page": n, "quality": "usable", "gaps": []} for n in (1, 2)],
                "blocks": blocks,
            }
        )
        original_id = str(original_source_id(UUID(m["document_version_id"])))
        parse_id = str(parse_source_id(UUID(m["parse"]["parse_run_id"])))
        for source, ancestor in (
            (original_id, original_id),
            (parse_id, parse_id),
            (parse_id, original_id),
        ):
            sources.append(
                {
                    "source_id": source,
                    "ancestor_id": ancestor,
                    "document_version_id": m["document_version_id"],
                    "digest": m["file_digest"],
                    "original_digest": m["file_digest"],
                    "kind": "document",
                    "policy_class": "prebid_content",
                    "known_at": "2026-01-01T00:00:00+00:00",
                    "revision": 1,
                    "status": "published",
                    "valid_from": "2026-01-01T00:00:00+00:00",
                    "valid_until": None,
                    "document_bid": uid(1),
                }
            )
        originals.append(
            {
                "document_version_id": m["document_version_id"],
                "digest": m["file_digest"],
                "byte_size": 1234,
            }
        )
    snapshot = {
        "target": target,
        "authority": authority,
        "inventory": inventory,
        "documents": documents,
        "source_snapshot": sources,
        "blocking_reasons": [],
        "observation": {"exact": "synthetic server observation"},
        "originals": originals,
    }
    request = {
        "purpose": "current_prebid",
        "package_digest": target["digest"],
        "authority_revision_id": authority["manifest"]["revision_id"],
        "authority_digest": authority["digest"],
        "inventory_id": im["id"],
        "inventory_digest": inventory["digest"],
        "technical_part_ids": ["body", "appendix/table"],
        "rule_scopes": [
            {
                "rule_id": r["rule_id"],
                "rule_digest": r["rule_digest"],
                "selection": "exclude"
                if r["rule_snapshot"]["provenance_status"] != "effective"
                else "include",
                "part_ids": []
                if r["rule_snapshot"]["provenance_status"] != "effective"
                else ["body", "appendix/table"],
                "reason": "合成测试：依据原条款明确选择；未证明真实完整性。",
            }
            for r in im["requirements"]
        ],
        "reason": "冻结准确技术分册和适用评分项，不开放模型执行。",
    }
    return snapshot, request


def codes(preview):
    return {row["code"] for row in preview["manifest"]["coverage"]["gaps"]}


def test_all_pages_and_rules_selected_still_cannot_grant_visual_or_scoring_readiness():
    snapshot, request = synthetic_scope()
    before = deepcopy(snapshot)
    result = policy.prepare(snapshot, request)
    assert result["manifest"]["coverage"]["state"] == "partial"
    assert result["manifest"]["coverage"]["all_scoring_rule_count"] == 4
    assert result["manifest"]["coverage"]["selected_part_count"] == 2
    assert result["manifest"]["documents"] == snapshot["documents"]
    assert result["manifest"]["timing"] == policy.TIMING
    assert all(result["manifest"][flag] is False for flag in policy.FLAGS)
    assert {
        "VISUAL_COMPLETENESS_UNPROVEN",
        "INVENTORY_COMPLETENESS_UNPROVEN",
        "REQUIRED_RANGE_UNPROVEN",
        "RULE_EXCLUDED_BY_DECLARATION",
    } <= codes(result)
    assert snapshot == before
    assert policy.prepare(snapshot, request) == result


def test_unselected_same_package_appendix_remains_visible_and_required_range_gap_is_preserved():
    snapshot, request = synthetic_scope()
    request["technical_part_ids"] = ["body"]
    for row in request["rule_scopes"]:
        if row["selection"] == "include":
            row["part_ids"] = ["body"]
    result = policy.prepare(snapshot, request)
    assert len(result["manifest"]["parts"]) == 2
    assert result["manifest"]["parts"][1]["selected"] is False
    assert {"PACKAGE_PART_NOT_SELECTED", "DECLARED_RULE_RANGE_OMITTED"} <= codes(result)
    assert result["manifest"]["rules"][0]["declared_target_part_ids"] == ["body", "appendix/table"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda s, r: r["rule_scopes"].pop(), "RULE_SET_INCOMPLETE"),
        (
            lambda s, r: r["rule_scopes"].append(deepcopy(r["rule_scopes"][0])),
            "RULE_SET_INCOMPLETE",
        ),
        (lambda s, r: r["technical_part_ids"].append("another-package"), "PART_NOT_FOUND"),
        (lambda s, r: r["rule_scopes"][0].update(rule_digest="0" * 64), "RULE_CHANGED"),
        (lambda s, r: r["rule_scopes"][0].update(part_ids=[]), "RULE_RANGE_INVALID"),
        (lambda s, r: r["rule_scopes"][0].update(selection="exclude"), "RULE_RANGE_INVALID"),
        (
            lambda s, r: r["rule_scopes"][-1].update(selection="include", part_ids=["body"]),
            "RULE_INACTIVE",
        ),
        (lambda s, r: r.update(authority_digest="0" * 64), "BASIS_CHANGED"),
        (lambda s, r: s["documents"].pop(), "DOCUMENT_SET_INVALID"),
        (lambda s, r: s["documents"][0]["pages"].pop(), "PAGE_SET_INVALID"),
        (
            lambda s, r: s["documents"][0]["blocks"][0].update(text_content="偷偷替换原文"),
            "EVIDENCE_INVALID",
        ),
        (lambda s, r: s["documents"][0]["blocks"][0].update(physical_page=3), "EVIDENCE_INVALID"),
        (lambda s, r: s["documents"][0]["parse"].update(parse_run_id=uid(999)), "DOCUMENT_INVALID"),
    ],
)
def test_scope_omissions_stale_bindings_and_wrong_evidence_fail_closed(mutation, code):
    snapshot, request = synthetic_scope()
    mutation(snapshot, request)
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request)
    assert error.value.code == "PACKAGE_TECHNICAL_SCOPE_" + code


def test_absent_exact_parse_has_readable_unknown_scope_not_latest_parse_substitution():
    snapshot, request = synthetic_scope()
    member = snapshot["target"]["manifest"]["members"][0]
    member["parse"] = {
        "status": "not_frozen",
        "parse_run_id": None,
        "parser_digest": None,
        "config_digest": None,
        "evidence_digest": None,
        "reason": "实际解析仍partial",
    }
    document = snapshot["documents"][0]
    document.update(parse=deepcopy(member["parse"]), pages=[], blocks=[])
    snapshot["target"]["digest"] = digest(snapshot["target"]["manifest"])
    snapshot["inventory"]["manifest"]["package_digest"] = snapshot["target"]["digest"]
    snapshot["inventory"]["digest"] = digest(snapshot["inventory"]["manifest"])
    request.update(
        package_digest=snapshot["target"]["digest"],
        inventory_digest=snapshot["inventory"]["digest"],
    )
    result = policy.prepare(snapshot, request)
    assert result["manifest"]["coverage"]["state"] == "unknown"
    assert "EXACT_PARSE_UNAVAILABLE" in codes(result)
    document["blocks"] = [deepcopy(snapshot["documents"][1]["blocks"][0])]
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request)
    assert error.value.code.endswith("DOCUMENT_INVALID")


def test_exclusion_without_exact_authority_evidence_is_not_allowed_but_unclassified_gap_remains():
    snapshot, request = synthetic_scope()
    snapshot["documents"][1]["blocks"] = []
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request)
    assert error.value.code.endswith("RULE_SOURCE_UNPROVEN")
    for choice in request["rule_scopes"]:
        choice.update(selection="unclassified", part_ids=[])
    result = policy.prepare(snapshot, request)
    assert "RULE_SOURCE_UNPROVEN" in codes(result)
    assert "RULE_NOT_CLASSIFIED" in codes(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scoring_ready", True),
        ("purpose", "historical_backtest"),
        ("submitted_at", "2019-01-01T00:00:00Z"),
        ("label", {"technical_total": "9"}),
        ("reason", "bad\x00data"),
    ],
)
def test_client_cannot_supply_qualification_labels_or_historical_times(field, value):
    snapshot, request = synthetic_scope()
    request[field] = value
    with pytest.raises(DomainError):
        policy.prepare(snapshot, request)


def test_shape_exact_json_and_full_capacity_are_enforced_without_truncation(monkeypatch):
    snapshot, request = synthetic_scope()
    with pytest.raises(DomainError):
        policy.bounded({"floating": float("nan")}, 1000)
    with pytest.raises(DomainError):
        policy.bounded({"text": "\ud800"}, 1000)
    monkeypatch.setitem(policy.LIMITS, "parts", 1)
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request)
    assert error.value.code.endswith("TOO_LARGE")


def test_server_byte_receipt_bindings_cover_all_members_without_upgrading_the_preview():
    snapshot, request = synthetic_scope()
    preview = policy.prepare(snapshot, request)
    recorded = datetime.now(timezone.utc)
    times = {
        "frozen_at": recorded.isoformat(),
        "verified_at": (recorded - timedelta(seconds=1)).isoformat(),
    }
    frozen = policy.freeze(
        preview,
        identity=uid(800),
        actor=uid(91),
        command=uid(801),
        originals=snapshot["originals"],
        **times,
    )
    assert frozen["manifest"]["preview"] == preview
    assert frozen["manifest"]["original_verification"]["state"] == "verified_at_recording"
    assert all(frozen["manifest"][flag] is False for flag in policy.FLAGS)
    assert frozen["manifest"]["preview"]["manifest"]["original_bytes_verified"] is False
    with pytest.raises(DomainError):
        policy.freeze(
            preview,
            identity=uid(800),
            actor=uid(91),
            command=uid(801),
            originals=snapshot["originals"][:1],
            **times,
        )
    with pytest.raises(DomainError):
        policy.freeze(
            preview,
            identity=uid(800),
            actor=uid(91),
            command=uid(801),
            originals=snapshot["originals"],
            frozen_at=recorded.isoformat(),
            verified_at=(recorded + timedelta(seconds=1)).isoformat(),
        )


def test_every_schema_is_valid_and_preview_rejects_unearned_execution_fields():
    from jsonschema import Draft202012Validator

    for value in contract.SCHEMAS.values():
        Draft202012Validator.check_schema(value)
    snapshot, request = synthetic_scope()
    preview = policy.prepare(snapshot, request)
    preview["manifest"]["scoring_ready"] = True
    preview["digest"] = digest(preview["manifest"])
    with pytest.raises(DomainError):
        contract.validate("PackageTechnicalScopePreview", preview)


@pytest.mark.parametrize(
    "observation",
    [
        {"profile": {"phase": "submitted"}},
        {
            "profile": {"phase": "open"},
            "current_submission_head": {"submission_id": uid(900), "revision": 1},
        },
    ],
)
def test_current_prebid_rejects_actual_submission_even_if_project_was_reopened(observation):
    snapshot, request = synthetic_scope()
    snapshot["observation"] = observation
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request)
    assert error.value.code.endswith("AFTER_SUBMISSION")


def test_self_signed_method_does_not_match_current_runtime_even_with_a_valid_digest():
    snapshot, request = synthetic_scope()
    method = policy.policy_identity()
    method["sources"][policy.SOURCES[0]] = "0" * 64
    method["digest"] = digest({key: value for key, value in method.items() if key != "digest"})
    with pytest.raises(DomainError) as error:
        policy.prepare(snapshot, request, method=method)
    assert error.value.code.endswith("METHOD_CHANGED")


def frozen(snapshot, preview):
    recorded = datetime.now(timezone.utc)
    return policy.freeze(
        preview,
        identity=uid(800),
        actor=uid(91),
        command=uid(801),
        frozen_at=recorded.isoformat(),
        verified_at=(recorded - timedelta(seconds=1)).isoformat(),
        originals=snapshot["originals"],
    )


@pytest.mark.parametrize(
    "change",
    ["omit_parse", "wrong_original", "cross_bid", "label", "withdrawn", "expired", "future_known"],
)
def test_current_freeze_rejects_canonical_root_purpose_or_ancestor_time_violations(change):
    snapshot, request = synthetic_scope()
    rows = snapshot["source_snapshot"]
    if change == "omit_parse":
        identity = str(parse_source_id(UUID(snapshot["documents"][0]["parse"]["parse_run_id"])))
        snapshot["source_snapshot"] = [row for row in rows if row["source_id"] != identity]
    elif change == "wrong_original":
        rows[0]["document_version_id"] = snapshot["documents"][1]["document_version_id"]
    elif change == "cross_bid":
        rows[0]["document_bid"] = uid(990)
    elif change == "label":
        rows[0]["policy_class"] = "official_label"
    elif change == "withdrawn":
        rows[0]["status"] = "withdrawn"
    elif change == "expired":
        rows[0]["valid_until"] = "2020-01-01T00:00:00Z"
    else:
        rows[0]["known_at"] = "2999-01-01T00:00:00Z"
    prepared = policy.prepare(snapshot, request)
    with pytest.raises(DomainError):
        frozen(snapshot, prepared)


def test_original_receipt_must_include_each_real_ancestor_and_no_unrelated_file():
    snapshot, request = synthetic_scope()
    ancestor = deepcopy(snapshot["source_snapshot"][0])
    ancestor.update(
        ancestor_id=uid(901),
        document_version_id=uid(902),
        digest="e" * 64,
        original_digest="e" * 64,
    )
    snapshot["source_snapshot"].append(ancestor)
    prepared = policy.prepare(snapshot, request)
    with pytest.raises(DomainError) as error:
        frozen(snapshot, prepared)
    assert error.value.code.endswith("ORIGINAL_SET_INVALID")
    snapshot["originals"].append(
        {"document_version_id": uid(902), "digest": "e" * 64, "byte_size": 42}
    )
    assert frozen(snapshot, prepared)["manifest"]["original_verification"]["files"] == sorted(
        snapshot["originals"], key=lambda row: row["document_version_id"]
    )
    snapshot["originals"].append(
        {"document_version_id": uid(903), "digest": "f" * 64, "byte_size": 12}
    )
    with pytest.raises(DomainError):
        frozen(snapshot, prepared)
