"""Closed metadata-only directories; availability and current qualification are distinct."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.contracts.package_historical_research_api import PROTOCOL
from packages.domain.runtime import DomainError

BASE = "/api/v1/package-historical-research"
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "format": "date-time"}
NULL = {"type": "null"}
ORIGIN = {"enum": ["synthetic", "external_evidence"]}


def optional(schema):
    return {"anyOf": [deepcopy(schema), NULL]}


FILTERS = obj(dict.fromkeys(("bid_id", "scope_id", "protocol_id", "cohort_id"), optional(UUID)))
ITEM = {
    "id": UUID,
    "created_at": TIME,
    "current_status": {"const": "not_rechecked"},
}
ITEMS = {
    "admissions": obj(
        ITEM
        | {
            "kind": {"const": "admission"},
            **dict.fromkeys(("bid_id", "scope_id", "submission_id", "outcome_id"), UUID),
            "digest": SHA,
            "origin": ORIGIN,
            "state": {"enum": ["mechanism_candidate", "retrospective_candidate"]},
            "historical_as_of": TIME,
            "label_known_at": TIME,
        }
    ),
    "protocols": obj(
        ITEM | {"kind": {"const": "protocol"}, "digest": SHA, "document": deepcopy(PROTOCOL)}
    ),
    "cohorts": obj(
        ITEM
        | {
            "kind": {"const": "cohort"},
            "protocol_id": UUID,
            "digest": SHA,
            "membership_digest": SHA,
            "origin": ORIGIN,
            "submission_split_at": TIME,
            "label_available_as_of": TIME,
            "member_count": {"type": "integer", "minimum": 4, "maximum": 1000},
        }
    ),
    "jobs": obj(
        ITEM
        | {
            "kind": {"const": "job"},
            "cohort_id": UUID,
            "job_kind": {"enum": ["train", "evaluate"]},
            "state": {"enum": ["queued", "running", "paused", "succeeded", "failed", "cancelled"]},
            "generation": {"type": "integer", "minimum": 1},
            "result_available": {"type": "boolean"},
            "result_digest": optional(SHA),
        }
    ),
}
NAMES = {
    "admissions": "PackageHistoryAdmissionDirectory",
    "protocols": "PackageHistoryProtocolDirectory",
    "cohorts": "PackageHistoryCohortDirectory",
    "jobs": "PackageHistoryJobDirectory",
}
COMMON = {
    "version": {"const": "package-history-directory/1"},
    "filters": FILTERS,
    "observed_at": TIME,
    "currentness_rechecked": {"const": False},
    "research_only": {"const": True},
    "formal_eligibility": {"const": "unavailable"},
    "qualification_granted": {"const": False},
}
SCHEMAS = {}
for kind, name in NAMES.items():
    common = COMMON | {"kind": {"const": kind}}
    SCHEMAS[name] = {
        "oneOf": [
            obj(
                common
                | {
                    "status": {"const": "observed"},
                    "schema_configured": {"const": True},
                    "items": {"type": "array", "maxItems": 50, "items": ITEMS[kind]},
                    "total": {"type": "integer", "minimum": 0, "maximum": 2000},
                    "observation_digest": SHA,
                    "complete_observation": {"const": True},
                    "has_more": {"type": "boolean"},
                    "next_cursor": optional({"type": "string", "minLength": 1, "maxLength": 4096}),
                }
            ),
            obj(
                common
                | {
                    "status": {"const": "unavailable"},
                    "schema_configured": {"const": False},
                    "items": {"type": "array", "maxItems": 0},
                    "total": NULL,
                    "observation_digest": NULL,
                    "complete_observation": {"const": False},
                    "has_more": NULL,
                    "next_cursor": NULL,
                }
            ),
        ]
    }


def validate(kind, value):
    if kind not in NAMES or not Draft202012Validator(
        SCHEMAS[NAMES[kind]], format_checker=FormatChecker()
    ).is_valid(value):
        raise DomainError("PACKAGE_HISTORY_DIRECTORY_INVALID", "历史研究目录不能核验", 500)
    return value


def extend_openapi(document):
    routes = (
        (BASE + "/admissions", "admissions"),
        (BASE + "/protocols", "protocols"),
        (BASE + "/cohorts", "cohorts"),
        (BASE + "/cohorts/{cohort_id}/jobs", "jobs"),
    )
    for path, kind in routes:
        operation = document["paths"].get(path, {}).get("get")
        if operation is None:
            continue
        name = NAMES[kind]
        document["components"]["schemas"][name] = deepcopy(SCHEMAS[name])
        operation["operationId"] = "listPackageHistory" + kind.title()
        operation["security"] = [{"SessionCookie": []}]
        operation["responses"] = {
            "200": {
                "description": "明确可用性与原生身份的只读目录；当前资格未重新检查",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + name}}
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
