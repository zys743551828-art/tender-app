"""Reject borrowed privileges and changed controls before admitting a receipt."""

import asyncio
from types import SimpleNamespace

import pytest
import yaml
from psycopg.pq import TransactionStatus

from deploy import fusion_material_derivation as controller
from deploy.fusion_asset_runtime import ROOT, FusionAssetRuntime, source_digest
from packages.model_governance import package_current_material as current


@pytest.mark.parametrize("fault", ["method", "same_connection", "transaction", "runtime"])
def test_invalid_control_inputs_never_start_docker(monkeypatch, fault):
    def must_not_start(*args, **kwargs):
        pytest.fail("invalid control input must reject before any Docker session")

    monkeypatch.setattr(controller.pages_port, "FusionMaterialPages", must_not_start)
    connections = [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(3)
    ]
    runtime = FusionAssetRuntime(
        expected_image_id="sha256:" + "a" * 64, expected_source_digest=source_digest()
    )
    expected = controller.method_digest()
    if fault == "method":
        expected = "a" * 64
    elif fault == "same_connection":
        connections[1] = connections[0]
    elif fault == "transaction":
        connections[2].info.transaction_status = TransactionStatus.INTRANS
    else:
        runtime = object()
    with pytest.raises((controller.MaterialDerivationError, current.CurrentMaterialError)):
        asyncio.run(
            controller.collect(
                *connections,
                runtime=runtime,
                expected_method_digest=expected,
                bid_id="unused",
                scope_id="unused",
                expected_scope_digest="a" * 64,
                profile="development_s3",
                url_for_locator=lambda _: pytest.fail("no GET"),
            )
        )


def test_runtime_configuration_change_during_material_collection_rejects(monkeypatch):
    connections = [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(3)
    ]
    runtime = FusionAssetRuntime(
        expected_image_id="sha256:" + "a" * 64, expected_source_digest=source_digest()
    )
    monkeypatch.setattr(
        controller.pages_port,
        "FusionMaterialPages",
        lambda _: SimpleNamespace(render_method_digest="b" * 64),
    )

    async def collecting(*args, **kwargs):
        runtime.hard_timeout_ms = 1
        return object()

    monkeypatch.setattr(current, "collect", collecting)
    with pytest.raises(controller.MaterialDerivationError, match="METHOD_OR_RUNTIME_CHANGED"):
        asyncio.run(
            controller.collect(
                *connections,
                runtime=runtime,
                expected_method_digest=controller.method_digest(),
                bid_id="unused",
                scope_id="unused",
                expected_scope_digest="a" * 64,
                profile="development_s3",
                url_for_locator=lambda _: pytest.fail("no GET"),
            )
        )


def test_host_bridge_override_exposes_only_random_loopback_checks_database():
    override = yaml.safe_load((ROOT / "deploy/compose.fusion.host-checks.yaml").read_text())
    assert set(override["services"]) == {"checks-postgres"}
    service = override["services"]["checks-postgres"]
    assert set(service) == {"ports", "networks"}
    assert service["ports"] == ["127.0.0.1::5432"]
    assert set(service["networks"]) == {"core", "host-checks"}
    assert override["networks"] == {"host-checks": {"driver": "bridge"}}
