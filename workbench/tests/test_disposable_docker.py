"""Failed and cancelled runs clean only their own recorded resources."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from deploy.disposable_docker import DISPOSABLE_LABEL, RUN_LABEL, DockerTestRun


@pytest.mark.parametrize("failure", [None, RuntimeError("synthetic failure"), KeyboardInterrupt()])
def test_success_failure_and_cancel_cleanup_exact_ids(tmp_path, monkeypatch, failure):
    run = DockerTestRun(tmp_path / "receipt.json")
    calls = []
    objects = {}

    def call(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return SimpleNamespace(returncode=0, stdout='[{"Config":{"Volumes":{"/data":{}}}}]')
        if args[1] == "create":
            identity = f"{args[0]}-immutable-id"
            objects[identity] = {
                "Id": identity,
                "Labels": {RUN_LABEL: run.run_id, DISPOSABLE_LABEL: "true"},
            }
            return SimpleNamespace(returncode=0, stdout=identity)
        if args[1] == "inspect":
            return SimpleNamespace(returncode=0, stdout=json.dumps([objects[args[2]]]))
        if args[1] == "rm":
            objects.pop(args[-1])
            return SimpleNamespace(returncode=0)
        raise AssertionError(args)

    monkeypatch.setattr(run, "_call", call)
    try:
        with run:
            run.network()
            run.container("synthetic-pinned-local-image", ["--network", "none"])
            if failure:
                raise failure
    except BaseException as error:
        assert error is failure
    assert not objects
    assert [args[0] for args in calls if args[1] == "rm"] == ["container", "network"]
    assert all(args[-1].endswith("-immutable-id") for args in calls if args[1] == "rm")
    create = next(args for args in calls if args[:2] == ("container", "create"))
    assert "never" in create and "/data" in create and "--tmpfs" in create
    assert json.loads(run.receipt.read_text())["closed"] is True


def test_changed_ownership_is_never_deleted_and_receipt_stays_open(tmp_path, monkeypatch):
    run = DockerTestRun(tmp_path / "receipt.json")
    run.resources.append(
        {"kind": "container", "name": "recorded", "id": "old-id", "state": "created"}
    )
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='[{"Id":"old-id","Config":{"Labels":{}}}]')

    monkeypatch.setattr(run, "_call", call)
    with pytest.raises(RuntimeError, match="CLEANUP_INCOMPLETE"):
        run.cleanup()
    assert not any(args[1] == "rm" for args in calls)
    receipt = json.loads(run.receipt.read_text())
    assert receipt["closed"] is False
    assert receipt["resources"][0]["cleanup_error"] == "DOCKER_TEST_RESOURCE_OWNERSHIP_CHANGED"


def test_create_timeout_can_find_only_exact_new_name_and_ownership(tmp_path, monkeypatch):
    run = DockerTestRun(tmp_path / "receipt.json")
    removed = []

    def call(*args, **kwargs):
        if args[1] == "create":
            raise subprocess.TimeoutExpired("docker", 60)
        if args[1] == "inspect":
            assert args[2] == f"tender-test-{run.run_id[:12]}-1"
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Id": "created-before-timeout",
                            "Labels": {RUN_LABEL: run.run_id, DISPOSABLE_LABEL: "true"},
                        }
                    ]
                ),
            )
        removed.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run, "_call", call)
    with pytest.raises(subprocess.TimeoutExpired), run:
        run.network()
    assert removed == [("network", "rm", "created-before-timeout")]
    assert run.closed


@pytest.mark.parametrize(
    ("kind", "message", "absent"),
    [
        ("network", "Error response from daemon: network exact-id not found", True),
        ("container", "Error response from daemon: No such container: exact-id", True),
        ("volume", "Error response from daemon: get exact-id: no such volume", True),
        ("container", "Cannot connect: no such socket", False),
        ("network", "permission denied", False),
    ],
)
def test_absence_requires_exact_target_and_does_not_hide_access_failure(
    tmp_path, monkeypatch, kind, message, absent
):
    run = DockerTestRun(tmp_path / "receipt.json")
    resource = {"kind": kind, "name": "generated-name", "id": "exact-id", "state": "created"}
    monkeypatch.setattr(
        run, "_call", lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr=message)
    )
    if absent:
        assert run._owned(resource) is None
    else:
        with pytest.raises(RuntimeError, match="INSPECTION_FAILED"):
            run._owned(resource)


def test_unavailable_docker_keeps_a_recoverable_open_receipt(tmp_path, monkeypatch):
    run = DockerTestRun(tmp_path / "receipt.json")
    run.resources.append(
        {"kind": "container", "name": "generated-name", "id": "exact-id", "state": "created"}
    )

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("synthetic private installation details")

    monkeypatch.setattr(run, "_call", unavailable)
    with pytest.raises(RuntimeError, match="CLEANUP_INCOMPLETE"):
        run.cleanup()
    value = json.loads(run.receipt.read_text())
    assert value["closed"] is False
    assert value["resources"][0]["cleanup_error"] == "DOCKER_TEST_CLEANUP_FAILED"
    assert "private installation" not in run.receipt.read_text()
