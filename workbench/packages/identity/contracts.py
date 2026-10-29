"""Actual identity selection operations; the reviewed target snapshot stays immutable."""

import json
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.runtime import ROOT, DomainError

ID = {"type": "string", "format": "uuid"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 1000, "pattern": r"\S"}


def obj(properties, required=None):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties) if required is None else required,
    }


SCHEMAS = {
    "CreateBid": deepcopy(
        json.loads(
            (ROOT / "packages/contracts/schemas/protocol.schema.json").read_text(encoding="utf-8")
        )["$defs"]["CreateBid"]
    ),
    "RegisterBidder": obj(
        {"name": TEXT | {"maxLength": 300}, "reason": TEXT, "set_as_default": {"type": "boolean"}},
        ["name", "reason"],
    ),
    "SelectDefaultBidder": obj({"bidder_id": ID}),
    "CorrectBidIdentity": obj(
        {"bidder_id": ID, "round_id": ID, "lot_id": ID, "reason": TEXT}, ["bidder_id", "reason"]
    ),
    "RegisterEngineering": obj(
        {
            "title": TEXT | {"maxLength": 200},
            "region": TEXT,
            "engineering_type": TEXT,
            "reason": TEXT,
        },
        ["title", "reason"],
    ),
    "RegisterLot": obj(
        {"engineering_project_id": ID, "label": TEXT | {"maxLength": 200}, "reason": TEXT}
    ),
    "RegisterRound": obj(
        {
            "engineering_project_id": ID,
            "lot_id": ID,
            "round_no": {"type": "integer", "minimum": 1, "maximum": 2147483647},
            "reason": TEXT,
        },
        ["engineering_project_id", "lot_id", "reason"],
    ),
}
SCHEMAS["CreateBid"]["properties"]["lot_id"] = ID
SCHEMAS["CreateBid"]["properties"]["lot"] = TEXT | {"maxLength": 200}

NULLTEXT = {"type": ["string", "null"]}
NULLID = {"type": ["string", "null"], "format": "uuid"}
BIDDER = obj(
    {
        "id": ID,
        "name": {"type": "string"},
        "registered": {"type": "boolean"},
        "registration_id": NULLID,
    }
)
SNAPSHOT = obj(
    {
        "bidder_id": ID,
        "bidder_name": {"type": "string"},
        "round_id": ID,
        "engineering_project_id": ID,
        "engineering_title": {"type": "string"},
        "region": NULLTEXT,
        "engineering_type": NULLTEXT,
        "lot": NULLTEXT,
        "lot_id": NULLID,
        "round_no": {"type": "integer", "minimum": 1},
        "binding_status": {"enum": ["confirmed", "pending"]},
        "authority_id": NULLID,
        "digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "identity_version": {"const": "bid-identity/2"},
    }
)
LEGACY_SNAPSHOT = deepcopy(SNAPSHOT)
for _field in ("lot_id", "identity_version"):
    LEGACY_SNAPSHOT["properties"].pop(_field)
    LEGACY_SNAPSHOT["required"].remove(_field)
LEGACY_SNAPSHOT["properties"]["identity_version"] = {"const": "bid-identity/1"}
SNAPSHOT["allOf"] = [
    {
        "if": {"properties": {"binding_status": {"const": "confirmed"}}},
        "then": {"properties": {"lot_id": ID, "authority_id": ID}},
    }
]
HISTORICAL_SNAPSHOT = {"oneOf": [LEGACY_SNAPSHOT, SNAPSHOT]}
IMPACT = obj(
    {
        key: {"type": "integer", "minimum": 0}
        for key in [
            "reviews",
            "submissions",
            "outcomes",
            "samples",
            "drafts",
            "documents",
            "facts",
            "knowledge_citations",
        ]
    }
)
DEFAULT_VIEW = obj({"bidder": {"anyOf": [BIDDER, {"type": "null"}]}, "authority_id": NULLID})
ENGINEERING = obj(
    {"id": ID, "title": {"type": "string"}, "region": NULLTEXT, "engineering_type": NULLTEXT}
)
ROUND = obj(
    {
        "id": ID,
        "engineering_project_id": ID,
        "lot": NULLTEXT,
        "lot_id": NULLID,
        "round_no": {"type": "integer", "minimum": 1},
        "engineering_title": {"type": "string"},
        "region": NULLTEXT,
        "engineering_type": NULLTEXT,
    }
)
LOT = obj({"id": ID, "engineering_project_id": ID, "label": {"type": "string"}})


def page(item):
    return obj(
        {
            "items": {"type": "array", "items": item},
            "has_more": {"type": "boolean"},
            "next_cursor": {"type": ["string", "null"]},
        }
    )


SCHEMAS.update(
    {
        "BiddingCompanyView": BIDDER,
        "BidIdentitySnapshot": SNAPSHOT,
        "HistoricalBidIdentitySnapshot": HISTORICAL_SNAPSHOT,
        "IdentityImpact": IMPACT,
        "DefaultBiddingCompanyView": DEFAULT_VIEW,
        "BiddingCompanyPage": page(BIDDER),
        "EngineeringIdentityPage": page(ENGINEERING),
        "EngineeringRoundPage": page(ROUND),
        "EngineeringIdentity": ENGINEERING,
        "EngineeringLot": LOT,
        "EngineeringLotPage": page(LOT),
        "EngineeringRound": ROUND,
        "BidIdentityView": obj({"identity": SNAPSHOT, "affected": IMPACT}),
        "BidIdentityCorrection": obj(
            {
                "identity": SNAPSHOT,
                "affected": IMPACT,
                "historical_records_rewritten": {"const": False},
                "qualification_recheck_required": {"const": True},
            }
        ),
        "RegisteredBiddingCompanyView": obj(
            {"bidder": BIDDER, "default": DEFAULT_VIEW, "qualification_verified": {"const": False}}
        ),
    }
)


def validate(name, value):
    errors = list(
        Draft202012Validator(SCHEMAS[name], format_checker=FormatChecker()).iter_errors(value)
    )
    if errors:
        raise DomainError(
            "INVALID_REQUEST",
            "请完整填写真实身份及选择依据",
            422,
            {"fields": [".".join(map(str, e.absolute_path)) for e in errors]},
        )


def extend_openapi(actual):
    actual["components"]["schemas"].update(deepcopy(SCHEMAS))
    bid = actual["components"]["schemas"].get("Bid")
    if bid is not None:
        bid["properties"]["identity"] = {"$ref": "#/components/schemas/BidIdentitySnapshot"}
        if "identity" not in bid["required"]:
            bid["required"].append("identity")
    operations = {
        ("/identity/bidders", "get"): ("listBiddingCompanies", None),
        ("/identity/bidders", "post"): ("registerBiddingCompany", "RegisterBidder"),
        ("/identity/default-bidder", "get"): ("getDefaultBiddingCompany", None),
        ("/identity/default-bidder", "put"): ("selectDefaultBiddingCompany", "SelectDefaultBidder"),
        ("/identity/engineering-projects", "get"): ("listEngineeringProjects", None),
        ("/identity/engineering-projects", "post"): (
            "registerEngineeringProject",
            "RegisterEngineering",
        ),
        ("/identity/lots", "get"): ("listEngineeringLots", None),
        ("/identity/lots", "post"): ("registerEngineeringLot", "RegisterLot"),
        ("/identity/rounds", "get"): ("listEngineeringRounds", None),
        ("/identity/rounds", "post"): ("registerEngineeringRound", "RegisterRound"),
        ("/bids/{bid_id}/identity", "get"): ("getBidIdentity", None),
        ("/bids/{bid_id}/identity", "put"): ("correctBidIdentity", "CorrectBidIdentity"),
    }
    responses = {
        "listBiddingCompanies": "BiddingCompanyPage",
        "registerBiddingCompany": "RegisteredBiddingCompanyView",
        "getDefaultBiddingCompany": "DefaultBiddingCompanyView",
        "selectDefaultBiddingCompany": "DefaultBiddingCompanyView",
        "listEngineeringProjects": "EngineeringIdentityPage",
        "registerEngineeringProject": "EngineeringIdentity",
        "listEngineeringLots": "EngineeringLotPage",
        "registerEngineeringLot": "EngineeringLot",
        "listEngineeringRounds": "EngineeringRoundPage",
        "registerEngineeringRound": "EngineeringRound",
        "getBidIdentity": "BidIdentityView",
        "correctBidIdentity": "BidIdentityCorrection",
    }
    for (path, method), (operation_id, schema) in operations.items():
        op = actual["paths"].get("/api/v1" + path, {}).get(method)
        if op is None:
            continue
        op["operationId"] = operation_id
        op["security"] = [{"SessionCookie": []}]
        if schema:
            op["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + schema}}
                },
            }
            op.setdefault("parameters", []).extend(
                [
                    {
                        "in": "header",
                        "name": "Idempotency-Key",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "in": "header",
                        "name": "X-CSRF-Token",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "in": "header",
                        "name": "Origin",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ]
            )
            if method == "put":
                op["parameters"].append(
                    {
                        "in": "header",
                        "name": "If-Match",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                )
        op["responses"] = {
            "201"
            if operation_id
            in {
                "registerBiddingCompany",
                "registerEngineeringProject",
                "registerEngineeringLot",
                "registerEngineeringRound",
            }
            else "200": {
                "description": "实际身份选择结果",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/" + responses[operation_id]}
                    }
                },
            },
            "default": {"$ref": "#/components/responses/DomainError"},
        }
