"""Select a frozen conversion protocol; legacy Word03 stays byte-for-byte intact."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from packages.domain.errors import DomainError
from packages.word_intake import execution_transport, prebuilt, renderer


def configured_profile():
    filename = os.environ.get("WORD_RENDER_PROFILE_PATH")
    if not filename:
        return renderer.configured_profile()
    path = Path(filename)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("profile")
        profile = json.loads(path.read_text(encoding="utf-8"))
        if profile.get("identity", {}).get("protocol") == prebuilt.PROTOCOL:
            prebuilt.validate_profile(profile)
            return profile
    except (OSError, ValueError, TypeError, AttributeError, prebuilt.PrebuiltError):
        raise DomainError(
            "WORD_RENDER_PROFILE_INVALID", "转换配置不可用，请重新安装所选版本", 503
        ) from None
    return renderer.configured_profile()


def render(source, profile):
    if profile.get("identity", {}).get("protocol") == prebuilt.PROTOCOL:
        test_directory = os.environ.get("WORD_RENDER_TEST_RECEIPT_DIRECTORY")
        if test_directory:
            directory = Path(test_directory)
            if (
                os.environ.get("RUN_WORD_PREBUILT_PG") != "1"
                or not directory.is_absolute()
                or directory.is_symlink()
                or not directory.is_dir()
            ):
                raise DomainError("WORD_TEST_RECEIPT_CONFIG_INVALID", "测试资源回执目录无效", 503)
            # Only the explicit disposable acceptance environment selects this
            # durable directory. Requests cannot choose a receipt path.
            receipt = directory / f"conversion-{uuid4().hex}.json"
            return _prebuilt_render(source, profile, receipt)
        with tempfile.TemporaryDirectory(prefix="word-prebuilt-job-") as temporary_directory:
            receipt = Path(temporary_directory) / "resources.json"
            return _prebuilt_render(source, profile, receipt)
    return renderer.render(source, profile)


def _prebuilt_render(source, profile, receipt):
    with execution_transport.deadline_budget(120):
        result = prebuilt.render(source, profile, receipt=receipt)
    if receipt.exists():
        record = json.loads(receipt.read_text(encoding="utf-8"))
        result["resource_receipt"] = {
            "run_id": record["run_id"],
            "closed": record["closed"],
            "resources": record["resources"],
        }
    return result
