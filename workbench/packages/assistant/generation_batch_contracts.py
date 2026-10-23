"""Actual M2 batch commands, bounded metadata pages and complete chapter previews."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID, object_schema
from packages.domain.runtime import DomainError

BASE = "/api/v1/bids/{bid_id}/drafts/{draft_id}/generation-batches"
MODE = "section_patch_set/1"
MAX_SECTIONS = 20
MAX_ATTEMPTS = 5
MAX_FROZEN_BYTES = 16 * 1024 * 1024
MAX_MINOR = 9007199254740991
SCALE = 1000000000
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TEXT = {"type": "string"}
NODE_ID = {"type": "string", "minLength": 1, "maxLength": 128}
TIME = {"type": "string", "format": "date-time"}
REV = {"type": "integer", "minimum": 1}
COUNT = {"type": "integer", "minimum": 0}
MONEY = {"type": "integer", "minimum": 0, "maximum": MAX_MINOR}
POSITIVE_MONEY = MONEY | {"minimum": 1}
CURRENCY = {"enum": ["USD", "CNY"]}
SCALE_SCHEMA = {"const": SCALE}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def array(schema, *, minimum=0, maximum=100):
    return {"type": "array", "items": schema, "minItems": minimum, "maxItems": maximum}


def text(maximum):
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": maximum,
        "pattern": r"\S",
        "not": {"pattern": r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\uD800-\uDFFF]"},
    }


REASON = text(1000)
INSTRUCTION = text(8000)
JSON = ref("AuthoringGenerationJson")
BLOCKED = object_schema({"code": TEXT, "message": TEXT})
SECTION_REQUEST = object_schema(
    {
        "section_id": UUID,
        "base_section_revision": REV,
        "instruction": INSTRUCTION,
        "source_version_ids": array(UUID, maximum=30) | {"uniqueItems": True},
        "selected_node_ids": nullable(
            array(NODE_ID, minimum=1, maximum=2000) | {"uniqueItems": True}
        ),
        "max_tokens": {"type": "integer", "minimum": 1, "maximum": 8192},
        "budget_limit_minor": POSITIVE_MONEY,
    }
)
CREATE = object_schema(
    {
        "base_draft_revision": REV,
        "price_version_id": UUID,
        "currency": CURRENCY,
        "amount_scale": SCALE_SCHEMA,
        "total_limit_minor": POSITIVE_MONEY,
        "sections": array(SECTION_REQUEST, minimum=1, maximum=MAX_SECTIONS),
        "reason": REASON,
    }
)
RETRY = object_schema(
    {
        "batch_digest": SHA,
        "section_id": UUID,
        "previous_attempt": {"type": "integer", "minimum": 1, "maximum": MAX_ATTEMPTS},
        "previous_job_id": UUID,
        "reason": REASON,
    }
)
SELECTION = object_schema(
    {
        "section_id": UUID,
        "attempt": {"type": "integer", "minimum": 1, "maximum": MAX_ATTEMPTS},
        "job_id": UUID,
        "action_id": UUID,
        "candidate_digest": SHA,
    }
)
RESOLVE = object_schema(
    {
        "decision": {"enum": ["apply", "reject"]},
        "batch_digest": SHA,
        "selections": array(SELECTION, maximum=MAX_SECTIONS),
        "reason": REASON,
    }
)


def command(request):
    return object_schema(
        {
            "command_id": UUID,
            "actor_id": UUID,
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
            "request_digest": SHA,
            "request": request,
            "if_match": nullable(TEXT),
        }
    )


COMMAND = command({"oneOf": [CREATE, RETRY, RESOLVE]})
PRICE = object_schema(
    {
        "price_version_id": UUID,
        "version": TEXT,
        "provider": TEXT,
        "model": TEXT,
        "currency": CURRENCY,
        "amount_scale": SCALE_SCHEMA,
        "input_upper": REV,
        "output_upper": REV,
        "input_per_million_minor": POSITIVE_MONEY,
        "output_per_million_minor": POSITIVE_MONEY,
        "valid_until": TIME,
        "source_kind": TEXT,
        "source_uri": TEXT,
        "source_sha256": SHA,
    }
)
BUDGET = object_schema(
    {
        "currency": CURRENCY,
        "amount_scale": SCALE_SCHEMA,
        "limit_minor": POSITIVE_MONEY,
        "charged_minor": MONEY,
        "reserved_minor": MONEY,
        "exposure_minor": MONEY,
        "remaining_minor": MONEY,
        "requires_reconciliation": {"type": "boolean"},
        "over_limit": {"type": "boolean"},
        "estimate_not_provider_spend_cap": {"const": True},
    }
)
ATTEMPT = object_schema(
    {
        "attempt": REV,
        "job_id": UUID,
        "operation_id": UUID,
        "writing_plan_id": UUID,
        "created_at": TIME,
        "created_by": UUID,
        "state": {
            "enum": ["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]
        },
        "publication_state": {"enum": ["pending", "published", "stale", "failed"]},
        "action_id": nullable(UUID),
        "candidate_digest": nullable(SHA),
        "candidate_url": nullable(TEXT),
        "error_code": nullable(TEXT),
        "budget_state": {"enum": ["held", "sent", "unknown", "settled", "released"]},
        "reserved_minor": POSITIVE_MONEY,
        "charged_minor": nullable(MONEY),
        "requires_reconciliation": {"type": "boolean"},
        "retry_allowed": {"type": "boolean"},
        "retry_blocked_reason": nullable(BLOCKED),
    }
)
RECEIPT = object_schema(
    {
        "protocol": {"const": "authoring-generation-batch-command/1"},
        "bid_id": UUID,
        "draft_id": UUID,
        "batch_id": UUID,
        "batch_digest": SHA,
        "kind": {"enum": ["created", "retried", "applied", "rejected"]},
        "batch_state": {"enum": ["open", "applied", "rejected"]},
        "created_job_ids": array(UUID, maximum=MAX_SECTIONS),
        "applied_section_ids": array(UUID, maximum=MAX_SECTIONS),
        "unselected_section_ids": array(UUID, maximum=MAX_SECTIONS),
        "draft_revision": nullable(REV),
        "snapshot_id": nullable(UUID),
        "snapshot_digest": nullable(SHA),
        "recorded_at": TIME,
        "command": COMMAND,
    }
)
SUMMARY = object_schema(
    {
        "batch_id": UUID,
        "bid_id": UUID,
        "draft_id": UUID,
        "batch_digest": SHA,
        "base_draft_revision": REV,
        "state": {"enum": ["open", "applied", "rejected"]},
        "created_at": TIME,
        "created_by": UUID,
        "section_count": REV,
        "ready_count": COUNT,
        "failed_count": COUNT,
        "running_count": COUNT,
        "budget": BUDGET,
    }
)
SCHEMAS = {
    "AuthoringGenerationJson": {
        "oneOf": [
            {"type": "null"},
            {"type": "boolean"},
            {"type": "number"},
            TEXT,
            {"type": "array", "items": JSON},
            {"type": "object", "additionalProperties": JSON},
        ]
    },
    "AuthoringGenerationBatchCreateRequest": CREATE,
    "AuthoringGenerationBatchRetryRequest": RETRY,
    "AuthoringGenerationBatchResolveRequest": RESOLVE,
    "AuthoringGenerationBatchReceipt": RECEIPT,
    "AuthoringGenerationBatch": object_schema(
        {
            **SUMMARY["properties"],
            "protocol": {"const": "authoring-generation-batch/1"},
            "generation_mode": {"const": MODE},
            "base_snapshot_id": UUID,
            "base_snapshot_digest": SHA,
            "base_draft_etag": TEXT,
            "price": PRICE,
            "reason": REASON,
            "etag": TEXT,
            "sections": array(
                object_schema(
                    {
                        **SECTION_REQUEST["properties"],
                        "title": TEXT,
                        "ordinal": COUNT,
                        "before_digest": SHA,
                        "current_attempt": REV,
                        "budget": BUDGET,
                        "attempts": array(ATTEMPT, minimum=1, maximum=MAX_ATTEMPTS),
                    }
                ),
                minimum=1,
                maximum=MAX_SECTIONS,
            ),
            "preparation": command(CREATE),
            "resolution": nullable(RECEIPT),
            "current_validity": {"const": "rechecked_on_retry_and_apply"},
            "requires_explicit_selection": {"const": True},
            "atomic_apply": {"const": True},
        }
    ),
    "AuthoringGenerationBatchPage": object_schema(
        {
            "bid_id": UUID,
            "draft_id": UUID,
            "items": array(SUMMARY, maximum=50),
            "next_cursor": nullable(UUID),
            "has_more": {"type": "boolean"},
        }
    ),
    "AuthoringGenerationBatchCandidate": object_schema(
        {
            "protocol": {"const": "authoring-generation-candidate/1"},
            "generation_mode": {"const": MODE},
            "bid_id": UUID,
            "draft_id": UUID,
            "batch_id": UUID,
            "batch_digest": SHA,
            "section_id": UUID,
            "attempt": REV,
            "job_id": UUID,
            "writing_plan_id": UUID,
            "action_id": UUID,
            "candidate_digest": SHA,
            "base_draft_revision": REV,
            "base_section_revision": REV,
            "base_draft_etag": TEXT,
            "before_digest": SHA,
            "after_digest": SHA,
            "scope_digest": SHA,
            "before": JSON,
            "after": JSON,
            "changes": object_schema(
                {
                    "replaced_node_ids": array(NODE_ID, maximum=2000),
                    "insertions": array(
                        object_schema(
                            {
                                "after_node_id": nullable(NODE_ID),
                                "node_ids": array(UUID, maximum=1000),
                            }
                        ),
                        maximum=2000,
                    ),
                    "added_paragraphs": COUNT,
                }
            ),
            "created_at": TIME,
            "expires_at": TIME,
            "state": {"enum": ["pending", "executed", "rejected", "expired", "stale", "failed"]},
            "etag": TEXT,
        }
    ),
    "AuthoringGenerationBatchCapabilities": object_schema(
        {
            "enabled": {"type": "boolean"},
            "unavailable_reason": nullable(BLOCKED),
            "generation_mode": {"const": MODE},
            "max_sections": REV,
            "max_attempts_per_section": REV,
            "max_frozen_bytes": REV,
            "max_instruction_chars": REV,
            "max_limit_minor": POSITIVE_MONEY,
            "amount_scale": SCALE_SCHEMA,
            "default_max_tokens": REV,
            "price": nullable(PRICE),
            "estimates": array(
                object_schema({"max_tokens": REV, "reservation_minor": POSITIVE_MONEY}), maximum=10
            ),
            "requires_explicit_selection": {"const": True},
            "atomic_apply": {"const": True},
            "requires_verified_identity": {"const": True},
            "automatic_retry_authorized": {"const": False},
        }
    ),
}


def validate(name, value):
    if not Draft202012Validator(
        {"components": {"schemas": SCHEMAS}, "allOf": [SCHEMAS[name]]},
        format_checker=FormatChecker(),
    ).is_valid(value):
        raise DomainError("AUTHORING_GENERATION_BATCH_INVALID", "批次字段不符合实际协议", 422)
    return value


def extend_openapi(document):
    operations = (
        (
            "/api/v1/authoring/generation-batch-capabilities",
            "get",
            None,
            "AuthoringGenerationBatchCapabilities",
            "getAuthoringGenerationBatchCapabilities",
        ),
        (BASE, "get", None, "AuthoringGenerationBatchPage", "listAuthoringGenerationBatches"),
        (
            BASE,
            "post",
            "AuthoringGenerationBatchCreateRequest",
            "AuthoringGenerationBatchReceipt",
            "createAuthoringGenerationBatch",
        ),
        (
            BASE + "/{batch_id}",
            "get",
            None,
            "AuthoringGenerationBatch",
            "getAuthoringGenerationBatch",
        ),
        (
            BASE + "/{batch_id}/retry",
            "post",
            "AuthoringGenerationBatchRetryRequest",
            "AuthoringGenerationBatchReceipt",
            "retryAuthoringGenerationBatch",
        ),
        (
            BASE + "/{batch_id}/resolve",
            "post",
            "AuthoringGenerationBatchResolveRequest",
            "AuthoringGenerationBatchReceipt",
            "resolveAuthoringGenerationBatch",
        ),
        (
            BASE + "/{batch_id}/candidates/{action_id}",
            "get",
            None,
            "AuthoringGenerationBatchCandidate",
            "getAuthoringGenerationBatchCandidate",
        ),
    )
    registered = [row for row in operations if row[1] in document["paths"].get(row[0], {})]
    if not registered:
        return
    document.setdefault("components", {}).setdefault("schemas", {}).update(deepcopy(SCHEMAS))
    for path, verb, request, result, identity in registered:
        operation = document["paths"][path][verb]
        operation["operationId"] = identity
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "201" if request == "AuthoringGenerationBatchCreateRequest" else "200": {
                "description": "冻结批次、章节候选或精确原请求回执",
                "content": {"application/json": {"schema": ref(result)}},
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
        if request:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": ref(request)}},
            }
            operation.setdefault("parameters", []).extend(
                {
                    "name": header,
                    "in": "header",
                    "required": header != "If-Match"
                    or request != "AuthoringGenerationBatchResolveRequest",
                    "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                }
                for header in ("Origin", "X-CSRF-Token", "Idempotency-Key", "If-Match")
            )
