"""Failure/cancellation receipt recovery; no Docker, PG, network or model calls."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from deploy import word_prebuilt_acceptance as entry
from packages.domain.errors import DomainError
from packages.word_intake import conversion, prebuilt


@pytest.fixture(autouse=True)
def no_external_resources(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No external process or Docker call in recovery unit tests")

    monkeypatch.setattr(entry.LocalRun, "_call", blocked)
    monkeypatch.setattr(prebuilt, "_call", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)


def receipt(directory, *, closed=False, pending=False):
    run_id = "a" * 32
    resource = {
        "kind": "container",
        "id": None if pending else "b" * 64,
        "name": f"tender-test-{run_id[:12]}-1",
        "state": "creating" if pending else "removed" if closed else "created",
    }
    path = directory / ("conversion-" + "c" * 32 + ".json")
    path.write_text(
        json.dumps({"run_id": run_id, "closed": closed, "resources": [resource]}), encoding="utf-8"
    )
    return path, resource


def docker_for(resource, *, wrong_label=False, missing=False):
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        assert args[-1] in {resource["id"], resource["name"], "b" * 64}
        if "inspect" in args:
            if missing:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr=f"No such container: {args[-1]}"
                )
            value = {
                "Id": resource["id"] or "b" * 64,
                "Config": {
                    "Labels": {
                        "tender.test.run": "wrong" if wrong_label else "a" * 32,
                        "tender.test.disposable": "true",
                    }
                },
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps([value]), stderr="")
        assert args[:3] == ("container", "rm", "--force")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return call, calls


@pytest.mark.parametrize("already_closed", [False, True])
def test_parent_recovers_exact_conversion_even_if_receipt_claimed_closed(
    tmp_path, monkeypatch, already_closed
):
    path, resource = receipt(tmp_path, closed=already_closed)
    call, calls = docker_for(resource)
    monkeypatch.setattr(entry.LocalRun, "_call", staticmethod(call))
    recovered = entry.recover_conversion_receipts(tmp_path)
    assert recovered[0]["closed"] is True
    assert calls == [
        ("container", "inspect", resource["id"]),
        ("container", "rm", "--force", resource["id"]),
    ]
    actual = json.loads(path.read_text())
    assert actual["closed"] is True and actual["resources"][0]["state"] == "removed"


def test_parent_refuses_changed_labels_and_reports_incomplete(tmp_path, monkeypatch):
    path, resource = receipt(tmp_path)
    call, calls = docker_for(resource, wrong_label=True)
    monkeypatch.setattr(entry.LocalRun, "_call", staticmethod(call))
    result = entry.recover_conversion_receipts(tmp_path)
    assert result[0]["closed"] is False
    assert not any("rm" in args for args in calls)
    assert json.loads(path.read_text())["closed"] is False


def test_pending_create_not_observed_is_uncertain_not_removed(tmp_path, monkeypatch):
    path, resource = receipt(tmp_path, pending=True)
    call, calls = docker_for(resource, missing=True)
    monkeypatch.setattr(entry.LocalRun, "_call", staticmethod(call))
    assert entry.recover_conversion_receipts(tmp_path)[0]["closed"] is False
    assert json.loads(path.read_text())["resources"][0]["state"] == "creating"
    assert calls == [("container", "inspect", resource["name"])]


def test_pending_create_observed_is_pinned_to_exact_id_before_cleanup(tmp_path, monkeypatch):
    path, resource = receipt(tmp_path, pending=True)
    call, calls = docker_for(resource)
    monkeypatch.setattr(entry.LocalRun, "_call", staticmethod(call))
    assert entry.recover_conversion_receipts(tmp_path)[0]["closed"] is True
    assert calls == [
        ("container", "inspect", resource["name"]),
        ("container", "inspect", "b" * 64),
        ("container", "rm", "--force", "b" * 64),
    ]
    actual = json.loads(path.read_text())
    assert actual["resources"][0]["id"] == "b" * 64
    assert actual["resources"][0]["state"] == "removed"


def test_malformed_receipt_does_not_touch_any_docker_resource(tmp_path):
    path, _ = receipt(tmp_path)
    record = json.loads(path.read_text())
    record["resources"][0]["name"] = "original-user-container"
    path.write_text(json.dumps(record))
    assert entry.recover_conversion_receipts(tmp_path)[0]["closed"] is False


@pytest.mark.parametrize("interrupted", [False, True])
def test_timeout_or_cancel_stops_owned_child_before_return(monkeypatch, interrupted):
    events = []

    class Child:
        pid = 123456
        returncode = None

        def poll(self):
            return self.returncode

        def send_signal(self, value):
            events.append("signal")

        def communicate(self, timeout):
            events.append("communicate")
            if len(events) == 1:
                if interrupted:
                    raise KeyboardInterrupt
                raise subprocess.TimeoutExpired("synthetic-owned-pytest", timeout)
            self.returncode = -2
            return "", ""

    if os.name != "nt":
        monkeypatch.setattr(os, "killpg", lambda pid, sig: events.append("signal"))
    child = Child()
    with pytest.raises(KeyboardInterrupt if interrupted else RuntimeError):
        entry.wait_test_process(child, timeout=1)
    assert child.poll() is not None
    assert events == ["communicate", "signal", "communicate"]


def test_conversion_persists_failed_cleanup_receipt_for_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_WORD_PREBUILT_PG", "1")
    monkeypatch.setenv("WORD_RENDER_TEST_RECEIPT_DIRECTORY", str(tmp_path))

    def render(source, profile, *, receipt):
        receipt.write_text(
            json.dumps({"run_id": "a" * 32, "closed": False, "resources": []}), encoding="utf-8"
        )
        return {"state": "failed", "coverage": "failed", "pdf": None}

    monkeypatch.setattr(prebuilt, "render", render)
    result = conversion.render(b"synthetic", {"identity": {"protocol": prebuilt.PROTOCOL}})
    assert result["state"] == "failed" and result["coverage"] == "failed"
    assert result["resource_receipt"]["closed"] is False
    assert len(list(tmp_path.glob("conversion-*.json"))) == 1


def test_persistent_receipts_require_explicit_disposable_test_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("RUN_WORD_PREBUILT_PG", raising=False)
    monkeypatch.setenv("WORD_RENDER_TEST_RECEIPT_DIRECTORY", str(tmp_path))
    with pytest.raises(DomainError) as error:
        conversion.render(b"synthetic", {"identity": {"protocol": prebuilt.PROTOCOL}})
    assert error.value.code == "WORD_TEST_RECEIPT_CONFIG_INVALID"
    assert not list(tmp_path.iterdir())
