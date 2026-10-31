"""Manage two explicitly pinned local full/2 Word executors; never rebind implicitly."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess  # nosec B404
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from deploy import fusion_desktop_compose as compose
from deploy import fusion_full_spec as spec
from deploy import word_execution_host as host

VERSION = "fusion-desktop-word-executors/2"
SERVICES = ("worker-document", "worker-export")
METADATA = "word-executors.json"
START_TIMEOUT = 45
STOP_TIMEOUT = 150
_HEX32 = re.compile(r"[a-f0-9]{32}\Z")
_HEX64 = re.compile(r"[a-f0-9]{64}\Z")
_READY_OBSERVATIONS: dict[tuple[str, str], tuple] = {}


def _fail(code):
    raise spec.ConfigurationError(code)


def _unlinked(path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            _fail("DESKTOP_WORD_PATH_INVALID")
        if item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            _fail("DESKTOP_WORD_PATH_INVALID")
    return path


def _root(path, request):
    path = Path(path).absolute()
    _unlinked(path)
    if ".." in path.parts or not path.is_dir():
        _fail("DESKTOP_WORD_PATH_INVALID")
    compose.validate_request(request, check_word_sources=False)
    if request["version"] != compose.WORD_VERSION:
        _fail("DESKTOP_WORD_REQUEST_INVALID")
    if os.name != "nt" and not sys.platform.startswith("linux"):
        _fail("DESKTOP_WORD_PLATFORM_UNSUPPORTED")
    _unlinked(path / METADATA)
    _unlinked(path / "word-executors")
    return path


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _read(path):
    _unlinked(path)
    descriptor = None
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= 65536
        ):
            raise ValueError()
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        )
        info = os.fstat(descriptor)
        if (
            (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not 0 < info.st_size <= 65536
        ):
            raise ValueError()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(65537)
        after = os.fstat(descriptor)
        # On Windows stat(path).ctime is creation time while fstat(fd).ctime can
        # be change time. Compare the same open inode before/after the read.
        if len(raw) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            raise ValueError()
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: _fail("DESKTOP_WORD_RECORD_INVALID"),
        )
    except (OSError, ValueError, UnicodeError):
        _fail("DESKTOP_WORD_RECORD_INVALID")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_new(path, value):
    _unlinked(path)
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as stream:
        stream.write(raw)


def _save(path, value):
    temporary = path.with_name(".word-executors-" + uuid4().hex + ".json")
    _write_new(temporary, value)
    try:
        _unlinked(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def _exclusive(path):
    lock = _unlinked(path / "word-executors.lock")
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    locked = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("DESKTOP_WORD_LOCK_INVALID")
        if info.st_size == 0:
            os.write(descriptor, b"1")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            _fail("DESKTOP_WORD_MANAGER_BUSY")
        yield
    finally:
        if locked:
            os.lseek(descriptor, 0, os.SEEK_SET)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _process_identity(pid):
    """Live process creation identity, not a PID or a saved ready marker alone."""
    if type(pid) is not int or pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            *([ctypes.POINTER(wintypes.FILETIME)] * 4),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 5:
                _fail("DESKTOP_WORD_PROCESS_UNVERIFIABLE")
            return None
        try:
            code = wintypes.DWORD()
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                return None
            return "windows:" + str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            if fields[0] in {"Z", "X"}:
                return None
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            return "linux:" + boot + ":" + fields[19]
        except PermissionError:
            _fail("DESKTOP_WORD_PROCESS_UNVERIFIABLE")
        except (OSError, ValueError, IndexError):
            return None
    _fail("DESKTOP_WORD_PLATFORM_UNSUPPORTED")


def _parent_pid(pid):
    """Query exactly one process, never enumerate processes or command lines."""
    if type(pid) is not int or pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class BasicInformation(ctypes.Structure):
            _fields_ = [
                ("ExitStatus", wintypes.LONG),
                ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_size_t),
                ("BasePriority", wintypes.LONG),
                ("UniqueProcessId", ctypes.c_size_t),
                ("InheritedFromUniqueProcessId", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        query.restype = wintypes.LONG
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            info = BasicInformation()
            length = wintypes.ULONG()
            if (
                query(handle, 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(length)) != 0
                or info.UniqueProcessId != pid
            ):
                return None
            return int(info.InheritedFromUniqueProcessId)
        finally:
            kernel.CloseHandle(handle)
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def _lineage(peer, pid):
    launcher = peer["launcher_pid"]
    expected = peer["launcher_identity"]
    if expected is None or _process_identity(launcher) != expected:
        return None
    token = _process_identity(pid)
    if token is None:
        return None
    if pid == launcher:
        return token if token == expected else None
    if _parent_pid(pid) != launcher:
        return None
    # Parent PID alone is insufficient after reuse; the child must belong to
    # the same OS boot and cannot predate the verified live launcher.
    parent_prefix, parent_time = expected.rsplit(":", 1)
    child_prefix, child_time = token.rsplit(":", 1)
    if child_prefix != parent_prefix or int(child_time) < int(parent_time):
        return None
    return token


def _docker(arguments):
    daemon = (
        "npipe:////./pipe/dockerDesktopLinuxEngine"
        if os.name == "nt"
        else "unix:///var/run/docker.sock"
    )
    # Fixed local daemon command; caller arguments never select executable/shell.
    result = subprocess.run(  # nosec B603
        ["docker", "--host", daemon, *arguments],
        cwd=compose.ROOT,
        env=host.clean_environment(),
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode or len(result.stdout) > 65536:
        _fail("DESKTOP_WORD_DOCKER_UNAVAILABLE")
    return result.stdout


def _creation_flags():
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _inspect(binding, *, running=True):
    value = json.loads(
        _docker(["container", "inspect", "--format", host._INSPECT, binding["container_id"]])
    )
    expected = {
        "tender.desktop.instance": binding["instance_id"],
        "tender.word.version": "word-conversion-execution/2",
        "tender.word.plan": binding["plan_digest"],
        "tender.word.deployment": binding["deployment_id"],
        "com.docker.compose.project": binding["project"],
        "com.docker.compose.service": binding["service"],
    }
    mounts = value.get("Mounts")
    if (
        value.get("Id") != binding["container_id"]
        or value.get("Running") is not running
        or value.get("User") != "65532:65532"
        or value.get("ReadonlyRootfs") is not True
        or value.get("Privileged") is not False
        or not isinstance(mounts, list)
        or not isinstance(value.get("Labels"), dict)
        or any(
            value["Labels"].get(key) != expected_value for key, expected_value in expected.items()
        )
        or any(
            re.search(r"\.sock(?:$|[/\\])|docker_engine", str(item.get(key, "")), re.I)
            for item in mounts
            for key in ("Source", "Destination")
        )
        or any(item.get("Type") == "npipe" for item in mounts)
    ):
        _fail("DESKTOP_WORD_PEER_INVALID")
    return value


def _metadata(path, request):
    value = _read(path / METADATA)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "instance_id",
            "generation",
            "deployment_id",
            "plan_digest",
            "state",
            "peers",
        }
        or value["version"] != VERSION
        or value["instance_id"] != request["instance_id"]
        or not isinstance(value["generation"], str)
        or not _HEX32.fullmatch(value["generation"])
        or not isinstance(value["deployment_id"], str)
        or not _HEX32.fullmatch(value["deployment_id"])
        or not isinstance(value["plan_digest"], str)
        or not _HEX64.fullmatch(value["plan_digest"])
        or value["state"] not in {"starting", "ready", "failed", "stopped"}
        or not isinstance(value["peers"], dict)
        or not set(value["peers"]) <= set(SERVICES)
    ):
        _fail("DESKTOP_WORD_METADATA_INVALID")
    for service, peer in value["peers"].items():
        if not isinstance(peer, dict) or set(peer) != {
            "binding",
            "pid",
            "process_identity",
            "was_ready",
            "launcher_pid",
            "launcher_identity",
        }:
            _fail("DESKTOP_WORD_METADATA_INVALID")
        binding = host.validate_deployment_binding(peer["binding"])
        if (
            binding["service"] != service
            or binding["instance_id"] != value["instance_id"]
            or binding["deployment_id"] != value["deployment_id"]
            or binding["plan_digest"] != value["plan_digest"]
            or (peer["pid"] is not None and (type(peer["pid"]) is not int or peer["pid"] <= 0))
            or (
                peer["process_identity"] is not None
                and (
                    type(peer["process_identity"]) is not str
                    or re.fullmatch(
                        r"windows:[0-9]+|linux:[a-f0-9-]{36}:[0-9]+", peer["process_identity"]
                    )
                    is None
                )
            )
            or type(peer["was_ready"]) is not bool
        ):
            _fail("DESKTOP_WORD_METADATA_INVALID")
        if (
            peer["launcher_pid"] is not None
            and (type(peer["launcher_pid"]) is not int or peer["launcher_pid"] <= 0)
        ) or (
            peer["launcher_identity"] is not None
            and (
                type(peer["launcher_identity"]) is not str
                or re.fullmatch(
                    r"windows:[0-9]+|linux:[a-f0-9-]{36}:[0-9]+", peer["launcher_identity"]
                )
                is None
            )
        ):
            _fail("DESKTOP_WORD_METADATA_INVALID")
    return value


def _paths(path, metadata, service):
    generation = _unlinked(path / "word-executors" / metadata["generation"])
    report = _unlinked(generation / service)
    return (
        report,
        _unlinked(generation / (service + "-peer.json")),
        _unlinked(generation / (service + ".stop")),
    )


def _ready(peer, record):
    binding = peer["binding"]
    return record == {
        "state": "ready",
        "container_id": binding["container_id"],
        "run_id": binding["instance_id"],
        "peer_mode": "deployment",
        "deployment_binding": binding,
        "pid": peer["pid"],
    }


def _peer_status(path, metadata, service, peer):
    report, _, _ = _paths(path, metadata, service)
    current_identity = _process_identity(peer["pid"])
    live = current_identity is not None and (
        peer["process_identity"] is None or current_identity == peer["process_identity"]
    )
    launcher_current = _process_identity(peer["launcher_pid"])
    launcher_live = launcher_current is not None and (
        peer["launcher_identity"] is None or launcher_current == peer["launcher_identity"]
    )
    ready = (report / "ready.json").exists() and _ready(peer, _read(report / "ready.json"))
    summary = _read(report / "summary.json") if (report / "summary.json").exists() else None
    try:
        _inspect(peer["binding"])
        peer_running = True
    except (spec.ConfigurationError, OSError, ValueError, TypeError):
        peer_running = False
    return {
        "container_id": peer["binding"]["container_id"],
        "pid": peer["pid"],
        "process_alive": live,
        "launcher_pid": peer["launcher_pid"],
        "launcher_alive": launcher_live,
        "peer_running": peer_running,
        "was_ready": peer["was_ready"],
        "ready_record_verified": ready,
        "summary": summary,
        "ready": live
        and launcher_live
        and peer["process_identity"] is not None
        and _lineage(peer, peer["pid"]) == peer["process_identity"]
        and peer_running
        and ready
        and summary is None,
    }


def status(path, request):
    path = _root(path, request)
    if not (path / METADATA).exists():
        return {"state": "not_started", "ready": False, "restart_required": False, "peers": {}}
    metadata = _metadata(path, request)
    peers = {
        service: _peer_status(path, metadata, service, peer)
        for service, peer in metadata["peers"].items()
    }
    ready = (
        metadata["state"] == "ready"
        and set(peers) == set(SERVICES)
        and all(peer["ready"] for peer in peers.values())
    )
    key = (str(path), metadata["generation"])
    if ready:
        _READY_OBSERVATIONS[key] = tuple(
            (
                service,
                metadata["peers"][service]["pid"],
                metadata["peers"][service]["process_identity"],
                metadata["peers"][service]["launcher_pid"],
                metadata["peers"][service]["launcher_identity"],
            )
            for service in SERVICES
        )
    else:
        _READY_OBSERVATIONS.pop(key, None)
    return {
        "state": "ready" if ready else "unavailable",
        "ready": ready,
        "restart_required": not ready,
        "peers": peers,
    }


def _touch(path):
    _unlinked(path)
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != 0:
            _fail("DESKTOP_WORD_STOP_FILE_INVALID")
    else:
        with path.open("xb"):
            pass


def _recover_launch(path, metadata, service, peer):
    """Only a matching ready record may identify an interrupted unsaved spawn."""
    if peer["pid"] is not None:
        return
    report, _, _ = _paths(path, metadata, service)
    if not (report / "ready.json").exists():
        return
    record = _read(report / "ready.json")
    pid = record.get("pid") if isinstance(record, dict) else None
    if type(pid) is not int or pid <= 0 or not _ready({**peer, "pid": pid}, record):
        _fail("DESKTOP_WORD_LAUNCH_RECOVERY_INVALID")
    token = _lineage(peer, pid)
    if token is not None:
        peer.update(pid=pid, process_identity=token, was_ready=True)
        _save(path / METADATA, metadata)
    elif pid == peer["launcher_pid"] and _process_identity(pid) is None:
        # A known Popen PID may already have exited. This cannot grant health;
        # only its closed final summary can later establish cleanup.
        peer["pid"] = pid
        _save(path / METADATA, metadata)


def _stop(path, request, *, peers_stopped):
    if not (path / METADATA).exists():
        return {"state": "not_started", "ready": False, "cleanup_closed": True, "peers": {}}
    metadata = _metadata(path, request)
    observation = _READY_OBSERVATIONS.pop((str(path), metadata["generation"]), None)
    expected_observation = (
        tuple(
            (
                service,
                metadata["peers"][service]["pid"],
                metadata["peers"][service]["process_identity"],
                metadata["peers"][service]["launcher_pid"],
                metadata["peers"][service]["launcher_identity"],
            )
            for service in SERVICES
        )
        if set(metadata["peers"]) == set(SERVICES)
        else None
    )
    for service in metadata["peers"]:
        _recover_launch(path, metadata, service, metadata["peers"][service])
        _, _, stopfile = _paths(path, metadata, service)
        _touch(stopfile)
    deadline = time.monotonic() + STOP_TIMEOUT
    while True:
        for service, peer in metadata["peers"].items():
            _recover_launch(path, metadata, service, peer)
        result = {
            service: _peer_status(path, metadata, service, peer)
            for service, peer in metadata["peers"].items()
        }
        pending_identity = any(peer["pid"] is None for peer in metadata["peers"].values())
        if (
            not pending_identity
            and not any(peer["process_alive"] or peer["launcher_alive"] for peer in result.values())
        ) or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    closed = acceptable = True
    planned = (
        peers_stopped
        and observation is not None
        and observation == expected_observation
        and all(peer["was_ready"] for peer in result.values())
    )
    if planned:
        try:
            for peer in metadata["peers"].values():
                _inspect(peer["binding"], running=False)
        except (spec.ConfigurationError, OSError, ValueError, TypeError):
            planned = False
    for service, peer in result.items():
        summary = peer["summary"]
        valid = (
            isinstance(summary, dict)
            and summary.get("cleanup_closed") is True
            and not peer["process_alive"]
            and not peer["launcher_alive"]
            and metadata["peers"][service]["pid"] is not None
        )
        normal = valid and summary.get("state") == "stopped"
        planned_exit = (
            valid
            and (planned or metadata["state"] == "stopped")
            and peer["was_ready"]
            and summary.get("state") == "failed"
            and summary.get("error_code") == "WORD_EXECUTION_PEER_INVALID"
        )
        peer["peer_exited_during_planned_stop"] = planned_exit
        peer["cleanup_closed"] = valid
        closed = closed and peer["cleanup_closed"]
        acceptable = acceptable and (normal or planned_exit)
    if closed and acceptable and metadata["state"] != "failed":
        metadata["state"] = "stopped"
        _save(path / METADATA, metadata)
    return {
        "state": "stopped" if closed and acceptable else "unavailable",
        "ready": False,
        "cleanup_closed": closed,
        "peers": result,
    }


def stop(path, request, peers_stopped=False):
    path = _root(path, request)
    with _exclusive(path):
        return _stop(path, request, peers_stopped=peers_stopped)


def _discover(path, request, service):
    raw = _docker(
        [
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=" + compose.project(request),
            "--filter",
            "label=com.docker.compose.service=" + service,
        ]
    )
    identities = raw.decode("ascii").split()
    if len(identities) != 1 or not _HEX64.fullmatch(identities[0]):
        _fail("DESKTOP_WORD_PEER_NOT_UNIQUE")
    return identities[0]


def _archive(path, metadata):
    archive = _unlinked(path / "word-executors" / metadata["generation"] / "metadata.json")
    _write_new(archive, metadata)
    (path / METADATA).unlink()


def _start(path, request, plan, expected_ids=None):
    compose.validate_request(request)
    compose.validate_public_plan(plan)
    if (
        plan["name"] != request["name"]
        or plan["origin"] != request["origin"]
        or plan["images"]["python"] != request["python_image"]
        or plan["images"]["web"] != request["web_image"]
    ):
        _fail("DESKTOP_WORD_PLAN_BINDING_INVALID")
    if (path / METADATA).exists():
        metadata = _metadata(path, request)
        if (
            metadata["plan_digest"] != spec.digest(plan)
            or metadata["deployment_id"] != plan["deployment_id"]
        ):
            _fail("DESKTOP_WORD_PLAN_BINDING_INVALID")
        current = status(path, request)
        if current["ready"]:
            return current
        if metadata["state"] == "stopped" and set(metadata["peers"]) == set(SERVICES):
            expected_ids = {
                service: metadata["peers"][service]["binding"]["container_id"]
                for service in SERVICES
            }
            if any(
                _discover(path, request, service) != expected_ids[service] for service in SERVICES
            ):
                _fail("DESKTOP_WORD_RESTART_REQUIRED")
            if _stop(path, request, peers_stopped=False)["cleanup_closed"]:
                _archive(path, _metadata(path, request))
                return _start(path, request, plan, expected_ids)
        _fail("DESKTOP_WORD_RESTART_REQUIRED")
    metadata = {
        "version": VERSION,
        "instance_id": request["instance_id"],
        "generation": uuid4().hex,
        "deployment_id": plan["deployment_id"],
        "plan_digest": spec.digest(plan),
        "state": "starting",
        "peers": {},
    }
    _write_new(path / METADATA, metadata)
    prepared_service = None
    process = None
    try:
        generation = _unlinked(path / "word-executors" / metadata["generation"])
        generation.mkdir(mode=0o700, parents=True)
        for service in SERVICES:
            prepared_service = None
            process = None
            identity = _discover(path, request, service)
            if expected_ids is not None and identity != expected_ids[service]:
                _fail("DESKTOP_WORD_RESTART_REQUIRED")
            binding = host.validate_deployment_binding(
                {
                    "version": "word-execution-peer/2",
                    "container_id": identity,
                    "instance_id": request["instance_id"],
                    "deployment_id": plan["deployment_id"],
                    "project": compose.project(request),
                    "service": service,
                    "plan_digest": metadata["plan_digest"],
                }
            )
            _inspect(binding)
            peer = {
                "binding": binding,
                "pid": None,
                "process_identity": None,
                "was_ready": False,
                "launcher_pid": None,
                "launcher_identity": None,
            }
            metadata["peers"][service] = peer
            prepared_service = service
            _save(path / METADATA, metadata)
            report, binding_path, stopfile = _paths(path, metadata, service)
            _write_new(binding_path, binding)
            environment = host.clean_environment()
            environment["WORKBENCH_ENV_FILE"] = "explicit-desktop-word-executor"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            # Fixed local module, no shell; each report directory is new.
            process = None
            process = subprocess.Popen(  # nosec B603
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "deploy.word_execution_host",
                    "--container-id",
                    binding["container_id"],
                    "--deployment-binding",
                    str(binding_path),
                    "--report-dir",
                    str(report),
                    "--stop-file",
                    str(stopfile),
                    "--poll-seconds",
                    "1",
                ],
                cwd=compose.ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creation_flags(),
            )
            peer["launcher_pid"] = process.pid
            peer["launcher_identity"] = _process_identity(process.pid)
            _save(path / METADATA, metadata)
            deadline = time.monotonic() + START_TIMEOUT
            while True:
                _recover_launch(path, metadata, service, peer)
                current = _peer_status(path, metadata, service, peer)
                if current["ready"]:
                    peer["was_ready"] = True
                    _save(path / METADATA, metadata)
                    break
                if (
                    not current["launcher_alive"]
                    or current["summary"] is not None
                    or time.monotonic() >= deadline
                ):
                    _fail("DESKTOP_WORD_START_FAILED")
                time.sleep(0.1)
        metadata["state"] = "ready"
        _save(path / METADATA, metadata)
        return status(path, request)
    except BaseException as error:
        if process is not None and prepared_service in metadata["peers"]:
            pending = metadata["peers"][prepared_service]
            if pending["launcher_pid"] is None:
                pending["launcher_pid"] = process.pid
                pending["launcher_identity"] = _process_identity(process.pid)
        # OSError from a failed Popen (or an earlier file operation) is known
        # not to have started the module. An interrupted spawn is uncertain and
        # retains its peer record for exact ready-record recovery instead.
        if (
            isinstance(error, OSError)
            and prepared_service in metadata["peers"]
            and metadata["peers"][prepared_service]["launcher_pid"] is None
            and process is None
        ):
            del metadata["peers"][prepared_service]
        metadata["state"] = "failed"
        _save(path / METADATA, metadata)
        _stop(path, request, peers_stopped=False)
        raise


def start(path, request, plan):
    path = _root(path, request)
    with _exclusive(path):
        return _start(path, request, plan)


def restart(path, request, plan):
    path = _root(path, request)
    with _exclusive(path):
        compose.validate_request(request)
        compose.validate_public_plan(plan)
        if (path / METADATA).exists():
            _metadata(path, request)
            result = _stop(path, request, peers_stopped=False)
            if not result["cleanup_closed"]:
                _fail("DESKTOP_WORD_CLEANUP_UNCONFIRMED")
            _archive(path, _metadata(path, request))
        return _start(path, request, plan)
