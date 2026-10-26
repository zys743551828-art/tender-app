"""Explicit access to historical acceptance inputs that are not in this repository.

These inputs include a fixed 308-source/15-SQL snapshot. They cannot be replaced
with today's checkout or regenerated and called the same historical evidence.
"""

import os
from pathlib import Path

import pytest

ARCHIVE_ROOT = Path("/workspace/tender-docs/04-验证与测试")
BASELINE = "application-recovery-development-checks/protocol-02/baseline-inputs.json"
DOMAIN_SQL = (
    "historical-input-initialization-checks/candidate02/sql-inputs/"
    "packages/contracts/sql/domain.sql"
)


def required_archive(relative_path):
    if os.environ.get("RUN_ARCHIVED_RECOVERY") != "1":
        pytest.skip(
            "Historical recovery archive is external to this checkout; "
            "set RUN_ARCHIVED_RECOVERY=1 with the original verified archive mounted. "
            "This is not a passed archive-recovery acceptance."
        )
    path = ARCHIVE_ROOT / relative_path
    if not path.is_file():
        pytest.fail(f"Explicit archived recovery acceptance is missing required input: {path}")
    return path
