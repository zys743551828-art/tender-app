"""Prepared fact summaries are bounded displays, not current facts or applicability proof."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_package_prepared_facts import page, preview
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def item(n, value='"180天"'):
    return {
        "fact": {
            "id": uid(n),
            "name": "工期",
            "subject": "工程",
            "scope": "本标段",
            "value_jsonb_text": value,
            "unit": "天",
        },
        "decision_basis_jsonb_text": "private-basis",
    }


@pytest.fixture
def packet(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "synthetic-pagination-secret")
    facts = {"head": {"fact_set_id": uid(9)}, "items": [item(n) for n in (12, 10, 11)]}
    snapshot = {"context": {"manifest": {"facts": facts, "facts_digest": digest(facts)}}}
    return SimpleNamespace(
        scope=tuple(uid(n) for n in range(1, 5)),
        frozen_id=uid(5),
        input_id=uid(6),
        digest="a" * 64,
        snapshot=lambda: deepcopy(snapshot),
    ), snapshot


def test_stable_original_fact_pages_are_sorted_signed_and_bound_to_prepared(packet):
    original, snapshot = packet
    first = page(original, 2)
    assert valid("PackagePreparedFactPage", first)
    assert [x["fact_id"] for x in first["items"]] == [uid(10), uid(11)]
    assert first["has_more"] and first["next_cursor"]
    second = page(original, 2, first["next_cursor"])
    assert valid("PackagePreparedFactPage", second)
    assert (
        [x["fact_id"] for x in second["items"]] == [uid(12)]
        and not second["has_more"]
        and second["next_cursor"] is None
    )
    assert snapshot["context"]["manifest"]["facts"]["items"][0]["fact"]["id"] == uid(12)
    assert "private-basis" not in json.dumps(
        first
    ) and "decision_basis_jsonb_text" not in json.dumps(first)
    original.input_id = uid(99)
    with pytest.raises(DomainError):
        page(original, 2, first["next_cursor"])


@pytest.mark.parametrize(
    "value,expected",
    [
        ('"180天"', "180天"),
        ("true", "是"),
        ("false", "否"),
        ("null", "未填写"),
        ("1e400", "1e400"),
        ('{"quantity":12345678901234567890}', '{"quantity":12345678901234567890}'),
    ],
)
def test_display_values_never_round_numbers_or_reconstruct_identity(value, expected):
    source = item(10, value)
    result = preview(source)
    assert result["value_preview"] == expected
    assert result["fact_item_digest"] == digest(source) and not result["preview_truncated"]


def test_long_previews_are_explicitly_truncated_without_changing_private_values():
    source = item(10, json.dumps("🙂" * 300, ensure_ascii=False))
    source["fact"]["name"] = "甲" * 300
    before = deepcopy(source)
    result = preview(source)
    assert source == before and result["preview_truncated"] is True
    assert len(result["value_preview"]) == len(result["name"]) == 240
    assert result["fact_item_digest"] == digest(before)


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_invalid_page_limits_fail(packet, limit):
    with pytest.raises(DomainError):
        page(packet[0], limit)


def test_empty_and_duplicate_fact_identity_contract(packet):
    original, snapshot = packet
    rows = snapshot["context"]["manifest"]["facts"]["items"]
    rows.append(deepcopy(rows[0]))
    with pytest.raises(DomainError, match="事实身份不唯一"):
        page(original)
    rows.clear()
    snapshot["context"]["manifest"]["facts"]["head"]["fact_set_id"] = None
    result = page(original)
    assert (
        valid("PackagePreparedFactPage", result)
        and result["fact_count"] == 0
        and result["items"] == []
        and result["next_cursor"] is None
    )


def test_corrupt_original_value_is_a_stored_input_error_not_current_scope_rejection(packet):
    original, snapshot = packet
    snapshot["context"]["manifest"]["facts"]["items"][0]["fact"]["value_jsonb_text"] = '"incomplete'
    with pytest.raises(DomainError) as error:
        page(original)
    assert error.value.status == 500 and error.value.code == "PACKAGE_EXECUTION_INPUT_CORRUPT"
