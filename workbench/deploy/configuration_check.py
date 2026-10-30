"""Offline entry-point configuration checks; never print values or contact providers."""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    pass


def load(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("ENV_FILE_REQUIRED: select an existing regular private file")
    if path.stat().st_mode & 0o077:
        raise ConfigurationError("ENV_FILE_NOT_PRIVATE: restrict the selected file to mode 600")
    if path.stat().st_size > 1024 * 1024:
        raise ConfigurationError("ENV_FILE_TOO_LARGE")
    values: dict[str, str] = {}
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, raw = line.partition("=")
            key = key.strip()
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
                raise ConfigurationError(
                    f"ENV_ASSIGNMENT_INVALID: line {number}; use unique KEY=value assignments"
                )
            parts = shlex.split(raw, comments=True)
            if len(parts) > 1:
                raise ConfigurationError(
                    f"ENV_VALUE_INVALID: line {number}; quote values containing spaces"
                )
            values[key] = parts[0] if parts else ""
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, ConfigurationError):
            raise
        raise ConfigurationError(
            "ENV_FILE_INVALID: check encoding and quoting; private details suppressed"
        ) from None
    return values


def workbench(path: Path, role: str | None = None) -> dict[str, str]:
    values = load(path)
    if any(
        key.startswith("BIDWB_")
        or key in {"OSS_URL", "OSS_ENDPOINT_URL", "OSS_PUBLIC_ENDPOINT_URL"}
        for key in values
    ):
        raise ConfigurationError(
            "ENV_ENTRY_MISMATCH: legacy backend/Compose variables; use the workbench profile, not the root deploy template"
        )
    if role and not values.get(f"{role.upper()}_DATABASE_DSN"):
        raise ConfigurationError(
            f"ENV_ROLE_DSN_REQUIRED: {role.upper()}_DATABASE_DSN must be explicit in the selected file"
        )
    return values


def check(path: Path, entry: str, role: str | None = None) -> dict:
    values = workbench(path, role) if entry == "workbench" else load(path)
    required = {
        "workbench": (
            "API_DATABASE_DSN",
            "APP_ORIGIN",
            "SESSION_SECRET",
            "CSRF_SECRET",
            "KAFKA_BOOTSTRAP_SERVERS",
            "OBJECT_STORE_BACKEND",
            "OBJECT_STORE_ENDPOINT",
            "OBJECT_STORE_BUCKET",
            "OBJECT_STORE_REGION",
            "OBJECT_STORE_ACCESS_KEY",
            "OBJECT_STORE_SECRET_KEY",
        ),
        "legacy-compose": (
            "OSS_ENDPOINT_URL",
            "OSS_PUBLIC_ENDPOINT_URL",
            "OSS_REGION",
            "OSS_BUCKET",
            "APP_IMAGE",
            "WEB_IMAGE",
            "POSTGRES_IMAGE",
            "KAFKA_IMAGE",
            "MILVUS_IMAGE",
            "MLFLOW_IMAGE",
            "PUBLIC_BASE_URL",
            "KAFKA_CLUSTER_ID",
        ),
        "legacy-direct": (
            "BIDWB_DATABASE_URL",
            "BIDWB_STORAGE_ENDPOINT_URL",
            "BIDWB_STORAGE_BUCKET",
            "BIDWB_STORAGE_ACCESS_KEY_ID",
            "BIDWB_STORAGE_SECRET_ACCESS_KEY",
        ),
    }[entry]
    if entry == "workbench" and role and role != "api":
        required = (f"{role.upper()}_DATABASE_DSN",) + (
            tuple(name for name in required if name.startswith(("KAFKA_", "OBJECT_STORE_")))
            if role in {"worker", "research_worker"}
            else ()
        )
    missing = [
        name
        for name in required
        if not values.get(name) and not (entry == "legacy-direct" and values.get(name + "_FILE"))
    ]
    if missing:
        raise ConfigurationError("ENV_REQUIRED: " + ", ".join(missing))
    return {
        "passed": True,
        "entry": entry,
        "scope": "offline configuration names only; no dependency, permission, model or business acceptance",
        "real_calls": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument(
        "--entry", choices=("workbench", "legacy-compose", "legacy-direct"), required=True
    )
    parser.add_argument(
        "--role", choices=("api", "worker", "research_worker", "score_read", "model")
    )
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.env_file, args.entry, args.role)))
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
