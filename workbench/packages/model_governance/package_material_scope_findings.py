"""Evidence-bound review claims. Identity and content authority are separate.

The reporter supplies substantive findings for every frozen checklist item.
This module checks structure, exact citations and declared scope consistency;
it cannot prove that a person read an image or that a claim is substantively true.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_material_scope_review as review
from packages.storage.private_cas import is_digest, sha

MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 100_000
MAX_CITATIONS = 2000
MAX_REASON = 8000
MAX_QUOTE = 16000
OUTCOMES = frozenset({"confirmed", "change_required", "unable_to_verify"})
RELATIONS = frozenset({"in_scope", "out_of_scope", "source_reference", "retained_non_scoring"})


class ScopeFindingsError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise ScopeFindingsError("SCOPE_FINDINGS_" + code)


@dataclass(frozen=True, repr=False)
class CheckedScopeFindings:
    metadata: dict
    review_packet: review.ScopeReviewPacket


def method_digest():
    return digest(
        {
            "version": "package-material-scope-findings-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "review_method": review.method_digest(),
            "limits": [MAX_BYTES, MAX_NODES, MAX_CITATIONS, MAX_REASON, MAX_QUOTE],
            "outcomes": sorted(OUTCOMES),
            "relations": sorted(RELATIONS),
            "authority_grants": False,
        }
    )


def _bounded(value):
    pending = [(value, 0)]
    nodes = total = 0
    invalid = False
    try:
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if depth > 64 or nodes > MAX_NODES:
                fail("STRUCTURE_LIMIT")
            if type(item) is dict:
                if nodes + len(pending) + 2 * len(item) > MAX_NODES:
                    fail("STRUCTURE_LIMIT")
                if any(type(k) is not str or any(ord(c) > 0xFFFF for c in k) for k in item):
                    fail("STRUCTURE_INVALID")
                total += 2 + 2 * len(item)
                pending.extend((v, depth + 1) for pair in item.items() for v in pair)
            elif type(item) is list:
                if nodes + len(pending) + len(item) > MAX_NODES:
                    fail("STRUCTURE_LIMIT")
                total += 2 + len(item)
                pending.extend((v, depth + 1) for v in item)
            elif type(item) is str:
                if len(item) > MAX_BYTES:
                    fail("BYTE_LIMIT")
                total += len(json.dumps(item, ensure_ascii=False).encode())
            elif type(item) is bool or item is None:
                total += 5
            elif type(item) is int and abs(item) <= 9_007_199_254_740_991:
                total += len(str(item))
            else:
                fail("STRUCTURE_INVALID")
            if total > MAX_BYTES:
                fail("BYTE_LIMIT")
    except ScopeFindingsError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        invalid = True
    if invalid:
        fail("STRUCTURE_INVALID")


def _uuid(value):
    valid = False
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        pass
    if not valid:
        fail("REFERENCE_INVALID")


def _citation(value, images, evidence, reviewed):
    fields = {
        "image_asset_id",
        "document_version_id",
        "parse_run_id",
        "physical_page",
        "evidence_id",
        "quote",
        "rectangle",
    }
    if type(value) is not dict or set(value) != fields or not is_digest(value["image_asset_id"]):
        fail("CITATION_INVALID")
    _uuid(value["document_version_id"])
    _uuid(value["parse_run_id"])
    image = images.get(value["image_asset_id"])
    if (
        image is None
        or type(value["physical_page"]) is not int
        or any(
            value[k] != image[k] for k in ("document_version_id", "parse_run_id", "physical_page")
        )
    ):
        fail("CITATION_BINDING_MISMATCH")
    if value["image_asset_id"] not in reviewed:
        fail("CITATION_IMAGE_NOT_REVIEWED")
    box = value["rectangle"]
    if box is not None and (
        type(box) is not list
        or len(box) != 4
        or any(type(n) is not int for n in box)
        or not 0 <= box[0] < box[2] <= image["asset"]["width"]
        or not 0 <= box[1] < box[3] <= image["asset"]["height"]
    ):
        fail("CITATION_RECTANGLE_INVALID")
    if value["evidence_id"] is None:
        if value["quote"] is not None:
            fail("CITATION_TEXT_INVALID")
    else:
        _uuid(value["evidence_id"])
        original = evidence.get(value["evidence_id"])
        quote = value["quote"]
        if (
            original is None
            or image["kind"] != "full_page"
            or any(
                value[k] != original[k]
                for k in ("document_version_id", "parse_run_id", "physical_page")
            )
            or image["asset"]["sha256"] != original["page_image_digest"]
            or type(quote) is not str
            or not quote.strip()
            or len(quote) > MAX_QUOTE
            or quote not in original["text_content"]
        ):
            fail("CITATION_TEXT_INVALID")
    return value


def _confirmed(item, finding, packet):
    m = packet.metadata
    subject = item["subject"]
    kind = item["kind"]
    citations = finding["citations"]
    if not citations:
        fail("CONFIRMED_EVIDENCE_REQUIRED")
    relation = finding["scope_relation"]
    required = set(finding["required_part_ids"])
    if kind in review.OBLIGATIONS:
        if relation is not None or required:
            fail("GLOBAL_SCOPE_INVALID")
        roles = (
            {"authority"}
            if kind in {"authority_and_amendment_completeness", "inventory_exhaustiveness"}
            else {"target", "authority"}
        )
        expected_documents = {
            r["member"]["document_version_id"] for r in m["documents"] if r["package_role"] in roles
        }
        if not expected_documents <= {c["document_version_id"] for c in citations}:
            fail("GLOBAL_DOCUMENT_EVIDENCE_INCOMPLETE")
    elif kind == "document_source_and_full_page_review":
        row = next(
            r
            for r in m["documents"]
            if r["package_role"] == subject["package_role"]
            and r["member"]["member_id"] == subject["member_id"]
        )
        if (
            relation is not None
            or required
            or not any(
                c["document_version_id"] == row["member"]["document_version_id"] for c in citations
            )
        ):
            fail("DOCUMENT_EVIDENCE_MISMATCH")
    elif kind == "declared_section_and_related_range_review":
        row = next(
            r
            for r in m["parts"]
            if r["package_role"] == subject["package_role"]
            and r["part"]["part_id"] == subject["part_id"]
        )
        expected_relation = (
            "source_reference"
            if row["package_role"] == "authority"
            else ("in_scope" if row["declared_selected"] else "out_of_scope")
        )
        if (
            relation != expected_relation
            or required
            or not any(
                c["document_version_id"] == row["document_version_id"]
                and c["physical_page"] in row["physical_pages"]
                for c in citations
            )
        ):
            fail("PART_SCOPE_REVISION_REQUIRED")
    elif kind == "requirement_applicability_and_scope_review":
        row = next(r for r in m["requirements"] if r["rule_id"] == subject["rule_id"])
        source = row["frozen_inventory_binding"]["rule_snapshot"]["evidence_ids"]
        if not source or not set(source) <= {
            c["evidence_id"] for c in citations if c["evidence_id"] is not None
        }:
            fail("RULE_SOURCE_EVIDENCE_INCOMPLETE")
        if row["kind"] != "scoring":
            if relation != "retained_non_scoring" or required:
                fail("NON_SCORING_SCOPE_INVALID")
        else:
            scoped = row["frozen_technical_scope_rule"]
            selection = row["declared_selection"]
            if (
                selection not in {"include", "exclude"}
                or relation != {"include": "in_scope", "exclude": "out_of_scope"}[selection]
            ):
                fail("RULE_SCOPE_REVISION_REQUIRED")
            expected = set(scoped["required_part_ids"]) if selection == "include" else set()
            declared = set(scoped["frozen_rule"]["declared_target_part_ids"])
            if required != expected or (selection == "include" and not declared <= required):
                fail("RULE_SCOPE_REVISION_REQUIRED")
    else:
        fail("CHECK_KIND_INVALID")


def validate(packet, draft, *, expected_review_digest, expected_method_digest):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    owned = review.verify(packet, expected_digest=expected_review_digest)
    _bounded(draft)
    raw = deepcopy(draft)
    fields = {"version", "context_digest", "review_digest", "reviewed_image_ids", "findings"}
    if (
        type(raw) is not dict
        or set(raw) != fields
        or raw["version"] != "package-material-scope-findings/1"
        or raw["context_digest"] != owned.metadata["context_digest"]
        or raw["review_digest"] != expected_review_digest
        or type(raw["reviewed_image_ids"]) is not list
        or type(raw["findings"]) is not list
        or len(raw["findings"]) != len(owned.metadata["check_items"])
    ):
        fail("DRAFT_INVALID")
    images = {r["asset"]["id"]: r for r in owned.context.metadata["images"]}
    ids = raw["reviewed_image_ids"]
    if (
        any(not is_digest(key) for key in ids)
        or len(set(ids)) != len(ids)
        or not set(ids) <= set(images)
    ):
        fail("REVIEWED_IMAGE_SET_INVALID")
    reviewed = set(ids)
    evidence = {r["id"]: r for r in owned.context.metadata["evidence_catalog"]}
    checks = {r["check_id"]: r for r in owned.metadata["check_items"]}
    seen = set()
    target_parts = {
        r["part"]["part_id"] for r in owned.metadata["parts"] if r["package_role"] == "target"
    }
    for finding in raw["findings"]:
        keys = {"check_id", "outcome", "scope_relation", "required_part_ids", "reason", "citations"}
        if (
            type(finding) is not dict
            or set(finding) != keys
            or not is_digest(finding["check_id"])
            or finding["check_id"] not in checks
            or finding["check_id"] in seen
            or type(finding["outcome"]) is not str
            or finding["outcome"] not in OUTCOMES
            or (
                finding["scope_relation"] is not None
                and (
                    type(finding["scope_relation"]) is not str
                    or finding["scope_relation"] not in RELATIONS
                )
            )
            or type(finding["reason"]) is not str
            or not finding["reason"].strip()
            or "\x00" in finding["reason"]
            or len(finding["reason"]) > MAX_REASON
            or type(finding["required_part_ids"]) is not list
            or any(type(p) is not str for p in finding["required_part_ids"])
            or type(finding["citations"]) is not list
            or len(finding["citations"]) > MAX_CITATIONS
        ):
            fail("FINDING_INVALID")
        required = finding["required_part_ids"]
        if len(set(required)) != len(required) or not set(required) <= target_parts:
            fail("REQUIRED_PART_SET_INVALID")
        seen.add(finding["check_id"])
        citations = finding["citations"]
        if len({digest(c) for c in citations}) != len(citations):
            fail("DUPLICATE_CITATION")
        for citation in citations:
            _citation(citation, images, evidence, reviewed)
        if finding["outcome"] == "confirmed":
            _confirmed(checks[finding["check_id"]], finding, owned)
    if seen != set(checks):
        fail("CHECK_SET_MISMATCH")
    all_confirmed = all(f["outcome"] == "confirmed" for f in raw["findings"])
    if all_confirmed and reviewed != set(images):
        fail("COMPLETE_IMAGE_REVIEW_CLAIM_REQUIRED")
    metadata = {
        "version": "package-material-scope-findings-check/1",
        "method_digest": method,
        "context_digest": raw["context_digest"],
        "review_digest": expected_review_digest,
        "draft_digest": digest(raw),
        "draft": raw,
        "all_findings_claimed_confirmed": all_confirmed,
        "all_images_claimed_reviewed": reviewed == set(images),
        "scope_changes_requested": any(f["outcome"] == "change_required" for f in raw["findings"]),
        "reviewer_identity_verified": False,
        "semantic_completeness_verified": False,
        "necessary_scope_verified": False,
        "native_binding_verified": False,
        "input_authority_granted": False,
        "execution_authorized": False,
        "regions_are_bounds_checked_only": True,
    }
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return CheckedScopeFindings(metadata | {"digest": digest(metadata)}, owned)


def verify(value, *, expected_digest):
    if (
        type(value) is not CheckedScopeFindings
        or type(value.metadata) is not dict
        or value.metadata.get("digest") != expected_digest
    ):
        fail("CHECKED_FINDINGS_MISMATCH")
    m = deepcopy(value.metadata)
    rebuilt = validate(
        value.review_packet,
        m.get("draft"),
        expected_review_digest=m.get("review_digest"),
        expected_method_digest=m.get("method_digest"),
    )
    if canonical(rebuilt.metadata) != canonical(m):
        fail("CHECKED_FINDINGS_MISMATCH")
    return rebuilt
