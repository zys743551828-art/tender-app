"""POSIX local content store. Digests establish byte identity, never authority.

The host provisions the owner-only root. No environment, credentials, remote
object writes, arbitrary names, replacement, listing, or garbage collection.
"""

import hashlib
import os
import stat
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_COMMIT_BYTES = 256 * 1024


class PrivateStoreError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise PrivateStoreError("PRIVATE_STORE_" + code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def is_digest(value):
    return (
        type(value) is str
        and len(value) == 64
        and value != "0" * 64
        and all(c in "0123456789abcdef" for c in value)
    )


def safe_io(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except OSError:
            pass
        # Raise outside except: filesystem paths must not remain in __context__.
        fail("IO_FAILED")

    return wrapped


def _private(info, *, directory):
    expected = 0o700 if directory else 0o600
    if (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != expected
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        fail("PRIVATE_BOUNDARY_INVALID")


def _identity(info):
    # Reading may update atime; it does not change any content identity field.
    return tuple(
        getattr(info, key)
        for key in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


class PrivateContentStore:
    """A pinned private root; use a distinct host-provisioned root per tenant."""

    @safe_io
    def __init__(self, root):
        self._fd = -1
        if os.name != "posix":
            fail("POSIX_REQUIRED")
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            fail("ROOT_INVALID")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open("/", flags)
        try:
            # Do not resolve symlinks in any ancestor supplied by the host.
            for component in path.parts[1:]:
                following = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = following
            _private(os.fstat(fd), directory=True)
            for name in ("objects", "commits"):
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(name, flags, dir_fd=fd)
                try:
                    _private(os.fstat(child), directory=True)
                    os.fsync(child)
                finally:
                    os.close(child)
            os.fsync(fd)
            self._fd, fd = fd, -1
        finally:
            if fd != -1:
                os.close(fd)

    def __repr__(self):
        return "<PrivateContentStore>"

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()

    def close(self):
        if self._fd != -1:
            fd, self._fd = self._fd, -1
            os.close(fd)

    @contextmanager
    def _locked(self, namespace):
        import fcntl

        if self._fd == -1:
            fail("CLOSED")
        _private(os.fstat(self._fd), directory=True)
        fd = os.open(
            namespace,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=self._fd,
        )
        try:
            _private(os.fstat(fd), directory=True)
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    pass
                if time.monotonic() >= deadline:
                    fail("BUSY")
                time.sleep(0.01)
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _read(fd, key, limit):
        stream = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
        try:
            before = os.fstat(stream)
            _private(before, directory=False)
            if not 1 <= before.st_size <= limit:
                fail("SIZE_INVALID")
            chunks, size = [], 0
            while size <= limit:
                raw = os.read(stream, min(1024 * 1024, limit + 1 - size))
                if not raw:
                    break
                chunks.append(raw)
                size += len(raw)
            data = b"".join(chunks)
            after = os.fstat(stream)
            _private(after, directory=False)
            if (
                _identity(before) != _identity(after)
                or size != before.st_size
                or size > limit
                or sha(data) != key
            ):
                fail("CONTENT_MISMATCH")
            return data
        finally:
            os.close(stream)

    def _put(self, namespace, data, limit):
        if type(data) is not bytes or not 1 <= len(data) <= limit:
            fail("SIZE_INVALID")
        key = sha(data)
        with self._locked(namespace) as fd:
            try:
                existing = self._read(fd, key, limit)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing != data:
                    fail("CONTENT_MISMATCH")
                os.fsync(fd)
                return key
            pending = ".pending-" + uuid4().hex
            stream = os.open(
                pending,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=fd,
            )
            try:
                os.fchmod(stream, 0o600)
                view = memoryview(data)
                while view:
                    written = os.write(stream, view)
                    if written <= 0:
                        fail("WRITE_INCOMPLETE")
                    view = view[written:]
                os.fsync(stream)
                _private(os.fstat(stream), directory=False)
            finally:
                os.close(stream)
            # The private directory lock covers the absence check and publication.
            # Rename leaves one link even if the process dies immediately afterward.
            # All cooperating publishers use this port; same-UID hostile mutation
            # is outside the isolation boundary and is detected when bytes are read.
            os.rename(pending, key, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
            return key

    @safe_io
    def put_object(self, data):
        return self._put("objects", data, MAX_OBJECT_BYTES)

    @safe_io
    def publish(self, data):
        """Publish a commit only after the caller verified every referenced object."""
        return self._put("commits", data, MAX_COMMIT_BYTES)

    @safe_io
    def get_object(self, key):
        return self._get("objects", key, MAX_OBJECT_BYTES)

    @safe_io
    def get_commit(self, key):
        return self._get("commits", key, MAX_COMMIT_BYTES)

    def _get(self, namespace, key, limit):
        if not is_digest(key):
            fail("DIGEST_INVALID")
        with self._locked(namespace) as fd:
            return self._read(fd, key, limit)
