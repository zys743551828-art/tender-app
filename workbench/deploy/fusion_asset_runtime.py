"""Trusted local Compose controller; not wired into API/Worker execution.

Each original gets a freshly recreated named service. No document paths, Docker
arguments, credentials or image names are accepted from a rendering request.
"""

import hashlib
import json
import re
import subprocess  # nosec B404
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

from packages.model_governance import package_technical_assets as assets
from packages.model_governance import technical_png as png
from packages.parsing import page_asset_wire as wire

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "asset-renderer"
IMAGE = "tender-fusion-checks:py312"
WORKER = "/workspace/deploy/fusion_asset_worker.py"
MAX_TIMEOUT_MS = 40_000
MAX_STDERR = 8192
# This is the private container mount, never a host temporary directory.
CONTAINER_TMPFS = "/tmp"  # nosec B108
SOURCE_FILES = (
    "deploy/compose.fusion.yaml",
    "deploy/fusion.defaults.env",
    "deploy/fusion_asset_worker.py",
    "deploy/fusion_asset_runtime.py",
    "packages/parsing/page_asset_wire.py",
    "packages/model_governance/package_technical_assets.py",
    "packages/model_governance/technical_png.py",
    "packages/contracts/package_technical_assets.py",
    "packages/parsing/pdfium_guard.py",
    "packages/domain/review_identity.py",
)
ALLOWED_ENVIRONMENT = {
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "HOSTNAME",
    "GPG_KEY",
    "PYTHON_VERSION",
    "PYTHON_SHA256",
    "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "WORKBENCH_ENV_FILE",
}


class AssetRuntimeError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise AssetRuntimeError(code)


@dataclass(frozen=True, repr=False)
class IsolatedPageAssets:
    bundle: assets.PageAssetBundle
    execution_receipt: dict


def source_descriptor():
    return {
        "files": {name: png.digest_bytes((ROOT / name).read_bytes()) for name in SOURCE_FILES},
        "host_platform": sys.platform,
        "host_python": list(sys.version_info[:3]),
        "schema_validator": version("jsonschema"),
        "maximum_timeout_ms": MAX_TIMEOUT_MS,
    }


def source_digest():
    return png.digest_bytes(wire.canonical(source_descriptor()))


@contextmanager
def exclusive():
    directory = ROOT / ".local/fusion"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "asset-renderer.lock"
    with path.open("a+b") as lock:
        lock.seek(0, 2)
        if lock.tell() == 0:
            lock.write(b"1")
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fail("ASSET_RUNTIME_BUSY")
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class FusionAssetRuntime:
    def __init__(
        self, *, expected_image_id, expected_source_digest, hard_timeout_ms=MAX_TIMEOUT_MS
    ):
        if not isinstance(expected_image_id, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", expected_image_id
        ):
            fail("ASSET_IMAGE_ID_INVALID")
        if not isinstance(expected_source_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_source_digest
        ):
            fail("ASSET_SOURCE_ID_INVALID")
        if type(hard_timeout_ms) is not int or not 1 <= hard_timeout_ms <= MAX_TIMEOUT_MS:
            fail("ASSET_DEADLINE_INVALID")
        self.expected_image_id = expected_image_id
        self.expected_source_digest = expected_source_digest
        self.hard_timeout_ms = hard_timeout_ms

    def _command(self, arguments, *, timeout=20):
        try:
            result = subprocess.run(
                ["docker", *arguments], cwd=ROOT, capture_output=True, timeout=timeout, check=False
            )  # nosec B603 B607
        except (OSError, subprocess.TimeoutExpired):
            fail("ASSET_DOCKER_COMMAND_FAILED")
        if result.returncode or len(result.stdout) > 262144:
            fail("ASSET_DOCKER_COMMAND_FAILED")
        return result.stdout

    @staticmethod
    def _compose(arguments):
        return [
            "compose",
            "--project-name",
            "tender-fusion",
            "--file",
            str(ROOT / "deploy/compose.fusion.yaml"),
            "--env-file",
            str(ROOT / "deploy/fusion.defaults.env"),
            "--profile",
            "assets",
            *arguments,
        ]

    def _inspect(self, identity):
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            fail("ASSET_CONTAINER_ID_INVALID")
        return json.loads(self._command(["inspect", identity]))[0]

    def _check_project(self):
        identity = self._command(self._compose(["ps", "--all", "--quiet", "api"])).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            fail("ASSET_PROJECT_UNAVAILABLE")
        labels = json.loads(
            self._command(["inspect", "--format", "{{json .Config.Labels}}", identity])
        )
        working = (
            labels.get("com.docker.compose.project.working_dir", "")
            .replace("\\", "/")
            .rstrip("/")
            .casefold()
        )
        expected = str(ROOT / "deploy").replace("\\", "/").rstrip("/").casefold()
        if (
            labels.get("com.docker.compose.project") != "tender-fusion"
            or labels.get("com.docker.compose.service") != "api"
            or working != expected
        ):
            fail("ASSET_PROJECT_SCOPE_MISMATCH")

    def _check_container(self, info):
        config, host = info["Config"], info["HostConfig"]
        labels = config.get("Labels") or {}
        environment_names = {entry.split("=", 1)[0] for entry in config.get("Env", [])}
        if (
            info["Image"] != self.expected_image_id
            or config["User"] != "65532:65532"
            or labels.get("com.docker.compose.project") != "tender-fusion"
            or labels.get("com.docker.compose.service") != SERVICE
            or host["Privileged"]
            or not host["ReadonlyRootfs"]
            or host["NetworkMode"] != "none"
            or host["Memory"] != 1073741824
            or host["MemorySwap"] != 1073741824
            or host["NanoCpus"] != 1000000000
            or host["PidsLimit"] != 32
            or host.get("CapDrop") != ["ALL"]
            or host.get("CapAdd")
            or host.get("PidMode") not in ("", "private")
            or host.get("IpcMode") != "private"
            or host.get("UTSMode") not in ("", "private")
            or host.get("CgroupnsMode") != "private"
            or "no-new-privileges:true" not in host.get("SecurityOpt", [])
            or host.get("PortBindings")
            or environment_names - ALLOWED_ENVIRONMENT
            or set(host.get("Tmpfs", {})) != {CONTAINER_TMPFS}
        ):
            fail("ASSET_CONTAINER_NOT_ISOLATED")
        mounts = {row["Destination"]: row for row in info["Mounts"]}
        required = {
            "/workspace/" + name
            for name in SOURCE_FILES
            if name.startswith("packages/") or name == "deploy/fusion_asset_worker.py"
        }
        if set(mounts) - (required | {CONTAINER_TMPFS}) or not required <= set(mounts):
            fail("ASSET_CONTAINER_MOUNTS_INVALID")
        for destination in required:
            if mounts[destination]["Type"] != "bind" or mounts[destination]["RW"]:
                fail("ASSET_CONTAINER_MOUNTS_INVALID")
        if CONTAINER_TMPFS in mounts and mounts[CONTAINER_TMPFS]["Type"] != "tmpfs":
            fail("ASSET_CONTAINER_MOUNTS_INVALID")
        if not info["State"]["Running"]:
            fail("ASSET_CONTAINER_NOT_RUNNING")

    def _exchange(self, identity, arguments, data=b"", *, timeout_ms, maximum):
        argv = ["docker", "exec", "-i", identity, "python", "-I", WORKER, *arguments]
        try:
            process = subprocess.Popen(
                argv,
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )  # nosec B603
        except OSError:
            fail("ASSET_EXEC_START_FAILED")
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            process.wait(timeout=5)
            fail("ASSET_EXEC_PIPE_UNAVAILABLE")
        output, diagnostic = bytearray(), bytearray()
        overflow = threading.Event()

        def drain(stream, target, limit):
            try:
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        break
                    if len(target) + len(chunk) > limit:
                        overflow.set()
                        break
                    target.extend(chunk)
            except OSError:
                overflow.set()
            finally:
                stream.close()

        def upload():
            stream = process.stdin
            if stream is None:
                overflow.set()
                return
            try:
                view = memoryview(data)
                while view:
                    written = stream.write(view)
                    if not written:
                        raise OSError("closed input")
                    view = view[written:]
            except OSError:
                pass
            finally:
                stream.close()

        threads = [
            threading.Thread(target=drain, args=(process.stdout, output, maximum), daemon=True),
            threading.Thread(
                target=drain, args=(process.stderr, diagnostic, MAX_STDERR), daemon=True
            ),
            threading.Thread(target=upload, daemon=True),
        ]
        started = time.monotonic()
        for thread in threads:
            thread.start()
        error = None
        try:
            while process.poll() is None:
                if overflow.is_set():
                    error = "ASSET_EXEC_OUTPUT_LIMIT"
                    break
                if (time.monotonic() - started) * 1000 >= timeout_ms:
                    error = "ASSET_EXEC_WALL_TIMEOUT"
                    break
                time.sleep(0.01)
        finally:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                error = "ASSET_EXEC_CONTROL_UNCONFIRMED"
            for thread in threads:
                thread.join(timeout=2)
        if error or overflow.is_set() or any(thread.is_alive() for thread in threads):
            fail(error or "ASSET_EXEC_OUTPUT_LIMIT")
        if process.returncode:
            fail("ASSET_RENDER_REJECTED")
        return bytes(output)

    def _stop(self, identity):
        previous = self._inspect(identity)
        labels = previous["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != "tender-fusion"
            or labels.get("com.docker.compose.service") != SERVICE
        ):
            fail("ASSET_CLEANUP_SCOPE_MISMATCH")
        try:
            self._command(["stop", "--time", "2", identity], timeout=10)
        except AssetRuntimeError:
            self._command(["kill", identity], timeout=10)
        info = self._inspect(identity)
        if info["State"]["Running"] or info["State"]["Pid"] != 0:
            fail("ASSET_CLEANUP_UNCONFIRMED")
        return {
            "stopped_verified": True,
            "container_pid": 0,
            "oom_killed": info["State"]["OOMKilled"],
            "container_finished_at": info["State"]["FinishedAt"],
            "container_exit_code": info["State"]["ExitCode"],
            "was_running_before_stop": previous["State"]["Running"],
        }

    @contextmanager
    def _session(self):
        with exclusive():
            self._check_project()
            if source_digest() != self.expected_source_digest:
                fail("ASSET_RUNTIME_SOURCE_MISMATCH")
            image = (
                self._command(["image", "inspect", "--format", "{{.Id}}", IMAGE]).decode().strip()
            )
            if image != self.expected_image_id:
                fail("ASSET_RUNTIME_IMAGE_MISMATCH")
            try:
                self._command(
                    self._compose(["up", "--detach", "--no-deps", "--force-recreate", SERVICE]),
                    timeout=30,
                )
            except AssetRuntimeError:
                failed_identity = (
                    self._command(self._compose(["ps", "--all", "--quiet", SERVICE]))
                    .decode()
                    .strip()
                )
                if failed_identity:
                    self._stop(failed_identity)
                raise
            identity = (
                self._command(self._compose(["ps", "--all", "--quiet", SERVICE])).decode().strip()
            )
            receipt = {
                "container_id": identity,
                "image_id": image,
                "source_digest": self.expected_source_digest,
                "compose_project": "tender-fusion",
                "compose_service": SERVICE,
                "hard_timeout_ms": self.hard_timeout_ms,
            }
            completed = False
            try:
                info = self._inspect(identity)
                self._check_container(info)
                description = wire.load(
                    self._exchange(identity, ["--describe"], timeout_ms=10000, maximum=65536)
                )
                if (
                    not isinstance(description, dict)
                    or set(description)
                    != {
                        "version",
                        "uid",
                        "worker_source_digest",
                        "wire_source_digest",
                        "render_method_digest",
                        "crop_method_digest",
                        "render_descriptor",
                        "isolation",
                    }
                    or description.get("version") != "package-page-render-runtime/1"
                    or description.get("uid") != 65532
                    or description.get("worker_source_digest")
                    != png.digest_bytes((ROOT / "deploy/fusion_asset_worker.py").read_bytes())
                    or description.get("wire_source_digest")
                    != png.digest_bytes((ROOT / "packages/parsing/page_asset_wire.py").read_bytes())
                ):
                    fail("ASSET_WORKER_SOURCE_MISMATCH")
                host_descriptor = assets.render_descriptor()
                if any(
                    description["render_descriptor"].get(key) != host_descriptor[key]
                    for key in (
                        "source",
                        "guard_source",
                        "contract_source",
                        "canonical_source",
                        "codec_source",
                        "schema_digest",
                        "regions_schema_digest",
                    )
                ):
                    fail("ASSET_WORKER_SOURCE_MISMATCH")
                receipt["container_started_at"] = info["State"]["StartedAt"]
                expected_limits = {
                    "memory.max": "1073741824",
                    "memory.swap.max": "0",
                    "pids.max": "32",
                    "cpu.max": "100000 100000",
                    "no_new_privileges": True,
                    "seccomp_filter_active": True,
                    "effective_permitted_bounding_ambient_capabilities_zero": True,
                    "network_interfaces": ["lo"],
                    "read_only_source_files": 7,
                }
                if description.get("isolation") != expected_limits:
                    fail("ASSET_WORKER_KERNEL_LIMITS_UNAVAILABLE")
                wire.check(description["isolation"], wire.ISOLATION)
                receipt["observed_kernel_limits"] = description["isolation"]
                yield identity, description, receipt
                completed = True
            finally:
                receipt.update(self._stop(identity))
                if completed and (not receipt["was_running_before_stop"] or receipt["oom_killed"]):
                    fail("ASSET_RUNTIME_CHANGED_BEFORE_CLEANUP")
                if source_digest() != self.expected_source_digest:
                    fail("ASSET_RUNTIME_SOURCE_MISMATCH")
                receipt["source_fingerprint_checked_before_and_after"] = True

    def describe(self):
        with self._session() as (_, description, receipt):
            result = dict(description)
        return {**result, "execution_receipt": receipt}

    def render(
        self,
        data,
        *,
        document_version_id,
        expected_source_digest,
        expected_source_size,
        expected_render_method_digest,
        expected_crop_method_digest,
        regions,
    ):
        if (
            not isinstance(data, bytes)
            or type(expected_source_size) is not int
            or not 0 < len(data) <= wire.MAX_SOURCE_BYTES
            or len(data) != expected_source_size
            or png.digest_bytes(data) != expected_source_digest
        ):
            fail("ASSET_ORIGINAL_BYTES_MISMATCH")
        request = {
            "version": "package-page-render-request/1",
            "document_version_id": document_version_id,
            "source_digest": expected_source_digest,
            "source_byte_size": expected_source_size,
            "render_method_digest": expected_render_method_digest,
            "crop_method_digest": expected_crop_method_digest,
            "regions": regions,
        }
        wire.check(request, wire.request_schema())
        encoded = wire.pack(request, data)
        if len(encoded) > wire.MAX_WIRE_BYTES:
            fail("ASSET_REQUEST_TOO_LARGE")
        with self._session() as (identity, description, receipt):
            if (
                description["render_method_digest"] != expected_render_method_digest
                or description["crop_method_digest"] != expected_crop_method_digest
            ):
                fail("ASSET_WORKER_METHOD_MISMATCH")
            raw = self._exchange(
                identity, [], encoded, timeout_ms=self.hard_timeout_ms, maximum=wire.MAX_WIRE_BYTES
            )
        # Verification happens after the complete container namespace has stopped.
        response, payload = wire.unpack(raw)
        wire.check(response, wire.success_schema())
        blobs = wire.decode_blocks(response["blobs"], payload)
        bundle = assets.PageAssetBundle(response["manifest"], blobs)
        assets.verify_bundle(bundle, expected_manifest_digest=bundle.manifest["digest"])
        if any(
            bundle.manifest[key] != expected
            for key, expected in (
                ("document_version_id", document_version_id),
                ("source_digest", expected_source_digest),
                ("source_byte_size", expected_source_size),
                ("render_method_digest", expected_render_method_digest),
            )
        ):
            fail("ASSET_RESULT_BINDING_MISMATCH")
        actual_regions = [
            {key: row[key] for key in ("physical_page", "parent_image_digest", "rectangle")}
            for row in bundle.manifest["details"]
        ]
        if actual_regions != sorted(
            regions, key=lambda row: row["physical_page"]
        ) or bundle.manifest["crop_method_digest"] != (
            expected_crop_method_digest if regions else None
        ):
            fail("ASSET_RESULT_CROP_MISMATCH")
        receipt.update(
            {
                "version": "package-page-render-execution/1",
                "original_digest": expected_source_digest,
                "result_manifest_digest": bundle.manifest["digest"],
                "wire_result_digest": hashlib.sha256(raw).hexdigest(),
                "container_boundary_observed": True,
                "input_authority_granted": False,
                "visual_readability_verified": False,
                "formal_execution_authorized": False,
            }
        )
        wire.check(receipt, wire.execution_schema())
        return IsolatedPageAssets(bundle, receipt)
