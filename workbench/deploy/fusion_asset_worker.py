"""Fixed isolated renderer entrypoint; no database, object store or credentials."""

import json
import os
import signal
import sys
from pathlib import Path

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
SOURCE_FILES = {
    "deploy/fusion_asset_worker.py",
    "packages/model_governance/package_technical_assets.py",
    "packages/model_governance/technical_png.py",
    "packages/contracts/package_technical_assets.py",
    "packages/parsing/pdfium_guard.py",
    "packages/parsing/page_asset_wire.py",
    "packages/domain/review_identity.py",
}


def configure():
    if sys.platform != "linux" or os.geteuid() != 65532 or set(os.environ) - ALLOWED_ENVIRONMENT:
        raise ValueError("ASSET_WORKER_NOT_ISOLATED")
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CPU, (35, 35))
    sys.dont_write_bytecode = True
    sys.path.insert(0, "/workspace")
    visible = {
        str(path.relative_to("/workspace"))
        for path in Path("/workspace").rglob("*")
        if path.is_file()
    }
    if visible != SOURCE_FILES:
        raise ValueError("ASSET_WORKER_SOURCES_NOT_ISOLATED")


def isolation():
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        status[key] = value.strip()
    limits = {
        name: Path("/sys/fs/cgroup", name).read_text().strip()
        for name in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
    }
    expected = {
        "memory.max": "1073741824",
        "memory.swap.max": "0",
        "pids.max": "32",
        "cpu.max": "100000 100000",
    }
    if (
        limits != expected
        or status.get("NoNewPrivs") != "1"
        or status.get("Seccomp") != "2"
        or any(
            status.get(name) != "0000000000000000"
            for name in ("CapEff", "CapPrm", "CapBnd", "CapAmb")
        )
        or sorted(os.listdir("/sys/class/net")) != ["lo"]
    ):
        raise ValueError("ASSET_WORKER_KERNEL_LIMITS_UNAVAILABLE")
    return {
        **limits,
        "no_new_privileges": True,
        "seccomp_filter_active": True,
        "effective_permitted_bounding_ambient_capabilities_zero": True,
        "network_interfaces": ["lo"],
        "read_only_source_files": len(SOURCE_FILES),
    }


def describe():
    from packages.model_governance import package_technical_assets as assets
    from packages.model_governance.technical_png import digest_bytes
    from packages.parsing import page_asset_wire as wire

    return {
        "version": "package-page-render-runtime/1",
        "uid": int(getattr(os, "geteuid", lambda: -1)()),
        "worker_source_digest": digest_bytes(Path(__file__).read_bytes()),
        "wire_source_digest": digest_bytes(Path(wire.__file__).read_bytes()),
        "render_method_digest": assets.render_method_digest(),
        "crop_method_digest": assets.crop_method_digest(),
        "render_descriptor": assets.render_descriptor(),
        "isolation": isolation(),
    }


def render(raw):
    from packages.model_governance import package_technical_assets as assets
    from packages.parsing import page_asset_wire as wire

    request, data = wire.unpack(raw)
    wire.check(request, wire.request_schema())
    result = assets.render_static_pdf(
        data,
        document_version_id=request["document_version_id"],
        expected_source_digest=request["source_digest"],
        expected_source_size=request["source_byte_size"],
        expected_method_digest=request["render_method_digest"],
    )
    if request["crop_method_digest"] != assets.crop_method_digest():
        raise ValueError("ASSET_WORKER_METHOD_MISMATCH")
    if request["regions"]:
        result = assets.crop_page_assets(
            result,
            request["regions"],
            expected_manifest_digest=result.manifest["digest"],
            expected_method_digest=request["crop_method_digest"],
        )
    reply = {
        "version": "package-page-render-response/1",
        "state": "succeeded",
        "manifest": result.manifest,
        "blobs": [{"id": key, "byte_size": len(data)} for key, data in result.blobs.items()],
    }
    encoded = wire.pack(reply, b"".join(result.blobs.values()))
    if len(encoded) > wire.MAX_WIRE_BYTES:
        raise ValueError("ASSET_WORKER_OUTPUT_LIMIT")
    return encoded


def main():
    try:
        configure()
        if sys.argv[1:] == ["--idle"]:
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            while True:
                signal.pause()  # type: ignore[attr-defined]  # Linux configure guard.
        if sys.argv[1:] == ["--describe"]:
            sys.stdout.buffer.write(json.dumps(describe(), separators=(",", ":")).encode("utf-8"))
            return
        if sys.argv[1:]:
            raise ValueError("ASSET_WORKER_ARGUMENT_INVALID")
        from packages.parsing import page_asset_wire as wire

        raw = sys.stdin.buffer.read(wire.MAX_WIRE_BYTES + 1)
        sys.stdout.buffer.write(render(raw))
    except ValueError:
        reply = b'{"version":"package-page-render-response/1","state":"failed","error_code":"ASSET_WORKER_REJECTED"}'
        sys.stdout.buffer.write(len(reply).to_bytes(4, "big") + reply)
        raise SystemExit(2) from None
    except Exception:
        reply = b'{"version":"package-page-render-response/1","state":"failed","error_code":"ASSET_WORKER_INTERNAL_ERROR"}'
        sys.stdout.buffer.write(len(reply).to_bytes(4, "big") + reply)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
