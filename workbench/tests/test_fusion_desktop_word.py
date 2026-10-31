"""Offline lifecycle tests; never start Docker, Word, or a real executor."""

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import fusion_desktop_word as manager


@pytest.fixture
def group(tmp_path, monkeypatch):
    request = {
        "version": manager.compose.WORD_VERSION,
        "instance_id": "a" * 32,
        "name": "full_manager",
        "origin": "http://127.0.0.1:5189",
        "python_image": "python@sha256:" + "b" * 64,
        "web_image": "nginx@sha256:" + "c" * 64,
        "word": {
            "version": "word-conversion-installation/2",
            "image": "word@sha256:" + "d" * 64,
            "profiles": {"external": {}, "page": {}, "rich": {}},
        },
    }
    plan = {
        "deployment_id": "e" * 32,
        "name": request["name"],
        "origin": request["origin"],
        "images": {"python": request["python_image"], "web": request["web_image"]},
    }
    source_checks = []

    def validate(value, *, check_word_sources=True):
        assert value == request
        source_checks.append(check_word_sources)
        return value

    monkeypatch.setattr(manager.compose, "validate_request", validate)
    monkeypatch.setattr(manager.compose, "validate_public_plan", lambda value: None)
    ids = {service: str(index + 1) * 64 for index, service in enumerate(manager.SERVICES)}
    running = {identity: True for identity in ids.values()}
    processes, launches, commands = {}, [], []
    failures = {"start": None, "cleanup": False, "summary_error": None}

    def inspect(identity):
        service = next((service for service, current in ids.items() if identity == current), None)
        if service is None:
            raise manager.spec.ConfigurationError("DESKTOP_WORD_DOCKER_UNAVAILABLE")
        return {
            "Id": identity,
            "Running": running[identity],
            "User": "65532:65532",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "Mounts": [{"Type": "tmpfs", "Destination": "/tmp"}],
            "Labels": {
                "tender.desktop.instance": request["instance_id"],
                "tender.word.version": "word-conversion-execution/2",
                "tender.word.plan": manager.spec.digest(plan),
                "tender.word.deployment": plan["deployment_id"],
                "com.docker.compose.project": manager.compose.project(request),
                "com.docker.compose.service": service,
            },
        }

    def docker(arguments):
        commands.append(arguments)
        if arguments[:2] == ["container", "ls"]:
            assert "--no-trunc" in arguments
            assert (
                "label=com.docker.compose.project=" + manager.compose.project(request) in arguments
            )
            return ids[arguments[-1].removeprefix("label=com.docker.compose.service=")].encode()
        if arguments[:2] == ["container", "inspect"]:
            return json.dumps(inspect(arguments[-1])).encode()
        raise AssertionError(arguments)

    def launch(arguments, **kwargs):
        assert arguments[:4] == [manager.sys.executable, "-B", "-m", "deploy.word_execution_host"]
        assert kwargs["stdout"] == manager.subprocess.DEVNULL == kwargs["stderr"]
        assert "OWNER_DATABASE_DSN" not in kwargs["env"] and "HTTP_PROXY" not in kwargs["env"]
        assert kwargs["env"]["WORKBENCH_ENV_FILE"]
        binding = manager._read(Path(arguments[arguments.index("--deployment-binding") + 1]))
        report = Path(arguments[arguments.index("--report-dir") + 1])
        stopfile = Path(arguments[arguments.index("--stop-file") + 1])
        assert not report.exists()
        report.mkdir()
        pid = 1000 + len(launches)
        peer = {"binding": binding, "pid": pid}
        ready = {
            "state": "ready",
            "container_id": binding["container_id"],
            "run_id": binding["instance_id"],
            "peer_mode": "deployment",
            "deployment_binding": binding,
            "pid": pid,
        }
        manager._write_new(report / "ready.json", ready)
        processes[pid] = "windows:" + str(pid)
        launches.append({"peer": peer, "report": report, "stop": stopfile, "kwargs": kwargs})
        if failures["start"] == binding["service"]:
            processes[pid] = None
            manager._write_new(
                report / "summary.json",
                {
                    "state": "failed",
                    "cleanup_closed": True,
                    "error_code": "WORD_EXECUTION_PEER_INVALID",
                },
            )
        return SimpleNamespace(pid=pid)

    def identity(pid):
        for item in launches:
            if item["peer"]["pid"] == pid and item["stop"].exists() and processes[pid] is not None:
                processes[pid] = None
                summary = {"state": "stopped", "cleanup_closed": not failures["cleanup"]}
                if failures["summary_error"]:
                    summary.update(state="failed", error_code=failures["summary_error"])
                manager._write_new(item["report"] / "summary.json", summary)
        return processes.get(pid)

    original_docker = manager._docker
    monkeypatch.setattr(manager, "_docker", docker)
    monkeypatch.setattr(manager.subprocess, "Popen", launch)
    monkeypatch.setattr(manager, "_process_identity", identity)
    monkeypatch.setattr(manager, "STOP_TIMEOUT", 0)
    monkeypatch.setenv("OWNER_DATABASE_DSN", "foreign")
    monkeypatch.setenv("HTTP_PROXY", "foreign")
    manager._READY_OBSERVATIONS.clear()
    return SimpleNamespace(
        path=tmp_path,
        request=request,
        plan=plan,
        ids=ids,
        running=running,
        processes=processes,
        launches=launches,
        commands=commands,
        failures=failures,
        source_checks=source_checks,
        inspect=inspect,
        original_docker=original_docker,
    )


def test_start_pins_two_unique_peers_and_is_idempotent_when_still_ready(group):
    result = manager.start(group.path, group.request, group.plan)
    assert result["ready"] and len(group.launches) == 2
    metadata = manager._metadata(group.path, group.request)
    assert all(
        metadata["peers"][service]["binding"]["container_id"] == group.ids[service]
        for service in manager.SERVICES
    )
    assert manager.start(group.path, group.request, group.plan)["ready"]
    assert len(group.launches) == 2
    assert True in group.source_checks and False in group.source_checks


@pytest.mark.parametrize("attack", ["reused_pid", "peer_stopped", "wrong_ready", "finished"])
def test_status_never_uses_pid_or_stale_ready_as_health(group, attack):
    manager.start(group.path, group.request, group.plan)
    first = group.launches[0]
    if attack == "reused_pid":
        group.processes[first["peer"]["pid"]] = "windows:99999"
    elif attack == "peer_stopped":
        group.running[group.ids["worker-document"]] = False
    elif attack == "wrong_ready":
        value = manager._read(first["report"] / "ready.json")
        value["deployment_binding"]["plan_digest"] = "f" * 64
        manager._save(first["report"] / "ready.json", value)
    else:
        manager._write_new(
            first["report"] / "summary.json", {"state": "stopped", "cleanup_closed": True}
        )
    assert manager.status(group.path, group.request)["state"] == "unavailable"
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_RESTART_REQUIRED"):
        manager.start(group.path, group.request, group.plan)
    assert len(group.launches) == 2


def test_normal_stop_is_idempotent_and_explicit_up_can_restart_same_exact_ids(group):
    manager.start(group.path, group.request, group.plan)
    generation = manager._metadata(group.path, group.request)["generation"]
    assert manager.stop(group.path, group.request)["cleanup_closed"]
    assert manager.stop(group.path, group.request)["state"] == "stopped"
    assert manager.start(group.path, group.request, group.plan)["ready"]
    assert len(group.launches) == 4
    assert (group.path / "word-executors" / generation / "metadata.json").is_file()


def test_changed_id_requires_explicit_restart_even_after_clean_stop(group):
    manager.start(group.path, group.request, group.plan)
    manager.stop(group.path, group.request)
    group.ids["worker-document"] = "9" * 64
    group.running["9" * 64] = True
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_RESTART_REQUIRED"):
        manager.start(group.path, group.request, group.plan)
    assert len(group.launches) == 2
    assert manager.restart(group.path, group.request, group.plan)["ready"]
    assert len(group.launches) == 4


def test_failed_second_start_stops_first_and_retains_failed_metadata(group):
    group.failures["start"] = "worker-export"
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_START_FAILED"):
        manager.start(group.path, group.request, group.plan)
    assert manager._metadata(group.path, group.request)["state"] == "failed"
    assert all(item["stop"].exists() for item in group.launches)
    assert group.processes[1000] is None
    assert manager.stop(group.path, group.request)["cleanup_closed"]
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_RESTART_REQUIRED"):
        manager.start(group.path, group.request, group.plan)


def test_unclean_receipt_prevents_restart_and_does_not_remove_metadata(group):
    manager.start(group.path, group.request, group.plan)
    group.failures["cleanup"] = True
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_CLEANUP_UNCONFIRMED"):
        manager.restart(group.path, group.request, group.plan)
    assert (group.path / manager.METADATA).exists()
    assert len(group.launches) == 2


@pytest.mark.parametrize("observed", [True, False])
def test_planned_peer_exit_is_narrowly_reported_not_disguised_as_normal_host_success(
    group, observed
):
    manager.start(group.path, group.request, group.plan)
    if not observed:
        manager._READY_OBSERVATIONS.clear()
    for item in group.launches:
        group.processes[item["peer"]["pid"]] = None
        group.running[item["peer"]["binding"]["container_id"]] = False
        manager._write_new(
            item["report"] / "summary.json",
            {
                "state": "failed",
                "error_code": "WORD_EXECUTION_PEER_INVALID",
                "cleanup_closed": True,
            },
        )
    result = manager.stop(group.path, group.request, peers_stopped=True)
    assert result["cleanup_closed"]
    assert result["state"] == ("stopped" if observed else "unavailable")
    assert all(peer["summary"]["state"] == "failed" for peer in result["peers"].values())
    assert all(
        peer["peer_exited_during_planned_stop"] is observed for peer in result["peers"].values()
    )


@pytest.mark.parametrize("attack", ["extra", "generation", "service", "pid", "identity", "binding"])
def test_metadata_paths_and_process_identity_are_closed(group, attack):
    manager.start(group.path, group.request, group.plan)
    value = manager._metadata(group.path, group.request)
    if attack == "extra":
        value["report_dir"] = "foreign"
    elif attack == "generation":
        value["generation"] = "../outside"
    elif attack == "service":
        value["peers"]["api"] = value["peers"].pop("worker-document")
    elif attack == "pid":
        value["peers"]["worker-document"]["pid"] = True
    elif attack == "identity":
        value["peers"]["worker-document"]["process_identity"] = "untrusted"
    else:
        value["peers"]["worker-document"]["binding"]["deployment_id"] = "f" * 32
    manager._save(group.path / manager.METADATA, value)
    with pytest.raises(manager.spec.ConfigurationError):
        manager.status(group.path, group.request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Running", False),
        ("User", "0:0"),
        ("Privileged", True),
        ("ReadonlyRootfs", False),
        ("Mounts", [{"Type": "bind", "Source": "/var/run/docker.sock"}]),
    ],
)
def test_peer_isolation_is_checked_before_launch(group, monkeypatch, field, value):
    original = manager._docker

    def docker(arguments):
        if arguments[:2] == ["container", "inspect"]:
            item = group.inspect(arguments[-1])
            item[field] = value
            return json.dumps(item).encode()
        return original(arguments)

    monkeypatch.setattr(manager, "_docker", docker)
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_PEER_INVALID"):
        manager.start(group.path, group.request, group.plan)
    assert group.launches == []


def test_nonunique_compose_peer_refuses_before_spawn(group, monkeypatch):
    monkeypatch.setattr(manager, "_docker", lambda args: b"1" * 64 + b"\n" + b"2" * 64)
    with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_PEER_NOT_UNIQUE"):
        manager.start(group.path, group.request, group.plan)
    assert not group.launches


def test_peer_lookup_uses_builtin_commands_without_user_home_or_compose_plugin(group, monkeypatch):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return manager.subprocess.CompletedProcess(arguments, 0, b"a" * 64, b"")

    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setattr(manager, "_docker", group.original_docker)
    monkeypatch.setattr(manager.subprocess, "run", run)
    assert manager._discover(group.path, group.request, "worker-document") == "a" * 64
    arguments, options = calls[0]
    assert arguments[3:5] == ["container", "ls"]
    assert "label=com.docker.compose.project=" + manager.compose.project(group.request) in arguments
    assert "label=com.docker.compose.service=worker-document" in arguments
    assert "HOME" not in options["env"] and "USERPROFILE" not in options["env"]


def test_status_and_stop_do_not_require_current_source_qualification(group, monkeypatch):
    manager.start(group.path, group.request, group.plan)

    def validate(value, *, check_word_sources=True):
        if check_word_sources:
            raise manager.spec.ConfigurationError("SOURCE_DRIFT")
        return value

    monkeypatch.setattr(manager.compose, "validate_request", validate)
    assert manager.status(group.path, group.request)["ready"]
    assert manager.stop(group.path, group.request)["cleanup_closed"]
    with pytest.raises(manager.spec.ConfigurationError, match="SOURCE_DRIFT"):
        manager.start(group.path, group.request, group.plan)


def test_record_reader_rejects_duplicate_keys_links_and_oversize(tmp_path, monkeypatch):
    path = tmp_path / "record.json"
    path.write_bytes(b'{"a":1,"a":2}')
    with pytest.raises(manager.spec.ConfigurationError):
        manager._read(path)
    path.write_bytes(b" " * 65537)
    with pytest.raises(manager.spec.ConfigurationError):
        manager._read(path)
    # Windows managed workspace prohibits creating hardlinks; exercise the
    # actual nlink rejection predicate without granting link-creation rights.
    original = Path.lstat
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "lstat",
            lambda item: SimpleNamespace(st_mode=0o100600, st_nlink=2, st_size=2)
            if item == path
            else original(item),
        )
        with pytest.raises(manager.spec.ConfigurationError):
            manager._read(path)


def test_real_os_creation_identity_distinguishes_live_controller_from_nonexistent_pid():
    current = manager._process_identity(os.getpid())
    assert isinstance(current, str) and current.startswith(("windows:", "linux:"))
    assert manager._process_identity(2147483647) is None


@pytest.mark.parametrize("has_ready", [True, False])
def test_interrupted_spawn_before_pid_save_is_recovered_only_from_exact_ready(
    group, monkeypatch, has_ready
):
    save = manager._save
    interrupted_once = []

    def interrupted(path, value):
        if not interrupted_once and any(
            peer["launcher_pid"] is not None and peer["pid"] is None
            for peer in value["peers"].values()
        ):
            interrupted_once.append(True)
            if not has_ready:
                (group.launches[-1]["report"] / "ready.json").unlink()
            raise KeyboardInterrupt()
        return save(path, value)

    monkeypatch.setattr(manager, "_save", interrupted)
    with pytest.raises(KeyboardInterrupt):
        manager.start(group.path, group.request, group.plan)
    assert len(group.launches) == 1
    result = manager.stop(group.path, group.request)
    assert result["cleanup_closed"] is has_ready
    peer = manager._metadata(group.path, group.request)["peers"]["worker-document"]
    assert (peer["pid"] is not None) is has_ready


def test_known_popen_failure_stops_other_started_peer_without_claiming_unknown_process(
    group, monkeypatch
):
    launch = manager.subprocess.Popen

    def failure(*args, **kwargs):
        if len(group.launches) == 1:
            raise OSError("synthetic process creation failure")
        return launch(*args, **kwargs)

    monkeypatch.setattr(manager.subprocess, "Popen", failure)
    with pytest.raises(OSError):
        manager.start(group.path, group.request, group.plan)
    assert len(group.launches) == 1 and group.processes[1000] is None
    assert manager.stop(group.path, group.request)["cleanup_closed"]
    assert manager._metadata(group.path, group.request)["state"] == "failed"


def test_unavailable_observation_revokes_historical_planned_stop_qualification(group):
    manager.start(group.path, group.request, group.plan)
    for item in group.launches:
        group.processes[item["peer"]["pid"]] = None
        group.running[item["peer"]["binding"]["container_id"]] = False
        manager._write_new(
            item["report"] / "summary.json",
            {
                "state": "failed",
                "error_code": "WORD_EXECUTION_PEER_INVALID",
                "cleanup_closed": True,
            },
        )
    assert not manager.status(group.path, group.request)["ready"]
    result = manager.stop(group.path, group.request, peers_stopped=True)
    assert result["state"] == "unavailable" and result["cleanup_closed"]
    assert not any(peer["peer_exited_during_planned_stop"] for peer in result["peers"].values())


def test_manager_lock_rejects_second_operator_without_launching(group):
    with manager._exclusive(group.path):
        with pytest.raises(manager.spec.ConfigurationError, match="DESKTOP_WORD_MANAGER_BUSY"):
            manager.start(group.path, group.request, group.plan)
    assert not group.launches


def test_unrecorded_launcher_is_not_claimed_from_ready_pid_alone(group, monkeypatch):
    launch = manager.subprocess.Popen

    def interrupted(*args, **kwargs):
        launch(*args, **kwargs)
        raise KeyboardInterrupt()

    monkeypatch.setattr(manager.subprocess, "Popen", interrupted)
    with pytest.raises(KeyboardInterrupt):
        manager.start(group.path, group.request, group.plan)
    assert manager.stop(group.path, group.request)["cleanup_closed"] is False


@pytest.mark.parametrize("attack", ["foreign_parent", "predates_launcher", "reused_launcher"])
def test_ready_pid_must_be_verified_launcher_or_its_new_direct_child(group, monkeypatch, attack):
    peer = {"launcher_pid": 1000, "launcher_identity": "windows:1000"}
    tokens = {1000: "windows:1000", 2000: "windows:2000"}
    parent = 1000
    if attack == "foreign_parent":
        parent = 9999
    elif attack == "predates_launcher":
        tokens[2000] = "windows:999"
    else:
        tokens[1000] = "windows:3000"
    monkeypatch.setattr(manager, "_process_identity", tokens.get)
    monkeypatch.setattr(manager, "_parent_pid", lambda pid: parent)
    assert manager._lineage(peer, 2000) is None


def test_real_venv_launcher_and_actual_interpreter_have_verified_identity(tmp_path):
    ready = tmp_path / "actual-pid.json"
    stopfile = tmp_path / "stop"
    script = """
import json,os,pathlib,sys,time
ready,stop=map(pathlib.Path,sys.argv[1:])
ready.write_text(json.dumps({'pid':os.getpid()}))
deadline=time.monotonic()+10
while not stop.exists() and time.monotonic()<deadline:time.sleep(.02)
"""
    process = manager.subprocess.Popen(
        [manager.sys.executable, "-B", "-c", script, str(ready), str(stopfile)],
        stdout=manager.subprocess.DEVNULL,
        stderr=manager.subprocess.DEVNULL,
        creationflags=manager._creation_flags(),
    )
    try:
        launcher_identity = manager._process_identity(process.pid)
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        pid = manager._read(ready)["pid"]
        token = manager._lineage(
            {"launcher_pid": process.pid, "launcher_identity": launcher_identity}, pid
        )
        assert token is not None
        if pid != process.pid:
            assert manager._parent_pid(pid) == process.pid
        assert manager._process_identity(process.pid) == launcher_identity
        assert manager._process_identity(pid) == token
        manager._write_new(
            tmp_path / "identity.json",
            {
                "launcher_pid": process.pid,
                "launcher_identity": launcher_identity,
                "executor_pid": pid,
                "executor_identity": token,
                "executor_parent_pid": manager._parent_pid(pid),
                "lineage_verified": True,
            },
        )
    finally:
        stopfile.touch()
        assert process.wait(timeout=12) == 0
