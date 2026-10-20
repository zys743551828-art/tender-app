"""Current display/edit data remains bounded and separate from factual use authority."""

import json

import pytest

from packages.domain.bid_package_current_facts import _editable_fact, _summary
from tests.test_bid_package_prepared_facts import item, uid


def current(raw='"180天"'):
    value = item(1, raw)
    value["fact"]["evidence_ids"] = [uid(10)]
    value.update(decision=None, scope_binding="unproven")
    return value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('"180天"', "180天"),
        ("false", False),
        ("true", True),
        ("null", None),
        ('"<script>"', "<script>"),
    ],
)
def test_only_existing_supported_scalar_types_are_editable(raw, expected):
    value = _editable_fact(current(raw))
    assert value is not None and value["value"] == expected
    assert "reason" not in value


@pytest.mark.parametrize("raw", ["180", "1.00000000000000000001", '{"amount":1.25}', "[]"])
def test_legacy_json_is_readable_as_preview_but_never_coerced_to_a_new_fact(raw):
    value = current(raw)
    assert _editable_fact(value) is None
    assert _summary(value)["value_preview"] == raw


@pytest.mark.parametrize(
    "change", ["name", "value", "empty", "duplicate_evidence", "too_many_evidence"]
)
def test_oversized_or_unsupported_existing_fields_require_explicit_reentry(change):
    value = current()
    if change == "name":
        value["fact"]["name"] = "x" * 5001
    if change == "value":
        value["fact"]["value_jsonb_text"] = json.dumps("x" * 20001)
    if change == "empty":
        value["fact"]["subject"] = " "
    if change == "duplicate_evidence":
        value["fact"]["evidence_ids"] *= 2
    if change == "too_many_evidence":
        value["fact"]["evidence_ids"] = [uid(n) for n in range(101)]
    assert _editable_fact(value) is None


def test_preview_is_bounded_and_recorded_confirmation_is_not_scope_or_use_qualification():
    value = current(json.dumps("😀" * 300))
    value.update(
        decision=dict(id=uid(20), object_kind="fact", decision="confirmed"),
        scope_binding="selected_frozen_parse",
    )
    result = _summary(value)
    assert (
        result["confirmation_recorded"] == "confirmed"
        and result["frozen_evidence_status"] == "selected_parse"
    )
    assert result["value_preview"] == "😀" * 240 and result["preview_truncated"] is True
    assert "private-basis" not in json.dumps(result)


def test_wrong_decision_kind_is_not_presented_as_a_recorded_fact_confirmation():
    value = current()
    value["decision"] = dict(id=uid(20), object_kind="rule", decision="confirmed")
    assert _summary(value)["confirmation_recorded"] == "pending"
