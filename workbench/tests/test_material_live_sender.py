"""Synthetic native receipts plus original HTTP codec; no credentials or network."""

# ruff: noqa: F401,F811
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from test_material_execution_attempts import envelope, lane, owned, synthetic
from test_package_technical_material import Stream, judgment, response

from packages.model_governance import material_execution_attempts as execution
from packages.model_governance import material_live_sender as live


@pytest.fixture
def qualified(lane, monkeypatch):
    value = deepcopy(lane.grant.metadata)
    d = value["attempt"]["document"]
    d.update(
        version="material-execution-attempt/2",
        execution_mode="qualified_live",
        qualified_send_once_granted=d.pop("mechanism_send_once_granted"),
        execution_authorized=True,
    )
    r = value["reservation"]["document"]
    r.update(
        version="material-execution-reservation/2",
        execution_mode="qualified_live",
        fee_ledger_reserved=r.pop("mechanism_fee_ledger_reserved"),
    )
    value.update(attempt=envelope(d), reservation=envelope(r), send_current=True)
    lane.grant = execution._observation(value)
    lane.state["credentials"] = []
    lane.state["current"] = lane.grant
    monkeypatch.setattr(live, "audit", lambda c: None)
    monkeypatch.setattr(execution, "begin_attempt", lambda *a, **k: lane.grant)
    monkeypatch.setattr(execution, "read", lambda *a, **k: lane.state["current"])

    def settle(c, grant, submitted, **kwargs):
        lane.state["settled"].append(submitted)
        return submitted

    def credential(account):
        lane.state["credentials"].append(account)
        return "synthetic-test-key"

    async def transport(request):
        lane.state["posts"].append(request)
        return httpx.Response(200, stream=Stream(lane.state["raw"]))

    monkeypatch.setattr(execution, "settle", settle)
    lane.state["raw"] = response(judgment(lane.owned.bundle))
    lane.sender = live.Sender(
        r["account_id"],
        d["profile_id"],
        d["profile_digest"],
        credential,
        enabled=True,
        transport=httpx.MockTransport(transport),
    )
    return lane


def run(lane):
    return asyncio.run(
        live.execute(
            lane.owned.connection,
            lane.connection,
            lane.owned.bundle,
            lane.checked,
            sender=lane.sender,
            **lane.args,
        )
    )


def test_original_codec_known_usage_and_settlement(qualified):
    result = run(qualified)
    assert result.metadata["valid_slot"] is True
    assert result.metadata["billing_state"] == "usage_reported"
    assert len(qualified.state["posts"]) == len(qualified.state["settled"]) == 1
    assert len(qualified.state["credentials"]) == 1
    assert not result.metadata["formal_prediction_eligible"]
    assert "synthetic-test-key" not in repr(qualified.sender)


@pytest.mark.parametrize("change", ["disabled", "profile", "digest", "transport"])
def test_configuration_refuses_before_credentials_or_http(qualified, change):
    edits = {
        "disabled": {"enabled": False},
        "profile": {"profile_id": qualified.sender.account_id},
        "digest": {"profile_digest": "0" * 64},
        "transport": {"transport": object()},
    }
    qualified.sender = replace(qualified.sender, **edits[change])
    with pytest.raises(execution.MaterialExecutionError):
        run(qualified)
    assert not qualified.state["posts"] and not qualified.state["credentials"]
    assert not qualified.state["settled"]


@pytest.mark.parametrize("change", ["revoked", "expired", "account", "drift", "credential"])
def test_final_boundary_failure_never_sends_and_preserves_unknown_hold(qualified, change):
    current = deepcopy(qualified.grant.metadata)
    if change == "revoked":
        current["send_current"] = False
    elif change == "expired":
        d = qualified.grant.metadata["attempt"]["document"]
        d["send_until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    elif change == "account":
        qualified.sender = replace(qualified.sender, account_id=qualified.args["slot_id"])
    elif change == "drift":
        current["attempt"]["digest"] = "0" * 64
    else:

        def unavailable(account):
            raise RuntimeError("private diagnostic must not escape")

        qualified.sender = replace(qualified.sender, credential=unavailable)
    qualified.state["current"] = execution.AttemptObservation(current)
    result = run(qualified)
    assert not qualified.state["posts"]
    assert len(qualified.state["settled"]) == 1
    assert result.metadata["billing_state"] == "unknown"
    assert result.metadata["usage"] is None
    assert "private diagnostic" not in repr(result)


def test_unknown_billing_replay_never_resolves_key_or_resends(qualified):
    qualified.state["raw"] = b"{broken"
    first = run(qualified)
    assert first.metadata["billing_state"] == "unknown"
    qualified.grant.metadata["new_send"] = False
    again = run(qualified)
    assert again is qualified.grant
    assert len(qualified.state["posts"]) == len(qualified.state["credentials"]) == 1
    assert len(qualified.state["settled"]) == 1


def test_settlement_after_send_does_not_recheck_revoked_qualification(qualified):
    async def transport(request):
        qualified.state["posts"].append(request)
        qualified.state["current"].metadata["send_current"] = False
        return httpx.Response(200, stream=Stream(qualified.state["raw"]))

    qualified.sender = replace(qualified.sender, transport=httpx.MockTransport(transport))
    assert run(qualified).metadata["billing_state"] == "usage_reported"
    assert len(qualified.state["settled"]) == 1


@pytest.mark.parametrize("part", ["attempt", "reservation"])
def test_mixed_receipt_versions_fail_closed(qualified, part):
    value = deepcopy(qualified.grant.metadata)
    value[part]["document"]["version"] = "material-execution-" + part + "/1"
    value[part] = envelope(value[part]["document"])
    with pytest.raises(execution.MaterialExecutionError):
        execution._observation(value)


def test_lost_settlement_ack_does_not_send_twice(qualified, monkeypatch):
    def lost(*args, **kwargs):
        qualified.grant.metadata["new_send"] = False
        raise execution.MaterialExecutionError("ACK_UNCERTAIN")

    monkeypatch.setattr(execution, "settle", lost)
    with pytest.raises(execution.MaterialExecutionError, match="ACK_UNCERTAIN"):
        run(qualified)
    assert run(qualified) is qualified.grant
    assert len(qualified.state["posts"]) == len(qualified.state["credentials"]) == 1


def test_cancellation_leaves_inflight_and_replay_never_resends(qualified):
    async def cancelled(request):
        qualified.state["posts"].append(request)
        qualified.grant.metadata["new_send"] = False
        raise asyncio.CancelledError()

    qualified.sender = replace(qualified.sender, transport=httpx.MockTransport(cancelled))
    with pytest.raises(asyncio.CancelledError):
        run(qualified)
    assert not qualified.state["settled"]
    assert run(qualified) is qualified.grant
    assert len(qualified.state["posts"]) == 1


@pytest.mark.parametrize("financial", [None, "unknown", "in_flight"])
def test_worker_injected_ports_consume_original_sender_and_stop_unresolved(
    qualified, monkeypatch, financial
):
    from types import SimpleNamespace

    from test_material_execution_dispatch import idle, observation

    from packages.model_governance import material_execution_dispatch as dispatch
    from packages.model_governance import material_execution_runtime as runtime

    base = deepcopy(observation(mode="synthetic_mechanism").metadata)
    lease = base["lease"]["document"]
    lease.update(
        version="material-dispatch-lease/2", mode="qualified_live", origin="current_prebid"
    )
    base["lease"] = envelope(lease)
    record = dispatch._observation(base, "worker")
    connections = [idle() for _ in range(5)]
    ports = runtime.QualifiedPorts(
        qualified.owned.connection,
        *connections[1:],
        qualified.connection,
        "development_s3",
        lambda v: None,
        qualified.sender,
    )
    monkeypatch.setattr(dispatch, "claim_delivery", lambda *a, **k: record)
    monkeypatch.setattr(dispatch, "heartbeat", lambda *a, **k: record)
    monkeypatch.setattr(dispatch, "finish", lambda *a, **k: record)
    job = {
        "job_id": lease["job_id"],
        "material_input_digest": qualified.owned.bundle.metadata["digest"],
        "slots": [{"slot_id": qualified.args["slot_id"], "rule_id": qualified.args["rule_id"]}],
    }
    source = dict(
        financial_state=financial,
        source_current=True,
        job=envelope(job),
        preparation_profile_id="test",
        preparation_profile_digest="test",
        store_command_id="test",
        packet_digest="test",
        storage_record_digest="test",
        execution_profile_id=qualified.args["profile_id"],
        execution_profile_digest=qualified.args["expected_profile_digest"],
    )
    monkeypatch.setattr(dispatch, "owned_job", lambda *a, **k: dispatch.OwnedJob(source))
    monkeypatch.setattr(
        runtime.preparation,
        "claim",
        lambda *a, **k: SimpleNamespace(
            metadata={"document": {"lease_id": "test"}, "digest": "test"}
        ),
    )
    monkeypatch.setattr(runtime.preparation, "heartbeat", lambda *a, **k: None)

    async def restore(*args, **kwargs):
        return qualified.owned.bundle, qualified.checked

    monkeypatch.setattr(runtime.preflight, "restore_and_preflight", restore)

    def settled(c, grant, submitted, **kwargs):
        qualified.state["settled"].append(submitted)
        return execution.AttemptObservation({"job_balance": {"state": "completed"}})

    monkeypatch.setattr(execution, "settle", settled)
    result = asyncio.run(
        runtime.deliver(
            connections[0],
            lease["message"],
            expected_method_digest=dispatch.method_digest(),
            qualified_ports=ports,
        )
    )
    assert result.acknowledge
    assert len(qualified.state["posts"]) == (1 if financial is None else 0)
    assert len(qualified.state["settled"]) == (1 if financial is None else 0)


@pytest.mark.parametrize("filename", ["material_live_sender.py", "material_qualification_guard.py"])
def test_execution_profile_method_pins_sender_and_qualification_audit(monkeypatch, filename):
    from pathlib import Path

    before = execution.method_digest()
    original = Path.read_bytes

    def changed(path):
        content = original(path)
        return content + b"\n# changed implementation\n" if path.name == filename else content

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert execution.method_digest() != before
