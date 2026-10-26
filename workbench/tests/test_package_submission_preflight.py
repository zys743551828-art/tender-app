"""Submission preflight closes IO boundaries without granting standard submission."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from package_submission_gate_cases import TIME, case, confirmation_rows, history, proof, report, uid

from packages.contracts.package_submissions_api import valid
from packages.domain import package_submission_gate as gate
from packages.domain import package_submission_preflight as preflight
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError


@pytest.fixture
def ports(monkeypatch):
    fixture = case()
    selection = {
        key: fixture["selection"][key] for key in ("target", "authority", "inventory", "coverage")
    }
    run = report(fixture)
    target, inv = selection["target"], selection["inventory"]
    request = {
        "package_id": target["manifest"]["package_id"],
        "revision_id": target["manifest"]["revision_id"],
        "package_digest": target["digest"],
        "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]},
        "coverage": None,
        "review_run": {
            "id": run["id"],
            "input_digest": run["input_digest"],
            "result_digest": run["result"]["digest"],
        },
    }
    observed = gate.assess(
        selection,
        observed_at=TIME,
        current=fixture["current"],
        run=run,
        inventory_proof=proof(fixture),
        rule_decisions=confirmation_rows(fixture),
        risk_history=history(run),
    )
    originals = [
        {
            "document_version_id": member["document_version_id"],
            "digest": member["file_digest"],
            "byte_size": 20,
            "media_type": "application/pdf",
            "artifact_kind": "source_original",
            "original_name": "synthetic.pdf",
            "roles": [role],
            "blob_id": uid(900 + index),
            "object_key": "synthetic-private-locator/" + member["member_id"],
        }
        for index, (role, member) in enumerate(
            (role, member)
            for role in ("target", "authority")
            for member in selection[role]["manifest"]["members"]
        )
    ]
    value = {
        "selection": selection,
        "selection_request": request,
        "input_digest": "a" * 64,
        "review_run": run,
        "gate": observed,
        "originals": originals,
        "observed_at": TIME,
    }
    runtime = {
        "state": "matched",
        "run_id": run["id"],
        "selected_input_digest": run["input_digest"],
        "current_input_digest": run["input_digest"],
        "codes": [],
    }
    state = {
        "open": False,
        "captures": 0,
        "reads": [],
        "value": value,
        "runtime": runtime,
        "etag": '"bid:' + uid(1) + ":" + "b" * 64 + '"',
        "callback": None,
        "actor": uid(90),
    }

    @contextmanager
    def connect():
        assert not state["open"]
        state["open"] = True
        state["captures"] += 1
        try:
            yield SimpleNamespace(
                execute=lambda statement: (
                    None
                    if statement == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    else pytest.fail("Preflight attempted a non-readonly statement")
                )
            )
        finally:
            state["open"] = False

    def observe(_c, scope, body):
        assert state["open"] and scope == (uid(1), uid(2), uid(3))
        assert body == request
        return deepcopy(state["value"])

    def verify(row):
        assert not state["open"], "No database session may span object IO"
        state["reads"].append(deepcopy(row))
        if state["callback"]:
            callback, state["callback"] = state["callback"], None
            callback()

    monkeypatch.setattr(preflight, "connection", connect)
    monkeypatch.setattr(preflight.repository, "require_schema", lambda _c: None)
    monkeypatch.setattr(preflight.observations, "observe", observe)
    monkeypatch.setattr(preflight, "_runtime", lambda _c, _v: deepcopy(state["runtime"]))
    monkeypatch.setattr(preflight.original_verification, "verify", verify)
    state["body"] = {"selection": request, "input_digest": value["input_digest"]}
    return state


def inspect(state, **kwargs):
    return preflight.inspect(
        (uid(1), uid(2), uid(3)),
        uid(90),
        kwargs.get("body", state["body"]),
        kwargs.get("condition", state["etag"]),
        bid_etag_fn=lambda _c, _b: state["etag"],
        final_auth=lambda: state["actor"],
    )


def test_full_originals_and_runtime_pass_one_gate_without_inventing_completeness(ports):
    result = inspect(ports)
    manifest = result["manifest"]
    assert valid("PackageSubmissionPreflightView", result)
    assert result["digest"] == digest(manifest)
    assert ports["captures"] == 2 and ports["reads"] == ports["value"]["originals"]
    assert not ports["open"]
    current = manifest["gates"]["current_input"]
    assert current["state"] == "pass" and current["codes"] == []
    assert current["original_verification"] == "verified_at_observation"
    assert current["original_count"] == len(ports["reads"])
    assert current["originals_digest"] == digest(manifest["originals"])
    assert manifest["gates"]["core_coverage"]["state"] == "unknown"
    assert manifest["review_runtime"]["state"] == "matched"
    assert manifest["state"] == "unknown"
    for flag in (
        "allowed",
        "inventory_complete",
        "submission_eligible",
        "publication_authorized",
        "platform_submission_verified",
    ):
        assert manifest[flag] is False
        changed = deepcopy(result)
        changed["manifest"][flag] = True
        assert not valid("PackageSubmissionPreflightView", changed)
    assert "synthetic-private-locator" not in str(result)
    assert "object_key" not in str(result) and "blob_id" not in str(result)


@pytest.mark.parametrize("change", ["invalid", "precondition", "etag", "input", "capacity"])
def test_invalid_stale_or_unbounded_request_never_reads_objects(ports, change):
    kwargs = {}
    if change == "invalid":
        kwargs["body"] = ports["body"] | {"verified": True}
    elif change == "precondition":
        kwargs["condition"] = None
    elif change == "etag":
        kwargs["condition"] = '"stale"'
    elif change == "input":
        kwargs["body"] = ports["body"] | {"input_digest": "0" * 64}
    else:
        ports["value"]["originals"][0]["byte_size"] = preflight.MAX_ORIGINAL_BYTES + 1
    with pytest.raises(DomainError):
        inspect(ports, **kwargs)
    assert ports["reads"] == []
    assert ports["captures"] == (0 if change in {"invalid", "precondition"} else 1)


@pytest.mark.parametrize(
    "change", ["input", "etag", "locator", "runtime", "source-expired", "identity", "actor"]
)
def test_any_change_during_object_io_prevents_a_published_receipt(ports, change):
    def callback():
        if change == "input":
            ports["value"]["input_digest"] = "0" * 64
        elif change == "etag":
            ports["etag"] = '"changed"'
        elif change == "locator":
            ports["value"]["originals"][0]["object_key"] = "different-private-locator"
        elif change == "runtime":
            ports["runtime"].update(state="blocked", codes=["PACKAGE_SCOPE_DEPENDENCIES_CHANGED"])
        elif change == "actor":
            ports["actor"] = uid(999)
        else:
            current = ports["value"]["gate"]["manifest"]["gates"]["current_input"]
            current["state"] = "blocked"
            current["codes"].append(
                "PACKAGE_SOURCE_NOT_EFFECTIVE"
                if change == "source-expired"
                else "CURRENT_IDENTITY_UNCONFIRMED"
            )

    ports["callback"] = callback
    with pytest.raises(DomainError) as failure:
        inspect(ports)
    assert failure.value.status in {403, 409, 412}
    assert len(ports["reads"]) > 0
    assert ports["captures"] == (1 if change == "actor" else 2)
    assert not ports["open"]


def test_original_byte_failure_does_not_publish_a_successful_receipt(ports, monkeypatch):
    def rejected(_row):
        assert not ports["open"]
        raise DomainError("ORIGINAL_BYTES_CORRUPTED", "synthetic corrupt bytes", 409)

    monkeypatch.setattr(preflight.original_verification, "verify", rejected)
    with pytest.raises(DomainError, match="synthetic corrupt"):
        inspect(ports)
    assert ports["captures"] == 1


@pytest.mark.parametrize("state", ["blocked", "not_selected"])
def test_review_runtime_unknown_or_blocked_never_makes_current_input_pass(ports, state):
    ports["runtime"].update(state=state, codes=["PACKAGE_REVIEW_NOT_SELECTED"])
    if state == "not_selected":
        ports["runtime"].update(run_id=None, selected_input_digest=None, current_input_digest=None)
    result = inspect(ports)["manifest"]
    assert result["gates"]["current_input"]["state"] == (
        "blocked" if state == "blocked" else "unknown"
    )
    assert not result["allowed"]


def test_runtime_checks_exact_original_executor_input_without_provider_or_launch(monkeypatch):
    fixture = case()
    run = report(fixture)
    manifest = {"synthetic": "exact original native manifest"}
    run["input_digest"] = digest(manifest)
    called = []

    def observe(c, scope, frozen, prepared, body, *, worker):
        called.append((c, scope, frozen, prepared, body, worker))
        return SimpleNamespace(input_manifest=lambda: manifest)

    monkeypatch.setattr(preflight.review_admission, "_observe", observe)
    result = preflight._runtime("readonly", {"review_run": run})
    assert result["state"] == "matched"
    assert called[0][-1] is False
    assert called[0][1] == tuple(
        run["scope"][key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    )
    run["input_digest"] = "0" * 64
    changed = preflight._runtime("readonly", {"review_run": run})
    assert changed["state"] == "blocked" and changed["codes"] == [
        "PACKAGE_REVIEW_RUNTIME_INPUT_CHANGED"
    ]


@pytest.mark.parametrize("status", [404, 409, 422, 500, 503])
def test_runtime_business_blockers_are_preserved_and_integrity_failures_propagate(
    monkeypatch, status
):
    def rejected(*_args, **_kwargs):
        raise DomainError("PACKAGE_SCOPE_SYNTHETIC_BLOCK", "synthetic", status)

    monkeypatch.setattr(preflight.review_admission, "_observe", rejected)
    value = {"review_run": report(case())}
    if status >= 500:
        with pytest.raises(DomainError) as failure:
            preflight._runtime(None, value)
        assert failure.value.status == status
    else:
        result = preflight._runtime(None, value)
        assert result["state"] == "blocked" and result["codes"] == ["PACKAGE_SCOPE_SYNTHETIC_BLOCK"]
