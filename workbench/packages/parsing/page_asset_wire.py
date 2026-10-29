"""Bounded JSON header and raw bytes; no business configuration or PDF parser."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import package_technical_assets as contract

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_HEADER_BYTES = 1024 * 1024
MAX_WIRE_BYTES = MAX_SOURCE_BYTES + MAX_HEADER_BYTES + 4


class AssetWireError(ValueError):
    pass


def fail(code):
    raise AssetWireError(code)


def canonical(value):
    def numbers(node):
        if isinstance(node, float):
            fail("ASSET_WIRE_JSON_INVALID")
        if isinstance(node, dict):
            for item in node.values():
                numbers(item)
        elif isinstance(node, list):
            for item in node:
                numbers(item)

    numbers(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def load(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_HEADER_BYTES:
        fail("ASSET_WIRE_SIZE_INVALID")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite JSON")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
            parse_float=reject_constant,
        )
        canonical(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail("ASSET_WIRE_JSON_INVALID")


def check(value, schema):
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        fail("ASSET_WIRE_SHAPE_INVALID")


def pack(header, payload):
    encoded = canonical(header)
    if (
        not 0 < len(encoded) <= MAX_HEADER_BYTES
        or not isinstance(payload, bytes)
        or len(payload) > MAX_SOURCE_BYTES
    ):
        fail("ASSET_WIRE_SIZE_INVALID")
    return len(encoded).to_bytes(4, "big") + encoded + payload


def unpack(raw):
    if not isinstance(raw, bytes) or not 4 < len(raw) <= MAX_WIRE_BYTES:
        fail("ASSET_WIRE_SIZE_INVALID")
    size = int.from_bytes(raw[:4], "big")
    if not 0 < size <= MAX_HEADER_BYTES or 4 + size > len(raw):
        fail("ASSET_WIRE_HEADER_INVALID")
    return load(raw[4 : 4 + size]), raw[4 + size :]


def decode_blocks(records, payload):
    check(records, SUCCESS["properties"]["blobs"])
    if (
        not isinstance(payload, bytes)
        or sum(row["byte_size"] for row in records) != len(payload)
        or len(payload) > MAX_SOURCE_BYTES
    ):
        fail("ASSET_WIRE_BLOCK_SIZE_MISMATCH")
    result: dict[str, bytes] = {}
    offset = 0
    for row in records:
        if row["id"] in result:
            fail("ASSET_WIRE_BLOCK_REUSED")
        end = offset + row["byte_size"]
        result[row["id"]] = payload[offset:end]
        offset = end
    return result


regions = contract.regions_schema()
regions["minItems"] = 0
REQUEST = contract.obj(
    {
        "version": {"const": "package-page-render-request/1"},
        "document_version_id": contract.ID,
        "source_digest": contract.SHA,
        "source_byte_size": {"type": "integer", "minimum": 1, "maximum": MAX_SOURCE_BYTES},
        "render_method_digest": contract.SHA,
        "crop_method_digest": contract.SHA,
        "regions": regions,
    }
)
SUCCESS = contract.obj(
    {
        "version": {"const": "package-page-render-response/1"},
        "state": {"const": "succeeded"},
        "manifest": contract.schema(),
        "blobs": {
            "type": "array",
            "minItems": 1,
            "maxItems": 256,
            "items": contract.obj(
                {
                    "id": contract.SHA,
                    "byte_size": {"type": "integer", "minimum": 1, "maximum": MAX_SOURCE_BYTES},
                }
            ),
        },
    }
)
FAILURE = contract.obj(
    {
        "version": {"const": "package-page-render-response/1"},
        "state": {"const": "failed"},
        "error_code": {"enum": ["ASSET_WORKER_REJECTED", "ASSET_WORKER_INTERNAL_ERROR"]},
    }
)
ISOLATION = contract.obj(
    {
        "memory.max": {"const": "1073741824"},
        "memory.swap.max": {"const": "0"},
        "pids.max": {"const": "32"},
        "cpu.max": {"const": "100000 100000"},
        "no_new_privileges": {"type": "boolean", "const": True},
        "seccomp_filter_active": {"type": "boolean", "const": True},
        "effective_permitted_bounding_ambient_capabilities_zero": {
            "type": "boolean",
            "const": True,
        },
        "network_interfaces": {"const": ["lo"]},
        "read_only_source_files": {"type": "integer", "const": 7},
    }
)
EXECUTION = contract.obj(
    {
        "version": {"const": "package-page-render-execution/1"},
        "container_id": contract.SHA,
        "image_id": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "source_digest": contract.SHA,
        "compose_project": {"const": "tender-fusion"},
        "compose_service": {"const": "asset-renderer"},
        "hard_timeout_ms": {"type": "integer", "minimum": 1, "maximum": 40000},
        "container_started_at": contract.TIME,
        "container_finished_at": contract.TIME,
        "stopped_verified": {"type": "boolean", "const": True},
        "container_pid": {"type": "integer", "const": 0},
        "oom_killed": {"type": "boolean", "const": False},
        "was_running_before_stop": {"type": "boolean", "const": True},
        "container_exit_code": {"type": "integer", "minimum": 0, "maximum": 255},
        "source_fingerprint_checked_before_and_after": {"type": "boolean", "const": True},
        "observed_kernel_limits": ISOLATION,
        "original_digest": contract.SHA,
        "result_manifest_digest": contract.SHA,
        "wire_result_digest": contract.SHA,
        "container_boundary_observed": {"type": "boolean", "const": True},
        "input_authority_granted": {"type": "boolean", "const": False},
        "visual_readability_verified": {"type": "boolean", "const": False},
        "formal_execution_authorized": {"type": "boolean", "const": False},
    }
)


def request_schema():
    return deepcopy(REQUEST)


def success_schema():
    return deepcopy(SUCCESS)


def execution_schema():
    return deepcopy(EXECUTION)
