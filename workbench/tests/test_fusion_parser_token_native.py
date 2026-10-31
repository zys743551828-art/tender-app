"""Explicit disposable Linux tmpfs checks; never inspect a real installation token."""

import os
import sys
from pathlib import Path

import pytest

from packages.parsing.http_port import ParsingUnavailable, runtime_token

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.environ.get("RUN_PARSER_TOKEN_NATIVE") != "1",
    reason="requires an explicitly owned disposable /parser-private tmpfs",
)
TOKEN = "synthetic-parser-token-" + "x" * 40


@pytest.fixture
def token_file(monkeypatch):
    directory = Path("/parser-private")
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    assert any(line.split()[4] == str(directory) and " - tmpfs " in line for line in mounts)
    assert not any(directory.iterdir())
    directory.chmod(0o700)
    os.chown(directory, 65532, 65532)
    path = directory / "token"
    path.write_text(TOKEN)
    path.chmod(0o600)
    os.chown(path, 65532, 65532)
    monkeypatch.setenv("PARSING_RUNTIME_TRANSPORT", "compose-private")
    monkeypatch.setenv("PARSING_RUNTIME_TOKEN_FILE", str(path))
    monkeypatch.delenv("PARSING_RUNTIME_TOKEN", raising=False)
    try:
        yield path
    finally:
        for child in directory.iterdir():
            assert child.name in {"token", "linked", "target"}
            child.unlink()


def test_exact_private_regular_file_is_read(token_file):
    assert runtime_token() == TOKEN


@pytest.mark.parametrize(
    "mutation",
    ["world_readable", "wrong_owner", "hard_link", "symlink", "directory_open", "bad_text"],
)
def test_unsafe_token_files_are_rejected_without_another_source(token_file, mutation):
    if mutation == "world_readable":
        token_file.chmod(0o644)
    elif mutation == "wrong_owner":
        os.chown(token_file, 0, 0)
    elif mutation == "hard_link":
        (token_file.parent / "linked").hardlink_to(token_file)
    elif mutation == "symlink":
        token_file.rename(token_file.parent / "target")
        token_file.symlink_to("target")
    elif mutation == "directory_open":
        token_file.parent.chmod(0o755)
    else:
        token_file.write_text(TOKEN + "\n")
    with pytest.raises(ParsingUnavailable, match="PARSING_RUNTIME_TOKEN_FILE_INVALID"):
        runtime_token()
