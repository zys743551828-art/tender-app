"""Explicit whole-package facts: verify originals outside transactions, then one native head."""

from copy import deepcopy

from psycopg.types.json import Jsonb

from packages.contracts.package_submissions_api import validate
from packages.domain import bid_package_submission_observations as observations
from packages.domain import bid_package_submission_repository as repository
from packages.domain import original_verification
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import canonical, utc
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    connection,
    require_read_committed,
    sha,
    uid,
)
from packages.domain.submissions import timestamp
from packages.knowledge.sources import lock_graph


def prepare(c, scope, body, *, bid_etag_fn):
    scope = tuple(map(str, scope))
    validate("PackageSubmissionSelection", body)
    repository.require_schema(c)
    value = observations.observe(c, scope, deepcopy(body))
    result = {
        "selection": value["selection"],
        "selection_request": value["selection_request"],
        "gate": value["gate"],
        "input_digest": value["input_digest"],
        "bid_etag": bid_etag_fn(c, scope[0]),
        "current_submission_head": value["context"]["current_submission_head"],
    }
    validate("PackageSubmissionPreview", result)
    return result


def _condition(c, bid, condition, bid_etag_fn):
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请提供项目当前强 ETag", 428)
    if condition != bid_etag_fn(c, bid):
        raise DomainError("REVISION_CONFLICT", "项目或实交头已变化，请保留输入并重新核对", 412)


def _head(body, current, supersedes):
    if supersedes is None:
        if body["expected_head"] is not None or body["correction_reason"] is not None:
            observations.failure("HEAD_INVALID", "首次登记不能携带更正头或更正理由", 422)
        if current is not None:
            observations.failure("ALREADY_RECORDED", "已有有效实际提交，请明确更正该记录")
    else:
        if (
            current is None
            or {key: current[key] for key in ("id", "revision")} != body["expected_head"]
            or current["id"] != supersedes
        ):
            observations.failure("HEAD_CONFLICT", "本次明确更正的实交头已变化", 412)
        if not body["correction_reason"] or not body["correction_reason"].strip():
            observations.failure("CORRECTION_REASON_REQUIRED", "请填写本次实际提交更正理由", 422)


def _new_use(c, body, value, supersedes):
    _head(body, value["context"]["current_submission_head"], supersedes)
    if not body["explanation"].strip():
        observations.failure(
            "EXPLANATION_REQUIRED", "请说明实际提交及未经过完整系统检查的依据", 422
        )
    if (
        timestamp(body["submitted_at"])
        > c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    ):
        observations.failure("FUTURE_TIME", "只能记录已经发生的提交，不能登记未来时间", 422)
    if value["input_digest"] != body["input_digest"]:
        observations.failure(
            "INPUT_CHANGED", "精确投标包、身份、来源、规则意见或历史风险已变化，请重新核对"
        )
    if body["kind"] == "standard" and not value["gate"]["manifest"]["allowed"]:
        raise DomainError(
            "PACKAGE_SUBMISSION_GATE_BLOCKED",
            "整包完整性及资格仍未证明，不能登记为标准检查通过",
            409,
            {"gate": value["gate"]},
        )


def _persist(
    c,
    scope,
    actor,
    key,
    body,
    condition,
    command,
    value,
    originals,
    attachment_sources,
    supersedes,
    bid_etag_fn,
):
    record_id = str(uid())
    recorded_at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
    head = value["context"]["current_submission_head"]
    manifest = {
        "version": "package-submission-binding/1",
        "submission_id": record_id,
        "bid_id": scope[0],
        "subject": {
            "kind": "bid_package",
            "bid_id": scope[0],
            "package_id": scope[1],
            "revision_id": scope[2],
            "package_digest": value["selection"]["target"]["digest"],
        },
        **{
            name: value[name]
            for name in (
                "selection",
                "selection_request",
                "context",
                "review_run",
                "inventory_proof",
                "input_digest",
                "gate",
            )
        },
        "package_identity": value["selection"]["target"]["identity"],
        "recorded_identity": value["context"]["current"]["current"]["identity"],
        "submitted_at": utc(body["submitted_at"]),
        "recorded_at": recorded_at,
        "assessed_at": value["observed_at"],
        "actor_id": actor,
        "command_id": str(command.id),
        "request": body,
        "request_digest": repository.command_digest(scope, body, condition, supersedes),
        "if_match": condition,
        "originals": [observations.public_original(row) for row in originals],
        "evidence": next(
            observations.public_original(row)
            for row in originals
            if row["document_version_id"] == body["evidence"]["document_version_id"]
        ),
        "attachment_sources": attachment_sources,
        "supersedes_id": supersedes,
        "head_revision": head["revision"] + 1 if head else 1,
        "platform_submission_verified": False,
        "pre_submission_system_check_verified": False,
        "original_bytes_verified": True,
    }
    frozen = {"manifest": manifest, "digest": sha(manifest)}
    if len(canonical(frozen)) > repository.MAX_BINDING_BYTES:
        observations.failure(
            "CAPACITY_EXCEEDED", "完整实际提交凭据超过保存容量，未截断任何包成员或风险", 422
        )
    validate("PackageSubmissionBindingView", frozen)
    c.execute(
        """INSERT INTO design.submission_records
        (id,bid_id,subject_kind,body_version_id,review_id,kind,gate_snapshot,evidence,submitted_at,created_by,supersedes_id,created_at)
        VALUES(%s,%s,'bid_package',NULL,NULL,%s,%s,%s,%s,%s,%s,%s)""",
        (
            record_id,
            scope[0],
            body["kind"],
            Jsonb(manifest["gate"]),
            Jsonb(repository.native_evidence(frozen)),
            manifest["submitted_at"],
            actor,
            supersedes,
            recorded_at,
        ),
    )
    selection = value["selection"]
    c.execute(
        """INSERT INTO design.bid_package_submission_bindings
        (submission_id,bid_id,package_id,revision_id,authority_revision_id,inventory_id,review_run_id,command_id,manifest,digest)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            record_id,
            *scope,
            selection["authority"]["manifest"]["revision_id"] if selection["authority"] else None,
            selection["inventory"]["manifest"]["id"] if selection["inventory"] else None,
            value["review_run"]["id"] if value["review_run"] else None,
            command.id,
            Jsonb(manifest),
            frozen["digest"],
        ),
    )
    if head:
        c.execute(
            "UPDATE design.submission_heads SET submission_id=%s,revision=revision+1 WHERE bid_id=%s",
            (record_id, scope[0]),
        )
    else:
        c.execute(
            "INSERT INTO design.submission_heads(bid_id,submission_id,revision) VALUES(%s,%s,1)",
            (scope[0], record_id),
        )
    # An actual fact may be supplemented after closure or archival. No reopen is implied.
    c.execute(
        "UPDATE design.bid_profiles SET phase='submitted' WHERE bid_id=%s AND phase IN ('preparation','working','submitted') AND archived_at IS NULL",
        (scope[0],),
    )
    c.execute("UPDATE design.bids SET revision=revision+1 WHERE id=%s", (scope[0],))
    audit(
        c,
        actor,
        scope[0],
        "submission.corrected" if supersedes else "submission.recorded",
        {
            "submission_id": record_id,
            "supersedes_id": supersedes,
            "kind": body["kind"],
            "subject_kind": "bid_package",
            "package_id": scope[1],
            "revision_id": scope[2],
            "package_digest": selection["target"]["digest"],
            "binding_digest": frozen["digest"],
            "identity_digest": manifest["package_identity"]["digest"],
            "recorded_identity_digest": manifest["recorded_identity"]["digest"],
            "evidence_digest": manifest["evidence"]["digest"],
            "gate_checked": False,
        },
        command.id,
    )
    result = {
        "submission": repository.load(c, scope[0], record_id),
        "command": {
            "command_id": str(command.id),
            "actor_id": actor,
            "idempotency_key": key,
            "request_digest": manifest["request_digest"],
            "request": body,
            "if_match": condition,
        },
    }
    validate("PackageSubmissionAppliedView", result)
    return command.finish(result, 201, {"X-Bid-ETag": bid_etag_fn(c, scope[0])})


def register(scope, actor, key, body, condition, *, supersedes=None, final_auth=None, bid_etag_fn):
    scope = tuple(map(str, scope))
    actor = str(actor)
    supersedes = str(supersedes) if supersedes is not None else None
    validate("PackageSubmissionRequest", body)
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供不超过128字的幂等键", 428)
    body = deepcopy(body)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, key, body, condition, supersedes)
        if old is not None:
            return old, True
        repository.require_schema(c)
        _condition(c, scope[0], condition, bid_etag_fn)
        before = observations.observe(c, scope, body["selection"])
        _new_use(c, body, before, supersedes)
        originals, sources = observations.originals(
            c, scope[0], before["selection"], body["evidence"]
        )
    for row in originals:
        original_verification.verify(row)
    if final_auth is not None and str(final_auth()) != actor:
        observations.failure("ACTOR_CHANGED", "原件核验期间当前账户发生变化，未登记实际提交", 403)
    with connection() as c:
        require_read_committed(c)
        lock_bid(c, scope[0])
        command = Command(
            c,
            actor,
            repository.KIND,
            scope[0],
            key,
            repository.request_body(scope, body, supersedes),
            condition,
        )
        if command.replay is not None:
            return repository.replay(c, actor, scope, key, body, condition, supersedes), True
        lock_graph(c)
        observations.submission_head(c, scope[0], lock=True)
        _condition(c, scope[0], condition, bid_etag_fn)
        current = observations.observe(c, scope, body["selection"])
        _new_use(c, body, current, supersedes)
        current_originals, current_sources = observations.originals(
            c, scope[0], current["selection"], body["evidence"]
        )
        if (
            current["input_digest"] != before["input_digest"]
            or current_originals != originals
            or current_sources != sources
        ):
            observations.failure(
                "CONTEXT_CHANGED", "原件核验期间包、附件、来源或历史风险已变化，未登记实际提交"
            )
        saved = _persist(
            c,
            scope,
            actor,
            key,
            body,
            condition,
            command,
            current,
            current_originals,
            current_sources,
            supersedes,
            bid_etag_fn,
        )
    return saved, False


def load(c, bid, submission_id):
    return repository.load(c, str(bid), str(submission_id))
