"""Owned joint read of native evidence, current sources and configured issuer.

Reads are bracketed observations, not an atomic snapshot or input/send authority.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from packages.domain.review_identity import digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_material_scope_findings as findings
from packages.model_governance import package_native_evidence_issuers as issuers
from packages.model_governance import package_native_evidence_registration as registration
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import is_digest, sha


class NativeCurrentReviewError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise NativeCurrentReviewError("NATIVE_CURRENT_REVIEW_" + code)


@dataclass(frozen=True, repr=False)
class NativeCurrentReview:
    context: material.MaterialContext
    findings: findings.CheckedScopeFindings
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-native-current-review-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "recovery_method": recovery.method_digest(),
            "registration_method": registration.method_digest(),
            "issuer_method": issuers.method_digest(),
            "current_material_method": current.method_digest(),
            "authority_granted": False,
        }
    )


def _issuer(connection, *, bid_id, scope_id, command_id, reference_digest, record_digest, pending):
    observed = issuers.read(
        connection,
        bid_id=bid_id,
        command_id=command_id,
        expected_reference_digest=reference_digest,
        expected_record_digest=record_digest,
        expected_method_digest=issuers.method_digest(),
    )
    d = observed.metadata["record"]["document"]
    p = pending.metadata["document"]
    if (
        d["scope_id"] != scope_id
        or d["registration_id"] != p["registration_id"]
        or d["registration_digest"] != pending.metadata["digest"]
    ):
        fail("ISSUER_REFERENCE_MISMATCH")
    if (
        not observed.metadata["current"]["issuer_active"]
        or not observed.metadata["current"]["case_active"]
    ):
        fail("ISSUER_OR_CASE_UNAVAILABLE")
    return observed


async def observe(
    registration_connection,
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    issuer_connection,
    *,
    registration_command_id,
    expected_registration_packet_digest,
    expected_registration_digest,
    issuer_command_id,
    expected_issuer_reference_digest,
    expected_issuer_digest,
    expected_context_digest,
    expected_method_digest,
    bid_id,
    scope_id,
    expected_scope_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    method = method_digest()
    if method != expected_method_digest:
        fail("METHOD_MISMATCH")
    if any(
        not is_digest(value)
        for value in (
            expected_registration_packet_digest,
            expected_registration_digest,
            expected_issuer_reference_digest,
            expected_issuer_digest,
            expected_context_digest,
            expected_scope_digest,
        )
    ):
        fail("NATIVE_DIGEST_REQUIRED")
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
    reg_args = {
        "bid_id": bid_id,
        "command_id": registration_command_id,
        "expected_packet_digest": expected_registration_packet_digest,
        "expected_record_digest": expected_registration_digest,
        "expected_method_digest": registration.method_digest(),
    }
    pending = registration.read(registration_connection, **reg_args)
    d = pending.metadata["document"]
    packet = d["packet"]
    if (
        d["scope_id"] != scope_id
        or d["scope_digest"] != expected_scope_digest
        or packet["context_digest"] != expected_context_digest
    ):
        fail("REGISTRATION_SCOPE_MISMATCH")
    issuer_args = {
        "bid_id": bid_id,
        "scope_id": scope_id,
        "command_id": issuer_command_id,
        "reference_digest": expected_issuer_reference_digest,
        "record_digest": expected_issuer_digest,
        "pending": pending,
    }
    before = _issuer(issuer_connection, **issuer_args)
    restored = await recovery.restore(
        store_connection,
        scope_connection,
        original_connection,
        parse_connection,
        store_command_id=d["recovery_observation"]["store_command_id"],
        expected_packet_digest=packet["storage_packet_digest"],
        expected_storage_record_digest=packet["storage_record_digest"],
        expected_context_digest=expected_context_digest,
        expected_method_digest=recovery.method_digest(),
        bid_id=bid_id,
        scope_id=scope_id,
        expected_scope_digest=expected_scope_digest,
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
    )
    reference = issuers.reference_for(
        pending,
        restored,
        expected_registration_digest=expected_registration_digest,
        expected_findings_digest=packet["findings_digest"],
    )
    if reference != before.metadata["record"]["document"]["reference"]:
        fail("FULL_REPORT_REFERENCE_MISMATCH")
    after = _issuer(issuer_connection, **issuer_args)
    if before.metadata["record"] != after.metadata["record"] or {
        k: v for k, v in before.metadata["current"].items() if k != "observed_at"
    } != {k: v for k, v in after.metadata["current"].items() if k != "observed_at"}:
        fail("ISSUER_STATE_CHANGED")
    final_pending = registration.read(registration_connection, **reg_args)
    if final_pending.metadata != pending.metadata:
        fail("REGISTRATION_CHANGED")
    current._idle(connections)
    if method_digest() != method:
        fail("METHOD_CHANGED")
    report = restored.findings.metadata
    status = (
        "scope_changes_requested"
        if report["scope_changes_requested"]
        else "review_incomplete"
        if not report["all_findings_claimed_confirmed"]
        else "synthetic_review_only"
        if after.metadata["record"]["document"]["issuer_origin"] == "synthetic_mechanism"
        else "configured_review_confirmed"
    )
    metadata = {
        "version": "package-native-current-review/1",
        "method_digest": method,
        "bid_id": bid_id,
        "scope_id": scope_id,
        "scope_digest": expected_scope_digest,
        "context_digest": expected_context_digest,
        "registration_id": d["registration_id"],
        "registration_digest": expected_registration_digest,
        "issuer_before": deepcopy(before.metadata),
        "issuer_after": deepcopy(after.metadata),
        "current_recovery": deepcopy(restored.metadata),
        "status": status,
        "all_findings_claimed_confirmed": report["all_findings_claimed_confirmed"],
        "scope_changes_requested": report["scope_changes_requested"],
        "configured_current_review_confirmed": status == "configured_review_confirmed",
        "trusted_derivation_bound": False,
        "current_native_sources_rechecked": True,
        "configured_issuer_identity_verified": True,
        "issuer_current_state_unchanged_across_material_check": True,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "actual_human_reading_verified": False,
        "historical_existence_verified": False,
        "atomic_snapshot_verified": False,
        "send_lease_granted": False,
    }
    return NativeCurrentReview(
        restored.context, restored.findings, metadata | {"digest": digest(metadata)}
    )
