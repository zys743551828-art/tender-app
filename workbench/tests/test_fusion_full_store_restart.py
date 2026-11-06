"""Bounded readiness for the persisted object-store binding on restart."""

from __future__ import annotations

import importlib
import io
import sys
import types

import pytest
from botocore.exceptions import ClientError


@pytest.fixture
def initializer(monkeypatch):
    # fcntl is used by the Linux bootstrap, not by the store binding check.
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "fcntl", types.ModuleType("fcntl"))
    return importlib.import_module("deploy.fusion_full_init")


def error(status, code):
    return ClientError(
        {"ResponseMetadata": {"HTTPStatusCode": status}, "Error": {"Code": code}},
        "GetObject",
    )


class Store:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def list_buckets(self):
        return {}

    def head_bucket(self, **_kwargs):
        raise error(404, "NotFound")

    def create_bucket(self, **_kwargs):
        return {}

    def put_object(self, **_kwargs):
        return {}

    def get_object(self, **_kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return {"Body": io.BytesIO(response)}


def configure(initializer, monkeypatch, responses, *, times=None):
    client = Store(responses)
    monkeypatch.setattr(initializer.probe, "store_client", lambda _environment: client)
    monkeypatch.setattr(initializer, "store_environment", lambda *_args: {})
    monkeypatch.setattr(initializer.time, "sleep", lambda _seconds: None)
    if times is not None:
        ticks = iter(times)
        monkeypatch.setattr(initializer.time, "monotonic", lambda: next(ticks))
    return client


def check(initializer):
    initializer.initialize_store(
        {"plan": {"bucket": "synthetic"}},
        marker={"key": "binding", "bytes": b"marker"},
        create=False,
    )


def test_restart_waits_for_specific_internal_error_then_verifies_bytes(initializer, monkeypatch):
    client = configure(initializer, monkeypatch, [error(500, "InternalError"), b"marker"])
    check(initializer)
    assert client.calls == 2


@pytest.mark.parametrize("status,code", [(403, "AccessDenied"), (404, "NoSuchKey"), (500, "Other")])
def test_restart_does_not_retry_other_failures(initializer, monkeypatch, status, code):
    client = configure(initializer, monkeypatch, [error(status, code)])
    with pytest.raises(ClientError):
        check(initializer)
    assert client.calls == 1


def test_restart_stops_retrying_after_deadline(initializer, monkeypatch):
    client = configure(initializer, monkeypatch, [error(500, "InternalError")], times=[0, 0, 36])
    with pytest.raises(ClientError):
        check(initializer)
    assert client.calls == 1


def test_restart_still_rejects_wrong_marker(initializer, monkeypatch):
    configure(initializer, monkeypatch, [error(500, "InternalError"), b"wrong"])
    with pytest.raises(initializer.spec.ConfigurationError, match="FULL_OBJECT_BINDING_MISMATCH"):
        check(initializer)


def test_fresh_initialization_does_not_retry_internal_error(initializer, monkeypatch):
    client = configure(initializer, monkeypatch, [error(500, "InternalError")])
    with pytest.raises(ClientError):
        initializer.initialize_store(
            {"plan": {"bucket": "synthetic"}},
            marker={"key": "binding", "bytes": b"marker"},
            create=True,
        )
    assert client.calls == 1
