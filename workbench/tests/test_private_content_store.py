"""Actual private Linux filesystem, concurrency and crash/reopen counterexamples."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from packages.storage import private_cas as cas

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX private filesystem required")


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    return directory


def test_actual_write_reopen_idempotence_and_modes(root):
    raw = b"synthetic private content"
    with cas.PrivateContentStore(root) as store:
        key = store.put_object(raw)
        assert key == cas.sha(raw) == store.put_object(raw)
        assert store.get_object(key) == raw
        commit = store.publish(b"synthetic commit")
        assert repr(store) == "<PrivateContentStore>"
    with cas.PrivateContentStore(root) as store:
        assert store.get_object(key) == raw
        assert store.get_commit(commit) == b"synthetic commit"
    assert (root / "objects").stat().st_mode & 0o777 == 0o700
    assert (root / "objects" / key).stat().st_mode & 0o777 == 0o600
    assert len(list((root / "objects").iterdir())) == 1


@pytest.mark.parametrize("key", ["../outside", "a" * 63, "A" * 64, "0" * 64, False, None])
def test_digest_names_are_closed(root, key):
    with (
        cas.PrivateContentStore(root) as store,
        pytest.raises(cas.PrivateStoreError, match="DIGEST_INVALID"),
    ):
        store.get_object(key)


@pytest.mark.parametrize("bad", [b"", "body", False])
def test_object_type_and_limits(root, bad):
    with (
        cas.PrivateContentStore(root) as store,
        pytest.raises(cas.PrivateStoreError, match="SIZE_INVALID"),
    ):
        store.put_object(bad)


def test_limit_before_write(root, monkeypatch):
    monkeypatch.setattr(cas, "MAX_OBJECT_BYTES", 5)
    with (
        cas.PrivateContentStore(root) as store,
        pytest.raises(cas.PrivateStoreError, match="SIZE_INVALID"),
    ):
        store.put_object(b"123456")
    assert list((root / "objects").iterdir()) == []


@pytest.mark.parametrize("where", ["root", "objects", "file"])
def test_public_permissions_rejected(root, where):
    with cas.PrivateContentStore(root) as store:
        key = store.put_object(b"synthetic")
        path = {"root": root, "objects": root / "objects", "file": root / "objects" / key}[where]
        path.chmod(0o755 if where != "file" else 0o644)
        with pytest.raises(cas.PrivateStoreError, match="PRIVATE_BOUNDARY_INVALID"):
            store.get_object(key)


@pytest.mark.parametrize("where", ["ancestor", "root", "objects", "file"])
def test_symlinks_rejected(root, where):
    with cas.PrivateContentStore(root) as store:
        key = store.put_object(b"synthetic")
    target = root.parent / "outside"
    target.mkdir(mode=0o700)
    if where == "ancestor":
        alias = root.parent / "alias"
        alias.symlink_to(root.parent, target_is_directory=True)
        with pytest.raises(cas.PrivateStoreError, match="IO_FAILED"):
            cas.PrivateContentStore(alias / root.name)
    elif where == "root":
        alias = root.parent / "alias"
        alias.symlink_to(root, target_is_directory=True)
        with pytest.raises(cas.PrivateStoreError, match="IO_FAILED"):
            cas.PrivateContentStore(alias)
    else:
        path = root / "objects" if where == "objects" else root / "objects" / key
        path.rename(root.parent / "old")
        path.symlink_to(target, target_is_directory=where == "objects")
        with pytest.raises(cas.PrivateStoreError, match="IO_FAILED"):
            with cas.PrivateContentStore(root) as store:
                store.get_object(key)


def test_hardlink_not_a_private_object(root):
    with cas.PrivateContentStore(root) as store:
        key = store.put_object(b"synthetic")
        os.link(root / "objects" / key, root.parent / "alias")
        with pytest.raises(cas.PrivateStoreError, match="PRIVATE_BOUNDARY_INVALID"):
            store.get_object(key)


def test_non_owner_root_rejected(root, monkeypatch):
    uid = os.geteuid()
    monkeypatch.setattr(cas.os, "geteuid", lambda: uid + 1)
    with pytest.raises(cas.PrivateStoreError, match="PRIVATE_BOUNDARY_INVALID"):
        cas.PrivateContentStore(root)


def test_busy_directory_has_bounded_wait(root, monkeypatch):
    import fcntl

    with cas.PrivateContentStore(root) as store:
        fd = os.open(root / "objects", os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            times = iter((0, 6))
            monkeypatch.setattr(cas.time, "monotonic", lambda: next(times))
            with pytest.raises(cas.PrivateStoreError, match="BUSY"):
                store.put_object(b"synthetic busy")
        finally:
            os.close(fd)


def test_fifo_does_not_block(root):
    with cas.PrivateContentStore(root) as store:
        key = "a" * 64
        os.mkfifo(root / "objects" / key, mode=0o600)
        with pytest.raises(cas.PrivateStoreError, match="PRIVATE_BOUNDARY_INVALID"):
            store.get_object(key)


def test_corruption_cannot_be_read_or_overwritten(root):
    with cas.PrivateContentStore(root) as store:
        raw = b"synthetic"
        key = store.put_object(raw)
        (root / "objects" / key).write_bytes(b"damaged!!")
        for action in (lambda: store.get_object(key), lambda: store.put_object(raw)):
            with pytest.raises(cas.PrivateStoreError, match="CONTENT_MISMATCH"):
                action()
        assert (root / "objects" / key).read_bytes() == b"damaged!!"


def test_pinned_root_and_closed_instance(root):
    store = cas.PrivateContentStore(root)
    moved = root.with_name("moved")
    root.rename(moved)
    root.mkdir(mode=0o700)
    key = store.put_object(b"synthetic")
    assert (moved / "objects" / key).exists()
    assert list(root.iterdir()) == []
    store.close()
    store.close()
    with pytest.raises(cas.PrivateStoreError, match="CLOSED"):
        store.get_object(key)


def test_concurrent_independent_instances_publish_identical_bytes(root):
    def write(index):
        with cas.PrivateContentStore(root) as store:
            key = store.put_object(b"synthetic same content")
            return key, store.get_object(key)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(24)))
    assert len(set(results)) == 1
    assert len(list((root / "objects").iterdir())) == 1


def test_short_writes_and_reopen(root, monkeypatch):
    write = cas.os.write
    monkeypatch.setattr(cas.os, "write", lambda fd, data: write(fd, data[:3]))
    with cas.PrivateContentStore(root) as store:
        key = store.put_object(b"synthetic short writes")
        assert store.get_object(key) == b"synthetic short writes"


def test_fsync_failure_leaves_no_published_key_and_no_path_in_error(root, monkeypatch):
    with cas.PrivateContentStore(root) as store:

        def broken(fd):
            raise OSError("synthetic private path must disappear")

        monkeypatch.setattr(cas.os, "fsync", broken)
        with pytest.raises(cas.PrivateStoreError, match="IO_FAILED") as captured:
            store.put_object(b"synthetic fsync failure")
        assert captured.value.__context__ is None
    assert not (root / "objects" / cas.sha(b"synthetic fsync failure")).exists()


def test_process_crash_before_publication_is_unreadable_and_recoverable(root):
    source = Path(__file__).resolve().parents[1]
    code = """import os,sys
sys.path.insert(0,sys.argv[1])
from packages.storage.private_cas import PrivateContentStore
with PrivateContentStore(sys.argv[2]) as store:
    os.link=os.rename=lambda *a,**k: os._exit(73)
    store.put_object(b'synthetic crash content')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source), str(root)], check=False, timeout=10
    )  # nosec B603
    assert result.returncode == 73
    assert all(p.name.startswith(".pending-") for p in (root / "objects").iterdir())
    with cas.PrivateContentStore(root) as store:
        with pytest.raises(cas.PrivateStoreError, match="IO_FAILED"):
            store.get_object(cas.sha(b"synthetic crash content"))
        key = store.put_object(b"synthetic crash content")
        assert store.get_object(key) == b"synthetic crash content"


def test_process_crash_after_atomic_publication_remains_readable(root):
    source = Path(__file__).resolve().parents[1]
    code = """import os,sys
sys.path.insert(0,sys.argv[1])
from packages.storage.private_cas import PrivateContentStore
with PrivateContentStore(sys.argv[2]) as store:
    def crash_after(function):
        def run(*a,**k):
            function(*a,**k)
            os._exit(74)
        return run
    os.link=crash_after(os.link)
    os.rename=crash_after(os.rename)
    store.put_object(b'synthetic published crash')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(source), str(root)], check=False, timeout=10
    )  # nosec B603
    assert result.returncode == 74
    with cas.PrivateContentStore(root) as store:
        key = cas.sha(b"synthetic published crash")
        assert store.get_object(key) == b"synthetic published crash"
        assert store.put_object(b"synthetic published crash") == key
