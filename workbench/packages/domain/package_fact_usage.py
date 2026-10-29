"""Explicit fact-use projection from one prepared input, without qualification or dispatch.

An empty selection is valid. It means no project/company facts were selected, not
that requirements need no facts. Workers must receive only the selected projection.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.review_identity import canonical, digest

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/schemas/package-fact-usage.schema.json"
    ).read_text("utf-8")
)


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _validate(name, value):
    _require(
        Draft202012Validator(
            {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
        ).is_valid(value),
        "fact_usage_contract",
    )


@dataclass(frozen=True, slots=True)
class SelectedPreparedFacts:
    digest: str
    _manifest_text: str = field(repr=False)
    _items_text: str = field(repr=False)
    _authority_text: str = field(repr=False)

    def view(self):
        return {"manifest": json.loads(self._manifest_text), "digest": self.digest}

    def selected_items(self):
        """Private unqualified payload; every consumer receives only owned selected copies."""
        return json.loads(self._items_text)

    def prepared_authority(self):
        """Original binding metadata only; no unused fact values or current-state claims."""
        return json.loads(self._authority_text)


def select(packet, request):
    _validate("Request", request)
    public = packet.view()["manifest"]
    context = packet.snapshot()["context"]["manifest"]
    facts = context["facts"]
    summary = public["execution_context"]
    binding = public["identity"]["binding"]
    _require(
        tuple(binding[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id"))
        == packet.scope
        and binding["frozen_input_id"] == packet.frozen_id
        and public["id"] == packet.input_id,
        "fact_usage_prepared_scope",
    )
    _require(
        context["facts_digest"] == summary["facts_digest"] == digest(facts),
        "fact_usage_pool_digest",
    )
    _require(facts["head"]["fact_set_id"] == summary["fact_set_id"], "fact_usage_pool_identity")
    _require(
        context["identity"]["digest"] == binding["identity_digest"], "fact_usage_subject_identity"
    )
    pool = {item["fact"]["id"]: item for item in facts["items"]}
    _require(len(pool) == len(facts["items"]), "fact_usage_duplicate_pool")
    _require(summary["fact_count"] == len(pool), "fact_usage_pool_count")
    ids = sorted(request["fact_ids"])
    _require(all(fact_id in pool for fact_id in ids), "fact_usage_fact_not_in_prepared")
    chosen = [pool[fact_id] for fact_id in ids]
    _require(
        all(
            item["fact"]["bid_id"] == binding["bid_id"]
            and item["fact"]["fact_set_id"] == summary["fact_set_id"]
            for item in chosen
        ),
        "fact_usage_fact_scope",
    )
    selected = [
        {"fact_id": item["fact"]["id"], "fact_item_digest": digest(item)} for item in chosen
    ]
    semantic = {
        "version": "package-fact-usage-content/1",
        "purpose": request["purpose"],
        "scope": {
            key: binding[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
        },
        "identity_digest": binding["identity_digest"],
        "selected": selected,
    }
    manifest = {
        "version": "package-fact-usage/1",
        "kind": "fact_usage_selection",
        "purpose": request["purpose"],
        "prepared": {
            **semantic["scope"],
            "frozen_input_id": packet.frozen_id,
            "execution_input_id": packet.input_id,
            "execution_input_digest": packet.digest,
        },
        "identity_digest": binding["identity_digest"],
        "selected": selected,
        "selection_digest": digest(semantic),
        "selected_facts_digest": digest(chosen),
        "required_facts_assessment": "not_performed",
        "facts_qualified": False,
        "review_ready": False,
        "launch_available": False,
        "publication_authorized": False,
    }
    _validate("Manifest", manifest)
    return SelectedPreparedFacts(
        digest(manifest),
        canonical(manifest).decode("utf-8"),
        canonical(chosen).decode("utf-8"),
        canonical(
            {
                "binding": binding,
                "facts_digest": context["facts_digest"],
                "fact_set_id": summary["fact_set_id"],
            }
        ).decode("utf-8"),
    )


def verify(record, packet):
    _validate("View", record)
    m = record["manifest"]
    rebuilt = select(
        packet, {"purpose": m["purpose"], "fact_ids": [item["fact_id"] for item in m["selected"]]}
    )
    _require(rebuilt.view() == record, "fact_usage_record_binding")
    return rebuilt
