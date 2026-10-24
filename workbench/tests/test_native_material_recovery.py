"""Joint native recovery controls reject before any private read or GET."""

import asyncio
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from packages.model_governance import package_current_material as current
from packages.model_governance import package_native_material_recovery as recovery


@pytest.mark.parametrize("fault", ["method", "digest", "connection", "transaction"])
def test_invalid_controls_reject_before_native_evidence_read(monkeypatch, fault):
    monkeypatch.setattr(
        recovery.store,
        "load",
        lambda *args, **kwargs: pytest.fail("must not read private evidence"),
    )
    conns = [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(4)
    ]
    args = {"expected_method_digest": recovery.method_digest(), "expected_packet_digest": "b" * 64}
    if fault == "method":
        args["expected_method_digest"] = "a" * 64
    elif fault == "digest":
        args["expected_packet_digest"] = "0" * 64
    elif fault == "connection":
        conns[2] = conns[0]
    else:
        conns[0].info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises((recovery.NativeMaterialRecoveryError, current.CurrentMaterialError)):
        asyncio.run(
            recovery.restore(
                *conns,
                **args,
                store_command_id="unused",
                expected_storage_record_digest="c" * 64,
                expected_context_digest="d" * 64,
                bid_id="unused",
                scope_id="unused",
                expected_scope_digest="e" * 64,
                profile="development_s3",
                url_for_locator=lambda _: pytest.fail("no GET"),
            )
        )
