"""Selection controls data consumption, never factual authority or submission readiness."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.package_fact_usage import SCHEMA, select, verify
from packages.domain.review_identity import digest


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def packet(items=None, input_id=None, fact_set_id=uid(9)):
    if items is None:
        items = [
            {
                "fact": {
                    "id": uid(10),
                    "bid_id": uid(1),
                    "fact_set_id": uid(9),
                    "name": "selected",
                    "value_jsonb_text": '"selected-private"',
                },
                "decision": {"decision": "confirmed"},
                "decision_basis_jsonb_text": "private-audit",
            },
            {
                "fact": {
                    "id": uid(11),
                    "bid_id": uid(1),
                    "fact_set_id": uid(9),
                    "name": "unused",
                    "value_jsonb_text": '"unused-private"',
                },
                "decision": None,
                "scope_binding": "unproven",
            },
        ]
    facts = {"head": {"fact_set_id": fact_set_id}, "items": items, "qualification": "not_validated"}
    public = {
        "id": input_id or uid(6),
        "identity": {
            "binding": {
                **dict(
                    zip(
                        ("bid_id", "package_id", "revision_id", "inventory_id"),
                        (uid(n) for n in range(1, 5)),
                        strict=True,
                    )
                ),
                "frozen_input_id": uid(5),
                "identity_digest": "a" * 64,
            }
        },
        "execution_context": {
            "facts_digest": digest(facts),
            "fact_set_id": fact_set_id,
            "fact_count": len(items),
        },
    }
    snapshot = {
        "context": {
            "manifest": {
                "identity": {"digest": "a" * 64},
                "facts": facts,
                "facts_digest": digest(facts),
            }
        }
    }
    return PreparedExecutionInput(
        tuple(uid(n) for n in range(1, 5)),
        uid(5),
        public["id"],
        digest({"manifest": public, "snapshot": snapshot}),
        json.dumps({"manifest": public}),
        json.dumps(snapshot),
    )


def request(*ids):
    return {"purpose": "prebid_compliance", "fact_ids": [uid(n) for n in ids]}


def test_explicit_empty_selection_requires_no_company_facts_but_does_not_prove_no_required_facts():
    Draft202012Validator.check_schema(SCHEMA)
    source = packet()
    selected = select(source, request())
    assert selected.selected_items() == [] and selected.view()["manifest"]["selected"] == []
    assert selected.view()["manifest"]["required_facts_assessment"] == "not_performed"
    assert all(
        selected.view()["manifest"][key] is False
        for key in ("facts_qualified", "review_ready", "launch_available", "publication_authorized")
    )
    assert source.snapshot()["context"]["manifest"]["facts"]["qualification"] == "not_validated"
    assert verify(selected.view(), source).view() == selected.view()


def test_selected_projection_does_not_expose_or_admit_unused_unconfirmed_facts():
    source = packet()
    selected = select(source, request(10))
    assert [x["fact"]["id"] for x in selected.selected_items()] == [uid(10)]
    assert "unused-private" not in str(selected.selected_items())
    assert "selected-private" not in str(selected.view()) + repr(selected)
    assert "private-audit" not in str(selected.view()) + repr(selected)
    assert selected.view()["manifest"]["facts_qualified"] is False
    assert len(source.snapshot()["context"]["manifest"]["facts"]["items"]) == 2


def test_explicit_order_is_normalized_and_each_consumer_owns_its_copy():
    source = packet()
    selected = select(source, request(11, 10))
    assert selected.view() == select(source, request(10, 11)).view()
    view = selected.view()
    view["manifest"]["selected"].clear()
    used = selected.selected_items()
    used[0]["fact"]["value_jsonb_text"] = "changed"
    assert len(selected.view()["manifest"]["selected"]) == 2
    assert selected.selected_items()[0]["fact"]["value_jsonb_text"] == '"selected-private"'


def test_no_fact_head_can_select_no_facts_without_claiming_requirements_complete():
    usage = select(packet([], fact_set_id=None), request())
    assert usage.selected_items() == []
    assert usage.view()["manifest"]["required_facts_assessment"] == "not_performed"


def test_explicitly_selecting_unconfirmed_fact_does_not_grant_admission():
    usage = select(packet(), request(11))
    assert usage.selected_items()[0]["decision"] is None
    assert usage.view()["manifest"]["facts_qualified"] is False


def test_unused_pool_change_preserves_usage_semantics_but_keeps_distinct_archive_proof():
    source = packet()
    old = select(source, request(10))
    items = source.snapshot()["context"]["manifest"]["facts"]["items"]
    items[1]["fact"]["value_jsonb_text"] = '"new-unused-value"'
    newer = packet(items, uid(99))
    new = select(newer, request(10))
    assert old.view()["manifest"]["selection_digest"] == new.view()["manifest"]["selection_digest"]
    assert (
        old.view()["manifest"]["selected_facts_digest"]
        == new.view()["manifest"]["selected_facts_digest"]
    )
    assert (
        old.digest != new.digest
        and old.view()["manifest"]["prepared"] != new.view()["manifest"]["prepared"]
    )
    with pytest.raises(ValueError):
        verify(old.view(), newer)


def test_selected_value_change_creates_new_usage_without_rewriting_old_input():
    source = packet()
    old = select(source, request(10))
    items = source.snapshot()["context"]["manifest"]["facts"]["items"]
    items[0]["fact"]["value_jsonb_text"] = '"new-selected-value"'
    new = select(packet(items, uid(99)), request(10))
    assert old.view()["manifest"]["selection_digest"] != new.view()["manifest"]["selection_digest"]
    assert old.selected_items()[0]["fact"]["value_jsonb_text"] == '"selected-private"'


@pytest.mark.parametrize(
    "bad",
    ["missing", "unknown", "duplicate", "latest", "uppercase", "digest_id", "purpose", "grant"],
)
def test_no_implicit_latest_all_foreign_or_qualification_request(bad):
    body = request(10)
    if bad == "missing":
        body.pop("fact_ids")
    if bad == "unknown":
        body["fact_ids"] = [uid(99)]
    if bad == "duplicate":
        body["fact_ids"] = [uid(10), uid(10)]
    if bad == "latest":
        body["fact_ids"] = ["latest"]
    if bad == "uppercase":
        body["fact_ids"] = ["AAAAAAAA-0000-4000-8000-000000000001"]
    if bad == "digest_id":
        body["fact_ids"] = ["a" * 64]
    if bad == "purpose":
        body["purpose"] = "formal_scoring"
    if bad == "grant":
        body["facts_qualified"] = True
    with pytest.raises(ValueError):
        select(packet(), body)


@pytest.mark.parametrize(
    "key", ["facts_qualified", "review_ready", "launch_available", "publication_authorized"]
)
def test_resealed_selection_cannot_be_promoted_to_authority(key):
    source = packet()
    value = select(source, request(10)).view()
    value["manifest"][key] = True
    value["digest"] = digest(value["manifest"])
    with pytest.raises(ValueError):
        verify(value, source)


@pytest.mark.parametrize("key,value", [("bid_id", uid(99)), ("fact_set_id", uid(99))])
def test_selected_item_must_belong_to_exact_prepared_scope(key, value):
    source = packet()
    items = source.snapshot()["context"]["manifest"]["facts"]["items"]
    items[0]["fact"][key] = value
    with pytest.raises(ValueError, match="fact_usage_fact_scope"):
        select(packet(items), request(10))


def test_record_digest_selected_identity_and_order_recomputed_on_read():
    source = packet()
    value = select(source, request(10, 11)).view()
    for change in ("digest", "item", "order"):
        forged = deepcopy(value)
        if change == "digest":
            forged["digest"] = "0" * 64
        if change == "item":
            forged["manifest"]["selected"][0]["fact_item_digest"] = "f" * 64
        if change == "order":
            forged["manifest"]["selected"].reverse()
        if change != "digest":
            forged["digest"] = digest(forged["manifest"])
        with pytest.raises(ValueError):
            verify(forged, source)
