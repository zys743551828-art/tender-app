"""Explicit package rule corrections, with exact originals verified outside transactions."""

from copy import deepcopy
from datetime import datetime

from packages.contracts.package_rule_corrections_api import validate
from packages.domain import bid_package_requirement_repository as inventories
from packages.domain import bid_package_rule_correction_repository as repository
from packages.domain import original_verification
from packages.domain.bid_package_review_documents import generated_observations, read_member
from packages.domain.bid_package_service import historical, lock_bid
from packages.domain.human_decisions import append_decision
from packages.domain.input_changes import invalidate_pending
from packages.domain.review_identity import digest, utc
from packages.domain.rule_corrections import COLUMNS, _insert
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import (
    Command,
    DomainError,
    audit,
    clean,
    connection,
    require_read_committed,
    uid,
)
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable


def _policy():
    from packages.domain import package_rule_corrections

    return package_rule_corrections


def _required_evidence(request):
    result: set[str] = set()
    for change in request["changes"]:
        quotes = (
            change["evidence_quotes"]
            if change["op"] == "withdraw"
            else change["rule"]["evidence_quotes"]
        )
        result.update(item["evidence_id"] for item in quotes)
    return sorted(result)


def _effective(snapshot, at):
    for row in snapshot:
        if (
            row["policy_class"] != "prebid_content"
            or row["status"] != "published"
            or row["known_at"] is None
            or row["valid_from"] is None
            or datetime.fromisoformat(row["known_at"]) > at
            or datetime.fromisoformat(row["valid_from"]) > at
            or (row["valid_until"] is not None and datetime.fromisoformat(row["valid_until"]) <= at)
        ):
            repository.failure(
                "SOURCE_CHANGED", "依据或其祖先当前未生效、已撤回或已到期，不能形成新的人工更正"
            )


def _source_originals(c, bid, authority, source_snapshot):
    direct_versions = [item["document_version_id"] for item in authority["manifest"]["members"]]
    direct = {
        row["id"]
        for row in c.execute(
            "SELECT id::text FROM retrieval.source_nodes WHERE document_version_id=ANY(%s::uuid[])",
            (direct_versions,),
        ).fetchall()
    }
    versions = set(direct_versions) | {
        row["document_version_id"]
        for row in source_snapshot
        if row["source_id"] in direct and row["document_version_id"] is not None
    }
    values = clean(
        c.execute(
            """SELECT v.id::text AS document_version_id,b.id::text AS blob_id,b.digest,b.byte_size,b.object_key
        FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id
        WHERE v.bid_id=%s AND v.id=ANY(%s::uuid[]) ORDER BY v.id""",
            (bid, sorted(versions)),
        ).fetchall()
    )
    if {row["document_version_id"] for row in values} != versions:
        repository.failure("SOURCE_CHANGED", "权威原件或其原件祖先不属于当前项目")
    return values


def _observe(c, scope, request):
    """One DB observation. Caller supplies RR/RO for preview or final locked RC."""
    repository.require_schema(c)
    base = inventories.load_inventory(c, *scope)
    im = base["manifest"]
    if im["version"] not in {"bid-package-requirements/2", "bid-package-requirements/3"}:
        repository.failure(
            "EXACT_EXTRACTION_REQUIRED", "该旧清单没有精确抽取身份，请重新准备确切权威包和清单"
        )
    if (
        request["base_inventory_digest"] != base["digest"]
        or request["base_rule_set_digest"] != im["rule_set_digest"]
    ):
        repository.failure("BASE_CHANGED", "更正请求的基础清单或规则集摘要与选择不一致")
    current = inventories.head(c, scope[2])
    if current is None or current["id"] != scope[3] or current["digest"] != base["digest"]:
        repository.failure("BASE_CHANGED", "要求清单已有新版，请保留本次编辑并核对新清单", 412)
    profile = c.execute(
        "SELECT current_rule_set_id::text,phase,archived_at FROM design.bid_profiles WHERE bid_id=%s",
        (scope[0],),
    ).fetchone()
    if profile is None or profile["current_rule_set_id"] != im["rule_set_id"]:
        repository.failure("BASE_CHANGED", "当前规则集已变化，请重新核对更正依据", 412)
    # Preview is a repeatable-read observation. The final command acquires the
    # lifecycle lock in assert_work_writable before calling this observer again.
    if profile["archived_at"] is not None or profile["phase"] in {"closed", "terminated"}:
        repository.failure("PROJECT_CLOSED", "项目已结束或归档，不能新增人工更正")
    target = historical(c, *scope[:3])
    official = repository.authority(c, scope[0], base)
    if (
        target.manifest_digest != im["package_digest"]
        or target.manifest()["scope"] != official["manifest"]["scope"]
    ):
        repository.failure("CONTEXT_CHANGED", "本方包与权威包的确切项目、标段或轮次不一致")
    heads = clean(
        c.execute(
            "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[]) ORDER BY package_id",
            ([scope[1], official["manifest"]["package_id"]],),
        ).fetchall()
    )
    by_package = {row["package_id"]: row["revision_id"] for row in heads}
    if (
        by_package.get(scope[1]) != scope[2]
        or by_package.get(official["manifest"]["package_id"]) != official["manifest"]["revision_id"]
    ):
        repository.failure("CONTEXT_CHANGED", "包修订已变化，请针对当前确切输入重新预览")
    identity = c.execute("SELECT design.identity_snapshot_v2(%s) AS value", (scope[0],)).fetchone()[
        "value"
    ]
    if identity["digest"] != im["identity_digest"]:
        repository.failure("CONTEXT_CHANGED", "工程、标段、轮次或投标主体身份已变化")
    actual_rules = repository.native_rules(c, scope[0], im["rule_set_id"])
    frozen_rules = [row["rule_snapshot"] for row in im["requirements"]]
    if sorted(actual_rules, key=lambda x: x["id"]) != sorted(frozen_rules, key=lambda x: x["id"]):
        repository.failure("CORRUPT", "原清单规则快照与确切原规则集不一致", 500)
    decisions = []
    for row in im["requirements"]:
        selected = current_decision(c, scope[0], "rule", row["rule_id"])
        actual = (
            c.execute(
                "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE id=%s", (selected["id"],)
            ).fetchone()["value"]
            if selected
            else None
        )
        if actual != row["decision_snapshot"]:
            repository.failure(
                "DECISION_CHANGED", "原清单的人工决定已变化，请重新冻结检查计划后再更正"
            )
        decisions.append(actual)
    source_snapshot = inventories._source_snapshot(c, scope[2], official["manifest"]["revision_id"])
    if source_snapshot != im["source_snapshot"]:
        repository.failure("SOURCE_CHANGED", "原清单的来源快照已变化，请重新核对并冻结检查计划")
    required_versions = {item["document_version_id"] for item in official["manifest"]["members"]}
    if not source_snapshot or not required_versions <= {
        row["document_version_id"] for row in source_snapshot
    }:
        repository.failure("SOURCE_UNPROVEN", "权威原件缺少可核验的来源及祖先记录")
    at = c.execute("SELECT clock_timestamp() AS at").fetchone()["at"]
    _effective(source_snapshot, at)
    documents = [
        clean(read_member(c, scope[0], member)) for member in official["manifest"]["members"]
    ]
    generated = generated_observations(
        c, {"bid_id": scope[0], "target": {"manifest": target.manifest()}, "authority": official}
    )
    if any(item["admission"]["state"] != "matched" for item in generated):
        repository.failure("SOURCE_CHANGED", "所选生成原件的采用或图片来源已变化")
    evidence = repository.evidence_rows(c, scope[0], official, _required_evidence(request))
    prepared = _policy().prepare(base, official, evidence, request)
    originals = _source_originals(c, scope[0], official, source_snapshot)
    return {
        "base": base,
        "authority": official,
        "evidence": evidence,
        "preview": prepared,
        "documents": documents,
        "originals": originals,
        "observations": {
            "profile": clean(profile),
            "heads": heads,
            "identity": identity,
            "source_snapshot": source_snapshot,
            "decisions": decisions,
            "generated": generated,
        },
    }


def preview(c, scope, body):
    validate("PackageRuleCorrectionRequest", body)
    return _observe(c, tuple(map(str, scope)), deepcopy(body))["preview"]


def _condition(scope, base, condition):
    if not condition:
        raise DomainError("PRECONDITION_REQUIRED", "请提供所选要求清单的强ETag", 428)
    if condition != repository.tag(scope[2], base["digest"]):
        raise DomainError(
            "REVISION_CONFLICT", "要求清单版本条件已变化，请保留更正内容并重新预览", 412
        )


def _persist(c, scope, actor, command, key, body, condition, observation):
    policy = _policy()
    base = observation["base"]
    old = base["manifest"]
    new_set, new_inventory, record_id = map(str, (uid(), uid(), uid()))
    rule_ids = {
        "existing": {row["rule_id"]: str(uid()) for row in old["requirements"]},
        "added": {
            str(index): str(uid())
            for index, change in enumerate(body["request"]["changes"])
            if change["op"] == "add"
        },
    }
    materialized = policy.materialize(
        base, observation["preview"], rule_set_id=new_set, rule_ids=rule_ids
    )
    prior = c.execute(
        "SELECT material_id,coverage FROM design.rule_sets WHERE bid_id=%s AND id=%s",
        (scope[0], old["rule_set_id"]),
    ).fetchone()
    revision = c.execute(
        "SELECT coalesce(max(revision),0)+1 AS value FROM design.rule_sets WHERE bid_id=%s",
        (scope[0],),
    ).fetchone()["value"]
    c.execute(
        "INSERT INTO design.rule_sets(id,bid_id,material_id,revision,digest,coverage) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            new_set,
            scope[0],
            prior["material_id"],
            revision,
            materialized["rule_set_digest"],
            prior["coverage"],
        ),
    )
    for rule in materialized["rules"]:
        _insert(c, scope[0], new_set, rule["id"], {name: rule[name] for name in COLUMNS})
    # The pure materializer supplies exact carry/decision instructions. Native
    # decisions remain the sole human authority, linked by immutable derivation.
    bindings = []
    for row in materialized["carryovers"]:
        c.execute(
            "INSERT INTO design.rule_carryovers(bid_id,new_rule_id,from_rule_id,from_decision_id,equivalence_digest) VALUES(%s,%s,%s,%s,%s)",
            (
                scope[0],
                row["new_rule_id"],
                row["from_rule_id"],
                row["from_decision_id"],
                row["equivalence_digest"],
            ),
        )
        value = c.execute(
            "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE id=%s",
            (row["from_decision_id"],),
        ).fetchone()["value"]
        bindings.append(
            {
                "rule_id": row["new_rule_id"],
                "decision_id": value["id"],
                "decision_digest": digest(value),
                "mode": "carried",
            }
        )
    for row in materialized["decisions"]:
        decision = append_decision(
            c,
            scope[0],
            actor,
            "rule",
            row["rule_id"],
            {
                "decision": row["decision"],
                "reason": row["reason"],
                "evidence_ids": row["evidence_ids"],
            },
            command_id=command.id,
            basis=row["basis"],
        )
        value = c.execute(
            "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE id=%s", (decision["id"],)
        ).fetchone()["value"]
        bindings.append(
            {
                "rule_id": row["rule_id"],
                "decision_id": value["id"],
                "decision_digest": digest(value),
                "mode": row["decision"],
            }
        )
    created_at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
    record = policy.make_record(
        observation["preview"],
        materialized,
        record_id=record_id,
        actor_id=actor,
        command_id=str(command.id),
        created_at=created_at,
        decision_bindings=bindings,
        result_inventory_id=new_inventory,
    )
    repository.insert(c, record)
    c.execute(
        "UPDATE design.bid_profiles SET current_rule_set_id=%s WHERE bid_id=%s", (new_set, scope[0])
    )
    inventory = inventories.create_inventory(
        c,
        scope[0],
        scope[1],
        scope[2],
        {
            "authority_revision_id": old["authority_revision_id"],
            "rule_set_id": new_set,
            "mappings": materialized["inventory_mappings"],
            "actor_id": actor,
        },
        expected_digest=base["digest"],
        inventory_id=new_inventory,
    )
    invalidate_pending(
        c, scope[0], "整包人工要求已更正，请核对新清单并明确准备下一轮", "RULE_SET_CHANGED"
    )
    ack = {
        "correction": record,
        "inventory": inventory,
        "command": {
            "command_id": str(command.id),
            "actor_id": actor,
            "idempotency_key": key,
            "request_digest": repository.command_digest(scope, body, condition),
            "request": body,
            "if_match": condition,
        },
    }
    audit(
        c,
        actor,
        scope[0],
        repository.EVENT,
        {"correction_id": record_id, "digest": record["digest"], "inventory_id": new_inventory},
        command.id,
    )
    validate("PackageRuleCorrectionAppliedView", ack)
    saved = command.finish(ack, 201, {"ETag": repository.tag(scope[2], inventory["digest"])})
    # Validate the entire persisted archive, including native decisions and original
    # ACKs, before committing. This also enforces the complete 64 MiB chain bound.
    checked = inventories.load_inventory(c, scope[0], scope[1], scope[2], new_inventory)
    if checked != inventory:
        repository.failure("CORRUPT", "更正后清单与原始回执不一致", 500)
    return saved


def apply(scope, actor, key, body, condition, *, final_auth=None):
    """Original ACK wins before source/lifecycle/IO gates; a new write uses double observation."""
    scope = tuple(map(str, scope))
    actor = str(actor)
    validate("ApplyPackageRuleCorrection", body)
    if not key or len(key) > 128:
        raise DomainError("IDEMPOTENCY_REQUIRED", "请提供不超过128字的有效幂等键", 428)
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        old = repository.replay(c, actor, scope, key, body, condition)
        if old is not None:
            return old, True
        before = _observe(c, scope, body["request"])
        _condition(scope, before["base"], condition)
        if before["preview"]["digest"] != body["preview_digest"]:
            repository.failure("PREVIEW_CHANGED", "更正预览或方法已变化，请重读后明确保存")
    for document in before["originals"]:
        original_verification.verify(document)
    if final_auth is not None:
        if str(final_auth()) != actor:
            repository.failure("ACTOR_CHANGED", "原件核验期间当前账户已变化，未保存更正", 403)
    with connection() as c:
        require_read_committed(c)
        lock_bid(c, scope[0])
        command = Command(
            c,
            actor,
            repository.KIND,
            scope[3],
            key,
            repository.request_body(scope, body),
            condition,
        )
        if command.replay is not None:
            stored = repository.replay(c, actor, scope, key, body, condition)
            return stored, True
        assert_work_writable(c, scope[0])
        lock_graph(c)
        current = _observe(c, scope, body["request"])
        _condition(scope, current["base"], condition)
        if current != before:
            repository.failure(
                "CONTEXT_CHANGED", "原件核验期间精确输入、来源或人工决定已变化，未保存更正"
            )
        stored = _persist(c, scope, actor, command, key, deepcopy(body), condition, current)
    return stored, False


def history(c, scope, cursor=None, limit=20):
    return repository.history(c, tuple(map(str, scope)), cursor, limit)


def load(c, scope, correction_id):
    return repository.load(c, tuple(map(str, scope)), str(correction_id))


def evidence_directory(c, scope, cursor=None, limit=20):
    return repository.evidence(c, tuple(map(str, scope)), cursor=cursor, limit=limit)


def evidence_detail(c, scope, evidence_id):
    return repository.evidence(c, tuple(map(str, scope)), evidence_id=str(evidence_id))
