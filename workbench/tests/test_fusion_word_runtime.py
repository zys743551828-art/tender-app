"""Minimal component environment and private installed-file eligibility."""

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy import fusion_word_runtime as runtime


@pytest.fixture
def overlay(monkeypatch):
    installed = {
        "bundle": {"profiles": {lane: {"lane": lane} for lane in runtime.word.PROFILE_FILES}}
    }
    reads, validations = [], []
    base_environment = {"PATH": "/fixed", "WORKER_DATABASE_DSN": "synthetic"}
    monkeypatch.setattr(
        runtime.runtime, "environment", lambda profile, component: dict(base_environment)
    )
    monkeypatch.setattr(
        runtime.word, "validate_installation", lambda *args: validations.append(args)
    )
    monkeypatch.setattr(runtime, "_directory", lambda path: None)

    def read(path):
        reads.append(path.name)
        if path.name == "word-profile.json":
            return installed
        lane = next(key for key, name in runtime.word.PROFILE_FILES.items() if name == path.name)
        return installed["bundle"]["profiles"][lane]

    monkeypatch.setattr(runtime, "_private_json", read)
    return installed, reads, validations, base_environment


@pytest.mark.parametrize(
    "component,role,lanes,transport",
    [
        ("api", "api", ("external", "page", "rich"), False),
        ("document", "worker", ("external",), True),
        ("export", "worker", (), True),
        ("word-controller", "controller", ("external",), False),
    ],
)
def test_component_gets_only_required_paths_and_transport(
    overlay, component, role, lanes, transport, monkeypatch
):
    installed, reads, validations, base_environment = overlay
    monkeypatch.setenv("OWNER_DATABASE_DSN", "foreign-owner")
    monkeypatch.setenv("AUTHORING_RICH_RENDER_PROFILE_PATH", "foreign-path")
    profile = {"role": role}
    directory = Path("/runtime")
    actual = runtime.environment(profile, component, installed, directory)
    expected = dict(base_environment)
    expected.update(
        {
            runtime.PROFILE_ENVIRONMENT[lane]: str(directory / runtime.word.PROFILE_FILES[lane])
            for lane in lanes
        }
    )
    if transport:
        expected["WORD_RENDER_EXECUTION_DIRECTORY"] = "/tmp/word-execution"
    assert actual == expected
    assert validations == [(installed, profile, role)]
    assert reads == [
        "word-profile.json",
        *(runtime.word.PROFILE_FILES[lane] for lane in runtime.word.ROLE_LANES[role]),
    ]


@pytest.mark.parametrize(
    "component", ["comparison", "relay", "build-controller", "review", "unknown"]
)
def test_nonword_components_never_enter_overlay(overlay, component):
    with pytest.raises(runtime.base.ConfigurationError, match="FULL_WORD_COMPONENT_INVALID"):
        runtime.environment({}, component, overlay[0])
    assert overlay[1] == []


@pytest.mark.parametrize(
    "attack", ["relative", "symlink", "parent_link", "owner", "group", "mode", "regular"]
)
def test_profile_directory_refuses_links_foreign_owner_or_public_permissions(attack):
    value = dict(st_mode=stat.S_IFDIR | 0o700, st_uid=65532, st_gid=65532)
    if attack in {"owner", "group"}:
        value["st_uid" if attack == "owner" else "st_gid"] = 0
    if attack == "mode":
        value["st_mode"] = stat.S_IFDIR | 0o755
    if attack == "regular":
        value["st_mode"] = stat.S_IFREG | 0o700
    path = SimpleNamespace(
        is_absolute=lambda: attack != "relative",
        is_symlink=lambda: attack == "symlink",
        parents=[SimpleNamespace(is_symlink=lambda: attack == "parent_link")],
        stat=lambda: SimpleNamespace(**value),
    )
    with pytest.raises(
        runtime.base.ConfigurationError, match="FULL_WORD_PROFILE_DIRECTORY_INVALID"
    ):
        runtime._directory(path)


@pytest.mark.parametrize(
    "file", ["word-profile.json", "word-external.json", "word-page.json", "word-rich.json"]
)
def test_installed_file_must_equal_bound_bundle(overlay, monkeypatch, file):
    original = runtime._private_json
    monkeypatch.setattr(
        runtime, "_private_json", lambda path: {} if path.name == file else original(path)
    )
    with pytest.raises(runtime.base.ConfigurationError, match="FULL_WORD_.*_FILE_CHANGED"):
        runtime.environment({}, "api", overlay[0])


@pytest.mark.parametrize("attack", ["owner", "group", "mode", "hardlink", "fifo", "large", "empty"])
def test_private_json_rejects_unsafe_inode_before_read(monkeypatch, attack):
    # Exercise the actual Linux predicate even on the Windows test controller.
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), raising=False)
    monkeypatch.setattr(runtime.os, "O_NONBLOCK", getattr(os, "O_NONBLOCK", 0), raising=False)
    value = dict(st_mode=stat.S_IFREG | 0o600, st_uid=65532, st_gid=65532, st_nlink=1, st_size=2)
    field, replacement = {
        "owner": ("st_uid", 0),
        "group": ("st_gid", 0),
        "mode": ("st_mode", stat.S_IFREG | 0o644),
        "hardlink": ("st_nlink", 2),
        "fifo": ("st_mode", stat.S_IFIFO | 0o600),
        "large": ("st_size", 1024 * 1024 + 1),
        "empty": ("st_size", 0),
    }[attack]
    value[field] = replacement
    closed = []
    monkeypatch.setattr(runtime.os, "open", lambda *args: 999)
    monkeypatch.setattr(runtime.os, "fstat", lambda fd: SimpleNamespace(**value))
    monkeypatch.setattr(runtime.os, "close", closed.append)
    with pytest.raises(runtime.base.ConfigurationError, match="FULL_WORD_PRIVATE_FILE_INVALID"):
        runtime._private_json(Path("/runtime/word-profile.json"))
    assert closed == [999]


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="requires actual Linux inode ownership"
)
def test_actual_linux_private_file_symlink_and_permissions(tmp_path):
    if os.geteuid() != 65532 or os.getegid() != 65532:
        pytest.skip("actual runtime uid/gid 65532 required")
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"ok": True}))
    path.chmod(0o600)
    assert runtime._private_json(path) == {"ok": True}
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    with pytest.raises(runtime.base.ConfigurationError):
        runtime._private_json(link)
    path.chmod(0o644)
    with pytest.raises(runtime.base.ConfigurationError):
        runtime._private_json(path)


def test_health_checks_profiles_and_original_probe_without_claiming_executor(
    overlay, monkeypatch, capsys
):
    installed = overlay[0]
    monkeypatch.setattr(
        runtime, "_private_json", lambda path: {} if path.name == "profile.json" else installed
    )
    monkeypatch.setattr(runtime, "environment", lambda *args: {"fixed": "environment"})
    monkeypatch.setattr(runtime.runtime.probe, "check", lambda profile: {"ready": True})
    monkeypatch.setattr(runtime.runtime, "http_ready", lambda: {"listener_verified": True})
    runtime.main(["api", "--check"])
    value = json.loads(capsys.readouterr().out)
    assert value["word"] == {"profiles_verified": True, "executor_health_checked": False}
    assert value["http"] == {"listener_verified": True}


def test_start_executes_only_existing_fixed_component_with_verified_environment(
    overlay, monkeypatch
):
    installed = overlay[0]
    calls = []
    monkeypatch.setattr(
        runtime, "_private_json", lambda path: {} if path.name == "profile.json" else installed
    )
    monkeypatch.setattr(runtime, "environment", lambda *args: {"fixed": "environment"})
    monkeypatch.setattr(runtime.runtime.probe, "check", lambda profile: {"ready": True})
    monkeypatch.setattr(runtime.os, "execve", lambda *args: calls.append(args))
    runtime.main(["export"])
    assert calls == [
        (
            sys.executable,
            [sys.executable, "-m", "apps.worker", "consume-export"],
            {"fixed": "environment"},
        )
    ]
