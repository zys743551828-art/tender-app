"""Pure, defensive consumption of an immutable evidence root; never execution permission.

The root retains exact parse references, not the PostgreSQL-text geometry used by
package-parse-evidence/1. That parse hash is carried as frozen, not recomputed from
lossy JSON geometry. A new execution must separately revalidate the exact parse.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_packages import PackageError, safe_integer
from packages.domain.package_review_identity import candidate, summary
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import sha


@dataclass(frozen=True, slots=True)
class FrozenPackageReviewInput:
    _manifest_text: str = field(repr=False)
    _evidence_text: str = field(repr=False)
    digest: str

    def view(self) -> dict[str, Any]:
        return {"manifest": json.loads(self._manifest_text), "digest": self.digest}

    def evidence(self) -> dict[str, Any]:
        # Every reader owns its copy; downstream mutations cannot rewrite the root.
        return json.loads(self._evidence_text)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite_json_number")


def _check(condition):
    if not condition:
        raise ValueError("frozen_input_binding")


def _documents(selected, documents):
    expected = [
        (role, member)
        for role in ("target", "authority")
        for member in selected[role]["manifest"]["members"]
    ]
    _check(isinstance(documents, list) and len(documents) == len(expected))
    for doc, (role, member) in zip(documents, expected, strict=True):
        _check(
            set(doc)
            == {
                "document_version_id",
                "blob_id",
                "digest",
                "byte_size",
                "parse_id",
                "parser_digest",
                "config_digest",
                "page_count",
                "coverage",
                "gaps",
                "member_id",
                "pages",
                "blocks",
                "package_role",
            }
        )
        parse = member["parse"]
        _check(
            parse["status"] == "frozen"
            and doc["package_role"] == role
            and doc["member_id"] == member["member_id"]
            and doc["document_version_id"] == member["document_version_id"]
            and doc["parse_id"] == parse["parse_run_id"]
            and doc["digest"] == member["file_digest"]
            and doc["parser_digest"] == parse["parser_digest"]
            and doc["config_digest"] == parse["config_digest"]
            and doc["page_count"] == member["page_count"]
            and safe_integer(doc["page_count"], 1)
            and safe_integer(doc["byte_size"])
            and str(UUID(doc["blob_id"])) == doc["blob_id"]
            and doc["coverage"] == "complete"
            and doc["gaps"] == []
            and isinstance(doc["pages"], list)
            and len(doc["pages"]) == doc["page_count"]
            and isinstance(doc["blocks"], list)
        )
        for number, page in enumerate(doc["pages"], 1):
            _check(
                set(page) == {"physical_page", "quality", "gaps"}
                and type(page["physical_page"]) is int
                and page["physical_page"] == number
                and page["quality"] == "usable"
                and page["gaps"] == []
            )
        previous, ids = None, set()
        for block in doc["blocks"]:
            _check(
                set(block)
                == {
                    "id",
                    "physical_page",
                    "ordinal",
                    "kind",
                    "text_content",
                    "bbox",
                    "structure",
                    "digest",
                }
                and str(UUID(block["id"])) == block["id"]
                and block["id"] not in ids
                and safe_integer(block["physical_page"], 1)
                and block["physical_page"] <= doc["page_count"]
                and safe_integer(block["ordinal"])
                and isinstance(block["kind"], str)
                and isinstance(block["text_content"], str)
                and sha(block["text_content"].encode("utf-8")) == block["digest"]
            )
            key = (block["physical_page"], block["ordinal"], block["id"])
            _check(previous is None or previous < key)
            previous = key
            ids.add(block["id"])


def consume(row: dict[str, Any], scope: tuple[str, str, str, str], input_id: str):
    """Validate the same row/root without any database, current-state or provider read."""
    try:
        m, text = row["manifest"], row["evidence_text"]
        _check(valid("PackageReviewFrozenInputManifest", m) and digest(m) == row["digest"])
        _check(
            m["id"] == input_id
            and tuple(m[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id"))
            == scope
        )
        _check(sha(text.encode("utf-8")) == row["evidence_digest"] == m["evidence_digest"])
        root = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _check(
            set(root) == {"version", "selection", "context", "documents"}
            and root["version"] == "package-review-evidence/1"
        )
        selected, context = root["selection"], root["context"]
        _check(
            valid("PackageReviewInputManifest", selected) and digest(selected) == m["input_digest"]
        )
        own, authority, inventory = (selected[k] for k in ("target", "authority", "inventory"))
        inv = inventory["manifest"]
        _check(
            selected["bid_id"] == scope[0]
            and own["manifest"]["scope"]["bid_id"] == scope[0]
            and own["manifest"]["package_id"] == scope[1]
            and own["manifest"]["revision_id"] == scope[2]
            and inv["id"] == scope[3]
            and inv["bid_id"] == scope[0]
            and inv["package_id"] == scope[1]
            and inv["target_revision_id"] == scope[2]
            and inv["package_digest"] == own["digest"]
            and inv["authority_revision_id"] == authority["manifest"]["revision_id"]
            and inv["authority_digest"] == authority["digest"]
            and inv["identity_digest"] == own["identity"]["digest"]
            and own["manifest"]["kind"] == "bid"
            and authority["manifest"]["kind"] == "authority"
            and own["manifest"]["scope"] == authority["manifest"]["scope"]
        )
        for view in (own, authority, inventory):
            _check(digest(view["manifest"]) == view["digest"])
        coverage = selected["coverage"]
        if coverage:
            cm = coverage["manifest"]
            _check(
                digest(cm) == coverage["digest"]
                and cm["bid_id"] == scope[0]
                and cm["inventory_id"] == scope[3]
                and cm["inventory_digest"] == inventory["digest"]
                and cm["package_digest"] == own["digest"]
            )
        rebuilt = candidate(
            selected,
            context["facts"],
            context["sources"],
            context["method"],
            context["policy"],
            context["as_of"],
        )
        _check(
            rebuilt["manifest"] == context
            and summary(rebuilt) == m["execution_context"]
            and rebuilt["semantic_digest"] == m["context_digest"]
            and context["as_of"] == m["as_of"]
            and datetime.fromisoformat(m["frozen_at"].replace("Z", "+00:00"))
            >= datetime.fromisoformat(m["as_of"].replace("Z", "+00:00"))
        )
        _documents(selected, root["documents"])
        return FrozenPackageReviewInput(canonical(m).decode("utf-8"), text, row["digest"])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise PackageError("PACKAGE_REVIEW_FROZEN_INPUT_CORRUPT") from None
