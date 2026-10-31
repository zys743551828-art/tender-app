"""Explicit ambiguity acknowledgement; no inferred semantic resolution or paid IO."""

from uuid import uuid4

import pytest

from apps.api.source_effectivity_contracts import models, validate_request
from packages.domain import source_effectivity as effectivity
from packages.domain.runtime import DomainError


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class History:
    def __init__(self):
        self.bid = str(uuid4())
        self.root = str(uuid4())
        self.operation = str(uuid4())
        self.sets = {self.root: {"id": self.root, "coverage": "conflict"}}
        self.effects = {
            self.root: [
                {
                    "operation_id": self.operation,
                    "result": {
                        "result_ref": self.root,
                        "ambiguities": ["工期冲突", "截止时间冲突"],
                    },
                }
            ]
        }
        self.parents = {}
        self.queries = 0

    def execute(self, query, parameters):
        self.queries += 1
        if "FROM rule_sets" in query:
            return Rows([self.sets[str(parameters[0])]] if str(parameters[0]) in self.sets else [])
        if "FROM effect_receipts" in query:
            return Rows(self.effects.get(str(parameters[1]), []))
        if "FROM audit_entries" in query:
            return Rows([{"parent": value} for value in self.parents.get(str(parameters[1]), [])])
        raise AssertionError("Unexpected query")


def test_origin_ids_are_stable_and_bind_text_index_and_extraction_identity():
    history = History()
    original = effectivity.ambiguity_context(history, history.bid, history.root)
    assert original["available"] and original["error"] is None
    assert [item["text"] for item in original["items"]] == ["工期冲突", "截止时间冲突"]
    assert len({item["id"] for item in original["items"]}) == 2
    assert effectivity.ambiguity_context(history, history.bid, history.root) == original
    history.effects[history.root][0]["operation_id"] = str(uuid4())
    assert (
        effectivity.ambiguity_context(history, history.bid, history.root)["items"]
        != original["items"]
    )


def test_current_child_uses_exact_ancestor_ambiguities_without_new_identifiers():
    history = History()
    child = str(uuid4())
    history.sets[child] = {"id": child, "coverage": "conflict"}
    history.parents[child] = [history.root]
    assert effectivity.ambiguity_context(
        history, history.bid, child
    ) == effectivity.ambiguity_context(history, history.bid, history.root)


@pytest.mark.parametrize(
    "variant", ["unknown", "cycle", "branch", "invalid_parent", "duplicate_origin", "bad_result"]
)
def test_untraceable_origins_fail_closed_without_losing_readonly_view(variant):
    history = History()
    if variant == "unknown":
        history.effects.clear()
    elif variant == "cycle":
        history.effects.clear()
        history.parents[history.root] = [history.root]
    elif variant == "branch":
        history.effects.clear()
        history.parents[history.root] = [str(uuid4()), str(uuid4())]
    elif variant == "invalid_parent":
        history.effects.clear()
        history.parents[history.root] = ["not-a-rule-set"]
    elif variant == "duplicate_origin":
        history.effects[history.root] *= 2
    else:
        history.effects[history.root][0]["result"]["ambiguities"] = []
    value = effectivity.ambiguity_context(history, history.bid, history.root)
    assert not value["available"] and value["items"] == [] and value["error"]


def test_origin_traversal_has_a_fixed_query_bound():
    history = History()
    history.effects.clear()
    current = history.root
    for _ in range(40):
        parent = str(uuid4())
        history.sets[parent] = {"id": parent, "coverage": "conflict"}
        history.parents[current] = [parent]
        current = parent
    value = effectivity.ambiguity_context(history, history.bid, history.root)
    assert value["error"] == "SOURCE_AMBIGUITY_HISTORY_LIMIT"
    assert history.queries <= 3 * effectivity.AMBIGUITY_HISTORY_LIMIT


def test_nonconflicting_or_absent_rule_set_has_no_resolvable_conflict():
    history = History()
    history.sets[history.root]["coverage"] = "partial"
    for identity in [history.root, None]:
        value = effectivity.ambiguity_context(history, history.bid, identity)
        assert value["items"] == [] and not value["available"] and value["error"] is None


def test_full_explicit_ack_is_required_and_missing_legacy_field_is_not_ack():
    history = History()
    value = effectivity.ambiguity_context(history, history.bid, history.root)
    assert not effectivity._validate_ambiguity_ack({"action": "partial_replace"}, value)
    assert not effectivity._validate_ambiguity_ack(
        {"action": "partial_replace", "acknowledged_ambiguity_ids": []}, value
    )
    assert effectivity._validate_ambiguity_ack(
        {
            "action": "partial_replace",
            "acknowledged_ambiguity_ids": [item["id"] for item in value["items"]],
        },
        value,
    )


@pytest.mark.parametrize(
    "variant", ["subset", "foreign", "duplicate", "defer", "malformed", "unknown_origin"]
)
def test_incomplete_foreign_deferred_or_invalid_ack_never_resolves(variant):
    history = History()
    value = effectivity.ambiguity_context(history, history.bid, history.root)
    ids = [item["id"] for item in value["items"]]
    body = {"action": "partial_replace", "acknowledged_ambiguity_ids": ids}
    if variant == "subset":
        body["acknowledged_ambiguity_ids"] = ids[:1]
    elif variant == "foreign":
        body["acknowledged_ambiguity_ids"] = ["f" * 64, *ids[1:]]
    elif variant == "duplicate":
        body["acknowledged_ambiguity_ids"] = ids * 2
    elif variant == "defer":
        body["action"] = "defer"
    elif variant == "malformed":
        body["acknowledged_ambiguity_ids"] = [None]
    else:
        value = {"available": False, "error": "SOURCE_AMBIGUITY_ORIGIN_UNKNOWN", "items": []}
    with pytest.raises(DomainError):
        effectivity._validate_ambiguity_ack(body, value)


def test_dto_adds_optional_closed_ack_and_visible_ambiguities():
    definitions = models(lambda name: {"$ref": "#/$defs/" + name})
    request = definitions["SourceEffectivityRequest"]
    assert "acknowledged_ambiguity_ids" in request["properties"]
    assert "acknowledged_ambiguity_ids" not in request["required"]
    assert request["properties"]["acknowledged_ambiguity_ids"]["uniqueItems"]
    view = definitions["SourceEffectivityView"]
    assert {"ambiguities", "ambiguity_resolution_available", "ambiguity_resolution_error"} <= set(
        view["required"]
    )
    body = {
        "base_rule_set_id": str(uuid4()),
        "action": "partial_replace",
        "old_document_version_id": str(uuid4()),
        "new_document_version_id": str(uuid4()),
        "rule_ids": [str(uuid4())],
        "scope_basis": [{"evidence_id": str(uuid4()), "quote": "仅修改工期"}],
        "additions": [],
        "reason": "SYNTHETIC explicit acknowledgement",
    }
    validate_request(body)
    validate_request(body | {"acknowledged_ambiguity_ids": ["a" * 64]})
    with pytest.raises(DomainError):
        validate_request(body | {"acknowledged_ambiguity_ids": ["a" * 64, "a" * 64]})


@pytest.mark.parametrize("marker", ["其余招标要求保持", "其余招标要求不变"])
@pytest.mark.parametrize("action", ["whole_replace", "partial_replace"])
def test_remaining_tender_requirements_scope_is_explicitly_partial(marker, action):
    document, evidence = str(uuid4()), str(uuid4())
    quote = f"本补遗明确替换以上两条，{marker}；虚构编制日期2030-01-10。"
    documents = [
        {
            "document_version_id": document,
            "role": "supplement",
            "blocks": [{"id": evidence, "text_content": quote}],
        }
    ]
    body = {
        "new_document_version_id": document,
        "action": action,
        "scope_basis": [{"evidence_id": evidence, "quote": quote}],
    }
    if action == "whole_replace":
        with pytest.raises(DomainError) as error:
            effectivity._quoted_basis(body, documents)
        assert error.value.code == "SOURCE_EFFECTIVITY_SCOPE_CONFLICT"
    else:
        selected, blocks = effectivity._quoted_basis(body, documents)
        assert selected == documents[0] and blocks[evidence]["text_content"] == quote
