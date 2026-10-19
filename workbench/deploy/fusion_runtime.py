"""API-only entry point for the isolated local fusion Compose group."""

import os
import sys
from pathlib import Path

from deploy.initialize_database import file_configuration

API_KEYS = frozenset({"API_DATABASE_DSN", "APP_ORIGIN", "SESSION_SECRET", "CSRF_SECRET"})
# Internal Compose network; nginx alone exposes a loopback host port.
API_BIND_HOST = "0.0.0.0"  # nosec B104


def api_environment(path=Path("/runtime/api.env")):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("FUSION_API_PROFILE_MUST_BE_PRIVATE")
    values = file_configuration(path)
    if set(values) != API_KEYS or any(not value for value in values.values()):
        raise RuntimeError("FUSION_API_PROFILE_KEYS_INVALID")
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": "/workspace",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "WORKBENCH_ENV_FILE": "explicit-fusion-no-business-profile",
        **values,
    }


def main():
    environment = api_environment()
    # Same interpreter and fixed module, without shell or user arguments.
    os.execve(  # nosec B606
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.api.main:app",
            "--host",
            API_BIND_HOST,
            "--port",
            "8000",
        ],
        environment,
    )


if __name__ == "__main__":
    main()
