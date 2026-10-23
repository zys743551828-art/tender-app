"""Associate official outcomes with immutable package submission facts.

This adapter does not create outcomes, decisions, heads, or samples.  The shared
research service appends the native outcome/decision records after this adapter
has checked the exact package subject.  No check here establishes completeness,
formal scoring readiness, or the fact of submission to an external platform.
"""

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import NoReturn
from uuid import UUID

from packages.contracts import package_outcomes_api as contract
from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_submission_repository as submissions
from packages.domain.bid_package_service import view as package_view
from packages.domain.bid_packages import PackageError
from packages.domain.review_identity import canonical
from packages.domain.runtime import DomainError, clean, require_read_committed, sha
from packages.knowledge import sources as source_graph
from packages.metrics import sources as official_sources
from packages.rag.indexing import original_source_id, parse_source_id
from packages.research.identities import require_submission_identity, submission_identity

MAX_SOURCE_ROWS = 20000
MAX_PROOF_BYTES = 2 * 1024 * 1024


def failure(code, message, status=409, details=None) -> NoReturn:
    raise DomainError("PACKAGE_OUTCOME_" + code, message, status, details)


def identity_for(frozen):
    """Always use the package's old identity, never its later recorded identity."""
    manifest = frozen["manifest"]
    subject, identity = manifest["subject"], manifest["package_identity"]
    return {
        "project_id": identity["engineering_project_id"],
        "lot_id": identity.get("lot_id"),
        "round_id": identity["round_id"],
        "bidder_id": identity["bidder_id"],
        "package_id": subject["package_id"],
        "revision_id": subject["revision_id"],
        "package_digest": subject["package_digest"],
        "binding_digest": frozen["digest"],
        "identity_digest": identity["digest"],
    }


def authority_for(frozen):
    authority = frozen["manifest"]["selection"]["authority"]
    if authority is None:
        return None
    return {
        "package_id": authority["manifest"]["package_id"],
        "revision_id": authority["manifest"]["revision_id"],
        "digest": authority["digest"],
        "identity_digest": authority["identity"]["digest"],
    }


def verification_request(body, frozen):
    """Pure exact-subject check; all states remain bound to the same old fact."""
    contract.validate("PackageOutcomeVerificationRequest", body)
    if body["identity"] != identity_for(frozen):
        failure("IDENTITY_MISMATCH", "核验身份与原始实交包、包修订或冻结身份不一致")
    if body["authority"] != authority_for(frozen):
        failure("AUTHORITY_MISMATCH", "核验依据不是原始提交绑定的确切招标材料包修订")
    if body["state"] == "verified":
        if body["authority"] is None:
            failure("AUTHORITY_MISSING", "原实交记录未绑定招标材料，不能确认官方结果核验")
        if not body["aggregation"].strip() or not body["published_at"] or not body["evidence_refs"]:
            failure("SOURCE_INCOMPLETE", "核验需成绩原页逐字引文、聚合方式和发布时间", 422)
    return deepcopy(body)


def _instant(value):
    try:
        result = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as error:
        raise DomainError("PACKAGE_OUTCOME_TIME_INVALID", "核验时间不是有效时间", 422) from error
    if not isinstance(result, datetime) or result.tzinfo is None:
        failure("TIME_INVALID", "核验时间必须包含明确时区", 422)
    return result


def check_times(submitted_at, known_at, published_at, checked_at):
    submitted, known, published, checked = map(
        _instant, (submitted_at, known_at, published_at, checked_at)
    )
    if not submitted <= published <= known <= checked:
        failure("TIME_INVALID", "实际提交、成绩公布、取得及核验时间关系不成立", 422)


def _exact_packages(c, frozen):
    """Historical revisions are read explicitly; current heads cannot substitute."""
    manifest = frozen["manifest"]
    for role in ("target", "authority"):
        selected = manifest["selection"][role]
        if selected is None:
            continue
        try:
            actual = packages.load_revision(
                c, manifest["bid_id"], selected["manifest"]["revision_id"]
            )
            current = package_view(c, actual)
        except PackageError as error:
            raise DomainError(
                "PACKAGE_OUTCOME_BINDING_CORRUPT", "原始提交绑定的包修订不能按原摘要还原", 500
            ) from error
        if current != selected:
            failure("BINDING_CORRUPT", "实际包修订与原始提交冻结内容不一致", 500)
        if role == "target" and current["identity"] != manifest["package_identity"]:
            failure("BINDING_CORRUPT", "原始包身份与实际提交绑定不一致", 500)


def require_registration(c, submission):
    if submission.get("subject_kind") != "bid_package":
        failure("SUBJECT_MISMATCH", "整包成绩不能引用单正文提交", 422)
    saved = submissions.load(c, submission["bid_id"], submission["id"])
    frozen = saved["package_binding"]
    _exact_packages(c, frozen)
    return frozen


def _source_snapshot(c, authority):
    """Read only this authority's complete ancestor closure, including digests."""
    versions = sorted({m["document_version_id"] for m in authority["manifest"]["members"]})
    nodes = clean(
        c.execute(
            "SELECT id,document_version_id,digest,kind,policy_class FROM retrieval.source_nodes "
            "WHERE document_version_id=ANY(%s::uuid[]) ORDER BY id LIMIT %s",
            (versions, MAX_SOURCE_ROWS + 1),
        ).fetchall()
    )
    if len(nodes) > MAX_SOURCE_ROWS:
        failure("CAPACITY_EXCEEDED", "招标材料来源超过核验容量，未省略来源", 422)
    direct = [row["id"] for row in nodes]
    rows = clean(
        c.execute(
            "SELECT a.source_id,n.id AS ancestor_id,n.document_version_id,n.kind,n.digest,"
            "n.policy_class,n.known_at,h.revision,h.status,h.valid_from,h.valid_until "
            "FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id "
            "LEFT JOIN retrieval.source_heads h ON h.source_id=n.id "
            "WHERE a.source_id=ANY(%s::uuid[]) ORDER BY a.source_id,n.id LIMIT %s",
            (direct, MAX_SOURCE_ROWS + 1),
        ).fetchall()
    )
    if len(rows) > MAX_SOURCE_ROWS:
        failure("CAPACITY_EXCEEDED", "招标材料祖先来源超过核验容量，未省略来源", 422)
    return nodes, rows


def _comparable_source(row):
    # PostgreSQL JSON timestamptz removes fractional trailing zeroes, while
    # datetime.isoformat preserves six digits. Compare instants, not encodings;
    # retain every other original field and never rewrite the stored binding.
    return {
        key: _instant(value).astimezone(timezone.utc).isoformat()
        if key in {"known_at", "valid_from", "valid_until"} and value is not None
        else value
        for key, value in row.items()
    }


def check_authority_sources(authority, frozen_sources, nodes, rows, *, checked_at, submitted_at):
    """Fail closed for incomplete graphs, source changes and post-submission knowledge."""
    if len(nodes) > MAX_SOURCE_ROWS or len(rows) > MAX_SOURCE_ROWS:
        failure("CAPACITY_EXCEEDED", "招标材料来源超过核验容量，未省略来源", 422)
    members = authority["manifest"]["members"]
    documents = {m["document_version_id"]: m["file_digest"] for m in members}
    required = {str(original_source_id(UUID(identity))) for identity in documents}
    required.update(
        str(parse_source_id(UUID(m["parse"]["parse_run_id"])))
        for m in members
        if m["parse"]["status"] == "frozen"
    )
    direct = {row["id"] for row in nodes}
    if (
        not members
        or not required <= direct
        or {row["source_id"] for row in rows} != direct
        or len(direct) != len(nodes)
        or len({(r["source_id"], r["ancestor_id"]) for r in rows}) != len(rows)
        or not direct <= {r["source_id"] for r in rows if r["source_id"] == r["ancestor_id"]}
    ):
        failure("AUTHORITY_SOURCE_UNPROVEN", "原招标材料缺少完整的原件、解析及祖先来源")
    for node in nodes:
        if (
            node["document_version_id"] not in documents
            or node["digest"] != documents[node["document_version_id"]]
            or node["kind"] != "document"
            or node["policy_class"] != "prebid_content"
        ):
            failure("AUTHORITY_SOURCE_INVALID", "招标材料来源不属于原确切原件或用途不符")
    reduced = [
        {key: value for key, value in row.items() if key not in {"kind", "digest"}} for row in rows
    ]
    frozen = [row for row in frozen_sources if row["source_id"] in direct]
    if sorted(map(_comparable_source, reduced), key=canonical) != sorted(
        map(_comparable_source, frozen), key=canonical
    ):
        failure("AUTHORITY_SOURCE_CHANGED", "招标材料来源或祖先与原始提交绑定不一致")
    checked, submitted = _instant(checked_at), _instant(submitted_at)
    for row in rows:
        if (
            row["kind"] != "document"
            or row["document_version_id"] is None
            or row["policy_class"] != "prebid_content"
            or row["status"] != "published"
            or row["revision"] is None
            or row["known_at"] is None
            or row["valid_from"] is None
            or _instant(row["known_at"]) > submitted
            or _instant(row["valid_from"]) > submitted
            or row["valid_until"] is not None
            and _instant(row["valid_until"]) <= checked
        ):
            failure(
                "AUTHORITY_SOURCE_INVALID",
                "招标材料来源或祖先已撤回、未生效、过期或提交时尚未取得",
            )


def _authority_proof(c, frozen, at):
    manifest = frozen["manifest"]
    authority = manifest["selection"]["authority"]
    if authority is None:
        failure("AUTHORITY_MISSING", "原始提交未绑定招标材料包")
    if authority["identity"] != manifest["package_identity"]:
        failure("AUTHORITY_IDENTITY_MISMATCH", "原招标材料与实交包冻结身份不一致")
    nodes, rows = _source_snapshot(c, authority)
    check_authority_sources(
        authority,
        manifest["context"]["current"]["sources"],
        nodes,
        rows,
        checked_at=at,
        submitted_at=manifest["submitted_at"],
    )
    versions = sorted({row["document_version_id"] for row in rows})
    documents = clean(
        c.execute(
            "SELECT v.id AS document_version_id,b.digest,b.byte_size FROM design.document_versions v "
            "JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=ANY(%s::uuid[]) "
            "AND v.artifact_kind='source_original' AND (EXISTS(SELECT 1 FROM design.material_assignments a "
            "WHERE a.bid_id=v.bid_id AND a.document_version_id=v.id AND a.role IN ('tender','supplement','drawing','boq')) "
            "OR EXISTS(SELECT 1 FROM design.document_file_versions fv JOIN design.document_files f ON f.id=fv.file_id "
            "WHERE fv.version_id=v.id AND f.bid_id=v.bid_id AND f.role IN ('tender','supplement','drawing','boq'))) "
            "ORDER BY v.id",
            (manifest["bid_id"], versions),
        ).fetchall()
    )
    by_id = {row["document_version_id"]: row for row in documents}
    original = {row["document_version_id"]: row for row in manifest["originals"]}
    if set(by_id) != set(versions) or any(
        row["digest"] != by_id[row["document_version_id"]]["digest"]
        or row["document_version_id"] not in original
        or any(
            by_id[row["document_version_id"]][field] != original[row["document_version_id"]][field]
            for field in ("digest", "byte_size")
        )
        for row in rows
    ):
        failure("AUTHORITY_ORIGINAL_CHANGED", "招标材料原件或其祖先与原实交原件摘要不一致")
    parses = []
    for member in authority["manifest"]["members"]:
        if member["parse"]["status"] != "frozen":
            continue
        parse = member["parse"]
        try:
            actual = packages.read_parse_identity(
                c,
                manifest["bid_id"],
                member["document_version_id"],
                parse["parse_run_id"],
                lock=False,
            )
        except PackageError as error:
            raise DomainError(
                "PACKAGE_OUTCOME_AUTHORITY_PARSE_CHANGED", "原招标材料解析身份无法核验", 409
            ) from error
        if any(getattr(actual, key) != value for key, value in parse.items()):
            failure("AUTHORITY_PARSE_CHANGED", "原招标材料确切解析或原页内容已变化")
        if not c.execute(
            "SELECT 1 FROM retrieval.lineage_edges WHERE child_id=%s AND parent_id=%s",
            (
                parse_source_id(UUID(parse["parse_run_id"])),
                original_source_id(UUID(member["document_version_id"])),
            ),
        ).fetchone():
            failure("AUTHORITY_SOURCE_UNPROVEN", "招标材料冻结解析缺少原件来源关系")
        parses.append({"document_version_id": member["document_version_id"], **parse})
    snapshot = {
        "version": "package-outcome-authority/1",
        "authority": authority_for(frozen),
        "binding_digest": frozen["digest"],
        "documents": documents,
        "parses": parses,
        "sources": rows,
    }
    if len(canonical(snapshot)) > MAX_PROOF_BYTES:
        failure("CAPACITY_EXCEEDED", "材料核验凭据超过容量，未截断依据", 422)
    return {"digest": sha(snapshot), "snapshot": snapshot}


def _references(c, outcome, refs):
    """Even an adverse opinion cannot attach another bid's or document's pages."""
    for ref in refs:
        row = c.execute(
            "SELECT e.text_content,e.digest,e.physical_page,p.document_version_id "
            "FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id "
            "WHERE e.bid_id=%s AND e.id=%s",
            (outcome["bid_id"], ref["evidence_id"]),
        ).fetchone()
        if (
            row is None
            or str(row["document_version_id"]) != str(outcome["source_version_id"])
            or ref["document_version_id"] != str(outcome["source_version_id"])
            or row["physical_page"] != ref["physical_page"]
            or sha(row["text_content"].encode()) != row["digest"]
            or ref["quote"] not in row["text_content"]
        ):
            failure("SOURCE_MISMATCH", "核验引文必须逐字来自当前正式成绩原件的确切页", 422)


def verification(c, submission, outcome, body):
    """Return server checked details for the existing native decision append."""
    frozen = require_registration(c, submission)
    request = verification_request(body, frozen)
    if str(outcome["bid_id"]) != str(submission["bid_id"]) or str(outcome["submission_id"]) != str(
        submission["id"]
    ):
        failure("SUBJECT_MISMATCH", "成绩记录与原实交包不属于同一项目或同一次提交", 422)
    _references(c, outcome, request["evidence_refs"])
    at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    authority_proof = official_proof = None
    if request["state"] == "verified":
        require_read_committed(c)
        source_graph.lock_graph(c)
        at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        require_submission_identity(c, submission)
        check_times(submission["submitted_at"], outcome["known_at"], request["published_at"], at)
        authority_proof = _authority_proof(c, frozen, at)
        official_proof, reasons = official_sources.inspect(
            c,
            outcome["bid_id"],
            outcome["source_version_id"],
            as_of=at,
            cutoff=outcome["known_at"],
            refs=request["evidence_refs"],
            lock=True,
        )
        if reasons or official_proof is None:
            failure(
                "SOURCE_INVALID", "官方成绩原件或其祖先来源未通过核验", details={"reasons": reasons}
            )
    details = clean(
        {
            "version": "package-outcome-verification-record/1",
            "subject_kind": "bid_package",
            "request": request,
            "package_identity": frozen["manifest"]["package_identity"],
            "binding_digest": frozen["digest"],
            "checked_at": at,
            "authority_proof": authority_proof,
            "official_source_proof": official_proof,
            "verification_scope": "official_outcome_association",
            "formal_sample_eligible": False,
            "formal_sample_blockers": [contract.SAMPLE_REASON],
        }
    )
    if len(canonical(details)) > MAX_PROOF_BYTES:
        failure("CAPACITY_EXCEEDED", "成绩核验凭据超过容量，未截断依据", 422)
    contract.validate("PackageOutcomeVerificationDetails", details)
    return {
        "details": details,
        "evidence_ids": sorted({ref["evidence_id"] for ref in request["evidence_refs"]}),
    }


def context(c, bid, submission_id):
    saved = submissions.load(c, bid, submission_id)
    frozen = saved["package_binding"]
    _exact_packages(c, frozen)
    manifest = frozen["manifest"]
    old_identity = manifest["package_identity"]
    # Use the already checked native evidence; never reconstruct it from current
    # profile values or treat recorded_identity as the historical package identity.
    native = {
        "bid_id": bid,
        "evidence": submissions.native_evidence(frozen),
        "submitted_at": manifest["submitted_at"],
        "created_at": manifest["recorded_at"],
    }
    identity = submission_identity(c, native)
    blockers = []
    if identity["status"] != "confirmed":
        blockers.append(identity["reason"])
    if authority_for(frozen) is None:
        blockers.append("PACKAGE_OUTCOME_AUTHORITY_MISSING")
    else:
        at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        try:
            _authority_proof(c, frozen, at)
        except DomainError as error:
            if error.status >= 500:
                raise
            blockers.append(error.code)
    candidates = c.execute(
        "SELECT d.id,d.original_name,d.obtained_at FROM design.document_versions d "
        "WHERE d.bid_id=%s AND d.artifact_kind='source_original' AND "
        "(EXISTS(SELECT 1 FROM design.material_assignments a WHERE a.bid_id=d.bid_id "
        "AND a.document_version_id=d.id AND a.role='official_result') OR EXISTS(SELECT 1 FROM "
        "design.document_files f JOIN design.document_file_versions v ON v.file_id=f.id "
        "WHERE f.bid_id=d.bid_id AND v.version_id=d.id AND f.role='official_result')) "
        "ORDER BY d.created_at DESC,d.id DESC LIMIT 100",
        (bid,),
    ).fetchall()
    result = clean(
        {
            "subject_kind": "bid_package",
            "bid_id": bid,
            "submission_id": submission_id,
            "body_version_id": None,
            "identity": identity_for(frozen),
            "package_identity": old_identity,
            "recorded_identity": manifest["recorded_identity"],
            "package_binding": frozen,
            "authority": authority_for(frozen),
            "display": {
                "project_title": old_identity["engineering_title"],
                "lot": old_identity["lot"],
                "round_no": old_identity["round_no"],
                "bidder_name": old_identity["bidder_name"],
                "body_filename": None,
            },
            "submitted_at": manifest["submitted_at"],
            "kind": saved["kind"],
            "source_candidates": candidates,
            "identity_ready": identity["status"] == "confirmed",
            "identity_status": identity["status"],
            "identity_reason": identity["reason"],
            "verification_blockers": sorted(set(blockers)),
            "verification_requires_source_evidence": True,
            "formal_sample_eligible": False,
            "formal_sample_blockers": [contract.SAMPLE_REASON],
        }
    )
    contract.validate("PackageOutcomeContext", result)
    return result


def reject_formal_sample(submission):
    if submission.get("subject_kind") == "bid_package":
        failure(
            "FORMAL_SAMPLE_UNSUPPORTED",
            "整包成绩可登记和核验，当前正式研究样本只支持单正文；未创建样本",
            details={"reasons": [contract.SAMPLE_REASON], "sample_created": False},
        )


def current_reasons(c, submission, outcome, details, as_of=None):
    """Read-only current association validity, without rewriting the old decision.

    An empty result is deliberately narrower than research admission. It says
    that this exact native official-result association remains supported at the
    requested observation boundary and now. Package samples stay unsupported.
    """
    if not contract.valid("PackageOutcomeVerificationDetails", details):
        return ["package_outcome_verification_unproven"]
    if details["request"]["state"] != "verified":
        return ["package_outcome_not_verified"]
    try:
        present = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
        boundary = min(_instant(as_of or present), _instant(present))
        if (
            str(outcome["bid_id"]) != str(submission["bid_id"])
            or str(outcome["submission_id"]) != str(submission["id"])
            or submission.get("subject_kind") != "bid_package"
        ):
            return ["package_outcome_subject_mismatch"]
        decision = c.execute(
            "SELECT d.* FROM design.decision_heads h JOIN design.decisions d ON d.id=h.decision_id "
            "AND d.bid_id=h.bid_id WHERE h.bid_id=%s AND h.object_kind='outcome' AND h.object_id=%s",
            (outcome["bid_id"], outcome["id"]),
        ).fetchone()
        head = c.execute(
            "SELECT outcome_id,revision FROM design.outcome_heads WHERE bid_id=%s AND submission_id=%s",
            (outcome["bid_id"], submission["id"]),
        ).fetchone()
        if (
            decision is None
            or decision["decision"] != "verified"
            or decision["object_kind"] != "outcome"
            or str(decision["object_id"]) != str(outcome["id"])
            or json.loads(decision["reason"]) != details
            or len(decision["evidence_ids"]) != len(set(decision["evidence_ids"]))
            or {str(value) for value in decision["evidence_ids"]}
            != {ref["evidence_id"] for ref in details["request"]["evidence_refs"]}
        ):
            return ["package_outcome_verification_changed"]
        if (
            head is None
            or str(head["outcome_id"]) != str(outcome["id"])
            or head["revision"] != decision["object_revision"]
        ):
            return ["package_outcome_not_current"]
        if any(
            _instant(value) > boundary
            for value in (
                submission["submitted_at"],
                submission["created_at"],
                outcome["known_at"],
                details["checked_at"],
                decision["created_at"],
            )
        ):
            return ["package_outcome_not_observed_at_as_of"]
        frozen = require_registration(c, submission)
        if (
            details["binding_digest"] != frozen["digest"]
            or details["package_identity"] != frozen["manifest"]["package_identity"]
        ):
            return ["package_outcome_binding_changed"]
        request = verification_request(details["request"], frozen)
        require_submission_identity(c, submission)
        check_times(
            submission["submitted_at"], outcome["known_at"], request["published_at"], boundary
        )
        for name in ("authority_proof", "official_source_proof"):
            proof = details[name]
            if proof is None or sha(proof["snapshot"]) != proof["digest"]:
                return ["package_outcome_source_proof_unproven"]
        authority = _authority_proof(c, frozen, present)
        if authority != details["authority_proof"]:
            return ["package_outcome_authority_proof_changed"]
        _references(c, outcome, request["evidence_refs"])
        official, reasons = official_sources.inspect(
            c,
            outcome["bid_id"],
            outcome["source_version_id"],
            as_of=boundary,
            cutoff=outcome["known_at"],
            refs=request["evidence_refs"],
        )
        if reasons:
            return ["package_outcome_" + reason for reason in reasons]
        if official != details["official_source_proof"]:
            return ["package_outcome_official_source_proof_changed"]
        return []
    except DomainError as error:
        return [error.code.lower()]
    except (KeyError, TypeError, ValueError):
        return ["package_outcome_verification_unproven"]
