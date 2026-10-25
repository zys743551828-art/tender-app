"""Connect native preparation ownership to the existing complete serializer.

This is a read-only preparation step. A receipt never reserves funds, grants a
send lease, or makes an expired preparation lease usable again. Request bodies
are prepared one at a time and are never logged or stored by this module.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from jsonschema import Draft202012Validator, FormatChecker
from psycopg.pq import TransactionStatus

from packages.contracts import package_technical_material as contract
from packages.domain.review_identity import canonical, digest
from packages.model_governance import material_preparation_leases as leases
from packages.model_governance import package_native_material_recovery as recovery
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import is_digest, sha

FALSE_FIELDS = frozenset(
    {
        "fee_ledger_reserved",
        "send_lease_granted",
        "execution_authorized",
        "model_token_limit_verified",
        "account_prices_verified",
        "visual_readability_verified",
        "atomic_snapshot_verified",
        "formal_prediction_eligible",
    }
)


class MaterialPreflightError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialPreflightError("MATERIAL_PREFLIGHT_" + code)


@dataclass(frozen=True, repr=False)
class MaterialRequestPreflight:
    """Only hashes and bounded request metadata; not a sending capability."""

    metadata: dict


RECEIPT_FIELDS = (
    frozenset(
        {
            "version",
            "method_digest",
            "serializer_digest",
            "preparation_method_digest",
            "lease_id",
            "lease_digest",
            "job_id",
            "job_digest",
            "quote_digest",
            "generation",
            "fence",
            "evidence_revision",
            "input_digest",
            "context_digest",
            "asset_set_digest",
            "requests",
            "rule_count",
            "required_valid_slots",
            "request_bytes_per_round",
            "checked_at",
            "lease_until_at_check",
            "all_included_rules_serialized",
            "complete_owned_images_matched",
            "digest",
        }
    )
    | FALSE_FIELDS
)


def method_digest():
    return digest(
        {
            "version": "material-request-preflight-method/1",
            "source_digest": sha(Path(__file__).read_bytes()),
            "preparation_method_digest": leases.method_digest(),
            "serializer_digest": vision.serializer_digest(),
            "input_method_digest": material.method_digest(),
            "recovery_method_digest": recovery.method_digest(),
            "execution_authorized": False,
        }
    )


def _idle(*connections):
    if any(c.info.transaction_status != TransactionStatus.IDLE for c in connections):
        fail("IDLE_CONNECTION_REQUIRED")


def _refs(lease_id, expected_lease_digest, expected_preparation_method_digest):
    return {
        "lease_id": lease_id,
        "expected_lease_digest": expected_lease_digest,
        "expected_method_digest": expected_preparation_method_digest,
    }


def _methods(expected_method_digest, expected_serializer_digest, refs):
    if (
        method_digest() != expected_method_digest
        or vision.serializer_digest() != expected_serializer_digest
        or leases.method_digest() != refs["expected_method_digest"]
    ):
        fail("METHOD_MISMATCH")


def _observe(connection, refs):
    observation = leases.inspect(connection, **refs)
    _idle(connection)
    if not observation.metadata["current"]["preparation_lease_current"]:
        fail("LEASE_NOT_CURRENT")
    return observation


def _owned_input(connection, bundle, expected_input_digest, refs):
    # Never cast the native JSON projection to MaterialContext. This invokes the
    # original complete verifier, including original PDF bytes and page assets.
    verified = material.verify_input(bundle, expected_input_digest)
    projection = leases.owned_context(connection, **refs)
    _idle(connection)
    value = projection.metadata
    lease = value["lease"]["document"]
    if (
        lease["material_input_digest"] != expected_input_digest
        or canonical(value["material_input"]) != canonical(verified.metadata)
        or canonical(value["context"]) != canonical(verified.context.metadata)
    ):
        fail("OWNED_INPUT_MISMATCH")
    objects: dict[str, bytes] = {}
    for page_bundle in verified.context.origin.page_bundles.values():
        for raw in page_bundle.blobs.values():
            key = sha(raw)
            if key in objects and objects[key] != raw:
                fail("OWNED_ASSET_MISMATCH")
            objects[key] = raw
    batch = leases.owned_assets(connection, **refs, expected_object_digests=sorted(objects))
    _idle(connection)
    if (
        batch.lease_id != refs["lease_id"]
        or set(batch.objects) != set(objects)
        or any(batch.objects[key] != value for key, value in objects.items())
    ):
        fail("OWNED_ASSET_MISMATCH")
    return verified, projection, digest(sorted(objects))


def _finish(connection, refs, projection, expected_method_digest, expected_serializer_digest):
    # A renewal, revocation, or takeover during serialization invalidates this
    # whole batch. The next explicit preflight can observe a new revision.
    latest = leases.owned_context(connection, **refs)
    if canonical(latest.metadata) != canonical(projection.metadata):
        fail("OWNED_INPUT_CHANGED")
    observed = _observe(connection, refs)
    if canonical(observed.record.metadata) != canonical(projection.metadata["lease"]):
        fail("LEASE_CHANGED")
    _methods(expected_method_digest, expected_serializer_digest, refs)
    return observed


def preflight(
    connection,
    bundle,
    *,
    lease_id,
    expected_lease_digest,
    expected_input_digest,
    expected_preparation_method_digest,
    expected_serializer_digest,
    expected_method_digest,
):
    """Check every included rule using native ownership and the /3 serializer.

    ``bundle`` must be an intact MaterialInput from the upstream verifier or
    ``restore_and_preflight``. Large bodies are discarded after each rule, so
    the maximum 400 rules do not retain hundreds of 48 MiB payloads in memory.
    """
    refs = _refs(lease_id, expected_lease_digest, expected_preparation_method_digest)
    _methods(expected_method_digest, expected_serializer_digest, refs)
    _idle(connection)
    _observe(connection, refs)
    verified, projection, asset_digest = _owned_input(
        connection, bundle, expected_input_digest, refs
    )
    included = [r for r in verified.context.metadata["rules"] if r["selection"] == "include"]
    if not 1 <= len(included) <= material.MAX_RULES:
        fail("RULE_SET_INVALID")
    requests = []
    for rule in included:
        request = vision.prepare_request(
            verified,
            rule["rule_id"],
            expected_input_digest=expected_input_digest,
            expected_serializer_digest=expected_serializer_digest,
        )
        vision.validate_request(request, request.receipt["request_digest"], vision.profile_digest())
        requests.append(deepcopy(request.receipt))
        del request
    observed = _finish(
        connection, refs, projection, expected_method_digest, expected_serializer_digest
    )
    lease = projection.metadata["lease"]["document"]
    metadata = {
        "version": "material-request-preflight/1",
        "method_digest": expected_method_digest,
        "serializer_digest": expected_serializer_digest,
        "preparation_method_digest": expected_preparation_method_digest,
        "lease_id": lease_id,
        "lease_digest": expected_lease_digest,
        "job_id": lease["job_id"],
        "job_digest": lease["job_digest"],
        "quote_digest": lease["quote_digest"],
        "generation": lease["generation"],
        "fence": lease["fence"],
        "evidence_revision": projection.metadata["evidence_revision"],
        "input_digest": expected_input_digest,
        "context_digest": verified.context.metadata["digest"],
        "asset_set_digest": asset_digest,
        "requests": requests,
        "rule_count": len(requests),
        "required_valid_slots": 3 * len(requests),
        "request_bytes_per_round": sum(r["body_byte_count"] for r in requests),
        "checked_at": observed.metadata["current"]["observed_at"],
        "lease_until_at_check": observed.metadata["current"]["lease_until"],
        "all_included_rules_serialized": True,
        "complete_owned_images_matched": True,
        **dict.fromkeys(FALSE_FIELDS, False),
    }
    return MaterialRequestPreflight(metadata | {"digest": digest(metadata)})


def prepare_rule_request(
    connection,
    bundle,
    checked,
    rule_id,
    *,
    expected_preflight_digest,
    expected_method_digest,
):
    """Recheck ownership and build one exact request from an earlier preflight.

    All three slots use these same bytes; slot IDs and attempts never enter the
    prompt. This function does not send, reserve funds, or renew a lease.
    """
    if type(checked) is not MaterialRequestPreflight:
        fail("RECEIPT_INVALID")
    m = deepcopy(checked.metadata)
    if (
        type(m) is not dict
        or set(m) != RECEIPT_FIELDS
        or not is_digest(expected_preflight_digest)
        or m.get("digest") != expected_preflight_digest
        or digest({k: v for k, v in m.items() if k != "digest"}) != expected_preflight_digest
        or m.get("version") != "material-request-preflight/1"
        or m.get("method_digest") != expected_method_digest
        or any(m.get(k) is not False for k in FALSE_FIELDS)
    ):
        fail("RECEIPT_INVALID")
    requests = m["requests"]
    validator = Draft202012Validator(contract.REQUEST_RECEIPT, format_checker=FormatChecker())
    if (
        type(requests) is not list
        or not 1 <= len(requests) <= material.MAX_RULES
        or any(type(r) is not dict or not validator.is_valid(r) for r in requests)
        or type(m["rule_count"]) is not int
        or m["rule_count"] != len(requests)
        or type(m["required_valid_slots"]) is not int
        or m["required_valid_slots"] != 3 * len(requests)
        or type(m["request_bytes_per_round"]) is not int
        or m["request_bytes_per_round"] != sum(r["body_byte_count"] for r in requests)
        or m["all_included_rules_serialized"] is not True
        or m["complete_owned_images_matched"] is not True
        or any(
            type(m[k]) is not int or m[k] < 1 for k in ("generation", "fence", "evidence_revision")
        )
    ):
        fail("RECEIPT_INVALID")
    refs = _refs(m["lease_id"], m["lease_digest"], m["preparation_method_digest"])
    _methods(expected_method_digest, m["serializer_digest"], refs)
    _idle(connection)
    _observe(connection, refs)
    verified, projection, asset_digest = _owned_input(connection, bundle, m["input_digest"], refs)
    rules = [
        r["rule_id"] for r in verified.context.metadata["rules"] if r["selection"] == "include"
    ]
    if (
        m.get("rule_count") != len(rules)
        or m.get("required_valid_slots") != 3 * len(rules)
        or type(m.get("requests")) is not list
        or [r.get("rule_id") for r in m["requests"]] != rules
        or rule_id not in rules
        or m["context_digest"] != verified.context.metadata["digest"]
        or m["asset_set_digest"] != asset_digest
        or m["evidence_revision"] != projection.metadata["evidence_revision"]
    ):
        fail("RECEIPT_INPUT_MISMATCH")
    lease = projection.metadata["lease"]["document"]
    if any(
        m[k] != lease[k] for k in ("job_id", "job_digest", "quote_digest", "generation", "fence")
    ):
        fail("RECEIPT_INPUT_MISMATCH")
    request = vision.prepare_request(
        verified,
        rule_id,
        expected_input_digest=m["input_digest"],
        expected_serializer_digest=m["serializer_digest"],
    )
    original = m["requests"][rules.index(rule_id)]
    if canonical(request.receipt) != canonical(original):
        fail("REQUEST_CHANGED")
    vision.validate_request(request, original["request_digest"], vision.profile_digest())
    _finish(connection, refs, projection, expected_method_digest, m["serializer_digest"])
    return request


async def restore_and_preflight(
    preparation_connection,
    store_connection,
    scope_connection,
    original_connection,
    parse_connection,
    *,
    lease_id,
    expected_lease_digest,
    expected_input_digest,
    expected_preparation_method_digest,
    expected_serializer_digest,
    expected_method_digest,
    store_command_id,
    expected_packet_digest,
    expected_storage_record_digest,
    profile,
    url_for_locator,
    byte_client=None,
):
    """Recover the same sealed input through the existing independent readers.

    The preparation LOGIN never gains access to PDFs or the private store. Its
    connection stays idle while the four existing, separately scoped readers
    restore and revalidate originals. Returned input is for the bounded sender
    preparation above, never proof of execution or a new input qualification.
    """
    connections = (
        preparation_connection,
        store_connection,
        scope_connection,
        original_connection,
        parse_connection,
    )
    if len({id(c) for c in connections}) != 5:
        fail("INDEPENDENT_CONNECTIONS_REQUIRED")
    refs = _refs(lease_id, expected_lease_digest, expected_preparation_method_digest)
    _methods(expected_method_digest, expected_serializer_digest, refs)
    _idle(*connections)
    _observe(preparation_connection, refs)
    projection = leases.owned_context(preparation_connection, **refs)
    d = projection.metadata
    bound = d["material_input"]
    if bound["digest"] != expected_input_digest:
        fail("OWNED_INPUT_MISMATCH")
    ctx = d["context"]
    _idle(*connections)
    recovered = await recovery.restore(
        store_connection,
        scope_connection,
        original_connection,
        parse_connection,
        store_command_id=store_command_id,
        expected_packet_digest=expected_packet_digest,
        expected_storage_record_digest=expected_storage_record_digest,
        expected_context_digest=ctx["digest"],
        expected_method_digest=recovery.method_digest(),
        bid_id=ctx["bid_id"],
        scope_id=ctx["scope_id"],
        expected_scope_digest=ctx["scope_digest"],
        profile=profile,
        url_for_locator=url_for_locator,
        byte_client=byte_client,
    )
    _idle(*connections)
    if canonical(recovered.context.metadata) != canonical(ctx):
        fail("RECOVERED_CONTEXT_MISMATCH")
    bundle = material.bind_input(
        recovered.context,
        bound["binding_reference"],
        expected_context_digest=ctx["digest"],
        expected_binding_digest=bound["binding_reference_digest"],
        expected_method_digest=bound["input_method_digest"],
    )
    if canonical(bundle.metadata) != canonical(bound):
        fail("RECOVERED_INPUT_MISMATCH")
    # Reacquire all native ownership facts after external I/O. No stale Python
    # object or successful byte recovery can substitute for a current lease.
    result = preflight(
        preparation_connection,
        bundle,
        lease_id=lease_id,
        expected_lease_digest=expected_lease_digest,
        expected_input_digest=expected_input_digest,
        expected_preparation_method_digest=expected_preparation_method_digest,
        expected_serializer_digest=expected_serializer_digest,
        expected_method_digest=expected_method_digest,
    )
    return bundle, result
