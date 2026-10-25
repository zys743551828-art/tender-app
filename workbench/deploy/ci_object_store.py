"""An isolated loopback S3 service for native authoring CI; no business credentials."""

from __future__ import annotations

import json
import secrets
import socket
import subprocess  # nosec B404
import tempfile
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def unused_ports(count: int) -> list[int]:
    with ExitStack() as stack:
        result = []
        for _ in range(count):
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            listener.bind(("127.0.0.1", 0))
            result.append(listener.getsockname()[1])
        return result


@contextmanager
def temporary_object_store(
    weed: Path, environment: dict[str, str], log_path: Path
) -> Iterator[dict[str, str]]:
    """Start only the given locally verified binary and destroy this service on exit."""
    weed = weed.resolve(strict=True)
    if not weed.is_file():
        raise ValueError("CI_SEAWEED_BINARY_REQUIRED")
    credentials = {
        name: {"accessKey": secrets.token_hex(16), "secretKey": secrets.token_urlsafe(40)}
        for name in ("admin", "app")
    }
    bucket = "tender-ci-authoring-" + secrets.token_hex(8)
    master, master_grpc, volume, volume_grpc, filer, filer_grpc, s3, s3_grpc = unused_ports(8)
    endpoint = f"http://127.0.0.1:{s3}"
    with tempfile.TemporaryDirectory(prefix="tender-ci-s3-") as temporary:
        private = Path(temporary)
        config = private / "s3.json"
        config.write_text(
            json.dumps(
                {
                    "identities": [
                        {
                            "name": "ci-bootstrap",
                            "credentials": [credentials["admin"]],
                            "actions": ["Admin", "Read", "Write", "List"],
                        },
                        {
                            "name": "ci-application",
                            "credentials": [credentials["app"]],
                            "actions": [
                                f"{action}:{bucket}" for action in ("Read", "Write", "List")
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        config.chmod(0o600)
        raw_log = private / "service.log"
        command = [
            str(weed),
            "server",
            "-ip=127.0.0.1",
            "-ip.bind=127.0.0.1",
            "-dir=" + str(private),
            f"-master.port={master}",
            f"-master.port.grpc={master_grpc}",
            "-master.telemetry=false",
            "-master.volumeSizeLimitMB=128",
            "-volume.max=4",
            f"-volume.port={volume}",
            f"-volume.port.grpc={volume_grpc}",
            "-filer",
            f"-filer.port={filer}",
            f"-filer.port.grpc={filer_grpc}",
            "-filer.disableDirListing",
            "-s3",
            f"-s3.port={s3}",
            f"-s3.port.grpc={s3_grpc}",
            "-s3.iam=false",
            "-s3.port.iceberg=0",
            "-s3.port.lance=0",
            "-s3.autoCreateBucket=false",
            "-s3.allowDeleteBucketNotEmpty=false",
            "-s3.config=" + str(config),
        ]
        with raw_log.open("wb") as output:
            process = subprocess.Popen(  # nosec B603
                command,
                cwd=private,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                admin = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    region_name="us-east-1",
                    aws_access_key_id=credentials["admin"]["accessKey"],
                    aws_secret_access_key=credentials["admin"]["secretKey"],
                    config=Config(
                        connect_timeout=1,
                        read_timeout=1,
                        retries={"max_attempts": 0},
                        proxies={},
                        s3={"addressing_style": "path"},
                    ),
                )
                deadline = time.monotonic() + 45
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("CI_OBJECT_STORE_EXITED_DURING_STARTUP")
                    try:
                        admin.list_buckets()
                        break
                    except (BotoCoreError, ClientError):
                        if time.monotonic() >= deadline:
                            raise RuntimeError("CI_OBJECT_STORE_NOT_READY") from None
                        time.sleep(0.2)
                admin.create_bucket(Bucket=bucket)
                yield {
                    "OBJECT_STORE_BACKEND": "s3",
                    "OBJECT_STORE_ENDPOINT": endpoint,
                    "OBJECT_STORE_REGION": "us-east-1",
                    "OBJECT_STORE_BUCKET": bucket,
                    "OBJECT_STORE_ACCESS_KEY": credentials["app"]["accessKey"],
                    "OBJECT_STORE_SECRET_KEY": credentials["app"]["secretKey"],
                }
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                output.flush()
                redacted = raw_log.read_text(encoding="utf-8", errors="replace")
                for credential in credentials.values():
                    for value in credential.values():
                        redacted = redacted.replace(value, "<redacted ephemeral CI credential>")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(redacted, encoding="utf-8")
