"""Select exact fact evidence from a validated frozen package, without current heads."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.package_review_frozen_input import FrozenPackageReviewInput
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError
from packages.rag.indexing import parse_source_id

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/schemas/package-fact-evidence.schema.json"
    ).read_text("utf-8")
)


def validate(name, value):
    _require(
        Draft202012Validator(
            {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
        ).is_valid(value)
    )


def _require(condition):
    if not condition:
        raise DomainError("PACKAGE_FACT_EVIDENCE_INVALID", "请选择冻结整包内的明确原页依据", 422)


@dataclass(frozen=True, slots=True)
class FrozenFactEvidenceSelection:
    digest: str
    _text: str = field(repr=False)

    def view(self):
        return json.loads(self._text)


def select(packet: FrozenPackageReviewInput, frozen_digest: str, evidence_ids: list[str]):
    if packet.digest != frozen_digest:
        raise DomainError(
            "PACKAGE_REVIEW_FROZEN_INPUT_CHANGED", "冻结记录摘要与明确选择不一致", 409
        )
    _require(isinstance(evidence_ids, list) and 1 <= len(evidence_ids) <= 500)
    try:
        _require(
            all(isinstance(value, str) and str(UUID(value)) == value for value in evidence_ids)
        )
        _require(len(set(evidence_ids)) == len(evidence_ids))
    except (ValueError, TypeError, AttributeError) as error:
        raise DomainError(
            "PACKAGE_FACT_EVIDENCE_INVALID", "请选择有效的明确原页依据", 422
        ) from error
    selected = set(evidence_ids)
    rows: dict[str, dict[str, Any]] = {}
    for doc in packet.evidence()["documents"]:
        for block in doc["blocks"]:
            if block["id"] in selected:
                row = {
                    "evidence_id": block["id"],
                    "document_version_id": doc["document_version_id"],
                    "parse_run_id": doc["parse_id"],
                    "source_id": str(parse_source_id(UUID(doc["parse_id"]))),
                    "file_digest": doc["digest"],
                    "evidence_digest": block["digest"],
                    "physical_page": block["physical_page"],
                }
                _require(block["id"] not in rows or rows[block["id"]] == row)
                rows[block["id"]] = row
    _require(set(rows) == selected)
    m = packet.view()["manifest"]
    manifest = {
        "version": "package-fact-evidence-selection/1",
        "frozen_input": {
            key: m[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id", "id")
        }
        | {"digest": packet.digest},
        "selected": [rows[key] for key in sorted(rows)],
        "original_bytes_verified": False,
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    validate("Selection", manifest)
    return FrozenFactEvidenceSelection(digest(manifest), canonical(manifest).decode("utf-8"))
