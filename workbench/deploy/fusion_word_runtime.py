"""Fixed full/2 Word component overlay, with no Docker access in the component."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from deploy import fusion_full_runtime as runtime
from deploy import fusion_full_spec as base
from deploy import fusion_word_spec as word

COMPONENTS = {"api", "document", "export", "word-controller"}
PROFILE_ENVIRONMENT = {
    "external": "WORD_RENDER_PROFILE_PATH",
    "page": "AUTHORING_GENERATED_RENDER_PROFILE_PATH",
    "rich": "AUTHORING_RICH_RENDER_PROFILE_PATH",
}


def _private_json(path):
    """Read the same pinned regular inode whose private ownership was checked."""
    if not sys.platform.startswith("linux"):
        raise base.ConfigurationError("FULL_WORD_LINUX_REQUIRED")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 65532
            or info.st_gid != 65532
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 < info.st_size <= 1024 * 1024
        ):
            raise ValueError()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(1024 * 1024 + 1)
        after = os.fstat(descriptor)
        if len(raw) != info.st_size or (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ):
            raise ValueError()
        return json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise base.ConfigurationError("FULL_WORD_PRIVATE_FILE_INVALID") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _directory(path):
    try:
        if not path.is_absolute() or path.is_symlink():
            raise ValueError()
        for parent in path.parents:
            if parent.is_symlink():
                raise ValueError()
        info = path.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 65532
            or info.st_gid != 65532
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ValueError()
    except (OSError, ValueError):
        raise base.ConfigurationError("FULL_WORD_PROFILE_DIRECTORY_INVALID") from None


def environment(base_profile, component, installation, profile_directory=Path("/runtime")) -> dict:
    if component not in COMPONENTS:
        raise base.ConfigurationError("FULL_WORD_COMPONENT_INVALID")
    allowed = runtime.environment(base_profile, component)
    role = base.COMMANDS[component][0]
    word.validate_installation(installation, base_profile, role)
    directory = Path(profile_directory)
    _directory(directory)
    if _private_json(directory / "word-profile.json") != installation:
        raise base.ConfigurationError("FULL_WORD_INSTALLATION_FILE_CHANGED")
    for lane in word.ROLE_LANES[role]:
        if (
            _private_json(directory / word.PROFILE_FILES[lane])
            != installation["bundle"]["profiles"][lane]
        ):
            raise base.ConfigurationError("FULL_WORD_RENDERER_FILE_CHANGED")
    lanes = (
        ("external", "page", "rich")
        if component == "api"
        else ("external",)
        if component in {"document", "word-controller"}
        else ()
    )
    for lane in lanes:
        allowed[PROFILE_ENVIRONMENT[lane]] = str(directory / word.PROFILE_FILES[lane])
    if component in {"document", "export"}:
        # Fixed Linux private tmpfs mailbox; transport verifies the actual mount.
        allowed["WORD_RENDER_EXECUTION_DIRECTORY"] = "/tmp/word-execution"  # nosec B108
    return allowed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=sorted(COMPONENTS))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    directory = Path("/runtime")
    try:
        profile = _private_json(directory / "profile.json")
        installation = _private_json(directory / "word-profile.json")
        allowed = environment(profile, args.component, installation, directory)
        result = runtime.probe.check(profile)
        if args.check and args.component == "api":
            result["http"] = runtime.http_ready()
    except Exception as error:
        code = (
            str(error) if isinstance(error, base.ConfigurationError) else "FULL_WORD_STARTUP_FAILED"
        )
        raise SystemExit(code) from None
    if args.check:
        result["word"] = {"profiles_verified": True, "executor_health_checked": False}
        print(json.dumps(result))
        return
    _, command = base.COMMANDS[args.component]
    # The executable and module arguments come only from the fixed component map.
    os.execve(sys.executable, [sys.executable, "-m", *command], allowed)  # nosec B606


if __name__ == "__main__":
    main()
