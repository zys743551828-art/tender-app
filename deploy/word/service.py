"""无网络、无凭据转换队列；共享输入只读，子进程不能访问队列或父进程。"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from landlock import abi_version
from renderer import read_regular, render

INPUT = Path("/word-input")
OUTPUT = Path("/word-output")
ROOT = Path(__file__).resolve().parent


def publish(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def confinement():
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        os.getuid() != 65534
        or status["NoNewPrivs"].strip() != "1"
        or int(status["CapEff"].strip(), 16)
    ):
        raise RuntimeError("word_container_privileges_invalid")
    if set(os.listdir("/sys/class/net")) != {"lo"}:
        raise RuntimeError("word_container_network_invalid")
    root = next(
        line
        for line in Path("/proc/mounts").read_text().splitlines()
        if line.split()[1] == "/"
    )
    if "ro" not in root.split()[3].split(","):
        raise RuntimeError("word_container_root_not_readonly")
    if os.access("/tmp", os.W_OK) or os.access("/var/tmp", os.W_OK):  # nosec B108：只核验公共目录不可写，不在此创建文件
        raise RuntimeError("word_shared_temporary_directory_writable")
    work = Path("/work").stat()
    if work.st_uid != os.getuid() or work.st_mode & 0o777 != 0o700:
        raise RuntimeError("word_private_work_directory_invalid")
    return {
        "network": "none",
        "no_new_privileges": True,
        "capabilities": 0,
        "readonly_root": True,
        "landlock_abi": abi_version(),
    }


def health():
    receipt = json.loads((OUTPUT / "heartbeat.json").read_text())
    return 0 if 0 <= time.time() - receipt["time"] < 120 else 1


def main():
    profile = json.loads((ROOT / "renderer-manifest.json").read_text())
    isolated = confinement()
    publish(
        OUTPUT / "renderer.json",
        json.dumps(
            {"fingerprint": profile["fingerprint"], "isolation": isolated}
        ).encode(),
    )
    while True:
        publish(
            OUTPUT / "heartbeat.json",
            json.dumps(
                {"time": time.time(), "fingerprint": profile["fingerprint"]}
            ).encode(),
        )
        for request_path in sorted(INPUT.glob("*.request.json")):
            identity = request_path.name.removesuffix(".request.json")
            if (
                not re.fullmatch(r"[0-9a-f]{32}", identity)
                or (OUTPUT / f"{identity}.json").exists()
            ):
                continue
            report = {
                "state": "failed",
                "error_code": "word_request_invalid",
                "conversion_attempted": False,
                "renderer_fingerprint": profile["fingerprint"],
                "operation_id": identity,
            }
            try:
                request = json.loads(read_regular(request_path, 8192))
                if request["renderer_fingerprint"] != profile["fingerprint"]:
                    raise ValueError("renderer_mismatch")
                source = read_regular(INPUT / f"{identity}.docx", 104857600)
                if (
                    hashlib.sha256(source).hexdigest() != request["source_sha256"]
                    or len(source) != request["source_bytes"]
                ):
                    raise ValueError("source_mismatch")
                report, pdf = render(source, request["filename"], profile)
                report.update({"operation_id": identity, "isolation": isolated})
                if pdf is not None:
                    publish(OUTPUT / f"{identity}.pdf", pdf)
            except (OSError, ValueError, KeyError, TypeError):
                pass
            publish(
                OUTPUT / f"{identity}.json",
                json.dumps(report, ensure_ascii=False).encode(),
            )
        for path in OUTPUT.iterdir():
            match = re.fullmatch(r"([0-9a-f]{32})\.(?:json|pdf)", path.name)
            if (
                match
                and not (INPUT / f"{match[1]}.request.json").exists()
                and time.time() - path.stat().st_mtime > 120
            ):
                path.unlink(missing_ok=True)
        time.sleep(0.25)


if __name__ == "__main__":
    if "--health" in sys.argv:
        raise SystemExit(health())
    main()
