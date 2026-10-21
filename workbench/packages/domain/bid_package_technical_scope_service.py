"""Two-observation scope freezing with original bytes checked outside all DB scopes."""

from copy import deepcopy

from packages.contracts import package_technical_scope_api as contract
from packages.domain import bid_package_technical_scope_repository as repository
from packages.domain import original_verification
from packages.domain import package_technical_scope as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    connection,
    etag,
    now,
    require_read_committed,
    uid,
)
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable


def _etag(scope, snapshot, method):
    return repository.tag(
        scope[2],
        digest(
            {"snapshot_digest": policy.context_digest(snapshot), "method_digest": method["digest"]}
        ),
    )


def context(c, scope, inventory_id):
    repository.require_schema(c)
    scope = tuple(map(str, scope))
    observation = repository.observe(c, scope, str(inventory_id))
    snapshot, method = observation["snapshot"], policy.policy_identity()
    result = {key: snapshot[key] for key in ("target", "authority", "inventory")} | {
        "method": method,
        "context_digest": policy.context_digest(snapshot),
        "etag": _etag(scope, snapshot, method),
        "can_freeze": not snapshot["blocking_reasons"],
        "blocking_reasons": snapshot["blocking_reasons"],
        "catalog_complete": True,
        "timing": dict(policy.TIMING),
        **policy.FLAGS,
    }
    contract.validate("PackageTechnicalScopeContext", result)
    return result


def preview(c, scope, body):
    repository.require_schema(c)
    contract.validate("PackageTechnicalScopeRequest", body)
    observed = repository.observe(c, tuple(map(str, scope)), body["inventory_id"])
    return policy.prepare(observed["snapshot"], body)


def preview_etag(value):
    manifest = value["manifest"]
    return repository.tag(
        manifest["scope"]["revision_id"],
        digest(
            {
                "snapshot_digest": manifest["context_digest"],
                "method_digest": manifest["method"]["digest"],
            }
        ),
    )


def _condition(scope, snapshot, method, condition):
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请提供确切技术范围上下文的强ETag", 428)
    if condition != _etag(scope, snapshot, method):
        raise DomainError("REVISION_CONFLICT", "技术范围上下文已变化，请保留原选择并重新预览", 412)


def _eligible(snapshot):
    if snapshot["blocking_reasons"]:
        policy.failure("CONTEXT_UNAVAILABLE", "当前包、项目或来源资格不允许登记新的事前技术范围")


def freeze(scope, actor, key, body, condition, *, final_auth=None):
    scope, actor = tuple(map(str, scope)), str(actor)
    policy.bounded(body, policy.LIMITS["request_bytes"])
    contract.validate("FreezePackageTechnicalScope", body)
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or "\x00" in key:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供1到128字符的原请求幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        prior = repository.replay(c, actor, scope, key, body, condition)
        if prior is not None:
            return prior, True
        repository.require_schema(c)
        before = repository.observe(c, scope, body["request"]["inventory_id"])
        prepared = policy.prepare(before["snapshot"], body["request"])
        _condition(scope, before["snapshot"], prepared["manifest"]["method"], condition)
        _eligible(before["snapshot"])
        if prepared["digest"] != body["preview_digest"]:
            policy.failure("PREVIEW_CHANGED", "范围、读取缺口或方法与已查看预览不同，请重新预览")
    for document in before["originals"]:
        original_verification.verify(document)
    verified_at = utc(now().isoformat())
    if final_auth is not None and str(final_auth()) != actor:
        policy.failure("ACTOR_CHANGED", "原件核验期间当前账户变化，未登记范围", 403)
    with connection() as c:
        require_read_committed(c)
        lock_bid(c, scope[0])
        command = Command(
            c,
            actor,
            repository.KIND,
            scope[2],
            key,
            repository.request_body(scope, body),
            condition,
        )
        if command.replay is not None:
            return repository.replay(c, actor, scope, key, body, condition), True
        assert_work_writable(c, scope[0])
        lock_graph(c)
        current = repository.observe(c, scope, body["request"]["inventory_id"])
        refreshed = policy.prepare(current["snapshot"], body["request"])
        _condition(scope, current["snapshot"], refreshed["manifest"]["method"], condition)
        _eligible(current["snapshot"])
        if current != before or refreshed != prepared:
            policy.failure("CONTEXT_CHANGED", "原件核验期间确切范围、来源闭包或方法已变化，未保存")
        frozen_at = utc(
            c.execute("SELECT clock_timestamp() AS value").fetchone()["value"].isoformat()
        )
        saved_scope = policy.freeze(
            prepared,
            identity=str(uid()),
            actor=actor,
            command=str(command.id),
            frozen_at=frozen_at,
            verified_at=verified_at,
            originals=current["originals"],
        )
        repository.insert(c, saved_scope)
        ack = {
            "scope": saved_scope,
            "command": {
                "command_id": str(command.id),
                "actor_id": actor,
                "idempotency_key": key,
                "request_digest": repository.command_digest(scope, body, condition),
                "request": deepcopy(body),
                "if_match": condition,
            },
        }
        audit(
            c,
            actor,
            scope[0],
            repository.EVENT,
            {
                "scope_id": saved_scope["manifest"]["id"],
                "digest": saved_scope["digest"],
                "inventory_id": body["request"]["inventory_id"],
            },
            command.id,
        )
        contract.validate("PackageTechnicalScopeApplied", ack)
        result = command.finish(
            ack,
            201,
            {
                "ETag": etag(
                    "package-technical-scope", saved_scope["manifest"]["id"], saved_scope["digest"]
                )
            },
        )
    return result, False


def load(c, scope, identity):
    return repository.load(c, tuple(map(str, scope)), str(identity))


def history(c, scope, cursor=None, limit=20):
    return repository.history(c, tuple(map(str, scope)), cursor, limit)
