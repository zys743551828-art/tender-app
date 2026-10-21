"""Private whole-package authoring observations and IO/final-lock fences."""

import json
from dataclasses import dataclass, field

from packages.authoring import package_input_observation as readers
from packages.authoring.package_input_contracts import PackageAuthoringInputRequest
from packages.domain import original_verification
from packages.domain.bid_package_service import lock_bid
from packages.domain.review_data import effective_at
from packages.domain.review_identity import utc
from packages.domain.runtime import (
    ROOT,
    DomainError,
    connection,
    fetch,
    require_read_committed,
    sha,
)
from packages.knowledge.sources import lock_graph
from packages.lifecycle.service import assert_work_writable

MAX_CONTEXT_BYTES = 32 * 1024 * 1024
FILES = (
    "packages/authoring/package_input_contracts.py",
    "packages/authoring/package_input_observation.py",
    "packages/authoring/package_admission.py",
    "packages/authoring/package_input_repository.py",
    "packages/authoring/package_input.py",
    "packages/contracts/sql/authoring-package-inputs.sql",
    "packages/domain/bid_package_repository.py",
    "packages/domain/bid_package_review_documents.py",
    "packages/domain/bid_package_inventory_proof.py",
    "packages/domain/package_inventory_proof.py",
    "packages/domain/package_rule_corrections.py",
    "packages/domain/package_rule_correction_proof.py",
    "packages/domain/bid_package_fact_provenance.py",
    "packages/domain/package_fact_validation.py",
    "packages/domain/package_review_context.py",
    "packages/domain/fact_decision_lineage.py",
    "packages/domain/original_verification.py",
    "packages/authoring/snapshot_structure.py",
    "packages/authoring/repository.py",
    "packages/assistant/intent_identity.py",
)


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def profile():
    return {
        "protocol": "package-authoring-input-policy/1",
        "purpose": "authoring",
        "target_relation": "draft_using_package_context",
        "supported_target": "plain_text_stable_node",
        "context_limit_bytes": MAX_CONTEXT_BYTES,
        "complete_package_required": True,
        "implicit_source_selection": False,
        "source_sha256": {name: sha((ROOT / name).read_bytes()) for name in FILES},
    }


@dataclass(frozen=True, slots=True)
class ObservedPackageInput:
    bid_id: str
    checked_at: str
    _request_text: str = field(repr=False)
    _context_text: str = field(repr=False)

    def request(self):
        return json.loads(self._request_text)

    def context(self):
        return json.loads(self._context_text)

    @property
    def digest(self):
        return sha(self._context_text.encode())


@dataclass(frozen=True, slots=True)
class VerifiedPackageInput:
    _observed: ObservedPackageInput = field(repr=False)


def capture(c, bid, request):
    body = PackageAuthoringInputRequest.model_validate(request).model_dump(mode="json")
    lifecycle = fetch(
        c, "SELECT phase,archived_at FROM design.bid_profiles WHERE bid_id=%s", (bid,)
    )
    if lifecycle["archived_at"] or lifecycle["phase"] in {"closed", "terminated"}:
        raise DomainError("PROJECT_WORK_CLOSED", "项目已结束或归档，不能保存新的编写输入", 409)
    at = utc(fetch(c, "SELECT clock_timestamp() AS at")["at"].isoformat())
    selection, identity = readers.selected_packages(c, bid, body)
    docs = readers.documents(c, bid, selection)
    closure = readers.sources(c, bid, docs, at)
    inventory = readers.inventory(c, bid, body, selection, docs)
    facts = readers.facts(c, bid, body, docs, identity, at)
    target = readers.target(c, bid, body, docs)
    policy = profile()
    context = {
        "protocol": "package-authoring-context/1",
        "bid_id": bid,
        "request": body,
        "packages": selection,
        "identity": identity,
        "documents": docs,
        "inventory": inventory,
        "facts": facts,
        "target": target,
        "sources": closure,
        "method": policy,
        "method_digest": sha(policy),
    }
    text = encoded(context)
    if len(text.encode()) > MAX_CONTEXT_BYTES:
        raise DomainError(
            "AUTHORING_PACKAGE_CONTEXT_TOO_LARGE",
            "完整输入超过本阶段保存容量，未截取部分成员或原页",
            422,
            {"context_bytes": len(text.encode()), "limit_bytes": MAX_CONTEXT_BYTES},
        )
    # Expiry is re-evaluated after reading all facts/sections as well.
    effective_at(closure, fetch(c, "SELECT clock_timestamp() AS at")["at"])
    return ObservedPackageInput(bid, at, encoded(body), text)


def observe(bid, body):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return capture(c, str(bid), body)


def same(before, after):
    if (
        before.bid_id != after.bid_id
        or before._request_text != after._request_text
        or before._context_text != after._context_text
    ):
        raise DomainError(
            "AUTHORING_PACKAGE_INPUT_CHANGED",
            "核验期间固定输入或当前使用资格已变化，请重新核对",
            409,
        )


def verify(observed):
    for document in observed.context()["documents"]:
        original_verification.verify(document)
    after = observe(observed.bid_id, observed.request())
    same(observed, after)
    return VerifiedPackageInput(after)


def recheck(c, verified):
    if not isinstance(verified, VerifiedPackageInput) or c.autocommit:
        raise ValueError("A private verified input and transaction are required")
    require_read_committed(c)
    old = verified._observed
    lock_bid(c, old.bid_id)
    assert_work_writable(c, old.bid_id)
    fetch(
        c,
        "SELECT id FROM design.drafts WHERE bid_id=%s AND id=%s FOR UPDATE",
        (old.bid_id, old.request()["target_section"]["draft_id"]),
    )
    lock_graph(c)
    ids = sorted({row["id"] for row in old.context()["sources"]})
    c.execute(
        "SELECT source_id FROM retrieval.source_heads WHERE source_id=ANY(%s::uuid[]) ORDER BY source_id FOR UPDATE",
        (ids,),
    ).fetchall()
    fresh = capture(c, old.bid_id, old.request())
    same(old, fresh)
    return fresh
