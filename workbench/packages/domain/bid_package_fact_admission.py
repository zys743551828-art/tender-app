"""Observe selected-fact admission and recheck under caller locks without IO/commit."""

from packages.domain import bid_package_execution_input_repository as inputs
from packages.domain import bid_package_fact_scope_repository as declarations
from packages.domain import package_fact_admission as policy
from packages.domain import package_fact_usage as usage_policy
from packages.domain.bid_package_fact_provenance import read_proof
from packages.domain.bid_package_service import lock_bid
from packages.domain.package_review_context import read_facts
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import ROOT, DomainError, connection, require_read_committed, sha
from packages.knowledge.sources import lock_graph

FILES = (
    "packages/domain/bid_package_fact_admission.py",
    "packages/domain/package_fact_admission.py",
    "packages/domain/package_fact_usage.py",
    "packages/domain/package_review_context.py",
    "packages/domain/bid_package_fact_provenance.py",
    "packages/domain/fact_decision_lineage.py",
    "packages/domain/package_fact_scope_snapshot.py",
    "packages/contracts/schemas/package-fact-proof-snapshot.schema.json",
    "packages/domain/package_fact_validation.py",
    "packages/domain/package_fact_scope.py",
    "packages/domain/bid_package_fact_scope_repository.py",
    "packages/domain/review_data.py",
    "packages/domain/rule_sets.py",
    "packages/domain/human_decisions.py",
    "packages/domain/review_identity.py",
    "packages/identity/contracts.py",
    "packages/identity/sql/stable-lot-identity.sql",
    "packages/rag/indexing.py",
    "packages/contracts/sql/bid-package-fact-scopes.sql",
    "packages/contracts/schemas/package-fact-usage.schema.json",
    "packages/contracts/schemas/selected-fact-admission.schema.json",
)


def _load(c, scope, frozen_id, input_id, prepared_digest, request):
    packet = inputs.load_packet(c, scope, frozen_id, input_id)
    if packet.digest != prepared_digest:
        raise DomainError("PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不符", 409)
    return packet, usage_policy.select(packet, request)


def _observe(c, packet, usage):
    ids = [item["fact_id"] for item in usage.view()["manifest"]["selected"]]
    now = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
    identity = None
    current = {}
    heads = {}
    proofs = {}
    if ids:
        identity = c.execute(
            "SELECT design.identity_snapshot_v2(%s) AS value", (packet.scope[0],)
        ).fetchone()["value"]
        selected_parses = {
            (doc["document_version_id"], doc["parse_id"]) for doc in packet.snapshot()["documents"]
        }
        current = {
            item["fact"]["id"]: item
            for item in read_facts(c, packet.scope[0], selected_parses, fact_ids=ids, as_of=now)[
                "items"
            ]
        }
        if set(current) != set(ids):
            raise DomainError(
                "PACKAGE_SELECTED_FACT_NOT_CURRENT", "选用事实已不在当前事实集中", 409
            )
        heads = {
            fact_id: declarations.head(c, packet.scope[0], packet.input_id, fact_id)
            for fact_id in ids
        }
        proofs = {fact_id: read_proof(c, packet.scope[0], current[fact_id], now) for fact_id in ids}
    profile = digest(
        {
            "version": "selected-fact-admission-policy/1",
            "sources": {name: sha((ROOT / name).read_bytes()) for name in FILES},
        }
    )
    try:
        return policy.admit(usage, identity, current, heads, proofs, profile, now)
    except ValueError as error:
        raise DomainError(
            "PACKAGE_SELECTED_FACTS_UNPROVEN", "选用事实、当前确认、来源或范围声明未通过核验", 409
        ) from error


def observe(scope, frozen_id, input_id, prepared_digest, request):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet, usage = _load(c, scope, frozen_id, input_id, prepared_digest, request)
        return _observe(c, packet, usage)


def recheck(c, observed):
    if c.autocommit:
        raise ValueError("Selected-fact recheck requires a transaction")
    require_read_committed(c)
    old = observed._usage.view()["manifest"]
    ref = old["prepared"]
    scope = tuple(ref[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id"))
    lock_bid(c, scope[0])
    lock_graph(c)
    packet, usage = _load(
        c,
        scope,
        ref["frozen_input_id"],
        ref["execution_input_id"],
        ref["execution_input_digest"],
        {"purpose": old["purpose"], "fact_ids": [x["fact_id"] for x in old["selected"]]},
    )
    if usage.view() != observed._usage.view():
        raise DomainError("PACKAGE_SELECTED_FACTS_CHANGED", "原事实消费投影已变化", 409)
    fresh = _observe(c, packet, usage)
    if (
        fresh.view()["manifest"]["content_digest"] != observed.view()["manifest"]["content_digest"]
        or fresh._proof_text != observed._proof_text
    ):
        raise DomainError("PACKAGE_SELECTED_FACTS_CHANGED", "事实准入依赖已变化，请重新核对", 409)
    return fresh
