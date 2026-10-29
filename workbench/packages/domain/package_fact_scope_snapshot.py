"""Persist actual proof metadata, not a later reconstruction from mutable source heads."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.package_fact_scope import verify
from packages.domain.review_data import effective_at
from packages.domain.review_identity import canonical, digest, utc
from packages.domain.runtime import DomainError, sha

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/package-fact-proof-snapshot.schema.json"
    ).read_text("utf-8")
)


def _require(condition):
    if not condition:
        raise ValueError("fact_proof_snapshot_binding")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_fact_proof_key")
        result[key] = value
    return result


def _validate(value):
    _require(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).is_valid(value))
    _require(value["observed_at"] == utc(value["observed_at"]))
    # This checks only the captured literal state at its recorded observation time.
    effective_at(value["proof"]["closure"], value["observed_at"])


def freeze(proof, observed_at):
    value = {"version": "package-fact-proof-snapshot/1", "observed_at": observed_at, "proof": proof}
    _validate(value)
    return canonical(value).decode("utf-8")


@dataclass(frozen=True, slots=True)
class ScopeDeclarationPacket:
    digest: str
    proof_snapshot_digest: str
    _view_text: str = field(repr=False)
    _proof_text: str = field(repr=False)

    def view(self):
        return json.loads(self._view_text)

    def proof(self):
        return json.loads(self._proof_text)["proof"]

    def snapshot_text(self):
        return self._proof_text


def consume(row):
    try:
        view = verify({"manifest": row["manifest"], "digest": row["digest"]})
        text = row["proof_text"]
        _require(sha(text.encode("utf-8")) == row["proof_snapshot_digest"])
        envelope = json.loads(text, object_pairs_hook=_pairs)
        _validate(envelope)
        _require(digest(envelope["proof"]) == view["manifest"]["binding"]["proof_digest"])
        if view["manifest"]["action"] == "bind":
            _require(envelope["observed_at"] == view["manifest"]["recorded_at"])
    except (ValueError, TypeError, KeyError, DomainError) as error:
        raise DomainError(
            "PACKAGE_FACT_SCOPE_CORRUPT", "已保存事实范围及实际依据快照完整性校验失败", 500
        ) from error
    return ScopeDeclarationPacket(
        row["digest"], row["proof_snapshot_digest"], canonical(view).decode("utf-8"), text
    )
