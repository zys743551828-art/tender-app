"""Closed project directory summary; risk and score qualification remain explicitly unknown."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.contracts.bid_package_api import UUID
from packages.contracts.bid_package_api import object_schema as obj
from packages.domain.runtime import DomainError

PATH = "/api/v1/project-work-summaries"
COUNT = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
TIME = {"type": "string", "format": "date-time"}
SUMMARY = obj(
    {
        "bid_id": UUID,
        "phase": {"enum": ["preparation", "working", "submitted", "closed", "terminated"]},
        "archived_at": {"oneOf": [TIME, {"type": "null"}]},
        "package_counts": obj({"authority": COUNT, "bid": COUNT}),
        "head_members": obj({"total": COUNT, "parse_not_frozen": COUNT}),
        "next_action": obj(
            {
                "action": {
                    "enum": [
                        "view_history",
                        "assemble_packages",
                        "inspect_package_parses",
                        "choose_package_revision",
                    ]
                },
                "reason": {"type": "string", "minLength": 1, "maxLength": 200},
                "target_url": {
                    "type": "string",
                    "pattern": r"^/bids/[0-9a-f-]{36}/(packages|work-context)$",
                },
                "blocked": {"type": "boolean"},
            }
        ),
        "action_scope": {"const": "package_directory"},
        "risk_status": {"const": "not_evaluated"},
        "critical_risk_count": {"type": "null"},
        "other_risk_count": {"type": "null"},
        "prediction_status": {"const": "not_evaluated"},
        "predicted_score": {"type": "null"},
        "inventory_complete": {"const": False},
        "formal_scoring_eligible": {"const": False},
        "submission_eligible": {"const": False},
    }
)
SCHEMAS = {
    "ProjectWorkSummary": SUMMARY,
    "ProjectWorkSummaryBatch": obj(
        {
            "version": {"const": "project-work-summary/1"},
            "observed_at": TIME,
            "items": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ProjectWorkSummary"},
                "minItems": 1,
                "maxItems": 20,
            },
        }
    ),
}


def validate(name, value):
    schema = {**SCHEMAS[name], "components": {"schemas": SCHEMAS}}
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise DomainError("PROJECT_SUMMARY_CONTRACT_INVALID", "项目摘要未通过完整协议核验", 500)


def extend_openapi(document):
    if "get" not in document.get("paths", {}).get(PATH, {}):
        return
    document["components"]["schemas"].update(deepcopy(SCHEMAS))
    operation = document["paths"][PATH]["get"]
    operation["operationId"] = "readProjectWorkSummaries"
    operation["security"] = [{"SessionCookie": []}]
    operation["responses"] = {
        "200": {
            "description": "同一只读快照中的整包目录摘要，不授核查或评分资格",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ProjectWorkSummaryBatch"}
                }
            },
        },
        "default": {"$ref": "#/components/responses/DomainError"},
    }
