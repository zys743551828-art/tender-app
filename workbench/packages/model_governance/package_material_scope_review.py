"""Complete private review checklist, without deciding semantic completeness.

All frozen package members, declared parts and inventory requirements remain in
the denominator. Selection, page bytes and a review checklist are not authority.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_technical_material as material
from packages.storage.private_cas import sha

MAX_PARTS = 4000
MAX_REQUIREMENTS = 2000
MAX_DECLARED_RELATIONS = 100_000
MAX_BYTES = 16 * 1024 * 1024
OBLIGATIONS = (
    "authority_and_amendment_completeness",
    "inventory_exhaustiveness",
    "complete_related_sections_attachments_and_cross_references",
    "original_page_readability_and_tables",
)


class MaterialScopeReviewError(ValueError):
    pass


def fail(code: str) -> NoReturn:
    raise MaterialScopeReviewError("MATERIAL_SCOPE_REVIEW_" + code)


@dataclass(frozen=True, repr=False)
class ScopeReviewPacket:
    metadata: dict
    context: material.MaterialContext


def method_digest():
    return digest(
        {
            "version": "package-material-scope-review-method/1",
            "source": sha(Path(__file__).read_bytes()),
            "context_method": material.context_method_digest(),
            "limits": [MAX_PARTS, MAX_REQUIREMENTS, MAX_DECLARED_RELATIONS, MAX_BYTES],
            "obligations": list(OBLIGATIONS),
            "authority_grants": False,
        }
    )


def _documents(context):
    m = context.metadata["material"]
    native = {r["document_version_id"]: r for r in m["native_documents"]}
    documents, members, seen = [], {}, set()
    for role in ("target", "authority"):
        for member in m[role]["manifest"]["members"]:
            key = (role, member["member_id"])
            if key in members or member["document_version_id"] not in native:
                fail("MEMBER_SET_MISMATCH")
            doc = native[member["document_version_id"]]
            identity = member["parse"]
            if (
                member["file_digest"] != doc["source_digest"]
                or type(member["page_count"]) is not int
                or member["page_count"] != doc["page_count"]
                or identity["status"] != "frozen"
                or any(
                    identity[left] != doc[right]
                    for left, right in (
                        ("parse_run_id", "parse_run_id"),
                        ("evidence_digest", "parse_digest"),
                        ("parser_digest", "parser_digest"),
                        ("config_digest", "config_digest"),
                    )
                )
            ):
                fail("MEMBER_BINDING_MISMATCH")
            images = [
                r
                for r in context.metadata["images"]
                if r["document_version_id"] == doc["document_version_id"]
            ]
            documents.append(
                {
                    "package_role": role,
                    "package_digest": m[role]["digest"],
                    "member": deepcopy(member),
                    "parse_run_id": doc["parse_run_id"],
                    "physical_pages": [p["physical_page"] for p in doc["pages"]],
                    "image_asset_ids": [p["asset"]["id"] for p in images],
                    "native_page_gaps": [
                        deepcopy(p)
                        for p in doc["pages"]
                        if p["quality"] != "usable" or json.loads(p["gaps"])
                    ],
                    "source_authority_review": "required",
                }
            )
            members[key] = (member, doc)
            seen.add(doc["document_version_id"])
    if seen != set(native):
        fail("MEMBER_SET_MISMATCH")
    return documents, members


def _parts(context, members):
    preview = context.metadata["material"]["scope"]["manifest"]["preview"]["manifest"]
    frozen_parts = preview["parts"]
    selected = {}
    for row in frozen_parts:
        key = row["part"]["part_id"]
        if key in selected or type(row["selected"]) is not bool:
            fail("PART_SELECTION_INVALID")
        selected[key] = row
    rows, known = [], set()
    for (role, member_id), (member, doc) in members.items():
        for part in member["parts"]:
            key = (role, part["part_id"])
            start, end = part["first_page"], part["last_page"]
            path = part["heading_path"]
            if (
                key in known
                or type(start) is not int
                or type(end) is not int
                or not 1 <= start <= end <= doc["page_count"]
                or type(part["shared_attachment"]) is not bool
                or type(path) is not list
                or any(type(n) is not int or n < 1 for n in path)
            ):
                fail("PART_DECLARATION_INVALID")
            known.add(key)
            pages = list(range(start, end + 1))
            blocks = [b for b in doc["blocks"] if b["physical_page"] in pages]
            original = None
            if role == "target":
                original = selected.get(part["part_id"])
                expected = {
                    "member_id": member_id,
                    "document_version_id": doc["document_version_id"],
                    "file_digest": doc["source_digest"],
                    "part": part,
                    "read_physical_pages": pages,
                    "block_ids": [b["id"] for b in blocks],
                    "text_evidence_present": any(
                        b["kind"] == "text" and b["text_content"].strip() for b in blocks
                    ),
                    "visual_coverage": "unproven",
                }
                if original is None or canonical(
                    {k: original.get(k) for k in expected}
                ) != canonical(expected):
                    fail("FROZEN_PART_PROJECTION_MISMATCH")
            rows.append(
                {
                    "package_role": role,
                    "member_id": member_id,
                    "document_version_id": doc["document_version_id"],
                    "parse_run_id": doc["parse_run_id"],
                    "part": deepcopy(part),
                    "physical_pages": pages,
                    "evidence_ids": [b["id"] for b in blocks],
                    "image_asset_ids": [
                        r["asset"]["id"]
                        for r in context.metadata["images"]
                        if r["document_version_id"] == doc["document_version_id"]
                        and r["physical_page"] in pages
                    ],
                    "declared_selected": original["selected"] if original is not None else None,
                    "frozen_scope_part": deepcopy(original),
                    "semantic_necessity_review": "required",
                }
            )
    if len(rows) > MAX_PARTS:
        fail("PART_LIMIT")
    if set(selected) != {identity for role, identity in known if role == "target"}:
        fail("PART_SET_MISMATCH")
    by_path: dict[tuple, list[dict]] = {}
    for row in rows:
        row["declared_heading_descendant_ids"] = []
        row["unselected_declared_descendant_ids"] = []
        key = (row["package_role"], row["member_id"], tuple(row["part"]["heading_path"]))
        by_path.setdefault(key, []).append(row)
    relations = 0
    for child in rows:
        path = child["part"]["heading_path"]
        for length in range(1, len(path)):
            key = (child["package_role"], child["member_id"], tuple(path[:length]))
            for parent in by_path.get(key, []):
                relations += 1
                if relations > MAX_DECLARED_RELATIONS:
                    fail("DECLARED_RELATION_LIMIT")
                parent["declared_heading_descendant_ids"].append(child["part"]["part_id"])
                if child["declared_selected"] is False:
                    parent["unselected_declared_descendant_ids"].append(child["part"]["part_id"])
    return rows


def _requirements(context, parts):
    frozen = context.metadata["material"]["inventory"]["manifest"]["requirements"]
    if not 1 <= len(frozen) <= MAX_REQUIREMENTS:
        fail("INVENTORY_LIMIT")
    rules = {r["rule_id"]: r for r in context.metadata["rules"]}
    available = {r["id"] for r in context.metadata["evidence_catalog"]}
    target_parts = {r["part"]["part_id"] for r in parts if r["package_role"] == "target"}
    rows, scoring, seen = [], set(), set()
    for binding in frozen:
        identity = binding["rule_id"]
        snapshot, requirement = binding["rule_snapshot"], binding["requirement"]
        if (
            identity in seen
            or snapshot["id"] != identity
            or digest(snapshot) != binding["rule_digest"]
            or digest(requirement) != binding["requirement_digest"]
            or not set(requirement["target_part_ids"]) <= target_parts
        ):
            fail("INVENTORY_BINDING_MISMATCH")
        seen.add(identity)
        scoped = rules.get(identity)
        if snapshot["kind"] == "scoring":
            scoring.add(identity)
            if scoped is None:
                fail("SCORING_RULE_SET_MISMATCH")
            original = scoped["frozen_rule"]
            if (
                original["rule_digest"] != binding["rule_digest"]
                or original["requirement_digest"] != binding["requirement_digest"]
                or canonical(original["rule_snapshot"]) != canonical(snapshot)
                or original["declared_target_part_ids"] != requirement["target_part_ids"]
            ):
                fail("SCORING_RULE_BINDING_MISMATCH")
        elif scoped is not None:
            fail("SCORING_RULE_SET_MISMATCH")
        rows.append(
            {
                "rule_id": identity,
                "kind": snapshot["kind"],
                "frozen_inventory_binding": deepcopy(binding),
                "frozen_technical_scope_rule": deepcopy(scoped),
                "available_source_evidence_ids": [
                    key for key in snapshot["evidence_ids"] if key in available
                ],
                "missing_source_evidence_ids": [
                    key for key in snapshot["evidence_ids"] if key not in available
                ],
                "declared_selection": scoped["selection"] if scoped is not None else None,
                "applicability_and_range_review": "required",
            }
        )
    if scoring != set(rules):
        fail("SCORING_RULE_SET_MISMATCH")
    return rows


def build(context, *, expected_context_digest, expected_method_digest):
    method = method_digest()
    if expected_method_digest != method:
        fail("METHOD_MISMATCH")
    owned = material.verify_context(context, expected_context_digest)
    malformed = False
    try:
        documents, members = _documents(owned)
        parts = _parts(owned, members)
        requirements = _requirements(owned, parts)
    except (KeyError, TypeError):
        malformed = True
    if malformed:
        fail("FROZEN_STRUCTURE_INVALID")
    subjects: list[tuple[str, dict | None]] = [(kind, None) for kind in OBLIGATIONS]
    subjects += [
        (
            "document_source_and_full_page_review",
            {"package_role": row["package_role"], "member_id": row["member"]["member_id"]},
        )
        for row in documents
    ]
    subjects += [
        (
            "declared_section_and_related_range_review",
            {"package_role": row["package_role"], "part_id": row["part"]["part_id"]},
        )
        for row in parts
    ]
    subjects += [
        ("requirement_applicability_and_scope_review", {"rule_id": row["rule_id"]})
        for row in requirements
    ]
    items = []
    for kind, subject in subjects:
        body = {"context_digest": expected_context_digest, "kind": kind, "subject": subject}
        items.append(
            {"check_id": digest(body), "kind": kind, "subject": subject, "state": "unreviewed"}
        )
    metadata = {
        "version": "package-material-scope-review/1",
        "method_digest": method,
        "context_digest": expected_context_digest,
        "scope_digest": owned.metadata["scope_digest"],
        "documents": documents,
        "parts": parts,
        "requirements": requirements,
        "check_items": items,
        "frozen_scope_coverage": deepcopy(
            owned.metadata["material"]["scope"]["manifest"]["preview"]["manifest"]["coverage"]
        ),
        "state": "requires_independent_review",
        "cross_reference_semantic_closure": "unproven",
        "inventory_exhaustiveness": "unproven",
        "visual_readability_verified": False,
        "necessary_scope_verified": False,
        "input_authority_granted": False,
        "native_binding_verified": False,
        "execution_authorized": False,
    }
    if len(canonical(metadata)) > MAX_BYTES:
        fail("REVIEW_LIMIT")
    if method_digest() != method:
        fail("METHOD_CHANGED")
    return ScopeReviewPacket(metadata | {"digest": digest(metadata)}, owned)


def verify(packet, *, expected_digest):
    if (
        type(packet) is not ScopeReviewPacket
        or type(packet.metadata) is not dict
        or packet.metadata.get("digest") != expected_digest
    ):
        fail("PACKET_MISMATCH")
    metadata = deepcopy(packet.metadata)
    rebuilt = build(
        packet.context,
        expected_context_digest=metadata.get("context_digest"),
        expected_method_digest=metadata.get("method_digest"),
    )
    if canonical(rebuilt.metadata) != canonical(metadata):
        fail("PACKET_MISMATCH")
    return rebuilt
