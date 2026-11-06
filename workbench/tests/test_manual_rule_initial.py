"""Boundaries for a human initial list; these unit checks do not claim native acceptance."""

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import human_routes
from apps.worker.report_handlers import report_document, rule_origin_label
from packages.domain import review_data, reviews, rule_corrections
from packages.domain.runtime import DomainError, validate

BID = UUID("00000000-0000-4000-8000-000000000001")
MATERIAL = UUID("00000000-0000-4000-8000-000000000002")
OPERATION = "00000000-0000-4000-8000-000000000003"
BODY = {
    "material_revision": 2,
    "reason": "SYNTHETIC source review",
    "additions": [
        {
            "kind": "mandatory",
            "statement": "human statement",
            "conditions": [],
            "exceptions": [],
            "scope": {"bid_id": str(BID), "description": "synthetic"},
            "maximum": None,
            "bands": [],
            "evidence_quotes": [{"evidence_id": str(MATERIAL), "quote": "source"}],
        }
    ],
}


def test_export_labels_human_model_and_legacy_unknown():
    assert rule_origin_label({"origin_kind": "human_added"}) == "人工来源"
    assert rule_origin_label({"origin_kind": "carried_human"}) == "人工来源"
    assert rule_origin_label({"origin_kind": "model_extracted"}) == "模型提取"
    assert rule_origin_label({}) == "来源未知"


def test_report_docx_retains_manual_origin_and_unknown_coverage():
    from io import BytesIO
    from zipfile import ZipFile

    rule = {
        "id": "synthetic-rule",
        "kind": "mandatory",
        "statement": "synthetic statement",
        "origin_kind": "human_added",
        "conditions": [],
        "exceptions": [],
        "scope": {},
        "provenance_status": "effective",
        "confirmation": "confirmed",
        "evidence_ids": [],
    }
    plan = {
        "content": {
            "manifest": {
                "body_version_id": "body",
                "rule_set_id": "set",
                "material_revision": 1,
                "evidence_manifest_digest": "digest",
                "as_of": "synthetic",
            },
            "body": {"original_name": "synthetic.pdf"},
            "review": {"id": "review", "current": True, "coverage_layers": {}},
            "source_state": "effective",
            "warnings": [],
            "prediction_policy": "hidden",
            "evidence": [],
            "findings": [],
            "matrix": {"rows": [{"rule": rule, "check_status": "unknown", "verdict": None}]},
        }
    }
    raw = report_document(plan, {})
    with ZipFile(BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "人工来源" in xml
    assert "逐条核对不代表整体覆盖完整" in xml


class Cursor:
    def __init__(self, value=None):
        self.value = value

    def fetchone(self):
        return self.value


class Connection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        self.calls.append((query, params))
        if "max(revision)" in query:
            return Cursor({"next": 1})
        return Cursor()


def test_initial_schema_requires_explicit_revision_and_original_quote():
    validate("ManualRuleSetInitialRequest", BODY)
    with pytest.raises(DomainError):
        validate("ManualRuleSetInitialRequest", BODY | {"material_revision": 0})
    with pytest.raises(DomainError):
        validate("ManualRuleSetInitialRequest", BODY | {"additions": []})


def test_initial_list_is_partial_human_and_uses_existing_correction(monkeypatch):
    c = Connection()
    monkeypatch.setattr(
        rule_corrections,
        "fetch",
        lambda *_: {"current_rule_set_id": None, "current_material_id": MATERIAL},
    )
    monkeypatch.setattr(
        rule_corrections, "uid", lambda: UUID("00000000-0000-4000-8000-000000000004")
    )
    captured = {}

    def correction(connection, bid, actor, command, request):
        captured["request"] = request
        return UUID("00000000-0000-4000-8000-000000000005")

    monkeypatch.setattr(rule_corrections, "correct_rules", correction)
    monkeypatch.setattr(rule_corrections, "audit", lambda *args: captured.update(audit=args))
    result = rule_corrections.initialize_manual_rules(c, BID, "actor", "command", BODY)
    assert str(result).endswith("5")
    inserted = next(
        params for query, params in c.calls if query.startswith("INSERT INTO rule_sets")
    )
    assert inserted[-1] == "partial"
    assert captured["request"]["additions"] == BODY["additions"]
    assert captured["audit"][3] == "rules.manual_initialized"
    assert captured["audit"][4]["model_extraction_claimed"] is False
    assert all(
        "effect_receipts" not in query and "extraction_runs" not in query for query, _ in c.calls
    )


def test_existing_rules_never_replaced(monkeypatch):
    c = Connection()
    monkeypatch.setattr(
        rule_corrections,
        "fetch",
        lambda *_: {"current_rule_set_id": MATERIAL, "current_material_id": MATERIAL},
    )
    with pytest.raises(DomainError) as error:
        rule_corrections.initialize_manual_rules(c, BID, "actor", "command", BODY)
    assert error.value.code == "RULE_SET_ALREADY_EXISTS"
    assert c.calls == []


@pytest.mark.parametrize(
    "state,kind,material,operation_state",
    [
        ("preparing", "rules", str(MATERIAL), "failed"),
        ("blocked", "parse", str(MATERIAL), "failed"),
        ("blocked", "rules", str(BID), "failed"),
        ("blocked", "rules", str(MATERIAL), "running"),
    ],
)
def test_route_rejects_nonfailed_or_stale_extraction(
    monkeypatch, state, kind, material, operation_state
):
    c = Connection()
    monkeypatch.setattr(human_routes, "auth", lambda *_: {"member_id": "actor"})
    monkeypatch.setattr(human_routes, "connection", lambda: nullcontext(c))
    monkeypatch.setattr(
        human_routes, "command", lambda *_: SimpleNamespace(replay=None, id="command")
    )
    monkeypatch.setattr(human_routes, "check_tag", lambda *_: None)
    monkeypatch.setattr(
        human_routes, "fetch", lambda *_: {"state": operation_state, "kind": "prepare-review"}
    )
    from apps.api import views

    monkeypatch.setattr(views, "bid_etag", lambda *_: '"synthetic"')
    monkeypatch.setattr(
        reviews,
        "_locked",
        lambda *_: (
            {"material_revision": 2, "current_material_id": MATERIAL},
            {
                "pending_intent": {
                    "state": state,
                    "preparation_kind": kind,
                    "material_snapshot_id": material,
                    "prepare_operation_id": OPERATION,
                }
            },
        ),
    )
    monkeypatch.setattr(review_data, "read_bundle", lambda *_: pytest.fail("must not read source"))
    with pytest.raises(DomainError) as error:
        human_routes.initialize_manual_rule_set(BID, SimpleNamespace(headers={}), BODY)
    assert error.value.code == "MANUAL_RULE_INITIAL_NOT_AVAILABLE"
