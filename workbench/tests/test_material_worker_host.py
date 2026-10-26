"""Launcher injection contract only: no real DSN, key, broker or model request."""

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_material_execution_dispatch import idle, launcher, observation

from packages.model_governance import material_execution_dispatch as dispatch
from packages.model_governance import material_execution_runtime as runtime
from packages.model_governance import material_worker_host as host


@pytest.fixture
def lane(monkeypatch):
    config = dict(
        version="material-qualified-worker-config/1",
        enabled=True,
        account_id=str(uuid4()),
        execution_profile_id=str(uuid4()),
        execution_profile_digest="a" * 64,
        dispatch_method_digest=dispatch.method_digest(),
        storage_profile="development_s3",
        max_messages=2,
    )
    calls = []

    @contextmanager
    def connection(purpose):
        calls.append(("open", purpose))
        try:
            yield idle()
        finally:
            calls.append(("close", purpose))

    broker = SimpleNamespace(
        subscribe=lambda topic: calls.append(("subscribe", topic)),
        close=lambda: calls.append(("broker_close",)),
    )

    def credential(account):
        pytest.fail("launcher must not eagerly read a credential")

    injected = host.Host(
        connection,
        lambda: broker,
        credential,
        lambda x: None,
        httpx.MockTransport(lambda r: pytest.fail("no HTTP expected")),
    )

    def consume(c, b, **kwargs):
        assert b is broker
        assert kwargs["qualified_ports"].sender.profile_id == config["execution_profile_id"]
        runtime._validate_ports(c, kwargs["qualified_ports"], qualified=True)
        calls.append(("consume",))
        return runtime.DeliveryResult(observation(state="blocked", new=False), True)

    monkeypatch.setattr(runtime, "consume_once", consume)
    return SimpleNamespace(config=config, host=injected, calls=calls)


def test_bounded_launcher_assembles_all_separate_ports_and_closes(lane):
    result = host.run(lane.config, lane.host)
    assert result["ok"] and len(result["receipts"]) == 2
    assert [x[1] for x in lane.calls if x[0] == "open"] == list(host.PURPOSES)
    assert len([x for x in lane.calls if x[0] == "close"]) == 7
    assert ("broker_close",) in lane.calls
    assert all(x["send_authorized"] is False for x in result["receipts"])


@pytest.mark.parametrize(
    "change",
    [
        {"enabled": False},
        {"enabled": 1},
        {"account_id": "bad"},
        {"execution_profile_digest": "bad"},
        {"dispatch_method_digest": "0" * 64},
        {"max_messages": True},
        {"max_messages": 1001},
        {"storage_profile": "arbitrary_host"},
        {"secret": "forbidden"},
        {"approved": True},
    ],
)
def test_invalid_or_self_authorized_configuration_opens_nothing(lane, change):
    assert host.run(lane.config | change, lane.host)["ok"] is False
    assert not lane.calls


def test_absent_host_and_bad_transport_are_closed(lane):
    assert not host.run(lane.config)["ok"]
    assert not host.run(lane.config, replace(lane.host, transport=object()))["ok"]
    assert not lane.calls


def test_failure_closes_resources_and_never_echoes_secrets(lane, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("private-key private-dsn private-url")

    monkeypatch.setattr(runtime, "consume_once", failed)
    value = host.run(lane.config, lane.host)
    assert value == {"ok": False, "code": "QUALIFIED_WORKER_UNAVAILABLE"}
    assert len([x for x in lane.calls if x[0] == "close"]) == 7
    assert ("broker_close",) in lane.calls


def test_shared_connection_is_rejected_before_subscribe(lane):
    c = idle()

    @contextmanager
    def connect(purpose):
        yield c

    assert not host.run(lane.config, replace(lane.host, connection=connect))["ok"]
    assert not lane.calls


@pytest.mark.parametrize("kind", ["symlink", "oversize", "duplicate", "directory"])
def test_configuration_reader_is_bounded_and_no_follow(tmp_path, kind):
    path = tmp_path / "config.json"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = tmp_path / "target"
        target.write_text("{}")
        path.symlink_to(target)
    elif kind == "oversize":
        path.write_text(" " * 16385)
    else:
        path.write_text('{"enabled":true,"enabled":false}')
    with pytest.raises((OSError, ValueError)):
        host.read_config(path)


def test_cli_entry_uses_only_explicit_injected_host(lane, tmp_path, monkeypatch, capsys):
    module = launcher()
    path = tmp_path / "config.json"
    path.write_text(json.dumps(lane.config))
    monkeypatch.setattr(
        "sys.argv", ["worker", "--purpose", "worker", "--qualified-config", str(path)]
    )
    assert module.main() == 2
    assert not lane.calls
    assert module.main(injected_host=lane.host) == 0
    output = capsys.readouterr().out
    assert "QUALIFIED_WORKER_UNAVAILABLE" in output and "receipts" in output
    assert "credential" not in output and "profile_digest" not in output
