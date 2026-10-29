"""Actual native nginx and Linux capability boundaries; no database or paid calls."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from deploy import fusion_full_spec as spec

TOOLS = os.environ.get("FUSION_FULL_PLATFORM_TOOLS")
RECEIPT = os.environ.get("FUSION_FULL_PLATFORM_RECEIPT")
pytestmark = pytest.mark.skipif(
    not TOOLS or not RECEIPT, reason="explicit local nginx/setpriv platform acceptance required"
)


@pytest.fixture(scope="module")
def platform_tools():
    value = json.loads(TOOLS)
    assert set(value) == {"nginx", "setpriv"}
    assert os.geteuid() == 0, (
        "this explicit capability drill requires root before dropping privileges"
    )
    for filename in value.values():
        path = Path(filename)
        assert path.is_absolute() and path.is_file() and not path.is_symlink()
    return value | {"checks": {}}


def test_initializer_can_read_a_host_users_private_files_with_only_required_caps(platform_tools):
    directory = Path(tempfile.mkdtemp(prefix="tender-full-permission-"))
    value = {"synthetic": True, "no_business_credential": True}
    path = directory / "operator.json"
    spec.write_private(path, value)
    for entry in (directory, path):
        os.chown(entry, 65532, 65532)
    script = "import json,sys; from pathlib import Path; value=json.loads(Path(sys.argv[1]).read_bytes()); assert value=={'synthetic': True,'no_business_credential': True}"
    base = [platform_tools["setpriv"], "--no-new-privs"]
    try:
        denied = subprocess.run(
            [*base, "--bounding-set=-all,+chown", sys.executable, "-c", script, str(path)],
            capture_output=True,
            check=False,
            timeout=5,
        )  # nosec B603
        assert denied.returncode != 0 and b"PermissionError" in denied.stderr
        allowed = subprocess.run(
            [
                *base,
                "--bounding-set=-all,+chown,+dac_override",
                sys.executable,
                "-c",
                script,
                str(path),
            ],
            capture_output=True,
            check=False,
            timeout=5,
        )  # nosec B603
        assert allowed.returncode == 0, (
            "minimal initializer capabilities failed private host-file access"
        )
        capability_script = "from pathlib import Path; lines=Path('/proc/self/status').read_text().splitlines(); print(next(x for x in lines if x.startswith('CapEff:')).split()[1])"
        observed = subprocess.run(
            [
                *base,
                "--bounding-set=-all,+chown,+dac_override",
                sys.executable,
                "-c",
                capability_script,
            ],
            capture_output=True,
            check=True,
            timeout=5,
        )  # nosec B603
        assert int(observed.stdout.strip(), 16) == 3
        assert directory.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        shutil.rmtree(directory)
    platform_tools["checks"]["initializer"] = {
        "host_file_owner_uid": 65532,
        "private_directory_mode": "0700",
        "private_file_mode": "0600",
        "chown_only_denied": True,
        "chown_dac_override_succeeded": True,
        "effective_capability_mask": "0x3",
        "business_capabilities_expanded": False,
    }


def test_real_nonroot_nginx_readonly_config_upload_budgets_and_proxy_headers(platform_tools):
    root = Path(tempfile.mkdtemp(prefix="tender-full-nginx-"))
    root.chmod(0o755)
    config, static, temporary = (root / name for name in ("config", "static", "tmp"))
    for directory in (config, static, temporary):
        directory.mkdir(mode=0o755)
    os.chown(temporary, 65532, 65532)
    temporary.chmod(0o700)
    (static / "index.html").write_text("<!doctype html><title>synthetic-only</title>")
    (static / "app.js").write_text("export const synthetic = true;\n")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            payload = json.dumps({"path": self.path, "method": "GET"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_PUT(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(
                {
                    "path": self.path,
                    "length": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "host": self.headers["Host"],
                    "origin": self.headers["Origin"],
                    "csrf": self.headers["X-CSRF-Token"],
                    "cookie": self.headers["Cookie"],
                }
            )
            payload = json.dumps(
                {"byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    main_raw = (spec.fresh.ROOT / "deploy/nginx-fusion-full-main.conf").read_text()
    server_raw = (spec.fresh.ROOT / "deploy/nginx-fusion-full.conf").read_text()
    assert "\nuser " not in main_raw and "nginx.conf" not in server_raw
    main = main_raw.replace("/tmp/", str(temporary) + "/").replace(
        "/etc/nginx/conf.d/fusion-full-server.conf", str(config / "server.conf")
    )
    server = (
        server_raw.replace("listen 8080;", f"listen 127.0.0.1:{port};")
        .replace("/usr/share/nginx/html", str(static))
        .replace("http://api:8000", "http://127.0.0.1:" + str(backend.server_port))
    )
    (config / "nginx.conf").write_text(main)
    (config / "server.conf").write_text(server)
    for directory in (config, static):
        for path in directory.iterdir():
            path.chmod(0o444)
        directory.chmod(0o555)
    command = [
        platform_tools["setpriv"],
        "--no-new-privs",
        "--reuid=65532",
        "--regid=65532",
        "--clear-groups",
        "--bounding-set=-all",
        platform_tools["nginx"],
        "-p",
        str(root),
        "-c",
        str(config / "nginx.conf"),
        "-e",
        "/dev/null",
    ]
    process = None
    logfile = root / "private-process.log"
    descriptor = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)

    def request(method, path, *, payload=None, declared_length=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {
            "Origin": "http://127.0.0.1:" + str(port),
            "X-CSRF-Token": "synthetic-csrf",
            "Cookie": "session=synthetic-cookie",
        }
        try:
            if declared_length is None:
                connection.request(method, path, body=payload, headers=headers)
            else:
                connection.putrequest(method, path)
                for key, value in headers.items():
                    connection.putheader(key, value)
                connection.putheader("Content-Length", str(declared_length))
                connection.endheaders()
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    try:
        checked = subprocess.run([*command, "-t"], capture_output=True, check=False, timeout=5)  # nosec B603
        assert checked.returncode == 0, checked.stderr.decode()
        with os.fdopen(descriptor, "wb") as output:
            process = subprocess.Popen(
                [*command, "-g", "daemon off;"], stdout=output, stderr=output
            )  # nosec B603
            deadline = time.monotonic() + 5
            while True:
                assert process.poll() is None
                try:
                    if request("GET", "/nginx-health")[0] == 200:
                        break
                except OSError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.05)
            status = Path(f"/proc/{process.pid}/status").read_text()
            assert "Uid:\t65532\t65532\t65532\t65532" in status
            assert "CapEff:\t0000000000000000" in status
            assert (temporary / "nginx-full.pid").is_file()
            code, response_headers, body = request("GET", "/app.js")
            assert code == 200 and response_headers["Content-Type"] == "application/javascript"
            assert body == (static / "app.js").read_bytes()
            assert request("GET", "/projects/synthetic")[2] == (static / "index.html").read_bytes()
            identity = "00000000-0000-4000-8000-000000000001"
            ticket = "synthetic-private-ticket-must-never-be-logged"
            source_path = "/api/v1/object-transfers/uploads/" + identity + "?ticket=" + ticket
            payload = b"S" * (6 * 1024 * 1024)
            code, _, body = request("PUT", source_path, payload=payload)
            assert code == 200 and json.loads(body)["sha256"] == hashlib.sha256(payload).hexdigest()
            assert request("PUT", source_path, declared_length=100 * 1024 * 1024 + 1)[0] == 413
            assert request("PUT", "/api/v1/bids", declared_length=6 * 1024 * 1024)[0] == 413
            part = "/api/v1/object-transfers/multipart/" + identity + "/parts/10000"
            assert request("PUT", part, payload=b"P" * (7 * 1024 * 1024))[0] == 200
            assert request("PUT", part, declared_length=8 * 1024 * 1024 + 1)[0] == 413
            assert request("PUT", part + "1", declared_length=6 * 1024 * 1024)[0] == 413
            assert all(
                row["host"] == "127.0.0.1:" + str(port)
                and row["origin"] == "http://127.0.0.1:" + str(port)
                and row["csrf"] == "synthetic-csrf"
                and row["cookie"] == "session=synthetic-cookie"
                for row in seen
            )
            backend.shutdown()
            backend.server_close()
            backend_thread.join(timeout=3)
            assert request("GET", "/api/v1/unavailable?ticket=" + ticket)[0] == 502
            process.terminate()
            process.wait(timeout=5)
        assert ticket.encode() not in logfile.read_bytes()
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=3)
        shutil.rmtree(root)
    platform_tools["checks"]["nginx"] = {
        "actual_nginx_t_succeeded": True,
        "master_uid": 65532,
        "effective_capabilities": 0,
        "configuration_directory_readonly": True,
        "static_directory_readonly": True,
        "pid_and_all_temporary_paths_in_private_tmp": True,
        "actual_static_javascript_mime": "application/javascript",
        "spa_fallback": True,
        "actual_6mib_source_transfer": True,
        "actual_7mib_last_multipart_part": True,
        "over_source_limit_413": True,
        "over_part_limit_413": True,
        "ordinary_json_limit_413": True,
        "host_origin_csrf_cookie_forwarded": True,
        "upstream_failure_502": True,
        "private_ticket_absent_from_logs": True,
        "backend_is_transport_test_fixture": True,
        "container_executed": False,
    }


def test_platform_receipt_preserves_actual_boundaries(platform_tools):
    assert set(platform_tools["checks"]) == {"initializer", "nginx"}
    versions = subprocess.run(
        [platform_tools["nginx"], "-v"], capture_output=True, check=True, timeout=5
    )  # nosec B603
    receipt = {
        "version": "fusion-full-platform-acceptance/1",
        "nginx_version": versions.stderr.decode().strip(),
        "nginx_binary_sha256": spec.digest(Path(platform_tools["nginx"]).read_bytes()),
        "source_sha256": {
            name: spec.digest((spec.fresh.ROOT / name).read_bytes())
            for name in (
                "deploy/nginx-fusion-full-main.conf",
                "deploy/nginx-fusion-full.conf",
                "deploy/compose.fusion-full.yaml",
                "deploy/fusion_full_configure.py",
                "deploy/fusion_full_control.py",
                "deploy/fusion_full_runtime.py",
            )
        },
        "checks": platform_tools["checks"],
        "provider_calls": 0,
        "docker_executed": False,
    }
    spec.write_private(Path(RECEIPT), receipt)
