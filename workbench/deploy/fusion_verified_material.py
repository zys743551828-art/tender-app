"""Trusted-host execution of actual derivation bracketed by current review reads.

This is a live procedure result. Stored JSON cannot restore this capability.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from deploy import fusion_context_derivation as derivation
from deploy.fusion_asset_runtime import FusionAssetRuntime
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_native_current_review as review
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha

REVIEW_FIELDS = frozenset(
    {
        "registration_command_id",
        "expected_registration_packet_digest",
        "expected_registration_digest",
        "issuer_command_id",
        "expected_issuer_reference_digest",
        "expected_issuer_digest",
        "expected_context_digest",
        "bid_id",
        "scope_id",
        "expected_scope_digest",
        "profile",
        "url_for_locator",
    }
)
MAX_OBSERVATION_BYTES = derivation.MAX_OBSERVATION_BYTES + 65536


class VerifiedMaterialError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise VerifiedMaterialError("VERIFIED_MATERIAL_" + code)


@dataclass(frozen=True, repr=False)
class LiveVerifiedMaterial:
    context: material.MaterialContext
    findings: findings.CheckedScopeFindings
    live_derivation: derivation.LiveDerivedContext
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "fusion-verified-material-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "derivation_method": derivation.method_digest(),
            "native_current_review_method": review.method_digest(),
            "maximum_observation_bytes": MAX_OBSERVATION_BYTES,
            "input_authority_granted": False,
        }
    )


def _state(observation):
    return {
        "record": deepcopy(observation["record"]),
        "current": {
            k: deepcopy(v) for k, v in observation["current"].items() if k != "observed_at"
        },
    }


async def collect(
    registration_connection,
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    issuer_connection,
    *,
    runtime,
    review_arguments,
    expected_method_digest,
    byte_client=None,
):
    method = method_digest()
    if method != expected_method_digest:
        fail("METHOD_MISMATCH")
    if type(review_arguments) is not dict or set(review_arguments) != REVIEW_FIELDS:
        fail("REVIEW_ARGUMENTS_INVALID")
    if type(runtime) is not FusionAssetRuntime:
        fail("TRUSTED_RUNTIME_REQUIRED")
    connections = (
        registration_connection,
        store_connection,
        scope_connection,
        original_connection,
        parse_connection,
        issuer_connection,
    )
    if len({id(c) for c in connections}) != 6:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    args = dict(review_arguments) | {
        "expected_method_digest": review.method_digest(),
        "byte_client": byte_client,
    }
    before = await review.observe(*connections, **args)
    live = await derivation.collect(
        before.context,
        scope_connection,
        original_connection,
        parse_connection,
        runtime=runtime,
        expected_context_digest=review_arguments["expected_context_digest"],
        expected_method_digest=derivation.method_digest(),
        profile=review_arguments["profile"],
        url_for_locator=review_arguments["url_for_locator"],
        byte_client=byte_client,
    )
    after = await review.observe(*connections, **args)
    if (
        type(before) is not review.NativeCurrentReview
        or type(after) is not review.NativeCurrentReview
        or type(live) is not derivation.LiveDerivedContext
        or canonical(before.context.metadata) != canonical(live.context.metadata)
        or canonical(after.context.metadata) != canonical(live.context.metadata)
        or canonical(before.findings.metadata) != canonical(after.findings.metadata)
        or before.metadata["registration_digest"] != after.metadata["registration_digest"]
        or before.metadata["status"] != after.metadata["status"]
    ):
        fail("CONTEXT_OR_REVIEW_CHANGED")
    observations = [
        item.metadata[key] for item in (before, after) for key in ("issuer_before", "issuer_after")
    ]
    if any(_state(item) != _state(observations[0]) for item in observations[1:]):
        fail("ISSUER_STATE_CHANGED_ACROSS_DERIVATION")
    current._idle(connections)
    if method_digest() != method:
        fail("METHOD_CHANGED")
    metadata = {
        "version": "fusion-live-verified-material/1",
        "method_digest": method,
        "context_digest": live.context.metadata["digest"],
        "findings_digest": after.findings.metadata["digest"],
        "initial_current_review": deepcopy(before.metadata),
        "live_derivation": deepcopy(live.metadata),
        "final_current_review": deepcopy(after.metadata),
        "status": after.metadata["status"],
        "actual_current_derivation_and_review_combined": True,
        "trusted_derivation_bound": True,
        "issuer_state_unchanged_across_all_stages": True,
        "exact_frozen_context_and_report_preserved": True,
        "actual_human_reading_verified": False,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
        "atomic_snapshot_verified": False,
        "send_lease_granted": False,
    }
    if len(canonical(metadata)) > MAX_OBSERVATION_BYTES:
        fail("OBSERVATION_LIMIT")
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return LiveVerifiedMaterial(
        live.context, after.findings, live, metadata | {"digest": digest(metadata)}
    )
