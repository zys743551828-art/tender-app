"""Operate one explicit desktop Compose group without host private profiles."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
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


def prepare(path, *, name, origin, python_image, web_image, word=False, model=False):
    path = directory(path)
    if model and not word:
        raise spec.ConfigurationError("DESKTOP_WORD_VERSION_REQUIRED_FOR_MODEL")
    if path.exists():
        raise spec.ConfigurationError("DESKTOP_NEW_DIRECTORY_REQUIRED")
    request = {
        "version": compose.VERSION,
        "instance_id": uuid4().hex,
        "name": name,
        "origin": origin,
        "python_image": python_image,
        "web_image": web_image,
    }
    compose.validate_request(request)
    path.mkdir(parents=True)
    if word:
        from deploy import fusion_word_spec

        request["version"] = compose.WORD_VERSION
        request["word"] = fusion_word_spec.bundle(path / "word-image-preparation.json")
        if model:
            request["model_configured"] = True
    compose.validate_request(request)
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


def _run(command, *, timeout, input=None):
    return subprocess.run(
        command, cwd=compose.ROOT, env=_environment(), check=True, timeout=timeout, input=input
    )  # nosec B603


def _request(path, *, check_word_sources=True):
    value = json.loads((path / "request.json").read_bytes())
    return compose.validate_request(value, check_word_sources=check_word_sources)


def _model_file(path):
    """Read only an explicitly selected existing profile; never emit its contents."""
    try:
        path = Path(path)
        before = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or not 0 < before.st_size <= 16384
            or (os.name != "nt" and stat.S_IMODE(before.st_mode) != 0o600)
        ):
            raise ValueError()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError()
            raw = stream.read(16385)
            after = os.fstat(stream.fileno())
        if len(raw) != opened.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ):
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        spec.validate_model(value)
        return value
    except (OSError, ValueError, spec.ConfigurationError):
        raise spec.ConfigurationError("DESKTOP_MODEL_PROFILE_INVALID") from None


def up(path, *, word_restart=False, admin_password=None, model=None):
    path = directory(path)
    request = _request(path)
    if model is not None and not request.get("model_configured", False):
        raise spec.ConfigurationError("DESKTOP_MODEL_NOT_DECLARED")
    if word_restart and request["version"] != compose.WORD_VERSION:
        raise spec.ConfigurationError("DESKTOP_WORD_INSTALLATION_REQUIRED")
    bootstrap = json.loads((path / "bootstrap.compose.json").read_bytes())
    compose.validate_document(bootstrap, request, path)
    _run(_command(path, request, "bootstrap.compose.json", "config", "--quiet"), timeout=30)
    bootstrap_container = None
    if admin_password is not None or model is not None:
        payload = {"admin_password": admin_password, "model": model}
        bootstrap_container = compose.project(request) + "-bootstrap-" + uuid4().hex[:12]
        _run(
            _command(
                path,
                request,
                "bootstrap.compose.json",
                "run",
                "--rm",
                "--name",
                bootstrap_container,
                "--no-deps",
                "-T",
                "--interactive",
                "configure",
                "python",
                "-m",
                "deploy.fusion_desktop_private",
                "configure",
                "--bootstrap-stdin",
            ),
            timeout=180,
            input=json.dumps(payload).encode("utf-8"),
        )
    else:
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
                "version": request["version"],
                "request_digest": spec.digest(request),
                "plan_digest": spec.digest(plan),
                "compose_sha256": spec.digest(raw),
            },
        )
    _run(_command(path, request, "full.compose.json", "config", "--quiet"), timeout=30)
    _run(
        _command(
            path,
            request,
            "full.compose.json",
            *(["--profile", "model"] if request.get("model_configured", False) else []),
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "240",
        ),
        timeout=300,
    )
    word_ready = None
    if request["version"] == compose.WORD_VERSION:
        from deploy import fusion_desktop_word

        try:
            word_ready = (
                fusion_desktop_word.restart(path, request, plan)
                if word_restart
                else fusion_desktop_word.start(path, request, plan)
            )
        except Exception:
            # An unready Word installation must not leave accepting consumers running.
            try:
                fusion_desktop_word.stop(path, request)
            finally:
                _run(_command(path, request, "full.compose.json", "stop"), timeout=360)
            raise
    return {
        "project": compose.project(request),
        "origin": request["origin"],
        "plan_digest": spec.digest(plan),
        "private_values_exported": False,
        **({"bootstrap_input_container": bootstrap_container} if bootstrap_container else {}),
        **({"word": word_ready} if word_ready is not None else {}),
    }


def verify(path):
    path = directory(path)
    request = _request(path)
    plan = json.loads((path / "public-plan.json").read_bytes())
    actual = json.loads((path / "full.compose.json").read_bytes())
    compose.validate_document(actual, request, path, plan)
    if request["version"] == compose.WORD_VERSION:
        from deploy import fusion_desktop_word

        if not fusion_desktop_word.status(path, request)["ready"]:
            raise spec.ConfigurationError("DESKTOP_WORD_EXECUTOR_UNAVAILABLE")
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
    request = _request(path, check_word_sources=False)
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
        or metadata["version"] != request["version"]
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
    word_result = None
    if request["version"] == compose.WORD_VERSION:
        from deploy import fusion_desktop_word

        if action == "status":
            word_result = fusion_desktop_word.status(path, request)
        else:
            before, drained = {"ready": False}, False
            try:
                before = fusion_desktop_word.status(path, request)
                # Stop producers first, keeping executors alive while consumers
                # drain their existing 120/240-second bounded computation.
                _run(
                    _command(
                        path,
                        request,
                        "full.compose.json",
                        "stop",
                        "web",
                        "api",
                        "word-controller",
                        "build-controller",
                        "relay",
                    ),
                    timeout=120,
                )
                _run(
                    _command(
                        path,
                        request,
                        "full.compose.json",
                        "stop",
                        "--timeout",
                        "300",
                        "worker-document",
                        "worker-export",
                    ),
                    timeout=330,
                )
                drained = True
            finally:
                try:
                    word_result = fusion_desktop_word.stop(
                        path, request, peers_stopped=before["ready"] and drained
                    )
                finally:
                    _run(_command(path, request, "full.compose.json", "stop"), timeout=120)
            return {
                "project": compose.project(request),
                "action": action,
                "volumes_deleted": False,
                "word": word_result,
            }
    arguments = ("ps", "--all") if action == "status" else ("stop",)
    _run(_command(path, request, "full.compose.json", *arguments), timeout=120)
    return {
        "project": compose.project(request),
        "action": action,
        "volumes_deleted": False,
        **({"word": word_result} if word_result is not None else {}),
    }


def main(argv=None):
    # Explicit opt-out of compatibility dotenv loading during profile construction.
    os.environ["WORKBENCH_ENV_FILE"] = "explicit-fusion-desktop-installation"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "up", "restart-word", "verify", "status", "stop")
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--name")
    parser.add_argument("--origin", default="http://127.0.0.1:5189")
    parser.add_argument("--python-image")
    parser.add_argument("--web-image")
    parser.add_argument(
        "--word", action="store_true", help="Install the explicit full/2 Word overlay"
    )
    parser.add_argument(
        "--model", action="store_true", help="Declare an optional DeepSeek profile at preparation"
    )
    parser.add_argument(
        "--ask-admin-password",
        action="store_true",
        help="Prompt privately for the bootstrap admin password",
    )
    parser.add_argument(
        "--model-profile",
        type=Path,
        help="Explicit existing private JSON with the three DeepSeek settings",
    )
    args = parser.parse_args(argv)
    try:
        if (
            (args.ask_admin_password or args.model_profile is not None)
            and args.action not in {"up", "restart-word"}
        ) or ((args.word or args.model) and args.action != "prepare"):
            raise spec.ConfigurationError("DESKTOP_OPTION_ACTION_MISMATCH")
        if args.action == "prepare":
            result = prepare(
                args.directory,
                name=args.name,
                origin=args.origin,
                python_image=args.python_image,
                web_image=args.web_image,
                word=args.word,
                model=args.model,
            )
        elif args.action in {"up", "restart-word"}:
            password = (
                getpass.getpass("Bootstrap admin password: ") if args.ask_admin_password else None
            )
            model = _model_file(args.model_profile) if args.model_profile is not None else None
            result = up(
                args.directory,
                word_restart=args.action == "restart-word",
                admin_password=password,
                model=model,
            )
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
    ready = args.action != "status" or result.get("word", {}).get("ready", True)
    print(json.dumps({"ok": ready, **result}))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
