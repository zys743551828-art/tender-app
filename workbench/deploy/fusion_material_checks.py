"""Run the fixed host/native/Compose derivation suite using existing runtimes.

Only a temporary loopback port on the existing grouped checks DB is exposed.
The dedicated DB password stays in process memory and is never a CLI argument.
"""

import json
import os
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local/native-material-recovery"
SYSTEM_ENVIRONMENT = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "COMSPEC",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "HOME",
    }
)
GROUPS = (
    "tender_current_source_verify",
    "tender_current_scope_verify",
    "tender_current_original_verify",
    "tender_material_registration",
    "tender_scope_review_issuer",
    "tender_scope_review_verify",
    "tender_material_store_write",
    "tender_material_store_read",
)
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "tender-fusion",
    "--env-file",
    "deploy/fusion.defaults.env",
    "-f",
    "deploy/compose.fusion.yaml",
]


def command(args, *, timeout=45):
    failed = False
    try:
        r = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout, check=False)  # nosec B603
        failed = r.returncode != 0 or len(r.stdout) > 262144
    except (OSError, subprocess.TimeoutExpired):
        failed = True
    if failed:
        raise RuntimeError("MATERIAL_CHECK_COMMAND_FAILED")
    return r.stdout


def inspect_state(name):
    return json.loads(command(["docker", "inspect", "--format", "{{json .State}}", name]))


def main():
    if len(sys.argv) != 1:
        raise RuntimeError("MATERIAL_CHECK_NO_ARGUMENTS_ALLOWED")
    LOCAL.mkdir(parents=True, exist_ok=True)
    if inspect_state("tender-fusion-checks-1")["Running"]:
        raise RuntimeError("MATERIAL_CHECK_GROUP_BUSY")
    image = (
        command(["docker", "image", "inspect", "--format", "{{.Id}}", "tender-fusion-checks:py312"])
        .decode()
        .strip()
    )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise RuntimeError("MATERIAL_CHECK_IMAGE_REQUIRED")
    dsn = None
    result = None
    try:
        command(
            [
                *COMPOSE,
                "-f",
                "deploy/compose.fusion.host-checks.yaml",
                "--profile",
                "checks",
                "up",
                "-d",
                "--wait",
                "checks-postgres",
            ]
        )
        ports = json.loads(
            command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{json .NetworkSettings.Ports}}",
                    "tender-fusion-checks-postgres-1",
                ]
            )
        )["5432/tcp"]
        if (
            len(ports) != 1
            or ports[0]["HostIp"] != "127.0.0.1"
            or not ports[0]["HostPort"].isdigit()
        ):
            raise RuntimeError("MATERIAL_CHECK_LOOPBACK_ONLY_REQUIRED")
        dsn = make_conninfo(
            host="127.0.0.1",
            port=ports[0]["HostPort"],
            user="postgres",
            dbname="postgres",
            password=(ROOT / ".local/fusion/checks-owner-password")
            .read_text(encoding="utf-8")
            .rstrip("\r\n"),
        )
        env = {k: v for k, v in os.environ.items() if k.upper() in SYSTEM_ENVIRONMENT}
        env.update(
            {
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "WORKBENCH_ENV_FILE": "explicit-host-material-derivation-no-business-env",
                "FUSION_MATERIAL_DERIVATION_NATIVE": "1",
                "FUSION_MATERIAL_DERIVATION_IMAGE": image,
                "FUSION_MATERIAL_DERIVATION_EVIDENCE": str(LOCAL),
                "FUSION_CONTEXT_DERIVATION_NATIVE": "1",
                "FUSION_CONTEXT_DERIVATION_EVIDENCE": str(LOCAL),
                "FUSION_NATIVE_MATERIAL_STORE_HOST": "1",
                "FUSION_NATIVE_MATERIAL_STORE_HOST_EVIDENCE": str(LOCAL),
                "FUSION_NATIVE_MATERIAL_RECOVERY_HOST": "1",
                "FUSION_REQUIREMENTS_ADMIN_DSN": dsn,
            }
        )
        result = subprocess.run(  # nosec B603
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "pytest",
                "tests/test_fusion_material_derivation_native.py",
                "tests/test_fusion_context_derivation_native.py",
                "tests/test_native_material_store_host.py",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
                "--junitxml=.local/native-material-recovery/host-native-final.xml",
            ],
            cwd=ROOT,
            env=env,
            check=False,
        ).returncode
    finally:
        try:
            if dsn is not None:
                with psycopg.connect(dsn, autocommit=True) as c:
                    row = c.execute(
                        "SELECT (SELECT count(*) FROM pg_database WHERE datname LIKE %s),(SELECT count(*) FROM pg_roles WHERE rolcanlogin AND rolname LIKE %s),(SELECT count(*) FROM pg_roles WHERE rolname=ANY(%s))",
                        ("fusion_%", "fusion_%", list(GROUPS)),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError("MATERIAL_CHECK_CLEANUP_OBSERVATION_REQUIRED")
                    cleanup = dict(
                        zip(
                            ("temporary_databases", "temporary_logins", "verification_roles"),
                            row,
                            strict=True,
                        )
                    )
                    (LOCAL / "checks-cleanup.json").write_text(
                        json.dumps(cleanup) + "\n", encoding="utf-8"
                    )
                    if any(cleanup.values()):
                        raise RuntimeError("MATERIAL_CHECK_DATABASE_CLEANUP_REQUIRED")
        finally:
            # Restore base definition to remove the host port and bridge attachment,
            # then stop only the checks/asset services, preserving preview and Word.
            try:
                command([*COMPOSE, "--profile", "checks", "up", "-d", "--wait", "checks-postgres"])
                bindings = json.loads(
                    command(
                        [
                            "docker",
                            "inspect",
                            "--format",
                            "{{json .HostConfig.PortBindings}}",
                            "tender-fusion-checks-postgres-1",
                        ]
                    )
                )
                if bindings:
                    raise RuntimeError("MATERIAL_CHECK_HOST_PORT_NOT_REMOVED")
            finally:
                command(
                    [
                        *COMPOSE,
                        "--profile",
                        "checks",
                        "--profile",
                        "assets",
                        "stop",
                        "checks",
                        "checks-postgres",
                        "asset-renderer",
                    ]
                )
            network = json.loads(
                command(["docker", "network", "inspect", "tender-fusion_host-checks"])
            )[0]
            if (
                network["Labels"].get("com.docker.compose.project") != "tender-fusion"
                or network["Containers"]
            ):
                raise RuntimeError("MATERIAL_CHECK_NETWORK_CLEANUP_REQUIRED")
            command(["docker", "network", "rm", "tender-fusion_host-checks"])
            (LOCAL / "host-bridge-cleanup.json").write_text(
                json.dumps({"host_port_removed": True, "temporary_bridge_removed": True}) + "\n",
                encoding="utf-8",
            )
    raise SystemExit(result if result is not None else 1)


if __name__ == "__main__":
    main()
