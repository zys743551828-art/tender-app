"""Compare authoritative observations for selected facts; never a task/dispatch permit."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.package_fact_scope import SUBJECTS
from packages.domain.package_fact_scope import verify as verify_declaration
from packages.domain.package_fact_usage import SCHEMA as USAGE_SCHEMA
from packages.domain.package_fact_usage import SelectedPreparedFacts
from packages.domain.package_fact_validation import assess
from packages.domain.review_identity import canonical, digest, utc
from packages.identity.contracts import SNAPSHOT

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/selected-fact-admission.schema.json"
    ).read_text("utf-8")
)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _time(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(
        at.tzinfo is not None and at.utcoffset() is not None, "selected_fact_timezone_required"
    )
    return at


@dataclass(frozen=True, slots=True)
class SelectedFactAdmission:
    digest: str
    _manifest_text: str = field(repr=False)
    _usage: SelectedPreparedFacts = field(repr=False)
    _proof_text: str = field(repr=False)

    def view(self):
        return {"manifest": json.loads(self._manifest_text), "digest": self.digest}

    def selected_items(self):
        """Historical admitted projection; current use still requires a fresh recheck."""
        return self._usage.selected_items()


def admit(usage, current_identity, current_items, declarations, proofs, policy_digest, checked_at):
    view = usage.view()
    m = view["manifest"]
    chosen = usage.selected_items()
    authority = usage.prepared_authority()
    _require(
        Draft202012Validator(USAGE_SCHEMA, format_checker=FormatChecker()).is_valid(view),
        "selected_fact_usage_contract",
    )
    _require(
        view["digest"] == digest(m) and digest(chosen) == m["selected_facts_digest"],
        "selected_fact_usage_digest",
    )
    refs = [{"fact_id": x["fact"]["id"], "fact_item_digest": digest(x)} for x in chosen]
    _require(refs == m["selected"], "selected_fact_projection_mismatch")
    _require(
        all(
            authority["binding"][key] == m["prepared"][key]
            for key in ("bid_id", "package_id", "revision_id", "inventory_id", "frozen_input_id")
        )
        and authority["binding"]["identity_digest"] == m["identity_digest"],
        "selected_fact_original_authority",
    )
    ids = {x["fact_id"] for x in refs}
    _require(
        set(current_items) == set(declarations) == set(proofs) == ids,
        "selected_fact_observation_scope",
    )
    _require(checked_at == utc(checked_at), "selected_fact_observation_time")
    at = _time(checked_at)
    if ids:
        _require(
            Draft202012Validator(SNAPSHOT, format_checker=FormatChecker()).is_valid(
                current_identity
            ),
            "selected_fact_subject_unproven",
        )
        _require(
            current_identity["binding_status"] == "confirmed"
            and current_identity["digest"]
            == m["identity_digest"]
            == digest({k: v for k, v in current_identity.items() if k != "digest"}),
            "selected_fact_subject_changed",
        )
    admitted = []
    private = []
    for ref in refs:
        fact_id = ref["fact_id"]
        item = current_items[fact_id]
        proof = proofs[fact_id]
        _require(digest(item) == ref["fact_item_digest"], "selected_fact_changed")
        _require(
            item["fact"]["bid_id"] == m["prepared"]["bid_id"]
            and item["fact"]["fact_set_id"] == authority["fact_set_id"],
            "selected_fact_current_scope",
        )
        _require(
            assess(item, proof)["provenance_status"] == "verified",
            "selected_fact_provenance_unproven",
        )
        _require(
            item["decision"]
            and item["decision"].get("created_at")
            and _time(item["decision"]["created_at"]) <= at,
            "selected_fact_decision_not_known",
        )
        head = declarations[fact_id]
        _require(head is not None, "selected_fact_scope_required")
        declaration = verify_declaration(head)["manifest"]
        _require(
            declaration["action"] == "bind" and _time(declaration["recorded_at"]) <= at,
            "selected_fact_scope_not_active",
        )
        expected = {
            **authority["binding"],
            "execution_input_id": m["prepared"]["execution_input_id"],
            "execution_input_digest": m["prepared"]["execution_input_digest"],
            "facts_digest": authority["facts_digest"],
            "fact_set_id": authority["fact_set_id"],
            "fact_id": fact_id,
            "fact_item_digest": ref["fact_item_digest"],
            "proof_digest": digest(proof),
        }
        _require(declaration["binding"] == expected, "selected_fact_scope_binding_changed")
        subject = declaration["subject"]
        _require(
            subject["id"] == current_identity[SUBJECTS[subject["kind"]]],
            "selected_fact_scope_subject_changed",
        )
        admitted.append(
            {
                "fact_id": fact_id,
                "declaration_id": declaration["id"],
                "declaration_digest": head["digest"],
            }
        )
        private.append(
            {
                "fact_id": fact_id,
                "fact_item_digest": ref["fact_item_digest"],
                "declaration": head,
                "proof": proof,
            }
        )
    state = {
        "authority": authority,
        "current_identity_digest": current_identity["digest"] if ids else None,
        "selected": private,
    }
    core = {
        "version": "selected-fact-admission/1",
        "kind": "selected_fact_admission_observation",
        "purpose": "prebid_compliance",
        "prepared": m["prepared"],
        "usage_digest": usage.digest,
        "selection_digest": m["selection_digest"],
        "selected_facts_digest": m["selected_facts_digest"],
        "identity_digest": m["identity_digest"],
        "selected_count": len(ids),
        "admission": "verified_for_selected_use" if ids else "not_used",
        "fact_declarations": admitted,
        "policy_digest": policy_digest,
        "proofs_digest": digest(state),
        "required_facts_assessment": "not_performed",
        "facts_qualified": bool(ids),
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    manifest = {
        **core,
        "checked_at": checked_at,
        "content_digest": digest({**core, "version": "selected-fact-admission-content/1"}),
    }
    _require(
        Draft202012Validator(
            {"$ref": "#/$defs/Manifest", "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
        ).is_valid(manifest),
        "selected_fact_admission_contract",
    )
    return SelectedFactAdmission(
        digest(manifest),
        canonical(manifest).decode("utf-8"),
        usage,
        canonical(state).decode("utf-8"),
    )
