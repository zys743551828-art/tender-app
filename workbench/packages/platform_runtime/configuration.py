"""Legacy-compatible configuration parsing, invoked explicitly by a composition root."""

import os
import shlex
from collections.abc import Mapping, MutableMapping
from pathlib import Path


def load_development_defaults(root: Path, environment: MutableMapping[str, str]) -> None:
    """Preserve precedence and the purpose-profile opt-out; never log values.

    WORKBENCH_ENV_FILE is the existing opt-out marker, not a path to read here.
    Calling code owns when bootstrap occurs. Importing this module performs no I/O.
    """
    path = root / ".env"
    if environment.get("WORKBENCH_ENV_FILE") or not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            parts = shlex.split(value, comments=True)
            environment.setdefault(key.strip(), parts[0] if parts else "")


def bootstrap_legacy(root: Path) -> None:
    """Compatibility entrypoint; new callers can supply an isolated mapping instead."""
    load_development_defaults(root, os.environ)


def required(name: str, environment: Mapping[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    value = values.get(name)
    if not value:
        raise RuntimeError(f"缺少配置 {name}")
    return value
