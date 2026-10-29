"""Transactional human review registry; no native jobs, grants or reservations."""

from psycopg.types.json import Jsonb

from packages.domain import bid_package_technical_scope_repository as scopes
from packages.domain.runtime import Command, audit, clean, etag, fetch, match, sha, uid
from packages.model_governance import material_qualification as policy


def available(c):
    if (
        c.execute("SELECT to_regclass('material_qualification.records') AS relation").fetchone()[
            "relation"
        ]
        is None
    ):
        policy.fail("UNAVAILABLE", "资格审核登记库尚未安装，未授予执行资格", 503)


def _scope(c, scope, scope_id):
    available(c)
    return scopes.load(c, tuple(map(str, scope)), str(scope_id))


def _evidence(c, bid, document):
    for proof in document["evidence"].values():
        row = c.execute(
            "SELECT b.digest FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s AND v.id=%s",
            (bid, proof["document_version_id"]),
        ).fetchone()
        if row is None or row["digest"] != proof["digest"]:
            policy.fail("EVIDENCE_CHANGED", "证据原件不属于该项目或摘要不一致", 409)


def _row(c, scope_id, record_id, *, lock=False):
    return fetch(
        c,
        "SELECT r.*,h.revision,d.decision,d.actor_id AS reviewer_id,d.reason,d.created_at AS reviewed_at FROM material_qualification.records r JOIN material_qualification.heads h ON h.record_id=r.id LEFT JOIN material_qualification.decisions d ON d.id=h.decision_id AND d.record_id=r.id AND d.revision=h.revision WHERE r.scope_id=%s AND r.id=%s"
        + (" FOR UPDATE OF h" if lock else ""),
        (scope_id, record_id),
    )


def _view(row, at):
    state = row["decision"] or "registered"
    if state == "approved" and not policy.timestamp(
        row["document"]["valid_from"]
    ) <= at < policy.timestamp(row["document"]["valid_until"]):
        state = "expired"
    return clean(
        {
            "version": "material-qualification-review-view/1",
            "id": row["id"],
            "scope_id": row["scope_id"],
            "digest": row["digest"],
            "document": row["document"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "revision": row["revision"],
            "decision": row["decision"],
            "state": state,
            "reviewer_id": row["reviewer_id"],
            "reason": row["reason"],
            "reviewed_at": row["reviewed_at"],
            "observed_at": at,
            "execution_authorized": False,
            "accuracy_verified": False,
        }
    )


def _now(c):
    return c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]


def read(c, scope, scope_id, record_id):
    _scope(c, scope, scope_id)
    row = _row(c, scope_id, record_id)
    return _view(row, _now(c)), etag("material-qualification", record_id, row["revision"])


def register(c, scope, scope_id, actor, body, key):
    saved = _scope(c, scope, scope_id)
    # Replay immutable receipts before revalidating now-expired methods/evidence.
    command = Command(
        c,
        actor,
        "register-material-qualification",
        scope_id,
        key,
        {"scope": list(scope), "body": body},
    )
    if command.replay is not None:
        return command.replay, True
    value = policy.validate(body)
    if value["binding"]["scope_digest"] != saved["digest"]:
        policy.fail("SCOPE_CHANGED", "登记记录不属于所选冻结范围", 409)
    _evidence(c, scope[0], value)
    record = uid()
    c.execute(
        "INSERT INTO material_qualification.records(id,bid_id,scope_id,document,digest,created_by) VALUES(%s,%s,%s,%s,%s,%s)",
        (record, scope[0], scope_id, Jsonb(value), sha(value), actor),
    )
    c.execute("INSERT INTO material_qualification.heads(record_id) VALUES(%s)", (record,))
    audit(
        c,
        actor,
        scope[0],
        "material.qualification_registered",
        {"record_id": str(record), "digest": sha(value)},
        command.id,
    )
    result, tag = read(c, scope, scope_id, record)
    return command.finish(result, 201, {"ETag": tag, "Cache-Control": "private, no-store"}), False


def review(c, scope, scope_id, record_id, actor, body, condition, key):
    _scope(c, scope, scope_id)
    # Lock the head before the command ledger: concurrent decisions serialize.
    row = _row(c, scope_id, record_id, lock=True)
    command = Command(
        c,
        actor,
        "review-material-qualification",
        record_id,
        key,
        {"scope": list(scope), "scope_id": scope_id, "body": body},
        condition,
    )
    if command.replay is not None:
        return command.replay, True
    match(condition, "material-qualification", record_id, row["revision"])
    policy.transition(row["document"], row["decision"], body, _now(c))
    if body["decision"] == "approved":
        _evidence(c, scope[0], row["document"])
    revision, decision_id = row["revision"] + 1, uid()
    c.execute(
        "INSERT INTO material_qualification.decisions(id,record_id,revision,decision,actor_id,reason) VALUES(%s,%s,%s,%s,%s,%s)",
        (decision_id, record_id, revision, body["decision"], actor, body["reason"]),
    )
    c.execute(
        "UPDATE material_qualification.heads SET decision_id=%s,revision=%s WHERE record_id=%s",
        (decision_id, revision, record_id),
    )
    audit(
        c,
        actor,
        scope[0],
        "material.qualification_reviewed",
        {"record_id": str(record_id), "decision": body["decision"], "revision": revision},
        command.id,
    )
    result, tag = read(c, scope, scope_id, record_id)
    return command.finish(
        result, headers={"ETag": tag, "Cache-Control": "private, no-store"}
    ), False
