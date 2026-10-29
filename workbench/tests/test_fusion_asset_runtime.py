"""Controller and wire fault guards; native Docker evidence is recorded separately."""

import io
import json
import subprocess
import sys

import pytest
import yaml

from deploy import fusion_asset_runtime as runtime
from packages.parsing import page_asset_wire as wire

IMAGE = "sha256:" + "a" * 64


def controller(**kwargs):
    return runtime.FusionAssetRuntime(
        expected_image_id=IMAGE, expected_source_digest="b" * 64, **kwargs
    )


@pytest.fixture
def info():
    return {
        "Image": IMAGE,
        "Config": {
            "User": "65532:65532",
            "Env": ["PATH=/usr/bin", "LANG=C.UTF-8"],
            "Labels": {
                "com.docker.compose.project": "tender-fusion",
                "com.docker.compose.service": "asset-renderer",
            },
        },
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "NetworkMode": "none",
            "Memory": 1073741824,
            "MemorySwap": 1073741824,
            "NanoCpus": 1000000000,
            "PidsLimit": 32,
            "CapDrop": ["ALL"],
            "CapAdd": [],
            "SecurityOpt": ["no-new-privileges:true"],
            "PortBindings": {},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=64m,uid=65532,gid=65532,mode=0700"},
            "PidMode": "",
            "IpcMode": "private",
            "UTSMode": "",
            "CgroupnsMode": "private",
        },
        "Mounts": [
            {"Destination": "/workspace/" + name, "Type": "bind", "RW": False}
            for name in runtime.SOURCE_FILES
            if name.startswith("packages/") or name == "deploy/fusion_asset_worker.py"
        ],
        "State": {"Running": True},
    }


def test_fixed_service_is_optional_and_has_only_current_renderer_code_mounts(info):
    service = yaml.safe_load((runtime.ROOT / "deploy/compose.fusion.yaml").read_text())["services"][
        "asset-renderer"
    ]
    assert service["profiles"] == ["assets"] and service["network_mode"] == "none"
    assert service["user"] == "65532:65532" and service["read_only"]
    assert (
        service["mem_limit"] == service["memswap_limit"] == "1g"
        and service["cpus"] == 1
        and service["pids_limit"] == 32
    )
    assert (
        service.get("secrets", []) == []
        and service.get("ports", []) == []
        and service.get("depends_on", {}) == {}
    )
    assert len(service["volumes"]) == 7 and all(
        value.endswith(":ro") for value in service["volumes"]
    )
    assert not any(
        token in str(service["volumes"])
        for token in ("history", "research", "apps/api", ".local", "tests", "docker.sock")
    )
    assert service["entrypoint"] == ["python", "-I", runtime.WORKER] and service["command"] == [
        "--idle"
    ]
    controller()._check_container(info)


@pytest.mark.parametrize(
    "field,value",
    [
        ("Privileged", True),
        ("ReadonlyRootfs", False),
        ("NetworkMode", "host"),
        ("Memory", 0),
        ("MemorySwap", -1),
        ("NanoCpus", 0),
        ("PidsLimit", -1),
        ("CapDrop", []),
        ("CapAdd", ["SYS_ADMIN"]),
        ("SecurityOpt", []),
        ("PortBindings", {"8000/tcp": [{"HostPort": "1"}]}),
        ("PidMode", "host"),
        ("IpcMode", "host"),
        ("UTSMode", "host"),
        ("CgroupnsMode", "host"),
    ],
)
def test_weakened_kernel_or_container_settings_refuse_before_original(info, field, value):
    info["HostConfig"][field] = value
    with pytest.raises(runtime.AssetRuntimeError, match="ASSET_CONTAINER_NOT_ISOLATED"):
        controller()._check_container(info)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["Config"].update(User="0:0"),
        lambda value: value["Config"]["Env"].append("DEEPSEEK_API_KEY=synthetic"),
        lambda value: value["Config"]["Labels"].update({"com.docker.compose.project": "other"}),
        lambda value: value["Mounts"].append(
            {"Destination": "/run/secrets", "Type": "bind", "RW": False}
        ),
        lambda value: value["Mounts"][0].update(RW=True),
        lambda value: value.update(Image="sha256:" + "f" * 64),
    ],
)
def test_foreign_identity_credentials_or_mounts_are_rejected(info, change):
    change(info)
    with pytest.raises(runtime.AssetRuntimeError, match="ASSET_CONTAINER_"):
        controller()._check_container(info)


@pytest.mark.parametrize("value", [0, 40001, True, 0.1])
def test_hard_deadline_cannot_be_disabled_or_extended(value):
    with pytest.raises(runtime.AssetRuntimeError, match="ASSET_DEADLINE_INVALID"):
        controller(hard_timeout_ms=value)


def test_lock_refuses_second_controller_without_waiting():
    with runtime.exclusive():
        with pytest.raises(runtime.AssetRuntimeError, match="ASSET_RUNTIME_BUSY"):
            with runtime.exclusive():
                raise AssertionError("second controller acquired the same service")


@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1.0}', b'"\\ud800"', b"[[[", b"\xff"]
)
def test_small_header_json_is_strict_and_safe(raw):
    with pytest.raises(wire.AssetWireError, match="JSON_INVALID"):
        wire.load(raw)


def test_wire_keeps_pdf_and_png_bytes_out_of_json_and_bounds_header_first(monkeypatch):
    data = b"%PDF-synthetic-raw\x00\xff"
    packed = wire.pack({"version": "synthetic"}, data)
    header, payload = wire.unpack(packed)
    assert header == {"version": "synthetic"} and payload == data
    assert packed[-len(data) :] == data
    with pytest.raises(wire.AssetWireError, match="HEADER_INVALID"):
        wire.unpack((wire.MAX_HEADER_BYTES + 1).to_bytes(4, "big") + b"{}")
    monkeypatch.setattr(wire, "MAX_HEADER_BYTES", 1)
    with pytest.raises(wire.AssetWireError, match="SIZE_INVALID"):
        wire.load(b'{"a":1}')


def test_blocks_reject_duplicates_trailing_bytes_and_unknown_sizes():
    row = {"id": "a" * 64, "byte_size": 2}
    assert wire.decode_blocks([row], b"ab") == {"a" * 64: b"ab"}
    with pytest.raises(wire.AssetWireError, match="BLOCK_REUSED"):
        wire.decode_blocks([row, row], b"abab")
    with pytest.raises(wire.AssetWireError, match="BLOCK_SIZE_MISMATCH"):
        wire.decode_blocks([row], b"abc")
    with pytest.raises(wire.AssetWireError, match="SHAPE_INVALID"):
        wire.decode_blocks([{**row, "byte_size": True}], b"a")


@pytest.mark.parametrize("field", ["path", "url", "command", "environment", "real"])
def test_render_header_cannot_select_files_commands_credentials_or_execution_mode(field):
    header = {
        "version": "package-page-render-request/1",
        "document_version_id": "00000000-0000-4000-8000-000000000001",
        "source_digest": "a" * 64,
        "source_byte_size": 1,
        "render_method_digest": "b" * 64,
        "crop_method_digest": "c" * 64,
        "regions": [],
    }
    wire.check(header, wire.request_schema())
    header[field] = "synthetic forbidden input"
    with pytest.raises(wire.AssetWireError, match="SHAPE_INVALID"):
        wire.check(header, wire.request_schema())


def test_wire_import_does_not_load_business_configuration():
    code = "import sys; sys.path.insert(0,sys.argv[1]); import packages.parsing.page_asset_wire; print('packages.domain.runtime' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(runtime.ROOT)], capture_output=True, check=True
    )  # nosec B603
    assert result.stdout.strip() == b"False"


def test_bad_original_hash_is_rejected_before_daemon_use(monkeypatch):
    port = controller()

    def forbidden(*args, **kwargs):
        raise AssertionError("daemon must not be used for invalid original bytes")

    monkeypatch.setattr(port, "_command", forbidden)
    with pytest.raises(runtime.AssetRuntimeError, match="ORIGINAL_BYTES_MISMATCH"):
        port.render(
            b"%PDF-synthetic",
            document_version_id="not-used",
            expected_source_digest="0" * 64,
            expected_source_size=14,
            expected_render_method_digest="0" * 64,
            expected_crop_method_digest="0" * 64,
            regions=[],
        )


class FakeProcess:
    def __init__(self, output, *, running=False):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output)
        self.stderr = io.BytesIO()
        self.returncode = None if running else 0
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        return self.returncode


def test_stdout_limit_and_host_deadline_terminate_exec_client(monkeypatch):
    port = controller()
    process = FakeProcess(b"0123456789")
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(runtime.AssetRuntimeError, match="OUTPUT_LIMIT"):
        port._exchange("a" * 64, [], timeout_ms=1000, maximum=4)
    process = FakeProcess(b"", running=True)
    with pytest.raises(runtime.AssetRuntimeError, match="WALL_TIMEOUT"):
        port._exchange("a" * 64, [], timeout_ms=1, maximum=4)
    assert process.killed


def test_cross_checkout_project_is_rejected_without_starting_a_service(monkeypatch):
    port = controller()
    seen = []

    def command(args, **kwargs):
        seen.append(args)
        if args[0] == "compose":
            return b"a" * 64
        return json.dumps(
            {
                "com.docker.compose.project": "tender-fusion",
                "com.docker.compose.service": "api",
                "com.docker.compose.project.working_dir": "D:/other-checkout/deploy",
            }
        ).encode()

    monkeypatch.setattr(port, "_command", command)
    with pytest.raises(runtime.AssetRuntimeError, match="PROJECT_SCOPE_MISMATCH"):
        port._check_project()
    assert len(seen) == 2 and all("up" not in args for args in seen)


def test_cleanup_targets_owned_container_and_falls_back_to_exact_kill(monkeypatch):
    port = controller()
    seen = []
    value = {
        "Config": {
            "Labels": {
                "com.docker.compose.project": "tender-fusion",
                "com.docker.compose.service": "asset-renderer",
            }
        },
        "State": {
            "Running": False,
            "Pid": 0,
            "OOMKilled": False,
            "FinishedAt": "synthetic-finish",
            "ExitCode": 0,
        },
    }
    monkeypatch.setattr(port, "_inspect", lambda identity: value)

    def command(args, **kwargs):
        seen.append(args)
        if args[0] == "stop":
            raise runtime.AssetRuntimeError("synthetic daemon stop failure")
        return b""

    monkeypatch.setattr(port, "_command", command)
    assert port._stop("a" * 64)["stopped_verified"]
    assert seen == [["stop", "--time", "2", "a" * 64], ["kill", "a" * 64]]
    value["Config"]["Labels"]["com.docker.compose.service"] = "api"
    with pytest.raises(runtime.AssetRuntimeError, match="CLEANUP_SCOPE_MISMATCH"):
        port._stop("a" * 64)
    assert len(seen) == 2


def test_cleanup_does_not_claim_success_with_a_live_namespace(monkeypatch):
    port = controller()
    value = {
        "Config": {
            "Labels": {
                "com.docker.compose.project": "tender-fusion",
                "com.docker.compose.service": "asset-renderer",
            }
        },
        "State": {"Running": True, "Pid": 123},
    }
    monkeypatch.setattr(port, "_inspect", lambda identity: value)
    monkeypatch.setattr(port, "_command", lambda *args, **kwargs: b"")
    with pytest.raises(runtime.AssetRuntimeError, match="CLEANUP_UNCONFIRMED"):
        port._stop("a" * 64)
