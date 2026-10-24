"""Owned composition of exact private claims, native issuer and fresh sources.

Only read ports are used. Observations do not form an atomic snapshot, input
binding, historical proof or send lease; old context/registration stay immutable.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_current_material as current
from packages.model_governance import package_material_recovery as recovery
from packages.model_governance import package_material_registration as registration
from packages.model_governance import package_material_scope_review as review
from packages.model_governance import package_scope_findings_store as findings_store
from packages.model_governance import package_scope_review_issuers as issuers
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import is_digest, sha


class CurrentScopeReviewError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise CurrentScopeReviewError("CURRENT_SCOPE_REVIEW_" + code)


@dataclass(frozen=True, repr=False)
class CurrentScopeReview:
    context: material.MaterialContext
    metadata: dict


def method_digest():
    return digest(
        {
            "version": "package-current-scope-review-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "recovery_method": recovery.method_digest(),
            "registration_method": registration.method_digest(),
            "review_method": review.method_digest(),
            "findings_store_method": findings_store.method_digest(),
            "issuer_method": issuers.method_digest(),
            "authority_grants": False,
        }
    )


def _issuer(connection, command, expected_digest):
    observed = issuers.read(
        connection,
        bid_id=command["bid_id"],
        command_id=command["command_id"],
        expected_reference_digest=digest(command["reference"]),
        expected_method_digest=issuers.method_digest(),
        expected_record_digest=expected_digest,
    )
    d = observed.metadata["record"]["document"]
    if (
        d["case_id"] != command["case_id"]
        or d["scope_id"] != command["scope_id"]
        or canonical(d["reference"]) != canonical(command["reference"])
    ):
        fail("ISSUER_REFERENCE_MISMATCH")
    state = observed.metadata["current"]
    if state["issuer_active"] is not True or state["case_active"] is not True:
        fail("ISSUER_OR_CASE_UNAVAILABLE")
    return observed


async def observe(
    store,
    scope_connection,
    original_connection,
    parse_connection,
    registration_connection,
    issuer_connection,
    *,
    recovery_commit_digest,
    registration_command_commit_digest,
    issuer_command_commit_digest,
    expected_context_digest,
    expected_registration_digest,
    expected_issuer_digest,
    expected_method_digest,
    bid_id,
    scope_id,
    expected_scope_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    if any(not is_digest(v) for v in (expected_registration_digest, expected_issuer_digest)):
        fail("NATIVE_DIGEST_REQUIRED")
    connections = (
        scope_connection,
        original_connection,
        parse_connection,
        registration_connection,
        issuer_connection,
    )
    if len({id(c) for c in connections}) != 5:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    current._idle(connections)
    registered_command = registration._command(store, registration_command_commit_digest)
    issuer_command = issuers._command(store, issuer_command_commit_digest)
    if any(
        c[k] != v
        for c in (registered_command, issuer_command)
        for k, v in (("bid_id", bid_id), ("scope_id", scope_id))
    ):
        fail("COMMAND_SCOPE_MISMATCH")
    if registered_command["scope_digest"] != expected_scope_digest:
        fail("COMMAND_SCOPE_MISMATCH")
    reference = issuer_command["reference"]
    if reference["context_digest"] != expected_context_digest:
        fail("CONTEXT_MISMATCH")
    args = {
        "recovery_commit_digest": recovery_commit_digest,
        "expected_context_digest": expected_context_digest,
        "expected_method_digest": recovery.method_digest(),
        "bid_id": bid_id,
        "scope_id": scope_id,
        "expected_scope_digest": expected_scope_digest,
        "profile": profile,
        "url_for_locator": url_for_locator,
        "byte_client": byte_client,
    }
    first = await recovery.restore(
        store, scope_connection, original_connection, parse_connection, **args
    )
    packet = review.build(
        first.context,
        expected_context_digest=expected_context_digest,
        expected_method_digest=review.method_digest(),
    )
    if packet.metadata["digest"] != reference["review_digest"]:
        fail("REVIEW_MISMATCH")
    findings = findings_store.load(
        store,
        packet,
        commit_digest=reference["findings_commit_digest"],
        expected_findings_digest=reference["findings_digest"],
        expected_method_digest=findings_store.method_digest(),
    )
    registered = registration.read(
        registration_connection,
        bid_id=bid_id,
        command_id=registered_command["command_id"],
        expected_packet_digest=digest(registered_command["packet"]),
        expected_method_digest=registration.method_digest(),
        expected_record_digest=expected_registration_digest,
    )
    native = registered.metadata["document"]
    if any(native[k] != registered_command[k] for k in ("scope_id", "scope_digest", "packet")):
        fail("REGISTRATION_COMMAND_MISMATCH")
    m = first.context.metadata
    expected = {
        "context_digest": expected_context_digest,
        "context_method_digest": material.context_method_digest(),
        "recovery_commit_digest": recovery_commit_digest,
        "recovery_method_digest": recovery.method_digest(),
        "source_observation_digest": m["source_observation_digest"],
        "material_digest": m["source_material_digest"],
    }
    if any(native["packet"][k] != v for k, v in expected.items()):
        fail("REGISTRATION_CONTEXT_MISMATCH")
    before = _issuer(issuer_connection, issuer_command, expected_issuer_digest)
    document = before.metadata["record"]["document"]
    if (
        document["registration_id"] != native["registration_id"]
        or document["registration_digest"] != expected_registration_digest
    ):
        fail("ISSUER_REGISTRATION_MISMATCH")
    current._idle(connections)
    final = await recovery.restore(
        store, scope_connection, original_connection, parse_connection, **args
    )
    after = _issuer(issuer_connection, issuer_command, expected_issuer_digest)
    if canonical(before.metadata["record"]) != canonical(after.metadata["record"]) or canonical(
        {k: v for k, v in before.metadata["current"].items() if k != "observed_at"}
    ) != canonical({k: v for k, v in after.metadata["current"].items() if k != "observed_at"}):
        fail("ISSUER_STATE_CHANGED")
    current._idle(connections)
    if method_digest() != method:
        fail("METHOD_CHANGED")
    complete = (
        findings.metadata["all_findings_claimed_confirmed"]
        and findings.metadata["all_images_claimed_reviewed"]
    )
    synthetic = document["issuer_origin"] == "synthetic_mechanism"
    status = (
        "review_changes_required"
        if findings.metadata["scope_changes_requested"]
        else "review_incomplete"
        if not complete
        else "synthetic_review_only"
        if synthetic
        else "configured_review_confirmed"
    )
    metadata = {
        "version": "package-current-scope-review-observation/1",
        "method_digest": method,
        "context_digest": expected_context_digest,
        "review_digest": reference["review_digest"],
        "findings_digest": reference["findings_digest"],
        "findings_commit_digest": reference["findings_commit_digest"],
        "registration_digest": expected_registration_digest,
        "issuer_record_digest": expected_issuer_digest,
        "initial_recovery": deepcopy(first.metadata),
        "final_recovery": deepcopy(final.metadata),
        "initial_issuer_observation": deepcopy(before.metadata),
        "final_issuer_observation": deepcopy(after.metadata),
        "status": status,
        "all_findings_claimed_confirmed": complete,
        "configured_current_review_confirmed": status == "configured_review_confirmed",
        "current_native_material_rechecked": True,
        "configured_issuer_identity_verified": True,
        "atomic_snapshot_verified": False,
        "send_lease_granted": False,
        "actual_human_reading_verified": False,
        "trusted_derivation_bound": False,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "historical_existence_verified": False,
    }
    return CurrentScopeReview(final.context, metadata | {"digest": digest(metadata)})
