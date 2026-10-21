"""Closed discovery projections; observations never confer authoring admission."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.assistant.intent_identity import IDENTITY_FACTS
from packages.contracts.authoring_history_api import content_schemas
from packages.domain.runtime import DomainError

BASE = "/api/v1/bids/{bid_id}/authoring/input-catalog"
NODES_PATH = BASE + "/draft-snapshots/{snapshot_id}/sections/{section_id}/nodes"
SETS_PATH = BASE + "/fact-sets"
FACTS_PATH = SETS_PATH + "/{fact_set_id}/facts"
UUID = {"type": "string", "format": "uuid"}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
REV = {"type": "integer", "minimum": 1}
TIME = {"type": "string", "format": "date-time"}
TEXT = {"type": "string"}
BOOL = {"type": "boolean"}


def obj(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def arr(item, maximum):
    return {"type": "array", "items": item, "maxItems": maximum}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def nullable(value):
    return {"oneOf": [value, {"type": "null"}]}


FLAGS = {
    "observation_only": {"const": True},
    "admission_granted": {"const": False},
    "original_bytes_reverified": {"const": False},
    "save_recheck_required": {"const": True},
    "formal_decisions_allowed": {"const": False},
}
ENVELOPE = {"observed_at": TIME, "observation_digest": SHA, **FLAGS}
BLOCKERS = arr({"type": "string", "minLength": 1, "maxLength": 200}, 50)
PAGE = {
    "next_cursor": nullable({"type": "string", "minLength": 1, "maxLength": 4096}),
    "has_more": BOOL,
    "total_items": {"type": "integer", "minimum": 0, "maximum": 1000},
}
PACKAGE = obj({"package_id": UUID, "revision_id": UUID, "manifest_digest": SHA})
SUBJECT = obj({"kind": {"enum": ["engineering_project", "lot", "round", "bidder"]}, "id": UUID})
HEAD = obj({"fact_set_id": UUID, "revision": REV, "fact_set_digest": SHA})
TARGET = obj(
    {
        "draft_id": UUID,
        "snapshot_id": UUID,
        "snapshot_digest": SHA,
        "base_draft_revision": REV,
        "section_id": UUID,
        "section_revision_id": UUID,
        "base_section_revision": REV,
        "section_digest": SHA,
        "schema_digest": SHA,
    }
)
NODE = obj(
    {
        "node_id": {"type": "string", "minLength": 1, "maxLength": 200},
        "before_node_digest": SHA,
        "node_type": {"enum": ["paragraph", "heading"]},
        "text": TEXT,
    }
)
NODES = obj(
    {
        "protocol": {"const": "package-authoring-node-catalog/1"},
        "bid_id": UUID,
        "target": TARGET,
        "section_title": {"type": "string", "minLength": 1, "maxLength": 200},
        "section_content": ref("AuthoringHistoryAuthoringRichDocument"),
        "nodes": arr(NODE, 10000),
        "unsupported_stable_node_count": {"type": "integer", "minimum": 0},
        "current_draft_revision": REV,
        "section_heads": arr(
            obj({"section_id": UUID, "selected_revision": REV, "head_revision": REV}), 500
        ),
        "whole_snapshot_plain": BOOL,
        "structure_supported": BOOL,
        "blocking_reasons": BLOCKERS,
        **ENVELOPE,
    }
)
SET_ITEM = obj(
    {
        "fact_set_id": UUID,
        "fact_set_digest": SHA,
        "fact_count": {"type": "integer", "minimum": 0},
        "is_current": BOOL,
    }
)
SETS = obj(
    {
        "protocol": {"const": "package-authoring-fact-set-page/1"},
        "bid_id": UUID,
        "items": arr(SET_ITEM, 50),
        "current_head": nullable(HEAD),
        "blocking_reasons": BLOCKERS,
        **PAGE,
        **ENVELOPE,
    }
)
EVIDENCE = obj(
    {
        "id": UUID,
        "parse_id": UUID,
        "document_version_id": UUID,
        "physical_page": REV,
        "digest": SHA,
    }
)
DECISION = obj(
    {
        "id": UUID,
        "decision": {"enum": ["confirmed", "rejected"]},
        "decision_revision": REV,
        "object_id": UUID,
        "actor_id": UUID,
        "created_at": TIME,
        "binding_verified": BOOL,
        "basis_verified": BOOL,
        "carryover_steps": {"type": "integer", "minimum": 0},
    }
)
FACT_ITEM = obj(
    {
        "fact_id": UUID,
        "fact_item_digest": SHA,
        "proof_digest": SHA,
        "name": TEXT,
        "subject_text": TEXT,
        "scope_text": TEXT,
        "value_jsonb_text": TEXT,
        "unit": nullable(TEXT),
        "identity_name": nullable({"enum": list(IDENTITY_FACTS)}),
        "identity_value_usable": BOOL,
        "decision": nullable(DECISION),
        "evidence": arr(EVIDENCE, 10000),
        "provenance_status": {"enum": ["verified", "unproven"]},
        "scope_binding": {"enum": ["selected_frozen_parse", "unproven"]},
        "facts_qualified": {"const": False},
        "blocking_reasons": BLOCKERS,
    }
)
FACTS = obj(
    {
        "protocol": {"const": "package-authoring-fact-catalog/1"},
        "bid_id": UUID,
        "selection": obj(
            {
                "fact_set_id": UUID,
                "fact_set_digest": SHA,
                "fact_head_revision": REV,
                "target": PACKAGE,
                "authority": PACKAGE,
            }
        ),
        "current_head": nullable(HEAD),
        "head_matches": BOOL,
        "package_identity_matches": BOOL,
        "subject_choices": arr(SUBJECT, 4),
        "identity_names": {"const": list(IDENTITY_FACTS)},
        "items": arr(FACT_ITEM, 50),
        "blocking_reasons": BLOCKERS,
        **PAGE,
        **ENVELOPE,
    }
)
SCHEMAS = content_schemas() | {
    "PackageAuthoringNodeCatalog": NODES,
    "PackageAuthoringFactSetPage": SETS,
    "PackageAuthoringFactCatalog": FACTS,
}
ROOTS = {
    NODES_PATH: ("PackageAuthoringNodeCatalog", "getPackageAuthoringStableNodes"),
    SETS_PATH: ("PackageAuthoringFactSetPage", "listPackageAuthoringFactSets"),
    FACTS_PATH: ("PackageAuthoringFactCatalog", "listPackageAuthoringExactFacts"),
}


def checked(name, value):
    validator = Draft202012Validator(
        {"$ref": "#/components/schemas/" + name, "components": {"schemas": SCHEMAS}},
        format_checker=FormatChecker(),
    )
    if not validator.is_valid(value):
        raise DomainError(
            "AUTHORING_INPUT_CATALOG_CORRUPT", "采集目录的精确身份或观察不能核验", 500
        )
    return value


def extend_openapi(document):
    if not set(ROOTS) & set(document["paths"]):
        return
    document.setdefault("components", {}).setdefault("schemas", {}).update(deepcopy(SCHEMAS))
    for path, (name, operation_id) in ROOTS.items():
        if path not in document["paths"]:
            continue
        operation = document["paths"][path]["get"]
        operation.update(operationId=operation_id, security=[{"SessionCookie": []}])
        operation["responses"]["200"] = {
            "description": "只读精确观察；不选最新头，不授予准入，显式保存仍需完整重核",
            "content": {"application/json": {"schema": ref(name)}},
        }
