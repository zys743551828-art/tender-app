"""Extended recovery rejects incomplete plans and implicit/remote local tool inputs."""

from dataclasses import replace

import pytest

from deploy import (
    authoring_candidate,
    completion_recovery,
    extended_recovery,
    extended_recovery_runtime,
)
from deploy.backups import run


def test_plan_preserves_old_plan_and_covers_authoring_and_full_material_chain_once():
    old = completion_recovery.plan_receipt(completion_recovery.frozen_plan())
    plan = extended_recovery.frozen_plan()
    assert completion_recovery.plan_receipt(plan[: len(old)]) == old
    paths = [item.path for item in plan]
    assert len(paths) == len(set(paths))
    assert set(authoring_candidate.OPTIONAL_SQL) <= set(paths)
    assert set(extended_recovery.MATERIAL_SQL) <= set(paths)
    assert (
        paths.index("deploy/sql/material-preparation-leases.sql")
        < paths.index("deploy/sql/material-execution-attempts.sql")
        < paths.index("deploy/sql/material-execution-dispatch.sql")
    )


@pytest.mark.parametrize("fault", ["missing", "reordered", "extra", "bytes", "digest"])
def test_changed_frozen_plan_never_enters_restore(fault):
    plan = list(extended_recovery.frozen_plan())
    if fault == "missing":
        plan.pop()
    elif fault == "reordered":
        plan[-1], plan[-2] = plan[-2], plan[-1]
    elif fault == "extra":
        plan.append(plan[-1])
    elif fault == "bytes":
        plan[-1] = replace(plan[-1], content=plan[-1].content + b"\n")
    else:
        plan[-1] = replace(plan[-1], sha256="a" * 64)
    with pytest.raises(run.BackupError, match="SQL_PLAN_CHANGED"):
        extended_recovery.checked_plan(plan)


@pytest.mark.parametrize(
    "dsn",
    [
        "host=example.invalid port=5432 dbname=x user=y",
        "host=127.0.0.1 port=5432 dbname=x user=y options='-c search_path=evil'",
        "host=127.0.0.1 port=1 dbname=x user=y",
        "host=127.0.0.1 port=5432 dbname=x user=y service=hidden",
    ],
)
def test_local_tool_rejects_remote_identity_injected_options_and_implicit_services(tmp_path, dsn):
    (tmp_path / "pg_dump").write_bytes(b"never execute invalid request")
    tool = extended_recovery.local_tool(tmp_path)
    with pytest.raises(run.BackupError, match="EXPLICIT_LOCAL"):
        tool("unused", "pg_dump", dsn, [])


def test_rerun_clears_all_case_evidence_before_any_selected_service_starts(tmp_path):
    stale = ["summary.json", "summary.md", "cleanup.json", "s3.log", "reader-rejection-proof.json"]
    stale.extend(
        label + suffix
        for label in extended_recovery_runtime.CASES
        for suffix in ("-proof.json", "-junit.xml")
    )
    for name in stale:
        (tmp_path / name).write_text("previous successful run")
    unrelated = tmp_path / "operator-notes.txt"
    unrelated.write_text("retain unrelated notes")
    extended_recovery_runtime.clear_reports(tmp_path)
    assert all(not (tmp_path / name).exists() for name in stale)
    assert unrelated.read_text() == "retain unrelated notes"
