"""隔离转换与保守的文字对应检查；复杂布局始终保留核实要求。"""

import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

from inspection import InspectionError, inspect_upload, public_report
from landlock import abi_version

MAX_PDF = 50 * 1024 * 1024
ROOT = Path(__file__).resolve().parent


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def font_coverage():
    output = subprocess.check_output(
        ["/usr/bin/fc-list", "--format", "%{charset}\n"], timeout=15, text=True
    )
    points = set()
    for token in output.split():
        if not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)?", token):
            raise ValueError("font_catalog_invalid")
        values = [int(value, 16) for value in token.split("-")]
        if values[-1] > 0x10FFFF:
            raise ValueError("font_catalog_invalid")
        points.update(range(values[0], values[-1] + 1))
    return points


def font_substitutions(names):
    substitutions = []
    for requested in names:
        matched = subprocess.check_output(
            ["/usr/bin/fc-match", "--format", "%{family}", "--", requested],
            timeout=3,
            text=True,
        ).strip()
        if normalized(requested).casefold() not in [
            normalized(name).casefold() for name in matched.split(",")
        ]:
            substitutions.append({"requested": requested, "used": matched[:200]})
    return substitutions


def read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= limit:
            raise ValueError("invalid_output_file")
        data = stream.read(limit + 1)
    if len(data) != metadata.st_size:
        raise ValueError("invalid_output_size")
    return data


def render(data, filename, profile):
    started = time.monotonic()
    result = {
        "contract": "word-conversion-1",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "renderer_fingerprint": profile["fingerprint"],
        "state": "failed",
        "conversion_attempted": False,
        "inspection": None,
        "gaps": [],
    }
    try:
        inspection = inspect_upload(filename, data, result["source_sha256"], len(data))[
            "inspection"
        ]
        if inspection is None:
            raise ValueError("word_format_unsupported")
        result["inspection"] = public_report(inspection)
        if not inspection["conversion_eligible"]:
            result["error_code"] = "word_content_not_supported"
            result["gaps"] = inspection["active_content_gaps"]
            return result, None
        abi_version()
        with tempfile.TemporaryDirectory(prefix="word-", dir="/work") as directory:
            job = Path(directory)
            (job / "source.docx").write_bytes(data)
            (job / "out").mkdir()
            (job / "profile/user").mkdir(parents=True)
            (job / "profile/user/registrymodifications.xcu").write_text(
                '<oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
                '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>',
                encoding="utf-8",
            )
            command = [sys.executable, str(ROOT / "child.py"), str(job)]
            deadline = time.monotonic() + 45
            # 新建独立配置时 LibreOffice 用 81 请求重新启动，最多在同一时限内重启一次。
            for attempt in range(2):
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    cwd=job,
                    env={
                        "PATH": "/usr/local/bin:/usr/bin:/bin",
                        "LANG": "C.UTF-8",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                result["conversion_attempted"] = True
                try:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    result["error_code"] = "word_conversion_timeout"
                    return result, None
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                if process.returncode != 81 or attempt:
                    break
            if process.returncode:
                raise ValueError("word_conversion_failed")
            pdf = read_regular(job / "out/source.pdf", MAX_PDF)
            (job / "inspection.json").write_text(
                json.dumps(inspection, ensure_ascii=False), encoding="utf-8"
            )
            validation = subprocess.Popen(
                [sys.executable, str(ROOT / "validator.py"), str(job)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                cwd=job,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            try:
                validation.wait(timeout=20)
            finally:
                try:
                    os.killpg(validation.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                validation.wait()
            if validation.returncode:
                raise ValueError("word_pdf_validation_failed")
            result.update(json.loads(read_regular(job / "validation.json", 2097152)))
        return result, pdf
    except InspectionError as error:
        result["error_code"] = error.code.lower()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        result["error_code"] = "word_conversion_failed"
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result, None
