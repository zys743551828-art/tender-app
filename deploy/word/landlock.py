"""无特权的逐任务文件与父进程隔离；能力不足就拒绝执行转换。"""

import ctypes
import os
import platform
from pathlib import Path

MIN_ABI = 6
HANDLED_FS = (1 << 15) - 1  # ABI 3：执行、读取、写入、创建、删除、重命名、截断
READ = (1 << 0) | (1 << 2) | (1 << 3)
WRITE_FILE = (1 << 1) | (1 << 2) | (1 << 14)


class Ruleset(ctypes.Structure):
    _fields_ = [
        ("fs", ctypes.c_uint64),
        ("net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _libc():
    if platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("word_sandbox_architecture_unsupported")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    return library


def abi_version():
    result = _libc().syscall(444, 0, 0, 1)
    if result < MIN_ABI:
        raise RuntimeError("word_sandbox_unavailable")
    return int(result)


def restrict(job_dir):
    """只在单线程 converter 的 fork 子进程调用，随后立即 exec 固定 LibreOffice。"""
    abi_version()
    library = _libc()
    attributes = Ruleset(
        HANDLED_FS, 0, 3
    )  # 禁止向域外进程发信号及连接域外抽象 Unix socket
    descriptor = library.syscall(
        444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0
    )
    if descriptor < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset")
    try:
        public = ["/usr", "/lib", "/lib64", "/etc", "/var/cache/fontconfig"]
        regular = [
            "/proc/cpuinfo",
            "/proc/meminfo",
            "/proc/stat",
            "/dev/urandom",
            "/dev/random",
        ]
        paths = [(name, READ) for name in public if Path(name).exists()]
        paths.extend((name, 1 << 2) for name in regular if Path(name).exists())
        paths.extend(
            [(str(Path(job_dir).resolve()), HANDLED_FS), ("/dev/null", WRITE_FILE)]
        )
        for path, rights in paths:
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(rights, parent)
                if library.syscall(445, descriptor, 1, ctypes.byref(rule), 0):
                    raise OSError(ctypes.get_errno(), "landlock_add_rule")
            finally:
                os.close(parent)
        if library.prctl(38, 1, 0, 0, 0) or library.syscall(446, descriptor, 0):
            raise OSError(ctypes.get_errno(), "landlock_restrict_self")
    finally:
        os.close(descriptor)
