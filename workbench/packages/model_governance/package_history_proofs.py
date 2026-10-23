"""One evidence adapter; authentic signatures are not proof that claims are true.

Deployment must independently establish an issuer's competence and source
semantics. This adapter binds those explicit assertions to exact native records
and original evidence bytes. It grants no prebid, online or model qualification.
Other reviewed evidence adapters may implement the same normalized contract.
"""

import base64
import binascii
import hashlib
import io
import json
import re
import warnings
from datetime import timezone
from decimal import Decimal
from typing import NoReturn

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from PIL import Image

from packages.model_governance.common import GovernanceError, digest, instant

ADAPTER = "signed-source-evidence/1"
MAX_BYTES = 16 * 1024 * 1024
MAX_RESOURCES = 20000
SCALE = re.compile(
    r"\A\s*技术总分满分为([0-9]+(?:\.[0-9]{1,8})?)分，量尺为未加权原始分；"
    r"聚合口径为官方公布的最终技术总分。\s*\Z"
)


def fail(code, message) -> NoReturn:
    raise GovernanceError("PACKAGE_HISTORY_" + code, message)


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        fail("EVIDENCE_SHAPE", "Closed, explicit evidence fields are required")


def nonblank(value, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        fail("EVIDENCE_SHAPE", "Bounded nonblank source provenance required")
    return value


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            fail("EVIDENCE_SHAPE", "Duplicate JSON fields are forbidden")
        result[key] = value
    return result


def _constant(_):
    fail("EVIDENCE_SHAPE", "Non-finite JSON values are forbidden")


def load(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        fail("EVIDENCE_CAPACITY", "Bounded original receipt bytes required")
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, GovernanceError):
            raise
        fail("EVIDENCE_SHAPE", "Evidence must be UTF-8 JSON")


def decoded(value, maximum=MAX_BYTES):
    try:
        if not isinstance(value, str) or len(value) > maximum * 2:
            raise ValueError
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) > maximum:
            raise ValueError
        return raw
    except (binascii.Error, ValueError):
        fail("EVIDENCE_BYTES", "Original evidence bytes are missing or invalid")


def resources(envelope, adapter):
    values = envelope["resources"]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_RESOURCES:
        fail("EVIDENCE_CAPACITY", "Every referenced evidence resource must be retained")
    result, manifest, total = {}, [], 0
    for value in values:
        keys(value, "id kind source_locator sha256 byte_size data_base64")
        identity = nonblank(value["id"], 200)
        locator = nonblank(value["source_locator"])
        if identity in result or not locator.startswith(adapter["source_prefix"]):
            fail("EVIDENCE_SOURCE", "Resource must belong to the configured source namespace")
        raw = decoded(value["data_base64"])
        total += len(raw)
        if total > MAX_BYTES or type(value["byte_size"]) is not int:
            fail("EVIDENCE_CAPACITY", "Evidence bytes cannot be truncated or exceed capacity")
        if sha(raw) != value["sha256"] or len(raw) != value["byte_size"]:
            fail("EVIDENCE_BYTES", "The exact original receipt bytes changed")
        if value["kind"] == "original_bytes":
            document = None
        elif value["kind"] == "page_render_png":
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                fail("VISUAL_EVIDENCE", "Actual bounded page image bytes are required")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as page:
                        if (
                            page.format != "PNG"
                            or min(page.size) < 32
                            or page.width * page.height > 40000000
                        ):
                            fail("VISUAL_EVIDENCE", "Bounded full-page raster evidence required")
                        page.verify()
            except (
                OSError,
                ValueError,
                Image.DecompressionBombWarning,
                Image.DecompressionBombError,
            ):
                fail("VISUAL_EVIDENCE", "Page rendering evidence is malformed")
            document = None
        elif value["kind"] in {"byte_event", "actual_submission", "coverage", "scale", "grouping"}:
            document = load(raw)
        else:
            fail("EVIDENCE_SHAPE", "Unsupported evidence resource kind")
        result[identity] = {"metadata": value, "document": document}
        manifest.append({k: v for k, v in value.items() if k != "data_base64"})
    if sorted(manifest, key=lambda row: row["id"]) != envelope["payload"]["resources_manifest"]:
        fail("EVIDENCE_SIGNATURE_BINDING", "Signed manifest must cover every original resource")
    return result


def _resource(values, identity, kind, used):
    if identity not in values or values[identity]["metadata"]["kind"] != kind:
        fail("EVIDENCE_SOURCE", "The required explicit source resource is absent")
    used.add(identity)
    return values[identity]["document"]


def _at(value):
    return instant(value).astimezone(timezone.utc)


def _event(values, identity, expected, original, context, issued, used):
    value = _resource(values, identity, "byte_event", used)
    keys(value, "schema event original_sha256 byte_size at valid_until party_id recorded_at")
    if (
        value["schema"] != "historical-original-byte-event/1"
        or value["event"] != expected
        or value["original_sha256"] != original["digest"]
        or value["byte_size"] != original["byte_size"]
        or type(value["byte_size"]) is not int
    ):
        fail("HISTORICAL_BYTES_UNPROVEN", "Historical event must identify these exact bytes")
    at, recorded = _at(value["at"]), _at(value["recorded_at"])
    boundary = _at(context["submission"]["submitted_at"])
    if not at <= recorded <= issued or recorded > boundary:
        fail(
            "HISTORICAL_TIME_UNPROVEN",
            "A current reconstruction is not a contemporaneous byte event",
        )
    if expected == "acquired":
        if value["party_id"] != context["identity"]["bidder_id"]:
            fail("HISTORICAL_PARTY_UNPROVEN", "Acquisition must be by the exact submitting bidder")
        if at != _at(original["obtained_at"]):
            fail(
                "HISTORICAL_ACQUISITION_MISMATCH",
                "Recorded acquisition and source evidence disagree",
            )
    elif value["party_id"] is not None:
        fail("EVIDENCE_SHAPE", "Only acquisition events carry the bidder identity")
    if expected == "effective":
        if value["valid_until"] is not None and _at(value["valid_until"]) <= boundary:
            fail("HISTORICAL_AUTHORITY_EXPIRED", "Authority was not effective at actual submission")
    elif value["valid_until"] is not None:
        fail("EVIDENCE_SHAPE", "Only effective events can declare an end instant")
    return value


def _history(payload, values, context, issued, used):
    originals = {row["document_version_id"]: row for row in context["originals"]}
    documents = payload["documents"]
    if not isinstance(documents, list) or len(documents) != len(originals):
        fail("HISTORICAL_DOCUMENT_SET", "All originals and full source ancestors require proof")
    seen, facts = set(), []
    for item in documents:
        keys(
            item,
            "document_version_id digest byte_size original_resource exists acquired published effective",
        )
        identity = item["document_version_id"]
        if identity in seen or identity not in originals:
            fail("HISTORICAL_DOCUMENT_SET", "A subset or another original cannot substitute")
        seen.add(identity)
        original = originals[identity]
        if any(item[field] != original[field] for field in ("digest", "byte_size")):
            fail("HISTORICAL_BYTES_UNPROVEN", "Today's converted bytes are not historic originals")
        _resource(values, item["original_resource"], "original_bytes", used)
        resource = values[item["original_resource"]]["metadata"]
        if (
            resource["sha256"] != original["digest"]
            or resource["byte_size"] != original["byte_size"]
        ):
            fail("HISTORICAL_BYTES_UNPROVEN", "The complete original bytes must still be available")
        exists = _event(values, item["exists"], "exists", original, context, issued, used)
        acquired = _event(values, item["acquired"], "acquired", original, context, issued, used)
        if _at(exists["at"]) > _at(acquired["at"]):
            fail("HISTORICAL_TIME_UNPROVEN", "Exact bytes must exist before acquisition")
        published = effective = None
        if original["requires_effective_proof"]:
            published = _event(
                values, item["published"], "published", original, context, issued, used
            )
            effective = _event(
                values, item["effective"], "effective", original, context, issued, used
            )
            if _at(published["at"]) > _at(effective["at"]):
                fail("HISTORICAL_TIME_UNPROVEN", "Publication and effectivity order is invalid")
        elif item["published"] is not None or item["effective"] is not None:
            fail("EVIDENCE_SHAPE", "Private submission content cannot invent public authority")
        facts.append(
            {
                "document_version_id": identity,
                "exists": exists,
                "acquired": acquired,
                "published": published,
                "effective": effective,
            }
        )
    return sorted(facts, key=lambda row: row["document_version_id"])


def _submission(payload, values, context, issued, used):
    value = _resource(values, payload["submission_resource"], "actual_submission", used)
    keys(value, "schema at recorded_at identity_digest package_digest files platform_reference")
    if (
        value["schema"] != "actual-package-submission-receipt/1"
        or _at(value["at"]) != _at(context["submission"]["submitted_at"])
        or not _at(value["at"]) <= _at(value["recorded_at"]) <= issued
        or value["identity_digest"] != context["identity"]["digest"]
        or value["package_digest"] != context["basis"]["package_digest"]
        or value["files"] != context["target_files"]
    ):
        fail(
            "ACTUAL_SUBMISSION_UNPROVEN",
            "Exact bidder, lot, round and complete submitted bytes required",
        )
    nonblank(value["platform_reference"])
    return value


def _coverage(payload, values, context, issued, used):
    value = _resource(values, payload["coverage_resource"], "coverage", used)
    keys(
        value,
        "schema reviewed_at reviewer_reference scope_digest inventory_digest parts rules pages",
    )
    if (
        value["schema"] != "full-package-coverage-review/1"
        or _at(value["reviewed_at"]) > issued
        or value["scope_digest"] != context["scope"]["digest"]
        or value["inventory_digest"] != context["basis"]["inventory_digest"]
        or value["parts"] != context["technical_part_ids"]
        or value["rules"] != context["rule_scopes"]
    ):
        fail(
            "REQUIRED_RANGE_UNPROVEN",
            "Independent range evidence must bind every native rule and part",
        )
    nonblank(value["reviewer_reference"])
    expected = {}
    for document in context["documents"]:
        for page in document["pages"]:
            if page["quality"] != "usable" or page["gaps"]:
                fail("FULL_VISUAL_UNPROVEN", "Incomplete pages remain ineligible")
            blocks = [b for b in document["blocks"] if b["physical_page"] == page["physical_page"]]
            key = (document["document_version_id"], page["physical_page"])
            expected[key] = {
                "document_version_id": key[0],
                "original_sha256": document["file_digest"],
                "parse_id": document["parse"]["parse_run_id"],
                "physical_page": key[1],
                "blocks_digest": digest(blocks),
            }
    if not isinstance(value["pages"], list) or len(value["pages"]) != len(expected):
        fail(
            "FULL_VISUAL_UNPROVEN",
            "Every full physical page requires bound original render evidence",
        )
    seen = set()
    for row in value["pages"]:
        keys(
            row,
            "document_version_id original_sha256 parse_id physical_page blocks_digest image_resource",
        )
        key = (row["document_version_id"], row["physical_page"])
        if (
            key in seen
            or key not in expected
            or {k: v for k, v in row.items() if k != "image_resource"} != expected[key]
        ):
            fail(
                "FULL_VISUAL_UNPROVEN",
                "Page renders, exact parsing and full evidence cannot be substituted",
            )
        seen.add(key)
        _resource(values, row["image_resource"], "page_render_png", used)
    return value


def _scale(payload, values, context, issued, used):
    value = _resource(values, payload["scale_resource"], "scale", used)
    keys(
        value,
        "schema reviewed_at reviewer_reference evidence_id quote maximum scale_description aggregation",
    )
    evidence = {
        block["id"]: block
        for document in context["documents"]
        if document["package_role"] == "authority"
        for block in document["blocks"]
    }
    block = evidence.get(value["evidence_id"])
    if (
        value["schema"] != "package-technical-scale-evidence/1"
        or _at(value["reviewed_at"]) > issued
        or block is None
        or block["text_content"] != value["quote"]
        or block["digest"] != sha(value["quote"].encode())
        or value["scale_description"] != "未加权原始分"
        or value["aggregation"] != "published_final_technical_total"
    ):
        fail(
            "MAXIMUM_AGGREGATION_UNPROVEN",
            "Independent authority evidence and supported explicit scale required",
        )
    nonblank(value["reviewer_reference"])
    match = SCALE.fullmatch(value["quote"])
    if (
        match is None
        or not isinstance(value["maximum"], str)
        or re.fullmatch(r"(0|[1-9][0-9]*)(\.[0-9]{1,8})?", value["maximum"]) is None
    ):
        fail("MAXIMUM_AGGREGATION_UNPROVEN", "Unknown aggregation is never an implicit average")
    maximum = Decimal(match.group(1))
    if not 0 < maximum <= Decimal("1000000000") or Decimal(value["maximum"]) != maximum:
        fail("MAXIMUM_AGGREGATION_UNPROVEN", "Exact authority maximum required")
    label = context["label"]
    if Decimal(label["maximum"]) != maximum:
        fail(
            "OFFICIAL_SCALE_MISMATCH",
            "Official label and independent authority use different scales",
        )
    rule_maximum = sum(Decimal(rule["maximum"]) for rule in context["applicable_rules"])
    if rule_maximum != maximum:
        fail(
            "REQUIRED_RANGE_UNPROVEN",
            "All applicable native rule maxima must equal the authority total",
        )
    return value


def _grouping(payload, values, context, issued, used):
    value = _resource(values, payload["grouping_resource"], "grouping", used)
    keys(
        value,
        "schema reviewed_at reviewer_reference scope_digest method source_references template_keys near_duplicate_keys",
    )
    if (
        value["schema"] != "package-related-content-review/1"
        or value["scope_digest"] != context["scope"]["digest"]
        or _at(value["reviewed_at"]) > issued
        or value["method"] != "evidence-backed-template-and-near-duplicate-review/1"
    ):
        fail(
            "GROUPING_UNPROVEN", "Related content assessment must bind the complete original scope"
        )
    nonblank(value["reviewer_reference"])
    references = value["source_references"]
    if not isinstance(references, list) or not references:
        fail("GROUPING_UNPROVEN", "Grouping review must retain its original evidence references")
    for reference in references:
        nonblank(reference)
    for name in ("template_keys", "near_duplicate_keys"):
        identities = value[name]
        if (
            not isinstance(identities, list)
            or len(identities) > 1000
            or len(set(identities)) != len(identities)
        ):
            fail("GROUPING_UNPROVEN", "Unique bounded related-source identifiers required")
        for identity in identities:
            nonblank(identity, 200)
    return value


def _verify(envelope, *, adapter, context, observed_at):
    """Return a normalized, auditable proof, never a qualification boolean."""
    keys(envelope, "schema key_id payload signature_base64 resources")
    payload = envelope["payload"]
    keys(
        payload,
        "schema receipt_id issued_at context_digest documents submission_resource coverage_resource scale_resource grouping_resource label_original_resource resources_manifest",
    )
    if (
        envelope["schema"] != "package-history-signed-evidence/1"
        or payload["schema"] != "package-history-proof/1"
        or adapter["method"] != ADAPTER
        or envelope["key_id"] != adapter["id"]
        or payload["context_digest"] != digest(context)
    ):
        fail("PROOF_BINDING", "Explicit adapter and exact native context are required")
    nonblank(payload["receipt_id"], 200)
    issued, observed = _at(payload["issued_at"]), _at(observed_at)
    if not _at(adapter["valid_from"]) <= issued <= observed or (
        adapter["valid_until"] is not None and issued >= _at(adapter["valid_until"])
    ):
        fail("PROOF_TIME", "Source issuance must be within its configured trust window")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(adapter["public_key_hex"])).verify(
            decoded(envelope["signature_base64"], 64), canonical(payload)
        )
    except (InvalidSignature, ValueError):
        fail("SIGNATURE_INVALID", "Source signature does not authenticate this exact assertion")
    values = resources(envelope, adapter)
    used: set[str] = set()
    history = _history(payload, values, context, issued, used)
    actual = _submission(payload, values, context, issued, used)
    coverage = _coverage(payload, values, context, issued, used)
    scale = _scale(payload, values, context, issued, used)
    grouping = _grouping(payload, values, context, issued, used)
    _resource(values, payload["label_original_resource"], "original_bytes", used)
    official = values[payload["label_original_resource"]]["metadata"]
    if (
        official["sha256"] != context["label"]["file_digest"]
        or official["byte_size"] != context["label"]["byte_size"]
    ):
        fail("OFFICIAL_ORIGINAL_UNAVAILABLE", "Exact official original bytes must be retained")
    if used != set(values):
        fail("EVIDENCE_SURPLUS", "Unreferenced attachments cannot enter a qualification receipt")
    return {
        "schema": "package-history-normalized-evidence/1",
        "adapter_id": adapter["id"],
        "adapter_method": ADAPTER,
        "origin": adapter["origin"],
        "context_digest": digest(context),
        "receipt_id": payload["receipt_id"],
        "issued_at": payload["issued_at"],
        "historical_as_of": context["submission"]["submitted_at"],
        "historical_facts": history,
        "actual_submission": actual,
        "coverage": coverage,
        "scale": scale,
        "grouping": grouping,
        "envelope_digest": digest(envelope),
        "research_only": True,
        "formal_eligibility": "unavailable",
        "strict_prebid_eligible": False,
        "online_metrics_eligible": False,
    }


def verify(envelope, *, adapter, context, observed_at):
    """Untrusted source bytes produce a bounded refusal, never a private traceback."""
    try:
        return _verify(envelope, adapter=adapter, context=context, observed_at=observed_at)
    except GovernanceError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError):
        fail("EVIDENCE_SHAPE", "Malformed or incomplete source evidence cannot qualify")
