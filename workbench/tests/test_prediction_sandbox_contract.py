"""Executable boundary: production consumers cannot depend on test qualification."""

import ast
from pathlib import Path

import pytest

from deploy import extended_recovery, schema_plan
from packages.model_governance.common import GovernanceError
from packages.package_model_registry import artifact

ROOT = Path(__file__).resolve().parents[1]


def test_test_protocol_is_never_business_bootstrap_or_recovery_plan():
    path = "deploy/sql/prediction-sandbox.sql"
    assert path not in schema_plan.BASE_SQL
    assert path not in {item.path for item in extended_recovery.frozen_plan(prediction=True)}


def test_production_prediction_and_exports_cannot_import_test_qualification():
    for directory in (ROOT / "packages", ROOT / "apps"):
        for path in directory.rglob("*.py"):
            if (
                "prediction_sandbox" in path.parts
                or path == ROOT / "apps/api/prediction_sandbox.py"
            ):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                assert not any("prediction_sandbox" in name for name in names), path
                if isinstance(node, ast.ImportFrom) and node.module == "packages":
                    assert all(alias.name != "prediction_sandbox" for alias in node.names), path


def test_test_result_is_not_a_registry_artifact():
    result = {
        "schema": "prediction-sandbox-result/1",
        "test_only": True,
        "production_eligible": False,
        "value": "50",
    }
    with pytest.raises(GovernanceError):
        artifact.validate(result)


def test_separate_test_application_default_disabled_and_closed_dto(monkeypatch):
    from fastapi.testclient import TestClient

    from apps.api import prediction_sandbox

    monkeypatch.setattr(prediction_sandbox, "auth", lambda *args: {"member_id": "actor"})
    app = prediction_sandbox.create_app()
    with TestClient(app) as client:
        response = client.post(
            "/test-only/bids/00000000-0000-0000-0000-000000000001/certificates",
            json={
                "command_id": "00000000-0000-0000-0000-000000000002",
                "source_ref": "a" * 64,
                "valid_until": "2026-10-30T00:00:00Z",
            },
        )
        assert response.status_code == 503
        assert response.headers["X-Prediction-Test-Only"] == "true"
        response = client.post(
            "/test-only/bids/00000000-0000-0000-0000-000000000001/certificates",
            json={"verified": True},
        )
        assert response.status_code == 422
