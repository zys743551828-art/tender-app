"""Invalid joint-read controls cannot enter any native or object port."""

import asyncio
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from packages.model_governance import package_current_material as current
from packages.model_governance import package_current_scope_review as joint


@pytest.mark.parametrize("fault", ["method", "digest", "connection", "transaction"])
def test_invalid_controls_reject_before_private_read(monkeypatch, fault):
    monkeypatch.setattr(
        joint.registration, "_command", lambda *args: pytest.fail("must not read private command")
    )
    conns = [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(5)
    ]
    args = {
        "expected_method_digest": joint.method_digest(),
        "expected_registration_digest": "b" * 64,
        "expected_issuer_digest": "c" * 64,
    }
    if fault == "method":
        args["expected_method_digest"] = "a" * 64
    elif fault == "digest":
        args["expected_issuer_digest"] = "0" * 64
    elif fault == "connection":
        conns[4] = conns[0]
    else:
        conns[4].info.transaction_status = TransactionStatus.INTRANS
    with pytest.raises((joint.CurrentScopeReviewError, current.CurrentMaterialError)):
        asyncio.run(
            joint.observe(
                None,
                *conns,
                **args,
                recovery_commit_digest="d" * 64,
                registration_command_commit_digest="e" * 64,
                issuer_command_commit_digest="f" * 64,
                expected_context_digest="1" * 64,
                bid_id="unused",
                scope_id="unused",
                expected_scope_digest="2" * 64,
                profile="development_s3",
                url_for_locator=lambda _: pytest.fail("no GET"),
            )
        )
