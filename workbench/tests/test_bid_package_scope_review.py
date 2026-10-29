"""Explicit synthetic observation ports; no PostgreSQL, object storage or model effects."""
# ruff: noqa: F401,F811

import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_package_scope_review import case, uid

from packages.domain import bid_package_scope_review as scope_review
from packages.domain.package_execution_input import PreparedExecutionInput
from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.runtime import DomainError


@pytest.fixture
def ports(case, monkeypatch):
    manifest = case["manifest"]
    snapshot = {
        "binding": manifest["execution_input"]["identity"]["binding"],
        "context": {
            "manifest": {"as_of": "old", "facts": {"head": "exact-facts"}},
            "semantic_digest": "context",
        },
        "result": {
            "checked_at": "old",
            "current_context": {
                "as_of": "old",
                "snapshot_digest": "old",
                "semantic_digest": "context",
            },
            "parse_evidence_status": "matched",
            "blockers": sorted(scope_review.OBSERVATION_LIMITATIONS),
            "review_ready": False,
            "launch_available": False,
            "publication_authorized": False,
        },
        "observations": {"head": "exact-revision", "sources": "published"},
        "documents": [
            {"member_id": "main-bid", "object_key": "private-locator", "digest": "a" * 64}
        ],
    }
    original = case["prepared"]
    prepared = PreparedExecutionInput(
        original.scope,
        original.frozen_id,
        original.input_id,
        original.digest,
        json.dumps(original.view()),
        json.dumps(snapshot | {"version": "package-review-prepared-snapshot/1"}),
    )
    frozen = FrozenPackageReviewInput(
        json.dumps(case["frozen"].view()["manifest"]),
        json.dumps(case["root"]),
        case["frozen"].digest,
    )
    assessment = {
        "manifest": {
            "dependency_review_status": "declared",
            "usage_digest": case["admission"].view()["manifest"]["usage_digest"],
            "selected_fact_count": 0,
            "requirements": [
                {
                    "declaration": case["declaration"],
                    "fact_status": "not_used",
                    "source_bound": True,
                }
            ],
        }
    }
    admission_manifest = case["admission"].view()["manifest"] | {
        "admission": "not_used",
        "selected_count": 0,
    }
    proof = {
        "manifest": {
            "extraction_range_proven": True,
            "extraction_receipt_state": "matched",
            "extraction_coverage": "complete",
            "blockers": [scope_review.policy.LIMITATION],
        },
        "digest": case["proof"]["digest"],
    }
    case["plan"]["manifest"]["usage"] = {}
    state = {
        "active": 0,
        "events": [],
        "snapshot": deepcopy(snapshot),
        "prepared": prepared,
        "frozen": frozen,
        "case": case,
        "plan": case["plan"],
        "assessment": assessment,
        "admission": admission_manifest,
        "proof_text": "original-proof",
        "proof": proof,
        "during_io": None,
    }

    class Connection:
        autocommit = False
        isolation = "read committed"

        def execute(self, sql, parameters=()):
            state["events"].append(sql)
            if sql.startswith("SET TRANSACTION"):
                self.isolation = "repeatable read"
            return SimpleNamespace(fetchone=lambda: {"transaction_isolation": self.isolation})

    @contextmanager
    def connection(worker=False):
        state["events"].append(("connection", worker))
        state["active"] += 1
        try:
            yield Connection()
        finally:
            state["active"] -= 1

    def observe_facts(*args):
        value = deepcopy(state["admission"])
        return SimpleNamespace(
            view=lambda: {"manifest": deepcopy(value)},
            selected_items=lambda: [],
            _proof_text=state["proof_text"],
        )

    def verify_original(document):
        assert state["active"] == 0
        state["events"].append("original-io")
        if state["during_io"]:
            state["during_io"]()

    monkeypatch.setattr(scope_review, "connection", connection)
    monkeypatch.setattr(
        scope_review.prepared_inputs, "load_packet", lambda *args: state["prepared"]
    )
    monkeypatch.setattr(scope_review.frozen_inputs, "load_input", lambda *args: state["frozen"])
    monkeypatch.setattr(scope_review.plans, "load", lambda *args: deepcopy(state["plan"]))
    monkeypatch.setattr(
        scope_review.originals, "capture", lambda *args: deepcopy(state["snapshot"])
    )
    monkeypatch.setattr(scope_review.fact_usage, "verify", lambda *args: "explicit-selection")
    monkeypatch.setattr(
        scope_review.dependencies,
        "verify",
        lambda *args: SimpleNamespace(view=lambda: deepcopy(state["assessment"])),
    )
    monkeypatch.setattr(scope_review.fact_admission, "_observe", observe_facts)
    monkeypatch.setattr(
        scope_review.inventory_reader, "_receipt", lambda *args: "exact-extraction-receipt"
    )
    monkeypatch.setattr(
        scope_review.inventory_proof,
        "assess",
        lambda *args: SimpleNamespace(view=lambda: deepcopy(state["proof"])),
    )
    monkeypatch.setattr(scope_review.original_verification, "verify", verify_original)
    monkeypatch.setattr(scope_review, "lock_bid", lambda *args: state["events"].append("bid-lock"))
    monkeypatch.setattr(
        scope_review, "lock_graph", lambda *args: state["events"].append("graph-lock")
    )
    monkeypatch.setattr(
        scope_review,
        "assert_work_writable",
        lambda *args, **kwargs: state["events"].append(("writable", kwargs["worker"])),
    )
    state["Connection"] = Connection
    return state


def observe(state, worker=False):
    p = state["prepared"]
    body = {
        "execution_input_digest": p.digest,
        "dependency_plan_id": state["plan"]["manifest"]["id"],
        "dependency_plan_digest": state["plan"]["digest"],
    }
    return scope_review.observe(p.scope, p.frozen_id, p.input_id, body, worker=worker)


def test_api_admission_does_not_need_model_credentials_or_grant_full_qualification(
    ports, monkeypatch
):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    observed = observe(ports)
    assert ports["active"] == 0 and "original-io" not in ports["events"]
    assert "private-locator" not in repr(observed)
    verified = scope_review.verify(observed)
    assert ports["events"].count("original-io") == 1
    ports["events"].clear()
    manifest = scope_review.recheck(ports["Connection"](), verified)
    assert ports["events"] == [
        "SHOW transaction_isolation",
        "bid-lock",
        ("writable", False),
        "graph-lock",
    ]
    assert manifest["limitations"] == [scope_review.policy.LIMITATION]
    assert ports["snapshot"]["result"]["review_ready"] is False
    assert "publication_authorized" not in manifest


def test_private_observation_preserves_complete_float_parse_snapshot(ports):
    ports["snapshot"]["documents"][0]["blocks"] = [
        {
            "bbox": [0.0, -0.0, 12.000000000000002, 841.8897637795277],
            "structure": {"table": {"cells": [{"row": 1, "width": 17.125}]}},
        }
    ]
    prepared = ports["prepared"]
    ports["prepared"] = replace(
        prepared,
        _snapshot_text=json.dumps(
            ports["snapshot"] | {"version": "package-review-prepared-snapshot/1"}
        ),
    )
    observed = observe(ports)
    assert json.loads(observed._snapshot_text) == ports["snapshot"]
    verified = scope_review.verify(observed)
    assert scope_review.recheck(ports["Connection"](), verified) == observed.input_manifest()

    # A geometry change during original IO is still an authority change.
    def alter_geometry():
        ports["snapshot"]["documents"][0]["blocks"][0]["structure"]["table"]["cells"][0][
            "width"
        ] = 17.5

    ports["during_io"] = alter_geometry
    with pytest.raises(DomainError) as error:
        scope_review.verify(observed)
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"


def test_independent_worker_uses_only_worker_role_and_missing_config_is_explicit(
    ports, monkeypatch
):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(DomainError) as error:
        observe(ports, worker=True)
    assert error.value.code == "MODEL_NOT_CONFIGURED" and not ports["events"]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-only-never-sent")
    verified = scope_review.verify(observe(ports, worker=True))
    assert ("connection", False) not in ports["events"]
    ports["events"].clear()
    scope_review.recheck(ports["Connection"](), verified)
    assert ports["events"][:4] == [
        "SHOW transaction_isolation",
        "SELECT design.lock_worker_bid(%s)",
        ("writable", True),
        "graph-lock",
    ]
    assert "original-io" not in ports["events"]


@pytest.mark.parametrize("change", ["head", "source", "facts", "method", "parse", "identity"])
def test_current_input_change_during_original_io_is_rejected(ports, change):
    observed = observe(ports)

    def mutate():
        if change == "head":
            ports["snapshot"]["observations"]["head"] = "new-revision"
        elif change == "source":
            ports["snapshot"]["observations"]["sources"] = "withdrawn"
        elif change == "facts":
            ports["snapshot"]["context"]["manifest"]["facts"]["head"] = "changed-facts"
        elif change == "method":
            ports["snapshot"]["binding"]["method_digest"] = "0" * 64
        elif change == "parse":
            ports["snapshot"]["documents"][0]["digest"] = "0" * 64
        else:
            ports["snapshot"]["binding"]["identity_digest"] = "0" * 64

    ports["during_io"] = mutate
    with pytest.raises(DomainError) as error:
        scope_review.verify(observed)
    assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"


@pytest.mark.parametrize("change", ["fact_scope", "plan", "source", "method"])
def test_late_fact_scope_plan_source_or_method_change_prevents_publication(
    ports, monkeypatch, change
):
    verified = scope_review.verify(observe(ports))
    if change == "fact_scope":
        ports["admission"]["content_digest"] = "0" * 64
        ports["proof_text"] = "scope-withdrawal"
    elif change == "plan":
        ports["plan"]["digest"] = "0" * 64
    elif change == "source":
        ports["snapshot"]["observations"]["sources"] = "withdrawn"
    else:
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    ports["events"].clear()
    with pytest.raises(DomainError):
        scope_review.recheck(ports["Connection"](), verified)
    assert "original-io" not in ports["events"]


@pytest.mark.parametrize(
    "code",
    [
        "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE",
        "PROJECT_WORK_CLOSED",
        "PACKAGE_REVIEW_PHYSICAL_RANGE_GAP",
        "FUTURE_NEW_POLICY_BLOCKER",
    ],
)
def test_only_three_observation_limitations_have_new_protocol_replacements(ports, code):
    snapshot = deepcopy(ports["snapshot"])
    snapshot["result"]["blockers"].append(code)
    with pytest.raises(DomainError) as error:
        scope_review._admit(
            snapshot,
            ports["assessment"],
            SimpleNamespace(view=lambda: {"manifest": ports["admission"]}),
            ports["proof"],
        )
    assert error.value.code == "PACKAGE_SCOPE_INPUT_BLOCKED"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "unknown",
        "undeclared",
        "unbound",
        "unverified_facts",
        "bad_receipt",
        "partial_extraction",
        "unbound_inventory",
    ],
)
def test_missing_or_unknown_dependency_and_inexact_extraction_cannot_launch(ports, change):
    if change in {"missing", "unknown"}:
        ports["assessment"]["manifest"]["requirements"][0]["fact_status"] = change
    elif change == "undeclared":
        ports["assessment"]["manifest"]["dependency_review_status"] = "incomplete"
    elif change == "unbound":
        ports["assessment"]["manifest"]["requirements"][0]["source_bound"] = False
    elif change == "unverified_facts":
        ports["assessment"]["manifest"]["selected_fact_count"] = 1
    elif change == "bad_receipt":
        ports["proof"]["manifest"]["extraction_receipt_state"] = "read_set_mismatch"
    elif change == "partial_extraction":
        ports["proof"]["manifest"]["extraction_coverage"] = "partial"
    else:
        ports["proof"]["manifest"]["blockers"].append("INVENTORY_UNBOUND_REQUIREMENT")
    with pytest.raises(DomainError):
        observe(ports)
    assert "original-io" not in ports["events"]


def test_observation_time_only_does_not_change_execution_identity(ports):
    observed = observe(ports)
    ports["snapshot"]["context"]["manifest"]["as_of"] = "later"
    ports["snapshot"]["result"]["checked_at"] = "later"
    ports["snapshot"]["result"]["current_context"].update(as_of="later", snapshot_digest="later")
    verified = scope_review.verify(observed)
    assert scope_review.recheck(ports["Connection"](), verified) == observed.input_manifest()


def test_publication_rejects_autocommit_rr_and_serialized_observations(ports):
    verified = scope_review.verify(observe(ports))
    c = ports["Connection"]()
    c.autocommit = True
    with pytest.raises(ValueError):
        scope_review.recheck(c, verified)
    c.autocommit = False
    c.isolation = "repeatable read"
    with pytest.raises(DomainError):
        scope_review.recheck(c, verified)
    with pytest.raises(TypeError):
        scope_review.recheck(c, {"manifest": verified._observed.input_manifest()})


def test_replaced_prepared_snapshot_is_not_silently_reconstructed(ports):
    verified = scope_review.verify(observe(ports))
    saved = ports["prepared"]
    snapshot = saved.snapshot()
    snapshot["documents"][0]["object_key"] = "another-locator"
    ports["prepared"] = replace(saved, _snapshot_text=json.dumps(snapshot))
    with pytest.raises(DomainError):
        scope_review.recheck(ports["Connection"](), verified)
