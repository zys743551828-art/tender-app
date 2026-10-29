"""Control guards and explicitly mocked orchestration, never kernel evidence."""
# ruff: noqa: F401,F811

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus
from test_native_material_store import prepared, review_origin
from test_package_technical_material import context, synthetic

from deploy import fusion_context_derivation as derivation
from deploy import fusion_verified_material as controller
from deploy.fusion_asset_runtime import FusionAssetRuntime
from packages.model_governance import package_native_current_review as review


def runtime():
    return FusionAssetRuntime(
        expected_image_id="sha256:" + "a" * 64, expected_source_digest="b" * 64
    )


def connections():
    return [
        SimpleNamespace(info=SimpleNamespace(transaction_status=TransactionStatus.IDLE))
        for _ in range(6)
    ]


def args():
    return {k: "unused" for k in controller.REVIEW_FIELDS}


@pytest.mark.parametrize("mutation", ["method", "extra", "missing", "runtime", "alias"])
def test_invalid_control_cannot_start_any_native_or_runtime_port(monkeypatch, mutation):
    async def forbidden(*args, **kwargs):
        pytest.fail("invalid control entered a native port")

    monkeypatch.setattr(review, "observe", forbidden)
    conns = connections()
    values = args()
    r = runtime()
    method = controller.method_digest()
    if mutation == "method":
        method = "c" * 64
    elif mutation == "extra":
        values["execution_receipt"] = {}
    elif mutation == "missing":
        values.pop("expected_context_digest")
    elif mutation == "runtime":
        r = SimpleNamespace(expected_image_id="sha256:" + "a" * 64)
    else:
        conns = [conns[0]] * 6
    with pytest.raises(controller.VerifiedMaterialError):
        asyncio.run(
            controller.collect(
                *conns, runtime=r, review_arguments=values, expected_method_digest=method
            )
        )


@pytest.mark.parametrize("mutation", ["stable", "reenable", "context"])
def test_mocked_stage_linkage_preserves_context_and_detects_between_stage_change(
    review_origin, monkeypatch, mutation
):
    p = prepared(context(review_origin))
    issuer = {
        "record": {"digest": "a" * 64},
        "current": {"observed_at": "first", "issuer_active": True, "profile_head_revision": 1},
    }
    metadata = {
        "registration_digest": "b" * 64,
        "status": "synthetic_review_only",
        "issuer_before": deepcopy(issuer),
        "issuer_after": deepcopy(issuer),
    }
    before = review.NativeCurrentReview(p.live.context, p.findings, deepcopy(metadata))
    after = review.NativeCurrentReview(p.live.context, p.findings, deepcopy(metadata))
    after.metadata["issuer_before"]["current"]["observed_at"] = "later"
    after.metadata["issuer_after"]["current"]["observed_at"] = "last"
    if mutation == "reenable":
        after.metadata["issuer_before"]["current"]["profile_head_revision"] = 3
        after.metadata["issuer_after"]["current"]["profile_head_revision"] = 3
    elif mutation == "context":
        after = review.NativeCurrentReview(deepcopy(p.live.context), p.findings, after.metadata)
        after.context.metadata["source_material_digest"] = "d" * 64
    stages = []

    async def observe(*args, **kwargs):
        stages.append("review")
        return before if len(stages) == 1 else after

    async def derive(*args, **kwargs):
        stages.append("actual-runtime-mocked")
        return p.live

    monkeypatch.setattr(review, "observe", observe)
    monkeypatch.setattr(derivation, "collect", derive)
    values = args() | {"expected_context_digest": p.live.context.metadata["digest"]}

    def collect():
        return asyncio.run(
            controller.collect(
                *connections(),
                runtime=runtime(),
                review_arguments=values,
                expected_method_digest=controller.method_digest(),
            )
        )

    if mutation == "stable":
        result = collect()
        assert result.context is p.live.context and result.findings is p.findings
        assert result.metadata["input_authority_granted"] is False
        assert stages == ["review", "actual-runtime-mocked", "review"]
    else:
        with pytest.raises(
            controller.VerifiedMaterialError, match="ISSUER_STATE_CHANGED|CONTEXT_OR_REVIEW_CHANGED"
        ):
            collect()
