"""Host mailbox boundaries with real codec and mocked Docker/provider ports.

Linux helper tests execute only the fixed stdlib program in a disposable test
container as UID 65532. They never execute Word, Docker, a model or a database.
"""

import importlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deploy import word_execution_host as host
from deploy import word_prebuilt_acceptance as acceptance
from packages.domain.errors import DomainError
from packages.word_intake import execution_transport as codec
from packages.word_intake import prebuilt

REAL_RUN = subprocess.run
PEER = "a" * 64
RUN = "b" * 32
REQUEST = "c" * 32
TOKEN = {"job": [1, 2], "request": [1, 3, 5, 6, 7]}


@pytest.fixture(autouse=True)
def no_real_docker(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must not invoke Docker/providers")

    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(prebuilt, "convert_in_isolation", blocked)


def peer():
    return {
        "Id": PEER,
        "Running": True,
        "User": "65532:65532",
        "Privileged": False,
        "ReadonlyRootfs": True,
        "Tmpfs": {},
        "Labels": {"tender.test.run": RUN, "tender.test.disposable": "true"},
        "Mounts": [{"Type": "tmpfs", "Destination": "/tmp"}],
    }


def arguments():
    return {"source": b"synthetic-source", "requested_fonts": ["Arial"]}


def result():
    return {
        "pdf": b"%PDF-synthetic",
        "font_facts": {
            "matches": [{"requested": "Arial", "families": "Arial"}],
            "charset": "20-7e",
        },
        "isolation": {},
        "conversion_attempted": True,
        "error_code": None,
        "source_docx_digest": codec._sha(arguments()["source"]),
        "image_reference": prebuilt.IMAGE,
        "image_id": prebuilt.IMAGE_ID,
        "cleanup_confirmed": True,
    }


class Mailbox:
    def __init__(self):
        self.raw = codec._request(arguments(), REQUEST)
        self.metadata = peer()
        self.cancelled = False
        self.calls = []
        self.response = None
        self.filesystem_verified = True

    def invoke(self, command, *, data=None, timeout=60):
        self.calls.append(command)
        if command[0] == "container":
            assert command[-1] == PEER and "Env" not in command[3]
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.metadata).encode())
        assert command[:5] == ["exec", "--user", "65532:65532", "-i", PEER]
        assert command[5:11] == [
            "/usr/bin/env",
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8",
            "/usr/local/bin/python",
            "-I",
        ]
        action = command[13]
        if action == "verify":
            return SimpleNamespace(
                returncode=0 if self.filesystem_verified else 2,
                stdout=b"verified" if self.filesystem_verified else b"",
            )
        if action == "list":
            return SimpleNamespace(returncode=0, stdout=json.dumps(REQUEST).encode())
        assert command[14] == REQUEST
        if action == "read":
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(TOKEN).encode() + b"\n" + self.raw
            )
        assert action == "publish"
        if self.cancelled:
            return SimpleNamespace(returncode=3, stdout=b"")
        self.response = data
        return SimpleNamespace(returncode=0, stdout=b"published")


def executor(tmp_path, monkeypatch, mailbox=None):
    directory = tmp_path / "report"
    directory.mkdir()
    value = host.Executor(PEER, RUN, directory)
    mailbox = mailbox or Mailbox()
    monkeypatch.setattr(value, "_invoke", mailbox.invoke)
    return value, mailbox


def test_fixed_conversion_uses_only_existing_helper_and_host_owned_receipts(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)
    calls = []

    def convert(source, fonts, *, receipt):
        calls.append((source, fonts, receipt))
        assert receipt == value.receipts / REQUEST / f"conversion-{REQUEST}.json"
        receipt.write_text(json.dumps({"run_id": "d" * 32, "closed": True, "resources": []}))
        return result() | {"resource_receipt": {"closed": False, "receipts": []}}

    monkeypatch.setattr(prebuilt, "convert_in_isolation", convert)
    observed = value.poll_once()
    assert observed["state"] == "published" and observed["cleanup_closed"] is True
    decoded = codec.decode_response(mailbox.raw, mailbox.response)
    assert decoded["pdf"] == b"%PDF-synthetic"
    assert decoded["resource_receipt"]["closed"] is True
    assert len(calls) == 1 and calls[0][:2] == (arguments()["source"], ["Arial"])
    assert value.poll_once() is None and len(calls) == 1


@pytest.mark.parametrize("attack", ["missing_receipt", "unconfirmed"])
def test_raw_success_requires_real_closed_receipt(tmp_path, monkeypatch, attack):
    value, mailbox = executor(tmp_path, monkeypatch)

    def convert(request, receipt):
        if attack != "missing_receipt":
            receipt.write_text(json.dumps({"run_id": "d" * 32, "closed": True, "resources": []}))
        return result() | {"cleanup_confirmed": attack != "unconfirmed"}

    monkeypatch.setattr(value, "_dispatch", convert)
    observed = value.poll_once()
    assert observed["cleanup_closed"] is False
    with pytest.raises(DomainError) as error:
        codec.decode_response(mailbox.raw, mailbox.response)
    assert error.value.code == "WORD_EXECUTION_CLEANUP_UNCONFIRMED"


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "user",
        "label",
        "privileged",
        "writable",
        "socket",
        "socket_directory",
        "shadow_tmpfs",
        "tmpfs",
    ],
)
def test_peer_identity_and_isolation_rejected_before_source_read(tmp_path, monkeypatch, change):
    value, mailbox = executor(tmp_path, monkeypatch)
    if change == "id":
        mailbox.metadata["Id"] = "e" * 64
    elif change == "user":
        mailbox.metadata["User"] = "0:0"
    elif change == "label":
        mailbox.metadata["Labels"]["tender.test.run"] = "e" * 32
    elif change == "privileged":
        mailbox.metadata["Privileged"] = True
    elif change == "writable":
        mailbox.metadata["ReadonlyRootfs"] = False
    elif change == "socket_directory":
        mailbox.metadata["Mounts"].append(
            {"Type": "bind", "Source": "/var/run", "Destination": "/hidden"}
        )
    elif change == "shadow_tmpfs":
        mailbox.metadata["Mounts"].append(
            {"Type": "bind", "Source": "/other", "Destination": "/tmp/word-execution"}
        )
    elif change == "socket":
        mailbox.metadata["Mounts"].append(
            {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/hidden/socket"}
        )
    else:
        mailbox.metadata["Mounts"] = []
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.poll_once()
    assert all(c[0] == "container" for c in mailbox.calls)


def test_operator_and_caller_paths_cannot_select_peer_or_host_receipt(tmp_path, monkeypatch):
    with pytest.raises(host.HostError):
        host.Executor("short; docker ps", RUN, tmp_path)
    value, _ = executor(tmp_path, monkeypatch)
    with pytest.raises(host.HostError):
        value._mailbox("read", "../other")


def test_desktop_tmpfs_declaration_is_accepted_only_with_actual_filesystem_proof(
    tmp_path, monkeypatch
):
    value, mailbox = executor(tmp_path, monkeypatch)
    mailbox.metadata["Mounts"] = [{"Type": "bind", "Source": "/work/source", "Destination": "/app"}]
    mailbox.metadata["Tmpfs"] = {"/tmp": "rw,nosuid,nodev,size=512m,mode=1777"}
    value.inspect_peer()
    assert mailbox.calls[-1][13] == "verify"
    mailbox.filesystem_verified = False
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_TMPFS_INVALID"):
        value.inspect_peer()


def test_desktop_nested_tmpfs_declaration_cannot_shadow_mailbox(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)
    mailbox.metadata["Tmpfs"] = {"/tmp": "rw", "/tmp/word-execution": "rw"}
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.inspect_peer()


def test_request_cannot_inject_receipt_or_command(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)
    message = json.loads(mailbox.raw)
    message["arguments"]["receipt"] = "/tmp/unrelated"
    mailbox.raw = json.dumps(message).encode()
    with pytest.raises(host.HostError, match="WORD_EXECUTION_REQUEST_INVALID"):
        value.poll_once()
    assert mailbox.response is None


def test_cancelled_or_removed_mailbox_discards_finished_result(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)

    def render(request, receipt):
        receipt.write_text(json.dumps({"run_id": "d" * 32, "closed": True, "resources": []}))
        mailbox.cancelled = True
        return result()

    monkeypatch.setattr(value, "_dispatch", render)
    metadata = value.poll_once()
    assert metadata["state"] == "discarded" and metadata["cleanup_closed"] is True
    assert mailbox.response is None


def test_cleanup_failure_never_publishes_success(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)
    monkeypatch.setattr(value, "_dispatch", lambda request, receipt: result())
    monkeypatch.setattr(
        acceptance, "recover_conversion_receipts", lambda directory: [{"closed": False}]
    )
    metadata = value.poll_once()
    assert metadata["cleanup_closed"] is False and value.cleanup_closed is False
    with pytest.raises(DomainError) as error:
        codec.decode_response(mailbox.raw, mailbox.response)
    assert error.value.code == "WORD_EXECUTION_CLEANUP_UNCONFIRMED"


def test_interrupt_finishes_receipt_cleanup_and_never_publishes(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)

    def interrupted(request, receipt):
        receipt.write_text(json.dumps({"run_id": "d" * 32, "closed": False, "resources": []}))
        raise KeyboardInterrupt

    monkeypatch.setattr(value, "_dispatch", interrupted)
    with pytest.raises(KeyboardInterrupt):
        value.poll_once()
    assert value.cleanup_closed is True and mailbox.response is None
    record = json.loads(next(value.records.glob("*.json")).read_text())
    assert record["state"] == "cancelled" and record["cleanup_closed"] is True


def test_provider_exception_is_not_logged_or_echoed(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)

    def failed(*args):
        raise RuntimeError("private source and credential-shaped text")

    monkeypatch.setattr(value, "_dispatch", failed)
    value.poll_once()
    assert b"private source" not in mailbox.response
    assert "private source" not in next(value.records.glob("*.json")).read_text()
    with pytest.raises(DomainError) as error:
        codec.decode_response(mailbox.raw, mailbox.response)
    assert error.value.code == "WORD_EXECUTION_HOST_RENDER_FAILED"


def test_host_environment_is_allowlisted_and_import_does_not_clear_process(monkeypatch):
    original = {
        "PATH": "safe",
        "SystemRoot": "safe-system",
        "API_DATABASE_DSN": "secret",
        "MODEL_API_KEY": "secret",
        "HTTP_PROXY": "secret",
        "HOME": "secret",
        "PYTHONPATH": "secret",
    }
    assert host.clean_environment(original) == {"PATH": "safe", "SystemRoot": "safe-system"}
    monkeypatch.setenv("HOST_IMPORT_SENTINEL", "kept")
    importlib.reload(host)
    assert os.environ["HOST_IMPORT_SENTINEL"] == "kept"


def test_cli_sanitizes_before_constructing_executor(tmp_path, monkeypatch):
    captured = []

    class Stopped:
        cleanup_closed = True
        processed = 0

        def __init__(self, *args, **kwargs):
            captured.append(dict(os.environ))

        def ready_record(self):
            return {
                "state": "ready",
                "container_id": PEER,
                "run_id": RUN,
                "peer_mode": "test",
                "deployment_binding": None,
                "pid": os.getpid(),
            }

        def stopped(self):
            return True

        def inspect_peer(self):
            return None

        def cleanup(self):
            return True

    monkeypatch.setattr(
        host.os, "environ", {"PATH": "safe", "MODEL_API_KEY": "private", "HTTP_PROXY": "private"}
    )
    monkeypatch.setattr(host, "Executor", Stopped)
    monkeypatch.setattr(acceptance, "private_directory", lambda path: None)
    directory = tmp_path / "cli-report"
    assert host.main(["--container-id", PEER, "--run-id", RUN, "--report-dir", str(directory)]) == 0
    assert set(captured[0]) == {"PATH", "WORKBENCH_ENV_FILE", "PYTHONDONTWRITEBYTECODE"}
    assert not Path(captured[0]["WORKBENCH_ENV_FILE"]).exists()
    assert json.loads((directory / "ready.json").read_text())["container_id"] == PEER


@pytest.fixture
def linux_job():
    if not sys.platform.startswith("linux") or os.geteuid() != 65532:
        pytest.skip("fixed fd helper requires disposable Linux UID65532 test container")
    root = Path("/tmp/word-execution")
    root.mkdir(mode=0o700, exist_ok=True)
    assert not root.is_symlink() and stat.S_IMODE(root.stat().st_mode) == 0o700
    identity = uuid4().hex
    directory = root / identity
    directory.mkdir(mode=0o700)
    raw = codec._request(arguments(), identity)
    path = directory / "request.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    return identity, directory, raw


def helper(action, identity, *, options=None, data=None):
    command = [sys.executable, "-I", "-c", host.HELPER, action, identity]
    if options is not None:
        command.append(json.dumps(options))
    return REAL_RUN(
        command,
        input=data,
        capture_output=True,
        timeout=5,
        check=False,
        env=host.clean_environment(),
    )


def test_fixed_helper_verifies_actual_tmpfs_and_identity(linux_job):
    identity, _, _ = linux_job
    checked = helper("verify", identity)
    assert checked.returncode == 0 and checked.stdout == b"verified"


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "fifo", "oversize"])
def test_fixed_helper_rejects_nonregular_or_linked_request(linux_job, unsafe):
    identity, directory, raw = linux_job
    path = directory / "request.json"
    if unsafe == "symlink":
        target = directory / "other"
        target.write_bytes(raw)
        path.unlink()
        path.symlink_to(target)
    elif unsafe == "hardlink":
        os.link(path, directory / "alias")
    elif unsafe == "fifo":
        path.unlink()
        os.mkfifo(path, mode=0o600)
    else:
        with path.open("r+b") as stream:
            stream.truncate(codec.MAX_REQUEST_BYTES + 1)
    assert helper("read", identity).returncode == 2


@pytest.mark.parametrize("revocation", ["cancel", "directory_removed", "request_replaced"])
def test_fixed_helper_atomic_publication_checks_frozen_job(linux_job, revocation):
    identity, directory, raw = linux_job
    read = helper("read", identity)
    assert read.returncode == 0
    header, _, frozen = read.stdout.partition(b"\n")
    assert frozen == raw
    token = json.loads(header)
    if revocation == "cancel":
        path = directory / "cancel"
        path.touch(mode=0o600)
    elif revocation == "directory_removed":
        (directory / "request.json").unlink()
        directory.rmdir()
    else:
        (directory / "request.json").unlink()
        (directory / "request.json").write_bytes(raw)
        (directory / "request.json").chmod(0o600)
    response = codec.encode_response(
        raw, result() | {"resource_receipt": {"closed": True, "receipts": [{"closed": True}]}}
    )
    published = helper(
        "publish", identity, options={"token": token, "size": len(response)}, data=response
    )
    assert published.returncode == 3
    assert not (directory / "response.json").exists()


def test_fixed_helper_response_is_atomic_private_single_link(linux_job):
    identity, directory, raw = linux_job
    read = helper("read", identity)
    assert read.returncode == 0
    token = json.loads(read.stdout.partition(b"\n")[0])
    response = codec.encode_response(
        raw, result() | {"resource_receipt": {"closed": True, "receipts": [{"closed": True}]}}
    )
    published = helper(
        "publish", identity, options={"token": token, "size": len(response)}, data=response
    )
    assert published.returncode == 0 and published.stdout == b"published"
    path = directory / "response.json"
    assert path.read_bytes() == response
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1


def deployment_binding(service="worker-document"):
    return {
        "version": "word-execution-peer/2",
        "container_id": PEER,
        "instance_id": RUN,
        "deployment_id": "d" * 32,
        "project": "tender-fusion-full-" + RUN[:12],
        "service": service,
        "plan_digest": "e" * 64,
    }


def deployment_peer(binding):
    value = peer()
    value["Labels"] = {
        "tender.desktop.instance": binding["instance_id"],
        "tender.word.version": "word-conversion-execution/2",
        "tender.word.plan": binding["plan_digest"],
        "tender.word.deployment": binding["deployment_id"],
        "com.docker.compose.project": binding["project"],
        "com.docker.compose.service": binding["service"],
    }
    return value


def deployment_executor(tmp_path, monkeypatch, service="worker-document"):
    binding = deployment_binding(service)
    directory = tmp_path / "deployment-report"
    directory.mkdir()
    value = host.Executor(PEER, None, directory, deployment_binding=binding)
    mailbox = Mailbox()
    mailbox.metadata = deployment_peer(binding)
    monkeypatch.setattr(value, "_invoke", mailbox.invoke)
    return value, mailbox, binding


@pytest.mark.parametrize("service", ["worker-document", "worker-export"])
def test_deployment_peer_does_not_need_test_labels_and_cannot_rebind(
    tmp_path, monkeypatch, service
):
    value, mailbox, binding = deployment_executor(tmp_path, monkeypatch, service)
    value.inspect_peer()
    assert not any(k.startswith("tender.test.") for k in mailbox.metadata["Labels"])
    assert value.run_id == RUN and value.peer_mode == "deployment"
    assert value.ready_record() == {
        "state": "ready",
        "container_id": PEER,
        "run_id": RUN,
        "peer_mode": "deployment",
        "deployment_binding": binding,
        "pid": os.getpid(),
    }
    binding["plan_digest"] = "f" * 64
    returned = value.deployment_binding
    returned["plan_digest"] = "f" * 64
    value.inspect_peer()
    assert value.deployment_binding["plan_digest"] == "e" * 64


@pytest.mark.parametrize(
    "key,bad",
    [
        ("version", "old"),
        ("container_id", "short"),
        ("instance_id", "short"),
        ("deployment_id", "short"),
        ("plan_digest", "bad"),
        ("project", "tender-fusion-full-other"),
        ("service", "api"),
        ("service", "worker-review"),
        ("instance_id", 1),
        ("command", "id"),
        ("image", "other"),
        ("path", "/private"),
    ],
)
def test_deployment_binding_closed_schema_before_report_mutation(tmp_path, key, bad):
    value = deployment_binding()
    value[key] = bad
    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.Executor(PEER, None, tmp_path, deployment_binding=value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("removed", list(deployment_binding()))
def test_deployment_binding_all_identities_required(removed):
    value = deployment_binding()
    del value[removed]
    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.validate_deployment_binding(value)


def test_peer_modes_and_container_identity_are_mutually_bound(tmp_path):
    for args, code in [
        ((PEER, RUN), "WORD_EXECUTION_PEER_MODE_INVALID"),
        (("f" * 64, None), "WORD_EXECUTION_PEER_INVALID"),
    ]:
        with pytest.raises(host.HostError, match=code):
            host.Executor(*args, tmp_path, deployment_binding=deployment_binding())
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        host.Executor(PEER, None, tmp_path)


@pytest.mark.parametrize("expected", ["f" * 64, "short", 1])
def test_public_binding_validator_checks_optional_expected_container(expected):
    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.validate_deployment_binding(deployment_binding(), container_id=expected)
    assert (
        host.validate_deployment_binding(deployment_binding(), container_id=PEER)
        == deployment_binding()
    )


@pytest.mark.parametrize(
    "key",
    [
        "tender.desktop.instance",
        "tender.word.version",
        "tender.word.plan",
        "tender.word.deployment",
        "com.docker.compose.project",
        "com.docker.compose.service",
    ],
)
@pytest.mark.parametrize("attack", ["missing", "wrong"])
def test_deployment_labels_fail_closed_even_with_valid_test_labels(
    tmp_path, monkeypatch, key, attack
):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    mailbox.metadata["Labels"].update({"tender.test.run": RUN, "tender.test.disposable": "true"})
    if attack == "missing":
        del mailbox.metadata["Labels"][key]
    else:
        mailbox.metadata["Labels"][key] = "wrong"
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.poll_once()
    assert all(c[0] == "container" for c in mailbox.calls)


@pytest.mark.parametrize(
    "attack", ["id", "stopped", "uid", "readonly", "privileged", "socket", "tmpfs", "shadow"]
)
def test_deployment_mode_keeps_existing_isolation_guards(tmp_path, monkeypatch, attack):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    changes = {
        "id": ("Id", "f" * 64),
        "stopped": ("Running", False),
        "uid": ("User", "0:0"),
        "readonly": ("ReadonlyRootfs", False),
        "privileged": ("Privileged", True),
    }
    if attack in changes:
        key, bad = changes[attack]
        mailbox.metadata[key] = bad
    elif attack == "socket":
        mailbox.metadata["Mounts"].append(
            {"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/socket"}
        )
    elif attack == "tmpfs":
        mailbox.metadata["Mounts"] = []
    else:
        mailbox.metadata["Tmpfs"] = {"/tmp": "rw", "/tmp/word-execution": "rw"}
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.inspect_peer()


def test_deployment_actual_tmpfs_and_idle_peer_stop_are_rechecked(tmp_path, monkeypatch):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    mailbox.filesystem_verified = False
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_TMPFS_INVALID"):
        value.inspect_peer()
    mailbox.filesystem_verified = True
    monkeypatch.setattr(
        value, "_mailbox", lambda action, **kwargs: b"verified" if action == "verify" else b"null"
    )
    assert value.poll_once() is None
    mailbox.metadata["Running"] = False
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.poll_once()


def test_desktop_linux_sharing_path_accepts_only_readonly_code_bind(tmp_path, monkeypatch):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    mailbox.metadata["Mounts"].append(
        {
            "Type": "bind",
            "Source": "/run/desktop/mnt/host/c/project/workbench/packages",
            "Destination": "/workspace/packages",
            "RW": False,
        }
    )
    value.inspect_peer()


@pytest.mark.parametrize("observation", ["active", "stopped", "other_id", "unavailable"])
def test_mailbox_failure_is_peer_exit_only_after_exact_stopped_observation(
    tmp_path, monkeypatch, observation
):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)

    def unavailable(action):
        assert action == "verify"
        mailbox.metadata["Running"] = observation == "active"
        if observation == "other_id":
            mailbox.metadata["Id"] = "f" * 64
        elif observation == "unavailable":
            monkeypatch.setattr(
                value,
                "_invoke",
                lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=b""),
            )
        raise host.HostError("WORD_EXECUTION_MAILBOX_INVALID")

    monkeypatch.setattr(value, "_mailbox", unavailable)
    code = (
        "WORD_EXECUTION_PEER_INVALID"
        if observation == "stopped"
        else "WORD_EXECUTION_PEER_TMPFS_INVALID"
    )
    with pytest.raises(host.HostError, match=code):
        value.inspect_peer()


@pytest.mark.parametrize("action", ["verify", "list", "read", "publish"])
@pytest.mark.parametrize("stopped", [False, True])
def test_each_mailbox_operation_rechecks_exact_peer_after_exec_failure(
    tmp_path, monkeypatch, action, stopped
):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    mailbox.metadata["Running"] = not stopped
    original = value._invoke

    def invoke(arguments, **kwargs):
        if arguments[0] == "exec":
            return SimpleNamespace(returncode=1, stdout=b"")
        return original(arguments, **kwargs)

    monkeypatch.setattr(value, "_invoke", invoke)
    expected = "WORD_EXECUTION_PEER_INVALID" if stopped else "WORD_EXECUTION_MAILBOX_INVALID"
    with pytest.raises(host.HostError, match=expected):
        value._mailbox(
            action,
            RUN if action in {"read", "publish"} else None,
            token={"synthetic": True},
            data=b"synthetic",
        )


@pytest.mark.parametrize(
    "source,destination,writable",
    [
        ("/run/docker", "/workspace/packages", False),
        ("/var/run", "/workspace/packages", False),
        ("/run/desktop/mnt/host/c", "/workspace/packages", False),
        ("/run/desktop/mnt/host/c/project", "/outside-code", False),
        ("/run/desktop/mnt/host/c/project", "/workspace/packages", True),
        ("/run/desktop/mnt/host/c/../run", "/workspace/packages", False),
        ("/run/desktop/mnt/host/c/project/docker.sock", "/workspace/packages", False),
    ],
)
def test_desktop_share_exception_preserves_runtime_bind_guards(
    tmp_path, monkeypatch, source, destination, writable
):
    value, mailbox, _ = deployment_executor(tmp_path, monkeypatch)
    mailbox.metadata["Mounts"].append(
        {"Type": "bind", "Source": source, "Destination": destination, "RW": writable}
    )
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.inspect_peer()


def test_original_test_mode_never_accepts_deployment_labels_alone(tmp_path, monkeypatch):
    value, mailbox = executor(tmp_path, monkeypatch)
    mailbox.metadata = deployment_peer(deployment_binding())
    with pytest.raises(host.HostError, match="WORD_EXECUTION_PEER_INVALID"):
        value.inspect_peer()


@pytest.mark.parametrize(
    "attack",
    ["missing", "directory", "oversize", "duplicate", "invalid_utf8", "unknown", "changed"],
)
def test_binding_file_bounded_explicit_and_stable(tmp_path, monkeypatch, attack):
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(deployment_binding()), encoding="utf-8")
    if attack == "missing":
        path.unlink()
    elif attack == "directory":
        path.unlink()
        path.mkdir()
    elif attack == "oversize":
        path.write_bytes(b"x" * 16385)
    elif attack == "duplicate":
        path.write_bytes(b'{"version":1,"version":2}')
    elif attack == "invalid_utf8":
        path.write_bytes(b"\xff")
    elif attack == "unknown":
        path.write_text(json.dumps(deployment_binding() | {"url": "not allowed"}))
    else:
        original = host.os.fstat
        calls = [0]

        def changed(fd):
            calls[0] += 1
            if calls[0] == 2:
                path.write_bytes(b"changed")
            return original(fd)

        monkeypatch.setattr(host.os, "fstat", changed)
    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.load_deployment_binding(path)


def test_binding_file_read_is_readonly(tmp_path):
    path = tmp_path / "binding.json"
    raw = json.dumps(deployment_binding()).encode()
    path.write_bytes(raw)
    assert host.load_deployment_binding(path) == deployment_binding()
    assert path.read_bytes() == raw


@pytest.mark.parametrize("handle_changed", [False, True])
def test_binding_path_and_handle_ctime_are_checked_in_their_own_domains(
    tmp_path, monkeypatch, handle_changed
):
    from types import SimpleNamespace

    path = tmp_path / "binding.json"
    path.write_text(json.dumps(deployment_binding()), encoding="utf-8")
    original = host.os.fstat
    calls = 0

    def handle_stat(descriptor):
        nonlocal calls
        calls += 1
        value = original(descriptor)
        fields = {
            name: getattr(value, name)
            for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        }
        fields["st_ctime_ns"] = value.st_ctime_ns + 1000 + int(handle_changed and calls > 1)
        return SimpleNamespace(**fields)

    with monkeypatch.context() as patch:
        patch.setattr(host.os, "fstat", handle_stat)
        if handle_changed:
            with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
                host.load_deployment_binding(path)
        else:
            assert host.load_deployment_binding(path) == deployment_binding()


def test_binding_path_ctime_change_is_rejected_with_unchanged_handle(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "binding.json"
    path.write_text(json.dumps(deployment_binding()), encoding="utf-8")

    class OperatorPath:
        calls = 0

        def __fspath__(self):
            return str(path)

        def is_symlink(self):
            return False

        def lstat(self):
            self.calls += 1
            value = path.lstat()
            fields = {
                name: getattr(value, name)
                for name in ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
            }
            fields["st_ctime_ns"] = value.st_ctime_ns + int(self.calls > 1)
            return SimpleNamespace(**fields)

    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.load_deployment_binding(OperatorPath())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows symlink creation requires OS privilege; no system changes",
)
def test_binding_file_never_follows_symlink(tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps(deployment_binding()))
    link = tmp_path / "binding.json"
    link.symlink_to(target)
    with pytest.raises(host.HostError, match="WORD_EXECUTION_DEPLOYMENT_BINDING_INVALID"):
        host.load_deployment_binding(link)


@pytest.mark.parametrize(
    "arguments", [[], ["--run-id", RUN, "--deployment-binding", "binding.json"]]
)
def test_cli_requires_exactly_one_peer_mode(tmp_path, arguments):
    with pytest.raises(SystemExit) as error:
        host.main(["--container-id", PEER, "--report-dir", str(tmp_path / "report"), *arguments])
    assert error.value.code == 2


def test_cli_deployment_ready_contains_bound_peer_and_pid(tmp_path, monkeypatch):
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(deployment_binding()))
    mailbox = Mailbox()
    mailbox.metadata = deployment_peer(deployment_binding())
    monkeypatch.setattr(host.os, "environ", {"PATH": "safe", "MODEL_API_KEY": "private"})
    monkeypatch.setattr(
        host.Executor, "_invoke", lambda self, *args, **kwargs: mailbox.invoke(*args, **kwargs)
    )
    monkeypatch.setattr(host.Executor, "stopped", lambda self: True)
    monkeypatch.setattr(acceptance, "private_directory", lambda path: None)
    report = tmp_path / "cli-deployment"
    assert (
        host.main(
            ["--container-id", PEER, "--deployment-binding", str(path), "--report-dir", str(report)]
        )
        == 0
    )
    ready = json.loads((report / "ready.json").read_text())
    assert ready == {
        "state": "ready",
        "container_id": PEER,
        "run_id": RUN,
        "peer_mode": "deployment",
        "deployment_binding": deployment_binding(),
        "pid": os.getpid(),
    }
    assert "MODEL_API_KEY" not in host.os.environ


def test_cli_binding_container_mismatch_precedes_report_creation(tmp_path):
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(deployment_binding()))
    report = tmp_path / "no-report"
    assert (
        host.main(
            [
                "--container-id",
                "f" * 64,
                "--deployment-binding",
                str(path),
                "--report-dir",
                str(report),
            ]
        )
        == 2
    )
    assert not report.exists()
