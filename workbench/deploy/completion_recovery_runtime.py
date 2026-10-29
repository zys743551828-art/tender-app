"""Run the synthetic current-schema drill with a new loopback S3 process.

No downloads, Docker changes, existing database, old transport state, workers or
paid providers are used. The test itself creates and stops a separate PG cluster.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess  # nosec B404
import sys
import tempfile
import time
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError

from deploy import completion_recovery as recovery
from deploy.backups import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--weed", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    recovery.frozen_plan()  # Reject missing current base before starting anything.
    if args.receipt.exists() or args.receipt.is_symlink():
        raise run.BackupError("REFUSING_EXISTING_COMPLETION_RECEIPT")
    for executable in (
        args.weed,
        *(args.pg_bin / name for name in ("postgres", "pg_dump", "pg_restore", "initdb", "pg_ctl")),
    ):
        if executable.is_symlink() or not executable.is_file() or not executable.is_absolute():
            raise run.BackupError("EXPLICIT_EXISTING_LOCAL_BINARIES_REQUIRED")
    directory = Path(tempfile.mkdtemp(prefix="tender-completion-s3-"))
    account = pwd.getpwnam("nobody") if os.geteuid() == 0 else pwd.getpwuid(os.geteuid())
    os.chown(directory, account.pw_uid, account.pw_gid)
    configuration = {
        "access_key": "synthetic-" + secrets.token_hex(12),
        "secret_key": secrets.token_urlsafe(36),
    }
    identity = directory / "s3-identity.json"
    run.private_write(
        identity,
        json.dumps(
            {
                "identities": [
                    {
                        "name": "synthetic-completion-recovery",
                        "credentials": [
                            {
                                "accessKey": configuration["access_key"],
                                "secretKey": configuration["secret_key"],
                            }
                        ],
                        "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                    }
                ]
            }
        ).encode(),
    )
    os.chown(identity, account.pw_uid, account.pw_gid)
    ports = []
    probes = []
    for _ in range(8):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        ports.append(probe.getsockname()[1])
        probes.append(probe)
    master, master_grpc, volume, volume_grpc, filer, filer_grpc, s3, s3_grpc = ports
    configuration["endpoint"] = "http://127.0.0.1:" + str(s3)
    profile = directory / "profile.json"
    run.private_write(
        profile,
        json.dumps(
            {
                "only_synthetic": True,
                "s3_endpoint": configuration["endpoint"],
                "credentials_path": str(identity),
            }
        ).encode(),
    )
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL"}}
    process = None
    log_path = directory / "seaweed.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        for probe in probes:
            probe.close()
        with os.fdopen(descriptor, "wb") as log:
            process = subprocess.Popen(  # nosec B603
                [
                    str(args.weed),
                    "server",
                    "-dir=" + str(directory),
                    "-ip=127.0.0.1",
                    "-ip.bind=127.0.0.1",
                    "-master.port=" + str(master),
                    "-master.port.grpc=" + str(master_grpc),
                    "-master.telemetry=false",
                    "-master.volumeSizeLimitMB=32",
                    "-volume.port=" + str(volume),
                    "-volume.port.grpc=" + str(volume_grpc),
                    "-volume.max=32",
                    "-filer",
                    "-filer.port=" + str(filer),
                    "-filer.port.grpc=" + str(filer_grpc),
                    "-filer.localSocket=" + str(directory / "filer.sock"),
                    "-s3",
                    "-s3.port=" + str(s3),
                    "-s3.port.grpc=" + str(s3_grpc),
                    "-s3.ip.bind=127.0.0.1",
                    "-s3.localSocket=" + str(directory / "s3.sock"),
                    "-s3.config=" + str(identity),
                    "-s3.iam=false",
                    "-s3.port.iceberg=0",
                    "-s3.port.lance=0",
                    "-s3.autoCreateBucket=false",
                    "-s3.allowDeleteBucketNotEmpty=false",
                ],
                cwd=directory,
                env=environment,
                user=account.pw_uid,
                group=account.pw_gid,
                extra_groups=[],
                stdout=log,
                stderr=log,
            )
            deadline = time.monotonic() + 45
            client = recovery.s3_client(configuration)
            while True:
                if process.poll() is not None:
                    raise run.BackupError("SYNTHETIC_S3_PROCESS_FAILED")
                try:
                    client.list_buckets()
                    break
                except (BotoCoreError, ClientError):
                    if time.monotonic() >= deadline:
                        raise run.BackupError("SYNTHETIC_S3_NOT_READY") from None
                    time.sleep(0.2)
            test_environment = environment | {
                "FUSION_COMPLETION_RECOVERY_PG_BIN": str(args.pg_bin),
                "FUSION_TRANSPORT_PROFILE": str(profile),
                "FUSION_COMPLETION_RECOVERY_RECEIPT": str(args.receipt),
                "WORKBENCH_ENV_FILE": "explicit-completion-no-business-profile",
            }
            result = subprocess.run(  # nosec B603
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/test_completion_recovery_pg.py",
                    "-x",
                    "--tb=short",
                ],
                cwd=run.ROOT,
                env=test_environment,
                timeout=180,
                check=False,
            )
        return result.returncode
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        shutil.rmtree(directory)


if __name__ == "__main__":
    raise SystemExit(main())
