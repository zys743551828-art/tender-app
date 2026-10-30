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
from packages.authoring import prebuilt_generated, prebuilt_rich
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
    monkeypatch.setattr(prebuilt, "render", blocked)
    monkeypatch.setattr(prebuilt_generated, "render", blocked)
    monkeypatch.setattr(prebuilt_rich, "render", blocked)


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


def arguments(lane):
    if lane == "external":
        return {"source": b"synthetic-source", "profile": {}}
    if lane == "page":
        return {
            "source": b"synthetic-source",
            "snapshot": {},
            "producer_manifest": {},
            "profile": {},
        }
    return {"snapshot": {}, "materials": [], "profile": {}, "mode": "continuous"}


def result():
    return {
        "state": "succeeded",
        "coverage": "complete",
        "conversion_attempted": True,
        "error_code": None,
        "retryable": False,
        "gaps": [],
        "chain": {},
        "pdf": b"%PDF-synthetic",
    }


class Mailbox:
    def __init__(self, lane="external"):
        self.raw = codec._request(lane, arguments(lane), REQUEST)
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


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_allowlisted_lanes_use_existing_provider_and_host_owned_receipts(
    tmp_path, monkeypatch, lane
):
    value, mailbox = executor(tmp_path, monkeypatch, Mailbox(lane))
    calls = []

    def render(*args, receipt, **kwargs):
        calls.append((args, kwargs, receipt))
        assert receipt == value.receipts / REQUEST / f"conversion-{REQUEST}.json"
        receipt.write_text(json.dumps({"run_id": "d" * 32, "closed": True, "resources": []}))
        return result()

    selected = {"external": prebuilt, "page": prebuilt_generated, "rich": prebuilt_rich}[lane]
    monkeypatch.setattr(selected, "render", render)
    observed = value.poll_once()
    assert observed["state"] == "published" and observed["cleanup_closed"] is True
    assert codec.decode_response(mailbox.raw, mailbox.response)["pdf"] == b"%PDF-synthetic"
    assert len(calls) == 1
    assert sum(c[13] == "read" for c in mailbox.calls if c[0] == "exec") == 1
    if lane == "rich":
        assert calls[0][1] == {"mode": "continuous"}
    assert value.poll_once() is None and len(calls) == 1


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
    raw = codec._request("external", arguments("external"), identity)
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
    response = codec.encode_response(raw, result())
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
    response = codec.encode_response(raw, result())
    published = helper(
        "publish", identity, options={"token": token, "size": len(response)}, data=response
    )
    assert published.returncode == 0 and published.stdout == b"published"
    path = directory / "response.json"
    assert path.read_bytes() == response
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
