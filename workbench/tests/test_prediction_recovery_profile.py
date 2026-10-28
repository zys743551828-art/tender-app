"""Profile format/closure unit checks; native data recovery is a separate suite."""

from dataclasses import replace

import pytest

from deploy import completion_recovery
from deploy import extended_recovery as recovery
from deploy import prediction_recovery_profile as profile
from deploy.backups import run


def test_prediction_profile_keeps_legacy_plan_and_installs_before_sealing():
    legacy = recovery.frozen_plan()
    plan = recovery.frozen_plan(prediction=True)
    assert completion_recovery.plan_receipt(
        plan[: len(legacy)]
    ) == completion_recovery.plan_receipt(legacy)
    paths = [item.path for item in plan]
    assert len(paths) == len(set(paths))
    assert paths.index("deploy/sql/package-history-feature-dispatch.sql") < paths.index(
        "deploy/sql/package-history-exposure-bridge.sql"
    )
    assert paths.index("deploy/sql/package-model-route-v2.sql") < paths.index(
        "deploy/sql/package-business-shadow.sql"
    )
    assert "deploy/sql/package-model-route.sql" not in paths
    assert recovery.FORMAT != profile.FORMAT


@pytest.mark.parametrize("fault", ["missing", "reorder", "bytes"])
def test_prediction_profile_rejects_changed_plan(fault):
    plan = list(recovery.frozen_plan(prediction=True))
    if fault == "missing":
        plan.pop()
    elif fault == "reorder":
        plan[-1], plan[-2] = plan[-2], plan[-1]
    else:
        plan[-1] = replace(plan[-1], content=plan[-1].content + b"\n")
    with pytest.raises(run.BackupError, match="SQL_PLAN_CHANGED"):
        recovery.checked_plan(plan, prediction=True)


def test_private_ref_invalid_is_not_silently_omitted():
    class Connection:
        def execute(self, *args):
            return self

        def fetchall(self):
            return [("a" * 64,), (None,)]

    with pytest.raises(run.BackupError, match="PRIVATE_REFERENCE_INVALID"):
        profile.private_references(Connection())


def test_private_object_requires_explicit_port_and_bounded_bytes():
    with pytest.raises(run.BackupError, match="PORT_REQUIRED"):
        profile.object_rows([], None, None, [])

    class Client:
        def head_object(self, **kwargs):
            return {"ContentLength": 32 * 1024 * 1024 + 1}

    with pytest.raises(run.BackupError, match="OBJECT_SIZE"):
        profile.object_rows(["a" * 64], Client(), "synthetic", [])
