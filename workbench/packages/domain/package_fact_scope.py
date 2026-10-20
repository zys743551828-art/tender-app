"""Immutable explicit applicability declarations; no persistence or execution authority.

The caller supplies an already validated prepared packet and a fresh locked snapshot.
Provenance ports supply exact proof data; this module never infers scope from text.
"""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.bid_package_frozen_originals import assert_same
from packages.domain.package_fact_validation import assess
from packages.domain.review_identity import digest, utc
from packages.identity.contracts import SNAPSHOT

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/schemas/package-fact-scope.schema.json"
    ).read_text("utf-8")
)
SUBJECTS = {
    "engineering_project": "engineering_project_id",
    "lot": "lot_id",
    "round": "round_id",
    "bidder": "bidder_id",
}


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _validate(name, value):
    schema = {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}
    _require(
        Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value),
        "fact_scope_contract",
    )


def validate_change(value):
    _validate("Change", value)


def verify(record):
    """Verify record shape and digest only; history is never a current validity grant."""
    _validate("Record", record)
    manifest = record["manifest"]
    _require(manifest["recorded_at"] == utc(manifest["recorded_at"]), "fact_scope_timestamp")
    _require(manifest["reason"] == manifest["reason"].strip(), "fact_scope_reason")
    _require(record["digest"] == digest(manifest), "fact_scope_digest")
    return deepcopy(record)


def _reference(packet, current, fact_id, proof, subject):
    # Compare every saved observation and private document, not just a caller's digest.
    prepared = packet.snapshot()
    assert_same({k: v for k, v in prepared.items() if k != "version"}, current)
    manifest = packet.view()["manifest"]
    binding = manifest["identity"]["binding"]
    context = current["context"]
    cm = context["manifest"]
    _require(
        context["semantic_digest"]
        == binding["context_digest"]
        == digest({k: v for k, v in cm.items() if k != "as_of"}),
        "fact_scope_context",
    )
    identity = cm["identity"]
    _require(
        Draft202012Validator(SNAPSHOT, format_checker=FormatChecker()).is_valid(identity)
        and identity["binding_status"] == "confirmed"
        and identity["digest"]
        == binding["identity_digest"]
        == digest({k: v for k, v in identity.items() if k != "digest"}),
        "fact_scope_identity",
    )
    _validate("Subject", subject)
    _require(subject["id"] == identity[SUBJECTS[subject["kind"]]], "fact_scope_subject")
    facts = cm["facts"]
    _require(cm["facts_digest"] == digest(facts), "fact_scope_facts")
    items = facts["items"]
    _require(len({x["fact"]["id"] for x in items}) == len(items), "fact_scope_duplicate_fact")
    selected = [x for x in items if x["fact"]["id"] == fact_id]
    _require(len(selected) == 1, "fact_scope_fact_not_found")
    item = selected[0]
    _require(
        item["fact"]["bid_id"] == binding["bid_id"]
        and item["fact"]["fact_set_id"] == facts["head"]["fact_set_id"],
        "fact_scope_fact_binding",
    )
    _require(assess(item, proof)["provenance_status"] == "verified", "fact_scope_provenance")
    return {
        **binding,
        "execution_input_id": packet.input_id,
        "execution_input_digest": packet.digest,
        "facts_digest": cm["facts_digest"],
        "fact_set_id": facts["head"]["fact_set_id"],
        "fact_id": fact_id,
        "fact_item_digest": digest(item),
        "proof_digest": digest(proof),
    }


def _record(
    binding, subject, action, previous, record_id, actor_id, command_id, recorded_at, reason
):
    manifest = {
        "version": "package-fact-scope/1",
        "kind": "fact_scope_declaration",
        "id": record_id,
        "actor_id": actor_id,
        "command_id": command_id,
        "recorded_at": recorded_at,
        "reason": reason,
        "action": action,
        "previous_digest": previous,
        "binding": deepcopy(binding),
        "subject": deepcopy(subject),
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    return verify({"manifest": manifest, "digest": digest(manifest)})


def declare(packet, current, fact_id, proof, subject, *, previous=None, **audit):
    binding = _reference(packet, current, fact_id, proof, subject)
    if previous is not None:
        previous = verify(previous)
        _require(previous["manifest"]["binding"] == binding, "fact_scope_predecessor")
        _require(previous["manifest"]["id"] != audit["record_id"], "fact_scope_record_reuse")
    return _record(binding, subject, "bind", previous["digest"] if previous else None, **audit)


def withdraw(previous, **audit):
    """Withdrawal must remain possible after source or fact invalidation."""
    previous = verify(previous)
    m = previous["manifest"]
    _require(m["action"] == "bind", "fact_scope_already_withdrawn")
    _require(m["id"] != audit["record_id"], "fact_scope_record_reuse")
    return _record(m["binding"], m["subject"], "withdraw", previous["digest"], **audit)


def current_status(record, packet, current, fact_id, proof):
    """Reobserve authority explicitly; a stored bind alone never proves current scope."""
    record = verify(record)
    if record["manifest"]["action"] == "withdraw":
        return "withdrawn"
    expected = _reference(packet, current, fact_id, proof, record["manifest"]["subject"])
    _require(expected == record["manifest"]["binding"], "fact_scope_binding_changed")
    return "matches_current_input"
