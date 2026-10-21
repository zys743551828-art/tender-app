"""Fresh, private admission for declared-scope review and locked publication rechecks.

Observe is read-only. Verify performs original-byte IO after closing that snapshot,
then observes again. Recheck only reads under the caller's publication locks. No
function here enqueues a task or alters historical readiness observations.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from packages.domain import bid_package_dependency_plan_repository as plans
from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_fact_admission as fact_admission
from packages.domain import bid_package_frozen_originals as originals
from packages.domain import bid_package_inventory_proof as inventory_reader
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import original_verification
from packages.domain import package_fact_usage as fact_usage
from packages.domain import package_input_dependencies as dependencies
from packages.domain import package_inventory_proof as inventory_proof
from packages.domain import package_scope_review as policy
from packages.domain.bid_package_service import lock_bid
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError, connection, require_read_committed
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable

OBSERVATION_LIMITATIONS = frozenset(
    {
        "PACKAGE_REVIEW_EXECUTOR_NOT_READY",
        "PACKAGE_REVIEW_REQUIREMENT_COMPLETENESS_UNPROVEN",
        "PACKAGE_REVIEW_FACTS_UNPROVEN",
    }
)


@dataclass(frozen=True, slots=True)
class ObservedScopeReview:
    scope: tuple[str, str, str, str]
    frozen_id: str
    prepared_id: str
    worker: bool
    _request_text: str = field(repr=False)
    _prepared: Any = field(repr=False)
    _frozen: Any = field(repr=False)
    _snapshot_text: str = field(repr=False)
    _plan_text: str = field(repr=False)
    _admission: Any = field(repr=False)
    _manifest_text: str = field(repr=False)

    def input_manifest(self):
        return json.loads(self._manifest_text)

    def model_input(self):
        return policy.model_input(
            self._frozen.evidence(), json.loads(self._plan_text), self._admission
        )


@dataclass(frozen=True, slots=True)
class VerifiedScopeReview:
    _observed: ObservedScopeReview = field(repr=False)


def _validate_request(scope, frozen_id, prepared_id, body):
    try:
        valid = (
            type(scope) is tuple
            and len(scope) == 4
            and isinstance(body, dict)
            and set(body)
            == {"execution_input_digest", "dependency_plan_id", "dependency_plan_digest"}
            and all(
                isinstance(body[key], str)
                and len(body[key]) == 64
                and set(body[key]) <= set("abcdef0123456789")
                for key in ("execution_input_digest", "dependency_plan_digest")
            )
            and all(
                isinstance(value, str) and str(UUID(value)) == value
                for value in (*scope, frozen_id, prepared_id, body["dependency_plan_id"])
            )
        )
    except (TypeError, ValueError, KeyError):
        valid = False
    policy.require(valid, "PACKAGE_SCOPE_REQUEST_INVALID", "整包核查请求字段或精确身份无效", 422)


def _assert_snapshot(prepared, current):
    snapshot = prepared.snapshot()
    snapshot.pop("version")
    originals.assert_same(snapshot, current)


def _admit(snapshot, assessment, admission, proof):
    result = snapshot["result"]
    blockers = sorted(set(result["blockers"]) - OBSERVATION_LIMITATIONS)
    policy.require(
        not blockers,
        "PACKAGE_SCOPE_INPUT_BLOCKED",
        "当前冻结来源、项目身份或输入条件已变化，不能启动本轮范围核查",
    )
    policy.require(
        result["parse_evidence_status"] == "matched",
        "PACKAGE_REVIEW_EVIDENCE_CHANGED",
        "精确冻结解析证据未通过核验",
    )
    am = assessment["manifest"]
    policy.require(
        am["dependency_review_status"] == "declared"
        and am["requirements"]
        and all(
            row["declaration"] is not None
            and row["fact_status"] in {"not_used", "selected_unvalidated"}
            and row["source_bound"] is True
            for row in am["requirements"]
        ),
        "PACKAGE_SCOPE_DEPENDENCIES_UNPROVEN",
        "请为每条冻结要求明确事实依赖并选齐需要的事实，再保存依赖计划",
    )
    facts = admission.view()["manifest"]
    policy.require(
        facts["usage_digest"] == am["usage_digest"]
        and facts["selected_count"] == am["selected_fact_count"]
        and facts["admission"]
        == ("verified_for_selected_use" if am["selected_fact_count"] else "not_used"),
        "PACKAGE_SCOPE_SELECTED_FACTS_UNPROVEN",
        "已保存计划所选事实没有取得本次精确范围的有效准入",
    )
    pm = proof["manifest"]
    policy.require(
        pm["extraction_range_proven"] is True
        and pm["extraction_receipt_state"] == "matched"
        and pm["extraction_coverage"] == "complete"
        and not set(pm["blockers"]) - {policy.LIMITATION},
        "PACKAGE_SCOPE_INVENTORY_UNPROVEN",
        "冻结要求清单与完整原抽取范围回执尚不能一致核验",
    )


def _observe(c, scope, frozen_id, prepared_id, body, *, worker):
    prepared = prepared_inputs.load_packet(c, scope, frozen_id, prepared_id)
    policy.require(
        prepared.digest == body["execution_input_digest"],
        "PACKAGE_EXECUTION_INPUT_CHANGED",
        "准备输入摘要与明确选择不一致",
    )
    frozen = frozen_inputs.load_input(c, scope, frozen_id)
    plan = plans.load(c, scope, frozen_id, prepared_id, body["dependency_plan_id"])
    policy.require(
        plan["digest"] == body["dependency_plan_digest"],
        "PACKAGE_SCOPE_DEPENDENCY_PLAN_CHANGED",
        "依赖计划摘要与明确选择不一致",
    )
    snapshot = originals.capture(c, scope, frozen_id, frozen.digest)
    _assert_snapshot(prepared, snapshot)
    try:
        usage = fact_usage.verify(plan["manifest"]["usage"], prepared)
        assessment = dependencies.verify(plan["manifest"]["assessment"], frozen, prepared, usage)
        admitted = fact_admission._observe(c, prepared, usage)
        inventory = frozen.evidence()["selection"]["inventory"]["manifest"]
        proof = inventory_proof.assess(
            frozen, prepared, inventory_reader._receipt(c, scope, inventory)
        ).view()
    except (ValueError, KeyError, TypeError) as error:
        raise DomainError(
            "PACKAGE_SCOPE_DEPENDENCIES_CHANGED",
            "计划、所选事实或原抽取回执不能按当前方法重新核验",
            409,
        ) from error
    _admit(snapshot, assessment.view(), admitted, proof)
    profile = policy.method_profile()
    manifest = policy.input_manifest(prepared, frozen, plan, admitted, proof, profile)
    return ObservedScopeReview(
        scope,
        frozen_id,
        prepared_id,
        worker,
        canonical(body).decode(),
        prepared,
        frozen,
        # Current private snapshots contain the same floating parse geometry as
        # the frozen model input; they are not the integer-only business manifest.
        policy.model_json(snapshot),
        canonical(plan).decode(),
        admitted,
        canonical(manifest).decode(),
    )


def observe(scope, frozen_id, prepared_id, body, *, worker=False):
    _validate_request(scope, frozen_id, prepared_id, body)
    # API admission does not need a provider credential. The independent worker
    # checks its own local configuration before original IO or any paid request.
    if worker:
        DeepSeekClient.from_env()
    with connection(worker) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _observe(c, scope, frozen_id, prepared_id, body, worker=worker)


def _assert_same(before: ObservedScopeReview, after: ObservedScopeReview):
    originals.assert_same(json.loads(before._snapshot_text), json.loads(after._snapshot_text))
    policy.require(
        before._prepared.view() == after._prepared.view()
        and before._prepared.snapshot() == after._prepared.snapshot()
        and before._frozen.view() == after._frozen.view()
        and before._frozen.evidence() == after._frozen.evidence()
        and before._plan_text == after._plan_text
        and before._admission._proof_text == after._admission._proof_text
        and before._manifest_text == after._manifest_text,
        "PACKAGE_SCOPE_ADMISSION_CHANGED",
        "原件核验或模型调用后，输入、方法、事实或依赖计划发生变化",
    )


def verify(observed: ObservedScopeReview) -> VerifiedScopeReview:
    if not isinstance(observed, ObservedScopeReview):
        raise TypeError("Scope verification requires a private observation")
    snapshot = json.loads(observed._snapshot_text)
    # Every logical member remains bound even when two members use identical bytes.
    for document in snapshot["documents"]:
        original_verification.verify(document)
    after = observe(
        observed.scope,
        observed.frozen_id,
        observed.prepared_id,
        json.loads(observed._request_text),
        worker=observed.worker,
    )
    _assert_same(observed, after)
    return VerifiedScopeReview(after)


def recheck(c, verified: VerifiedScopeReview) -> dict[str, Any]:
    if not isinstance(verified, VerifiedScopeReview):
        raise TypeError("Scope publication requires privately verified originals")
    if c.autocommit:
        raise ValueError("Scope publication requires a transaction")
    require_read_committed(c)
    observed = verified._observed
    if observed.worker:
        c.execute("SELECT design.lock_worker_bid(%s)", (observed.scope[0],))
    else:
        lock_bid(c, observed.scope[0])
    assert_work_writable(c, observed.scope[0], worker=observed.worker)
    lock_graph(c)
    fresh = _observe(
        c,
        observed.scope,
        observed.frozen_id,
        observed.prepared_id,
        json.loads(observed._request_text),
        worker=observed.worker,
    )
    _assert_same(observed, fresh)
    manifest = fresh.input_manifest()
    policy.require(
        manifest["executor_method"]["digest"] == digest(policy.method_profile()),
        "PACKAGE_SCOPE_METHOD_CHANGED",
        "整包范围核查方法已变化，请重新准备本次核查",
    )
    return manifest


def execution_key(verified: VerifiedScopeReview, manifest: dict[str, Any]) -> str:
    """Project only the privately verified declarations; no database or original IO."""
    from packages.domain.package_scope_review_identity import identify

    if not isinstance(verified, VerifiedScopeReview):
        raise TypeError("Scope execution identity requires privately verified originals")
    observed = verified._observed
    policy.require(
        manifest == observed.input_manifest(),
        "PACKAGE_SCOPE_EXECUTION_KEY_INVALID",
        "核查语义键必须来自同一份已核验并锁内复核的输入",
    )
    try:
        proof = json.loads(observed._admission._proof_text)
        policy.require(
            digest(proof) == manifest["fact_admission"]["proofs_digest"],
            "PACKAGE_SCOPE_EXECUTION_KEY_INVALID",
            "原选用事实的私有依据与核查输入摘要不一致",
        )
        records = [row["declaration"] for row in proof["selected"]]
    except (KeyError, TypeError, ValueError) as error:
        raise DomainError(
            "PACKAGE_SCOPE_EXECUTION_KEY_INVALID", "原选用事实声明无法核验", 409
        ) from error
    return identify(manifest, records)["digest"]
