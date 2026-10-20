"""Pure validation of a stored prepared snapshot; never current-state or dispatch authority."""

import json

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.package_review_execution_identity import verify as verify_identity
from packages.domain.package_review_identity import candidate, summary
from packages.domain.review_data import frozen_documents
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, sha


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_snapshot_key")
        result[key] = value
    return result


def _check(condition):
    if not condition:
        raise ValueError("execution_input_binding")


def consume(row, scope, frozen_id, input_id, packet):
    try:
        m = row["manifest"]
        _check(valid("PackageExecutionInputManifest", m) and digest(m) == row["digest"])
        _check(
            tuple(m[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id")) == scope
        )
        _check(m["id"] == input_id and m["frozen_input_id"] == frozen_id)
        _check(row["snapshot_digest"] == m["snapshot_digest"] == sha(row["snapshot_text"].encode()))
        s = json.loads(row["snapshot_text"], object_pairs_hook=_pairs)
        _check(s["version"] == "package-review-prepared-snapshot/1")
        frozen = packet.view()["manifest"]
        root = packet.evidence()
        _check(valid("PackageReviewEligibilityObservation", s["result"]))
        _check(
            s["result"]["frozen_input_id"] == frozen_id
            and s["result"]["frozen_digest"] == packet.digest
        )
        _check(s["result"]["input_digest"] == frozen["input_digest"])
        _check(frozen_documents(s["documents"]) == root["documents"])
        context = s["context"]
        cm = context["manifest"]
        _check(
            context
            == candidate(
                packet.evidence()["selection"],
                cm["facts"],
                cm["sources"],
                cm["method"],
                cm["policy"],
                cm["as_of"],
            )
        )
        _check(summary(context) == m["execution_context"] == s["result"]["current_context"])
        identity = verify_identity(m["identity"])
        b = identity["binding"]
        _check(b == s["binding"])
        _check(b["identity_digest"] == root["selection"]["target"]["identity"]["digest"])
        _check(s["observations"]["sources"] == cm["sources"])
        _check(s["result"]["checked_at"] == cm["as_of"])
        _check(
            all(
                b[k] == m[k]
                for k in ("bid_id", "package_id", "revision_id", "inventory_id", "frozen_input_id")
            )
        )
        _check(all(b[k] == frozen[k] for k in ("input_digest", "evidence_digest")))
        _check(
            b["frozen_digest"] == packet.digest
            and b["context_digest"] == context["semantic_digest"]
        )
        _check(
            b["method_digest"] == cm["method_digest"]
            and b["policy_digest"] == cm["policy_digest"]
            and b["purpose"] == cm["purpose"]
        )
        _check(
            m["blockers"] == s["result"]["blockers"]
            and m["originals_verified_at"] == s["result"]["checked_at"]
        )
    except (AssertionError, ValueError, KeyError, TypeError) as error:
        raise DomainError(
            "PACKAGE_EXECUTION_INPUT_CORRUPT", "执行输入完整性校验失败", 500
        ) from error
    return {"manifest": m, "digest": row["digest"]}
