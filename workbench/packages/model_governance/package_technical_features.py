"""Deterministic, non-numeric features from an explicitly bound owned projection.

No database, provider, configuration or environment authority is acquired here.
The caller must obtain the expected projection/method digests from its owned job.
"""

import hashlib
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts import package_technical_features as contract
from packages.domain import review_identity
from packages.domain.review_identity import canonical, digest

MAX_BYTES = 16 * 1024 * 1024


class FeatureProjectionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fail(code: str) -> NoReturn:
    raise FeatureProjectionError(code)


def _source_digest(module):
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        fail("FEATURE_METHOD_SOURCE_UNAVAILABLE")
    try:
        return hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    except OSError:
        fail("FEATURE_METHOD_SOURCE_UNAVAILABLE")


def descriptor():
    return {
        "version": "package-technical-feature-method/2",
        "projection_version": "package-technical-feature-projection/2",
        "output_version": "package-technical-features/2",
        "valid_slots_required": 3,
        "diagnostics": list(contract.DIAGNOSTICS),
        "dimensions": list(contract.DIMENSIONS),
        "modal_ties": "preserve_frozen_band_order",
        "numeric_aggregation": "not_provided",
        "maximum_projection_bytes": MAX_BYTES,
        "source_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "contract_source_digest": _source_digest(contract),
        "canonical_source_digest": _source_digest(review_identity),
        "validator": {
            "distribution": "jsonschema",
            "version": version("jsonschema"),
            "draft": "2020-12",
        },
        "schema_digest": digest(contract.schema()),
        "output_schema_digest": digest(contract.output_schema()),
    }


def method_digest():
    return digest(descriptor())


def _unique(rows, key, code):
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        fail(code)
    return result


def _citation_parts(value, rule, catalog):
    if (
        value["coverage"] != "complete"
        or set(value["covered_part_ids"]) != set(rule["required_part_ids"])
        or not value["reason"].strip()
        or (
            value["band_id"] not in rule["band_ids"]
            if rule["band_ids"]
            else value["band_id"] is not None
        )
    ):
        fail("FEATURE_VALID_JUDGMENT_INCOMPLETE")
    cited_parts, cited_ids = set(), set()
    for cite in value["evidence"]:
        entry = catalog.get(cite["evidence_id"])
        if not entry or any(
            entry[key] != cite[key]
            for key in ("document_version_id", "parse_run_id", "physical_page", "page_image_digest")
        ):
            fail("FEATURE_CITATION_IDENTITY_MISMATCH")
        quote, region = cite["quote"], cite["region"]
        if (not quote.strip() and region is None) or (quote and quote not in entry["text"]):
            fail("FEATURE_QUOTE_MISMATCH")
        if region is not None:
            left, top, right, bottom = region
            if not (
                0 <= left < right <= entry["page_width"]
                and 0 <= top < bottom <= entry["page_height"]
            ):
                fail("FEATURE_REGION_OUT_OF_PAGE")
        cited_parts.update(entry["part_ids"])
        cited_ids.add(entry["evidence_id"])
    if not set(rule["required_part_ids"]) <= cited_parts:
        fail("FEATURE_REQUIRED_PART_UNSUPPORTED")
    return cited_ids


def _valid(attempt, rule, catalog):
    if attempt["state"] != "succeeded":
        if attempt["judgment"] is not None or attempt["judgment_digest"] is not None:
            fail("FEATURE_UNRESOLVED_HAS_JUDGMENT")
        return None
    value = attempt["judgment"]
    if (
        value is None
        or attempt["judgment_digest"] != digest(value)
        or attempt["response_id"] is None
        or attempt["response_digest"] is None
        or attempt["response_model"] is None
    ):
        fail("FEATURE_RESPONSE_RECEIPT_INCOMPLETE")
    if value["status"] != "valid":
        return None
    return _citation_parts(value, rule, catalog)


def _features(valid, bands):
    values = [attempt["judgment"] for attempt in valid]
    votes = [
        {"band_id": band, "count": sum(row["band_id"] == band for row in values)} for band in bands
    ]
    maximum = max((row["count"] for row in votes), default=0)
    return {
        "band_votes": votes,
        "modal_band_ids": [row["band_id"] for row in votes if row["count"] == maximum],
        "band_disagreement": len({row["band_id"] for row in values}) > 1,
        "dimension_votes": {
            dimension: {
                state: sum(row["dimensions"][dimension] == state for row in values)
                for state in contract.DIAGNOSTICS
            }
            for dimension in contract.DIMENSIONS
        },
    }


def build_features(projection, *, expected_projection_digest, expected_method_digest):
    if expected_method_digest != method_digest():
        fail("FEATURE_METHOD_MISMATCH")
    try:
        raw = canonical(projection)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        fail("FEATURE_PROJECTION_INVALID")
    if len(raw) > MAX_BYTES:
        fail("FEATURE_PROJECTION_TOO_LARGE")
    if hashlib.sha256(raw).hexdigest() != expected_projection_digest:
        fail("FEATURE_PROJECTION_DIGEST_MISMATCH")
    if not Draft202012Validator(contract.schema(), format_checker=FormatChecker()).is_valid(
        projection
    ):
        fail("FEATURE_PROJECTION_INVALID")
    rules = _unique(projection["rules"], "rule_id", "FEATURE_RULE_REUSED")
    catalog = _unique(projection["evidence_catalog"], "evidence_id", "FEATURE_EVIDENCE_REUSED")
    pages: dict[tuple[str, str, int], tuple[str, int, int]] = {}
    for entry in catalog.values():
        if hashlib.sha256(entry["text"].encode("utf-8")).hexdigest() != entry["text_digest"]:
            fail("FEATURE_EVIDENCE_DIGEST_MISMATCH")
        page = (entry["document_version_id"], entry["parse_run_id"], entry["physical_page"])
        image = (entry["page_image_digest"], entry["page_width"], entry["page_height"])
        if page in pages and pages[page] != image:
            fail("FEATURE_PAGE_IMAGE_CONTRADICTION")
        pages[page] = image
    calls, responses = set(), set()
    grouped: dict[str, dict[int, list[dict[str, Any]]]] = {
        key: {slot: [] for slot in (1, 2, 3)} for key in rules
    }
    for attempt in projection["attempts"]:
        rule = rules.get(attempt["rule_id"])
        if not rule or attempt["call_id"] in calls:
            fail("FEATURE_CALL_REUSED_OR_RULE_UNKNOWN")
        calls.add(attempt["call_id"])
        response = attempt["response_id"]
        if response is not None:
            if response in responses:
                fail("FEATURE_PROVIDER_RESPONSE_REUSED")
            responses.add(response)
        if (
            attempt["semantic_input_digest"] != rule["semantic_input_digest"]
            or attempt["request_digest"] != rule["request_digest"]
            or any(
                attempt[key] != projection["binding"][key]
                for key in ("judgment_method_digest", "provider_profile_digest")
            )
            or (
                attempt["response_model"] is not None
                and attempt["response_model"] != projection["provider"]["response_model"]
            )
        ):
            fail("FEATURE_ATTEMPT_BINDING_MISMATCH")
        grouped[rule["rule_id"]][attempt["slot"]].append(attempt)
    items = []
    for rule_id, rule in rules.items():
        valid, cited, slots = [], set(), []
        for slot, attempts in grouped[rule_id].items():
            attempts.sort(key=lambda item: item["attempt"])
            if [row["attempt"] for row in attempts] != list(range(1, len(attempts) + 1)) or len(
                attempts
            ) > projection["max_attempts_per_slot"]:
                fail("FEATURE_ATTEMPT_SEQUENCE_INVALID")
            for index, attempt in enumerate(attempts):
                evidence = _valid(attempt, rule, catalog)
                if evidence is not None:
                    if index != len(attempts) - 1:
                        fail("FEATURE_SUCCESSFUL_SLOT_RETRIED")
                    valid.append(attempt)
                    cited.update(evidence)
                    slots.append(slot)
                if attempt["state"] == "unknown" and index != len(attempts) - 1:
                    fail("FEATURE_UNKNOWN_ATTEMPT_RETRIED")
        complete = len(valid) == 3
        items.append(
            {
                "rule_id": rule_id,
                "rule_digest": rule["rule_digest"],
                "attempt_count": sum(len(rows) for rows in grouped[rule_id].values()),
                "valid_slot_count": len(valid),
                "valid_slots": slots,
                "missing_valid_slots": [slot for slot in (1, 2, 3) if slot not in slots],
                "unresolved_slots": [
                    slot
                    for slot, rows in grouped[rule_id].items()
                    if rows and rows[-1]["state"] == "unknown"
                ],
                "call_ids": [row["call_id"] for row in valid],
                "response_ids": [row["response_id"] for row in valid],
                "cited_evidence_ids": sorted(cited),
                "features": _features(valid, rule["band_ids"]) if complete else None,
            }
        )
    complete_rules = sum(item["valid_slot_count"] == 3 for item in items)
    result = {
        "version": "package-technical-features/2",
        "binding": deepcopy(projection["binding"]),
        "provider": deepcopy(projection["provider"]),
        "source_projection_digest": expected_projection_digest,
        "feature_method_digest": expected_method_digest,
        "feature_coverage": "complete" if complete_rules == len(rules) else "partial",
        "expected_rule_count": len(rules),
        "complete_rule_count": complete_rules,
        "items": items,
        "raw_numeric_total": None,
        "formal_prediction": None,
        "input_authority_granted": False,
        "original_bytes_reverified": False,
        "visual_readability_verified": False,
        "formal_prediction_eligible": False,
        "training_eligible": False,
        "metrics_eligible": False,
        "limitations": [
            "OWNED_PROJECTION_ONLY",
            "FEATURES_DO_NOT_VERIFY_PROVIDER_OR_INPUT",
            "MODEL_ALIAS_NOT_IMMUTABLE",
            "THREE_CALLS_NOT_STATISTICAL_INDEPENDENCE",
            "NO_NUMERIC_AUTHORITY_OR_CALIBRATION",
        ],
    }
    result["digest"] = digest(result)
    if not Draft202012Validator(contract.output_schema(), format_checker=FormatChecker()).is_valid(
        result
    ):
        fail("FEATURE_OUTPUT_INVALID")
    return result
