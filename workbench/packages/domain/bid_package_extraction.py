"""Exact package identity for the existing rule-extraction worker path."""

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from packages.domain import bid_package_repository as packages
from packages.domain.bid_packages import PackageError
from packages.domain.review_identity import digest
from packages.domain.runtime import clean


def _full_page_parts(member: dict[str, Any]) -> bool:
    count = member["page_count"]
    if count is None or count < 1:
        return False
    covered_until = 0
    for first, last in sorted((part["first_page"], part["last_page"]) for part in member["parts"]):
        if first > covered_until + 1:
            return False
        covered_until = max(covered_until, last)
    return covered_until == count


def _member_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "member_id": member["member_id"],
            "document_version_id": member["document_version_id"],
            "file_digest": member["file_digest"],
            "parse_run_id": member["parse"]["parse_run_id"],
            "parser_digest": member["parse"]["parser_digest"],
            "config_digest": member["parse"]["config_digest"],
            "evidence_digest": member["parse"]["evidence_digest"],
            "page_count": member["page_count"],
            "parts": member["parts"],
        }
        for member in manifest["members"]
    ]


def _document_matches(
    c: Any, bid_id: str, document: dict[str, Any], member: dict[str, Any]
) -> bool:
    """Bind the text actually sent to the model, as well as the parse identifier."""
    pages = packages._all(
        c,
        "SELECT physical_page,quality,gaps FROM design.pages WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page",
        (bid_id, member["parse_run_id"]),
    )
    blocks = packages._all(
        c,
        """SELECT id,physical_page,ordinal,kind,text_content,bbox,structure,digest
        FROM design.evidence_blocks WHERE bid_id=%s AND parse_id=%s ORDER BY physical_page,ordinal""",
        (bid_id, member["parse_run_id"]),
    )
    return (
        document["digest"] == member["file_digest"]
        and str(document["parse_id"]) == member["parse_run_id"]
        and document["parser_digest"] == member["parser_digest"]
        and document["config_digest"] == member["config_digest"]
        and document["page_count"] == member["page_count"]
        and document["coverage"] == "complete"
        and document["gaps"] == []
        and clean(document["pages"]) == clean(pages)
        and clean(document["blocks"]) == clean(blocks)
    )


def freeze_matching_input(
    c: Any,
    bid_id: str,
    material_id: str,
    documents: list[dict[str, Any]],
    method: dict[str, Any],
    method_digest: str,
) -> dict[str, Any] | None:
    """Freeze only a unique current authority package exactly represented by this bundle."""
    if digest(method) != method_digest:
        raise PackageError("PACKAGE_EXTRACTION_INPUT_IDENTITY_MISMATCH")
    sources = [doc for doc in documents if doc["role"] != "body"]
    if not sources or any(
        doc["coverage"] != "complete"
        or doc["gaps"]
        or doc["page_count"] < 1
        or len(doc["pages"]) != doc["page_count"]
        or any(page["quality"] != "usable" or page["gaps"] for page in doc["pages"])
        for doc in sources
    ):
        return None

    source_by_version = {str(doc["document_version_id"]): doc for doc in sources}
    if len(source_by_version) != len(sources):
        return None
    identity_row = packages._one(c, "SELECT design.identity_snapshot_v2(%s) AS value", (bid_id,))
    current_identity = identity_row["value"] if identity_row else None
    if not isinstance(current_identity, dict) or not current_identity.get("digest"):
        return None
    candidates = packages._all(
        c,
        """SELECT p.id AS package_id,h.revision_id FROM design.bid_packages p
        JOIN design.bid_package_heads h ON h.package_id=p.id
        WHERE p.bid_id=%s AND p.kind='authority' ORDER BY p.id""",
        (bid_id,),
    )
    matches = []
    for candidate in candidates:
        package = packages.load_revision(c, bid_id, str(candidate["revision_id"]))
        if package.manifest_digest is None:
            continue
        frozen_identity = packages.load_frozen_identity(c, bid_id, package.revision_id)
        if frozen_identity["digest"] != current_identity["digest"]:
            continue
        members = {member.document_version_id: member for member in package.members}
        manifest_members = {
            member["document_version_id"]: member for member in package.manifest()["members"]
        }
        if set(members) != set(source_by_version):
            continue
        exact = True
        for version_id, member in members.items():
            document = source_by_version[version_id]
            parse_id = str(document["parse_id"])
            try:
                actual_parse = packages.read_parse_identity(c, bid_id, version_id, parse_id)
            except PackageError:
                exact = False
                break
            if (
                member.file_digest != document["digest"]
                or member.parse.status != "frozen"
                or member.parse.parse_run_id != parse_id
                or member.parse != actual_parse
                or not _full_page_parts(manifest_members[version_id])
                or not _document_matches(
                    c,
                    bid_id,
                    document,
                    next(
                        item
                        for item in _member_inputs(package.manifest())
                        if item["document_version_id"] == version_id
                    ),
                )
            ):
                exact = False
                break
        if exact:
            matches.append((package, frozen_identity))
    if len(matches) != 1:
        return None

    package, frozen_identity = matches[0]
    manifest = package.manifest()
    parts = [
        {
            "member_id": member["member_id"],
            "document_version_id": member["document_version_id"],
            "parse_run_id": member["parse"]["parse_run_id"],
            "part_id": part["part_id"],
            "first_page": part["first_page"],
            "last_page": part["last_page"],
            "shared_attachment": part["shared_attachment"],
        }
        for member in manifest["members"]
        for part in member["parts"]
    ]
    value = {
        "identity_version": "package-rule-extraction-input/1",
        "bid_id": bid_id,
        "material_snapshot_id": material_id,
        "scope": manifest["scope"],
        "authority_package": {
            "package_id": package.package_id,
            "revision_id": package.revision_id,
            "digest": package.manifest_digest,
            "identity_digest": frozen_identity["digest"],
            "manifest": manifest,
            "identity_snapshot": frozen_identity,
        },
        "members": _member_inputs(manifest),
        "extraction_scope": {
            "policy": "all_declared_package_parts",
            "coverage": "all_physical_pages",
            "parts": parts,
        },
        "method_profile": method,
        "method_digest": method_digest,
    }
    return {"manifest": value, "digest": digest(value)}


def validate_frozen_input(
    c: Any,
    bid_id: str,
    frozen_input: dict[str, Any],
    documents: list[dict[str, Any]],
    method: dict[str, Any],
    method_digest: str,
    material_id: str,
) -> None:
    value = frozen_input.get("manifest")
    if (
        not isinstance(value, dict)
        or digest(value) != frozen_input.get("digest")
        or value.get("identity_version") != "package-rule-extraction-input/1"
        or value.get("bid_id") != bid_id
        or value.get("material_snapshot_id") != material_id
        or value.get("method_profile") != method
        or value.get("method_digest") != method_digest
        or digest(method) != method_digest
    ):
        raise PackageError("PACKAGE_EXTRACTION_INPUT_IDENTITY_MISMATCH")
    authority = value["authority_package"]
    package = packages.load_revision(c, bid_id, authority["revision_id"])
    frozen_identity = packages.load_frozen_identity(c, bid_id, package.revision_id)
    if (
        package.package_id != authority["package_id"]
        or package.manifest_digest != authority["digest"]
        or package.manifest() != authority["manifest"]
        or frozen_identity != authority["identity_snapshot"]
        or frozen_identity["digest"] != authority["identity_digest"]
        or package.manifest()["scope"] != value["scope"]
        or package.scope.bid_id != bid_id
        or value["members"] != _member_inputs(package.manifest())
    ):
        raise PackageError("PACKAGE_EXTRACTION_INPUT_IDENTITY_MISMATCH")
    sources = [doc for doc in documents if doc["role"] != "body"]
    member_by_version = {member["document_version_id"]: member for member in value["members"]}
    if len(sources) != len(value["members"]) or {
        str(doc["document_version_id"]) for doc in sources
    } != set(member_by_version):
        raise PackageError("PACKAGE_EXTRACTION_INPUT_MEMBERS_MISMATCH")
    for document in sources:
        version_id = str(document["document_version_id"])
        member = member_by_version[version_id]
        try:
            actual_parse = packages.read_parse_identity(
                c, bid_id, version_id, str(document["parse_id"])
            )
        except PackageError as error:
            raise PackageError("PACKAGE_EXTRACTION_PARSE_NOT_FROZEN") from error
        if (
            member["file_digest"] != document["digest"]
            or member["parse_run_id"] != str(document["parse_id"])
            or member["parser_digest"] != actual_parse.parser_digest
            or member["config_digest"] != actual_parse.config_digest
            or member["evidence_digest"] != actual_parse.evidence_digest
            or member["page_count"] != document["page_count"]
            or not _full_page_parts(member)
            or document["coverage"] != "complete"
            or document["gaps"]
            or len(document["pages"]) != document["page_count"]
            or any(page["quality"] != "usable" or page["gaps"] for page in document["pages"])
            or not _document_matches(c, bid_id, document, member)
        ):
            raise PackageError("PACKAGE_EXTRACTION_INPUT_MEMBERS_MISMATCH")
    expected_parts = [
        {
            "member_id": member["member_id"],
            "document_version_id": member["document_version_id"],
            "parse_run_id": member["parse_run_id"],
            "part_id": part["part_id"],
            "first_page": part["first_page"],
            "last_page": part["last_page"],
            "shared_attachment": part["shared_attachment"],
        }
        for member in value["members"]
        for part in member["parts"]
    ]
    if value["extraction_scope"] != {
        "policy": "all_declared_package_parts",
        "coverage": "all_physical_pages",
        "parts": expected_parts,
    }:
        raise PackageError("PACKAGE_EXTRACTION_SCOPE_MISMATCH")


def record_completion(
    c: Any,
    message: dict[str, Any],
    frozen_input: dict[str, Any],
    rule_set_id: str,
    result: dict[str, Any],
) -> None:
    manifest = frozen_input["manifest"]
    if (
        digest(manifest) != frozen_input["digest"]
        or manifest["bid_id"] != message["bid_id"]
        or result.get("input_digest") != frozen_input["digest"]
        or result.get("rule_set_id") != rule_set_id
        or result.get("authority_revision_id") != manifest["authority_package"]["revision_id"]
        or result.get("authority_digest") != manifest["authority_package"]["digest"]
        or result.get("method_digest") != manifest["method_digest"]
        or result.get("range_status") != "all_frozen_evidence_submitted"
        or result.get("extraction_coverage") not in {"complete", "partial", "conflict"}
        or result.get("quality_status") != "not_measured"
    ):
        raise PackageError("PACKAGE_EXTRACTION_RESULT_BINDING_MISMATCH")
    identity = str(uuid4())
    c.execute(
        """INSERT INTO design.bid_package_requirement_extraction_runs
        (id,bid_id,authority_revision_id,authority_digest,input_blob_id,input_digest,input_manifest,
         operation_id,operation_input_digest,rule_set_id,result_digest,result)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identity,
            message["bid_id"],
            manifest["authority_package"]["revision_id"],
            manifest["authority_package"]["digest"],
            message["payload_ref"],
            frozen_input["digest"],
            Jsonb(manifest),
            message["operation_id"],
            message["input_digest"],
            rule_set_id,
            digest(result),
            Jsonb(result),
        ),
    )


def completion_for_rule_set(
    c: Any, bid_id: str, rule_set_id: str, authority_revision_id: str, authority_digest: str
) -> dict[str, Any] | None:
    row = packages._one(
        c,
        """SELECT r.* FROM design.bid_package_requirement_extraction_runs r
        WHERE r.bid_id=%s AND r.rule_set_id=%s""",
        (bid_id, rule_set_id),
    )
    if row is None:
        return None
    # Historical inventory reads remain database-only. The worker persists the
    # exact input alongside its receipt; original blobs are verified at execution.
    manifest = row["input_manifest"]
    if (
        str(row["authority_revision_id"]) != authority_revision_id
        or row["authority_digest"] != authority_digest
        or row["result_digest"] != digest(row["result"])
        or row["result"].get("rule_set_id") != rule_set_id
        or row["result"].get("input_digest") != row["input_digest"]
        or row["result"].get("authority_revision_id") != authority_revision_id
        or row["result"].get("authority_digest") != authority_digest
        or not row["result"].get("method_digest")
        or digest(manifest) != row["input_digest"]
    ):
        raise PackageError("PACKAGE_REQUIREMENT_EXTRACTION_BINDING_MISMATCH")
    operation = packages._one(
        c,
        "SELECT bid_id,input_digest,handler_version,state FROM design.operations WHERE id=%s",
        (row["operation_id"],),
    )
    receipt = packages._one(
        c,
        "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='extract-rules'",
        (row["operation_id"],),
    )
    package = packages.load_revision(c, bid_id, authority_revision_id)
    if (
        operation is None
        or str(operation["bid_id"]) != bid_id
        or operation["input_digest"] != row["operation_input_digest"]
        or operation["handler_version"] != "prepare/1"
        or operation["state"] != "succeeded"
        or receipt is None
        or receipt["result"].get("result_ref") != rule_set_id
        or receipt["result"].get("extraction_input_digest") != row["input_digest"]
        or receipt["result"].get("method_digest") != row["result"]["method_digest"]
        or package.manifest_digest != authority_digest
        or manifest["authority_package"]["revision_id"] != authority_revision_id
        or manifest["authority_package"]["digest"] != authority_digest
        or manifest["authority_package"]["manifest"] != package.manifest()
        or manifest["members"] != _member_inputs(package.manifest())
        or manifest["scope"] != package.manifest()["scope"]
        or manifest["bid_id"] != bid_id
        or digest(manifest["method_profile"]) != manifest["method_digest"]
        or manifest["method_digest"] != row["result"]["method_digest"]
    ):
        raise PackageError("PACKAGE_REQUIREMENT_EXTRACTION_BINDING_MISMATCH")
    return row
