"""One optional private parser service; no inherited URL or credential discovery."""

import re
from pathlib import Path

VERSION = "parsing-installation/1"
URL = "http://parser:8812"
TOKEN_FILE = "/parser-private/token"  # nosec B105 # fixed private filename, never a token value.
COMPONENTS = frozenset({"api", "document", "word-controller"})


def descriptor(image):
    from deploy.fusion_full_spec import ConfigurationError, pinned_image

    if not pinned_image(image):
        raise ConfigurationError("FULL_PARSER_PINNED_IMAGE_REQUIRED")
    return {"version": VERSION, "image": image, "transport": "compose-private", "url": URL}


def validate(value):
    from deploy.fusion_full_spec import ConfigurationError

    if not isinstance(value, dict) or value != descriptor(value.get("image")):
        raise ConfigurationError("FULL_PARSER_DESCRIPTOR_INVALID")
    return value


def environment(plan, component):
    if "parser" not in plan or component not in COMPONENTS:
        return {}
    validate(plan["parser"])
    return {
        "PARSING_RUNTIME_TRANSPORT": "compose-private",
        "PARSING_RUNTIME_URL": URL,
        "PARSING_RUNTIME_TOKEN_FILE": TOKEN_FILE,
    }


def publish_token(value, directory):
    """Idempotently publish only this installation's secret to its dedicated volume."""
    import os
    import stat

    from deploy.fusion_full_spec import ConfigurationError, write_private

    token = value.get("parser_token")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ConfigurationError("FULL_PARSER_TOKEN_INVALID")
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ConfigurationError("FULL_PARSER_SECRET_VOLUME_REQUIRED")
    path = directory / "token"
    if path.exists() or path.is_symlink():
        info = path.lstat()
        parent = directory.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 65532
            or info.st_gid != 65532
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or path.read_bytes() != token.encode()
            or parent.st_uid != 65532
            or parent.st_gid != 65532
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise ConfigurationError("FULL_PARSER_SECRET_BINDING_CHANGED")
        return
    else:
        if any(directory.iterdir()):
            raise ConfigurationError("FULL_PARSER_SECRET_PARTIAL_STATE")
        directory.chmod(0o700)
        write_private(path, token.encode())
        os.chown(path, 65532, 65532)
    os.chown(directory, 65532, 65532)
