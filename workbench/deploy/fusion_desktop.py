"""Operate one explicit desktop Compose group without host private profiles."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404
from pathlib import Path
from uuid import uuid4

from deploy import fusion_desktop_compose as compose
from deploy import fusion_full_spec as spec


def directory(value):
    base = compose.ROOT / ".local/full-desktop"
    path = Path(value).absolute()
    if (
        base.is_symlink()
        or base.parent.is_symlink()
        or path.is_symlink()
        or path.resolve().parent != base.resolve()
        or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", path.name)
    ):
        raise spec.ConfigurationError("DESKTOP_LOCAL_DIRECTORY_REQUIRED")
    return path


def _write(path, value):
    with path.open("xb") as handle:
        handle.write(compose.encoded(value))


def prepare(path, *, name, origin, python_image, web_image):
    path = directory(path)
    request = compose.validate_request(
        {
            "version": compose.VERSION,
            "instance_id": uuid4().hex,
            "name": name,
            "origin": origin,
            "python_image": python_image,
            "web_image": web_image,
        }
    )
    if path.exists():
        raise spec.ConfigurationError("DESKTOP_NEW_DIRECTORY_REQUIRED")
    path.mkdir(parents=True)
    _write(path / "request.json", request)
    (path / "compose.public.env").write_bytes(b"# Explicit public-only Compose environment.\n")
    _write(path / "bootstrap.compose.json", compose.document(request, path))
    return {"directory": str(path), "project": compose.project(request), "services_started": 0}


def _environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "LANG",
            "LC_ALL",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "SystemRoot",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "PROGRAMDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "HOMEDRIVE",
            "HOMEPATH",
            "SYSTEMDRIVE",
            "COMSPEC",
            "PATHEXT",
        }
    }


def _command(path, request, filename, *arguments):
    return [
        "docker",
        "compose",
        "--project-name",
        compose.project(request),
        "--env-file",
        str(path / "compose.public.env"),
        "--file",
        str(path / filename),
        *arguments,
    ]


def _run(command, *, timeout):
    return subprocess.run(
        command, cwd=compose.ROOT, env=_environment(), check=True, timeout=timeout
    )  # nosec B603


def _request(path):
    value = json.loads((path / "request.json").read_bytes())
    return compose.validate_request(value)


def up(path):
    path = directory(path)
    request = _request(path)
    bootstrap = json.loads((path / "bootstrap.compose.json").read_bytes())
    compose.validate_document(bootstrap, request, path)
    _run(_command(path, request, "bootstrap.compose.json", "config", "--quiet"), timeout=30)
    _run(
        _command(
            path,
            request,
            "bootstrap.compose.json",
            "up",
            "--abort-on-container-exit",
            "--exit-code-from",
            "configure",
            "configure",
        ),
        timeout=180,
    )
    plan = json.loads((path / "public-plan.json").read_bytes())
    full = compose.document(request, path, plan)
    actual = path / "full.compose.json"
    raw = compose.encoded(full)
    if actual.exists():
        if actual.read_bytes() != raw:
            raise spec.ConfigurationError("DESKTOP_COMPOSE_BINDING_CHANGED")
    else:
        _write(actual, full)
        _write(
            path / "transport.json",
            {
                "version": compose.VERSION,
                "request_digest": spec.digest(request),
                "plan_digest": spec.digest(plan),
                "compose_sha256": spec.digest(raw),
            },
        )
    _run(_command(path, request, "full.compose.json", "config", "--quiet"), timeout=30)
    _run(
        _command(path, request, "full.compose.json", "up", "-d", "--wait", "--wait-timeout", "240"),
        timeout=300,
    )
    return {
        "project": compose.project(request),
        "origin": request["origin"],
        "plan_digest": spec.digest(plan),
        "private_values_exported": False,
    }


def verify(path):
    path = directory(path)
    request = _request(path)
    plan = json.loads((path / "public-plan.json").read_bytes())
    actual = json.loads((path / "full.compose.json").read_bytes())
    compose.validate_document(actual, request, path, plan)
    _run(
        _command(
            path,
            request,
            "full.compose.json",
            "--profile",
            "checks",
            "up",
            "--no-deps",
            "--abort-on-container-exit",
            "--exit-code-from",
            "validation",
            "validation",
        ),
        timeout=240,
    )
    return {
        "project": compose.project(request),
        "synthetic_transport_verified": True,
        "provider_calls": 0,
        "private_values_exported": False,
    }


def observe(path, action):
    path = directory(path)
    request = _request(path)
    if not (path / "transport.json").exists():
        actual = json.loads((path / "bootstrap.compose.json").read_bytes())
        compose.validate_document(actual, request, path)
        arguments = ("ps", "--all") if action == "status" else ("stop",)
        _run(_command(path, request, "bootstrap.compose.json", *arguments), timeout=120)
        return {
            "project": compose.project(request),
            "action": action,
            "bootstrap_only": True,
            "volumes_deleted": False,
        }
    metadata = json.loads((path / "transport.json").read_bytes())
    raw = (path / "full.compose.json").read_bytes()
    manifest = json.loads(raw)
    if (
        set(metadata) != {"version", "request_digest", "plan_digest", "compose_sha256"}
        or metadata["version"] != compose.VERSION
        or metadata["request_digest"] != spec.digest(request)
        or metadata["compose_sha256"] != spec.digest(raw)
        or manifest.get("name") != compose.project(request)
        or any(
            service.get("labels", {}).get("tender.desktop.instance") != request["instance_id"]
            for service in manifest["services"].values()
        )
    ):
        raise spec.ConfigurationError("DESKTOP_TRANSPORT_BINDING_CHANGED")
    # Source edits must not prevent observing or stopping this exact saved group.
    arguments = ("ps", "--all") if action == "status" else ("stop",)
    _run(_command(path, request, "full.compose.json", *arguments), timeout=120)
    return {"project": compose.project(request), "action": action, "volumes_deleted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "up", "verify", "status", "stop"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--name")
    parser.add_argument("--origin", default="http://127.0.0.1:5189")
    parser.add_argument("--python-image")
    parser.add_argument("--web-image")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(
                args.directory,
                name=args.name,
                origin=args.origin,
                python_image=args.python_image,
                web_image=args.web_image,
            )
        elif args.action == "up":
            result = up(args.directory)
        elif args.action == "verify":
            result = verify(args.directory)
        else:
            result = observe(args.directory, args.action)
    except Exception as error:
        code = (
            str(error) if isinstance(error, spec.ConfigurationError) else "DESKTOP_CONTROL_FAILED"
        )
        print(json.dumps({"ok": False, "code": code}))
        return 2
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
