"""Deterministic /3 features for one rule's three independently recorded slots.

No provider calls, retries, fee decisions, native authorization or numeric score.
Wire records and semantic validity remain separate; absent judgments stay absent.
"""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from packages.domain.providers.deepseek_vision import VisionGeneration
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_complete_vision as vision
from packages.model_governance import package_technical_material as inputs
from packages.model_governance.technical_png import digest_bytes

MAX_ATTEMPTS = 15
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, repr=False)
class CompleteJudgmentAttempt:
    rule_id: str
    slot: int
    attempt: int
    call_id: str
    state: str
    request: vision.PreparedCompleteVisionRequest
    generation: VisionGeneration | None = None


def method_digest():
    return digest(
        {
            "version": "package-complete-rule-features-method/3",
            "source_digest": digest_bytes(Path(__file__).read_bytes()),
            "input_method_digest": inputs.method_digest(),
            "serializer_digest": vision.serializer_digest(),
            "judgment_method_digest": vision.judgment_method_digest(),
            "maximum_attempts": MAX_ATTEMPTS,
            "maximum_response_bytes": MAX_RESPONSE_BYTES,
            "native_binding_verified": False,
            "numeric_authority_granted": False,
        }
    )


def fail(code: str) -> NoReturn:
    inputs.fail("FEATURE_" + code)


def aggregate_rule(bundle, rule_id, attempts, *, expected_input_digest, expected_method_digest):
    method = method_digest()
    if method != expected_method_digest:
        fail("METHOD_MISMATCH")
    if not isinstance(attempts, (list, tuple)) or len(attempts) > MAX_ATTEMPTS:
        fail("ATTEMPT_LIMIT")
    verified = inputs.verify_input(bundle, expected_input_digest)
    request = vision.prepare_request(
        verified,
        rule_id,
        expected_input_digest=expected_input_digest,
        expected_serializer_digest=vision.serializer_digest(),
    )
    packet = next(r for r in verified.context.metadata["rules"] if r["rule_id"] == rule_id)
    slots: dict[int, list[CompleteJudgmentAttempt]] = {1: [], 2: [], 3: []}
    calls = set()
    response_ids = set()
    total = 0
    for row in attempts:
        if (
            type(row) is not CompleteJudgmentAttempt
            or row.rule_id != rule_id
            or type(row.slot) is not int
            or row.slot not in slots
            or type(row.attempt) is not int
            or not 1 <= row.attempt <= 5
        ):
            fail("ATTEMPT_INVALID")
        valid_id = False
        try:
            valid_id = str(UUID(row.call_id)) == row.call_id
        except (ValueError, TypeError, AttributeError):
            pass
        if not valid_id or row.call_id in calls:
            fail("CALL_ID_REUSED_OR_INVALID")
        calls.add(row.call_id)
        if (
            type(row.request) is not vision.PreparedCompleteVisionRequest
            or row.request.body != request.body
            or canonical(row.request.receipt) != canonical(request.receipt)
        ):
            fail("REQUEST_MISMATCH")
        if row.state not in {"succeeded", "failed", "unknown"} or (row.state == "succeeded") != (
            row.generation is not None
        ):
            fail("GENERATION_STATE_MISMATCH")
        if row.generation is not None:
            if type(row.generation) is not VisionGeneration:
                fail("GENERATION_INVALID")
            total += len(row.generation.raw_response)
            if total > MAX_RESPONSE_BYTES:
                fail("RESPONSE_LIMIT")
        slots[row.slot].append(row)
    valid = []
    reports = []
    unknown = []
    for slot, rows in slots.items():
        rows.sort(key=lambda r: r.attempt)
        if [r.attempt for r in rows] != list(range(1, len(rows) + 1)):
            fail("ATTEMPT_SEQUENCE_INVALID")
        for index, row in enumerate(rows):
            if row.state == "unknown":
                if index != len(rows) - 1:
                    fail("UNKNOWN_ATTEMPT_RETRIED")
                unknown.append(slot)
            checked = None
            rejection = None
            if row.generation is not None:
                try:
                    checked = vision.check_judgment(
                        verified,
                        row.request,
                        row.generation,
                        expected_input_digest=expected_input_digest,
                        expected_request_digest=request.receipt["request_digest"],
                    )
                except inputs.MaterialInputError as error:
                    if not str(error).startswith("MATERIAL_INPUT_JUDGMENT_"):
                        raise
                    rejection = str(error)
                identity = row.generation.response_id
                if identity in response_ids:
                    fail("RESPONSE_ID_REUSED")
                response_ids.add(identity)
                if checked is not None and checked["valid_slot"]:
                    if index != len(rows) - 1:
                        fail("SUCCESSFUL_SLOT_RETRIED")
                    valid.append(row)
            reports.append(
                {
                    "slot": slot,
                    "attempt": row.attempt,
                    "call_id": row.call_id,
                    "state": row.state,
                    "response_id": None if row.generation is None else row.generation.response_id,
                    "response_digest": None
                    if row.generation is None
                    else row.generation.raw_response_digest,
                    "valid_slot": checked is not None and checked["valid_slot"],
                    "semantic_rejection": rejection,
                }
            )
    complete = len(valid) == 3
    feature = None
    if complete:
        generations = [row.generation for row in valid if row.generation is not None]
        if len(generations) != 3:
            fail("GENERATION_INVALID")
        votes = Counter(g.data["band_id"] for g in generations)
        feature = {
            "band_votes": [
                {"band_id": b["band_id"], "count": votes[b["band_id"]]} for b in packet["bands"]
            ],
            "modal_band_ids": [
                b["band_id"] for b in packet["bands"] if votes[b["band_id"]] == max(votes.values())
            ],
            "band_disagreement": len(votes) > 1,
            "dimension_votes": {
                key: {
                    state: sum(g.data["dimensions"][key] == state for g in generations)
                    for state in ("supported", "unsupported", "uncertain")
                }
                for key in ("specificity", "validity", "consistency")
            },
        }
    if method_digest() != method:
        fail("METHOD_CHANGED")
    m = {
        "version": "package-complete-rule-features/3",
        "rule_id": rule_id,
        "rule_digest": packet["frozen_rule"]["rule_digest"],
        "input_digest": expected_input_digest,
        "semantic_input_digest": request.receipt["semantic_input_digest"],
        "feature_method_digest": method,
        "judgment_method_digest": vision.judgment_method_digest(),
        "provider_profile_digest": vision.profile_digest(),
        "attempt_count": len(attempts),
        "valid_slots": [row.slot for row in valid],
        "missing_valid_slots": [s for s in (1, 2, 3) if s not in {row.slot for row in valid}],
        "unresolved_slots": unknown,
        "feature_coverage": "complete" if complete else "partial",
        "attempts": reports,
        "features": feature,
        "raw_numeric_total": None,
        "formal_prediction": None,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "formal_prediction_eligible": False,
        "training_eligible": False,
        "metrics_eligible": False,
        "statistical_independence_claimed": False,
    }
    return m | {"digest": digest(m)}
