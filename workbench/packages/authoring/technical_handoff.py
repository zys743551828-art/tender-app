"""Read a direct adoption on an exact bid package revision without granting its use."""

from uuid import UUID

from packages.authoring.package_adoptions import KIND
from packages.authoring.package_outputs import EVENT, PROTOCOL
from packages.domain import bid_package_service as packages
from packages.domain.bid_packages import PackageKind, PackageRevision
from packages.domain.bid_packages import sha as valid_digest
from packages.domain.runtime import DomainError, sha

ADOPTED = "authoring.output_adopted"
TECHNICAL = {"技术", "技术标", "施工组织设计", "technical"}


def _unverified():
    return DomainError(
        "TECHNICAL_HANDOFF_UNVERIFIED", "生成件采用记录与此冻结修订不一致，不能确认交接", 409
    )


def _receipt(package: PackageRevision, row: dict):
    adoption, qualification = row["adoption"], row["qualification"]
    if not isinstance(adoption, dict) or not isinstance(qualification, dict):
        raise _unverified()
    proof = qualification.get("proof")
    if not isinstance(proof, dict) or qualification.get("proof_digest") != sha(proof):
        raise _unverified()
    document_id = adoption.get("document_version_id")
    members = [m for m in package.members if m.document_version_id == document_id]
    if (
        len(members) != 1
        or adoption.get("package_id") != package.package_id
        or adoption.get("package_revision_id") != package.revision_id
        or adoption.get("package_digest") != package.manifest_digest
        or proof.get("protocol") != PROTOCOL
        or proof.get("bid_id") != package.scope.bid_id
        or proof.get("build_id") != adoption.get("build_id")
        or proof.get("document_version_id") != document_id
        or proof.get("sha256") != members[0].file_digest
        or proof.get("format") not in ("docx", "pdf")
        or row["command_kind"] != KIND
        or row["command_target"] != proof.get("build_id")
        or row["command_status"] != 201
        or row["command_protocol"] != "authoring-output-adoption/1"
        or row["command_actor"] != row["receipt_actor"]
        or row["command_id"] != row["receipt_command"]
        or row["receipt_bid"] != package.scope.bid_id
        or row["command_output"] != proof
        or row["command_revision"] != package.revision_id
        or row["command_package_digest"] != package.manifest_digest
        or not valid_digest(row["command_request_digest"])
        or row["command_request_digest"] != row["receipt_request_digest"]
    ):
        raise _unverified()
    member = members[0]
    if not (
        TECHNICAL.intersection(member.purposes)
        or any(part.category in TECHNICAL and not part.shared_attachment for part in member.parts)
    ):
        return None
    try:
        build = UUID(proof["build_id"])
        identity = proof["build_identity"]
        snapshot_id = UUID(identity["snapshot_id"])
        snapshot_digest = identity["snapshot_digest"]
        if not valid_digest(snapshot_digest):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _unverified() from None
    return {
        "member_id": member.member_id,
        "document_version_id": document_id,
        "artifact_sha256": member.file_digest,
        "format": proof["format"],
        "build_id": build,
        "snapshot_id": snapshot_id,
        "snapshot_digest": snapshot_digest,
        "parse_run_id": member.parse.parse_run_id,
    }


def read(c, bid_id: UUID, package_id: UUID, revision_id: UUID):
    package: PackageRevision = packages.historical(c, bid_id, package_id, revision_id)
    if package.kind != PackageKind.BID:
        raise DomainError("TECHNICAL_HANDOFF_NOT_BID_PACKAGE", "只读取本方投标包的技术稿交接", 422)
    # The adaptation could otherwise mistake a copied member, a separate command's
    # qualification, or a later revision for a directly adopted exact file.
    rows = c.execute(
        """SELECT a.payload AS adoption,q.payload AS qualification,
          cmd.command_kind,cmd.target_id::text AS command_target,
          cmd.actor_id::text AS command_actor,cmd.id::text AS command_id,
          cmd.request_digest AS command_request_digest,cmd.response->'status' AS command_status,
          cmd.response#>>'{body,protocol}' AS command_protocol,
          cmd.response#>>'{body,actor_id}' AS receipt_actor,
          cmd.response#>>'{body,command_id}' AS receipt_command,
          cmd.response#>>'{body,bid_id}' AS receipt_bid,
          cmd.response#>>'{body,request_digest}' AS receipt_request_digest,
          cmd.response#>'{body,output}' AS command_output,
          cmd.response#>>'{body,package,manifest,revision_id}' AS command_revision,
          cmd.response#>>'{body,package,digest}' AS command_package_digest
        FROM design.audit_entries a LEFT JOIN design.audit_entries q
          ON q.bid_id=a.bid_id AND q.actor_id=a.actor_id AND q.command_id=a.command_id
          AND q.event_type=%s
        LEFT JOIN design.commands cmd ON cmd.id=a.command_id AND cmd.actor_id=a.actor_id
        WHERE a.bid_id=%s AND a.event_type=%s
          AND a.payload->>'package_revision_id'=%s LIMIT 2""",
        (EVENT, bid_id, ADOPTED, str(revision_id)),
    ).fetchall()
    if len(rows) > 1:
        raise _unverified()
    head = c.execute(
        """SELECT h.revision_id,h.digest FROM design.bid_package_heads h
        JOIN design.bid_packages p ON p.id=h.package_id WHERE p.bid_id=%s AND p.id=%s""",
        (bid_id, package_id),
    ).fetchone()
    is_head = head is not None and str(head["revision_id"]) == str(revision_id)
    if head is None or (is_head and head["digest"] != package.manifest_digest):
        raise _unverified()
    return {
        "protocol": "technical-authoring-handoff/1",
        "bid_id": bid_id,
        "package_id": package_id,
        "revision_id": revision_id,
        "package_digest": package.manifest_digest,
        "revision_status": "head_at_read" if is_head else "historical",
        "record": _receipt(package, rows[0]) if rows else None,
        "independent_approval_available": False,
        "publication_authorized": False,
    }
