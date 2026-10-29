"""Versioned human review metadata. Approval never grants execution or accuracy.

The existing active-member administration boundary applies (DEC-016). Immutable
original references establish provenance, not the truth of a capability claim.
"""

from copy import deepcopy
from datetime import datetime
from uuid import UUID

from packages.domain.errors import DomainError
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_cost as cost
from packages.model_governance import package_technical_complete_vision as vision
from packages.storage.private_cas import is_digest

VERSION = "material-qualification-review/1"
IDS = {"seal_id", "quote_id", "job_profile_id", "execution_profile_id", "account_id"}
DIGESTS = {
    "scope_digest",
    "input_digest",
    "seal_digest",
    "quote_digest",
    "job_profile_digest",
    "execution_profile_digest",
    "profile_digest",
    "serializer_digest",
    "judgment_method_digest",
}


def fail(code, message="资格记录不符合固定协议", status=422):
    raise DomainError("MATERIAL_QUALIFICATION_" + code, message, status)


def identity(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def timestamp(value):
    try:
        if type(value) is str and len(value) <= 40:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if result.tzinfo is not None:
                return result
    except ValueError:
        pass
    fail("TIME_INVALID")


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        fail("INVALID")


def validate(value):
    closed(
        value, {"version", "binding", "price", "evidence", "requests", "valid_from", "valid_until"}
    )
    if value["version"] != VERSION:
        fail("VERSION_INVALID")
    binding = value["binding"]
    closed(binding, IDS | DIGESTS)
    if any(not identity(binding[k]) for k in IDS) or any(
        not is_digest(binding[k]) for k in DIGESTS
    ):
        fail("BINDING_INVALID")
    if any(
        binding[k] != expected
        for k, expected in {
            "profile_digest": vision.profile_digest(),
            "serializer_digest": vision.serializer_digest(),
            "judgment_method_digest": vision.judgment_method_digest(),
        }.items()
    ):
        fail("METHOD_CHANGED", "模型或方法已变化，请重新登记证据", 409)
    try:
        cost.bind_policy(value["price"], expected_policy_digest=digest(value["price"]))
    except (cost.MaterialCostError, TypeError, ValueError):
        fail("PRICE_INVALID")
    start, end = timestamp(value["valid_from"]), timestamp(value["valid_until"])
    price = value["price"]
    if not timestamp(price["valid_from"]) <= start < end <= timestamp(price["valid_until"]):
        fail("WINDOW_INVALID")
    closed(value["evidence"], {"price", "capacity", "validation"})
    for proof in value["evidence"].values():
        closed(proof, {"document_version_id", "digest", "note"})
        if (
            not identity(proof["document_version_id"])
            or not is_digest(proof["digest"])
            or type(proof["note"]) is not str
            or not proof["note"].strip()
            or len(proof["note"]) > 4000
        ):
            fail("EVIDENCE_INVALID")
    requests = value["requests"]
    if type(requests) is not list or not 1 <= len(requests) <= 1000:
        fail("REQUESTS_INVALID")
    seen = set()
    for item in requests:
        closed(item, {"rule_id", "request_digest", "body_byte_count", "input_tokens"})
        if (
            not identity(item["rule_id"])
            or item["rule_id"] in seen
            or not is_digest(item["request_digest"])
            or type(item["body_byte_count"]) is not int
            or not 1 <= item["body_byte_count"] <= vision.profile()["maximum_body_bytes"]
            or type(item["input_tokens"]) is not int
            or not 1
            <= item["input_tokens"]
            <= price["context_token_capacity"] - vision.profile()["max_output_tokens"]
        ):
            fail("REQUESTS_INVALID")
        seen.add(item["rule_id"])
    if len(canonical(value)) > 262144:
        fail("TOO_LARGE")
    return deepcopy(value)


def decision(value):
    closed(value, {"decision", "reason"})
    if (
        type(value["decision"]) is not str
        or value["decision"] not in {"approved", "revoked"}
        or type(value["reason"]) is not str
        or not value["reason"].strip()
        or len(value["reason"]) > 4000
    ):
        fail("DECISION_INVALID")
    return value


def transition(document, previous, requested, at):
    """Revocation is terminal. New evidence requires a new immutable record."""
    decision(requested)
    if previous == "revoked" or previous == requested["decision"]:
        fail("TRANSITION_INVALID", "该审核状态不可重复变更，请读取原回执或登记新版本", 409)
    if requested["decision"] == "approved":
        validate(document)
        if not timestamp(document["valid_from"]) <= at < timestamp(document["valid_until"]):
            fail("EXPIRED", "证据尚未生效或已过期", 409)
    return requested["decision"]
