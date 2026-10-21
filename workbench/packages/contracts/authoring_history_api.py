"""Closed, opt-in exact historical chapter read; no restoration permission."""

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from packages.authoring import contracts as text_contracts
from packages.authoring import rich_contracts
from packages.domain.runtime import DomainError

PATH = "/api/v1/bids/{bid_id}/drafts/{draft_id}/sections/{section_id}/revisions/{revision}"
UUID = {"type": "string", "format": "uuid"}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
REV = {"type": "integer", "minimum": 1}
TIME = {"type": "string", "format": "date-time"}


def obj(properties):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def content_schemas():
    """Reuse actual closed rich/text definitions under independent read names."""
    document: dict[str, Any] = {
        "paths": {"/api/v1/authoring/rich-capabilities": {}},
        "components": {
            "schemas": {
                name: obj({})
                for name in (
                    "BuildRequest",
                    "BuildView",
                    "SectionChange",
                    "SectionView",
                    "DraftSaved",
                )
            }
        },
    }
    text_contracts.extend_openapi(document)
    rich_contracts.extend_openapi(document)
    available, selected = document["components"]["schemas"], {}

    def collect(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].split("/")[-1]
                if name not in selected:
                    selected[name] = deepcopy(available[name])
                    collect(selected[name])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(ref("AuthoringRichDocument"))

    def rename(value):
        if isinstance(value, dict):
            return {
                key: "#/components/schemas/AuthoringHistory" + item.split("/")[-1]
                if key == "$ref"
                else rename(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [rename(item) for item in value]
        return value

    return {"AuthoringHistory" + name: rename(value) for name, value in selected.items()}


IMAGE = obj(
    {
        "asset_id": UUID,
        "asset_revision": REV,
        "asset_version_id": UUID,
        "version_digest": SHA,
        "normalized_sha256": SHA,
        "media_type": {"const": "image/png"},
    }
)
VIEW = obj(
    {
        "version": {"const": "authoring-historical-section/1"},
        "bid_id": UUID,
        "draft_id": UUID,
        "section_id": UUID,
        "section_revision_id": UUID,
        "revision": REV,
        "schema_digest": SHA,
        "digest": SHA,
        "content": ref("AuthoringHistoryAuthoringRichDocument"),
        "created_by": UUID,
        "created_at": TIME,
        "images": {"type": "array", "items": IMAGE, "maxItems": 10000},
        "read_only": {"const": True},
        "source_qualification_assessed": {"const": False},
        "restoration_authorized": {"const": False},
    }
)
SCHEMAS = content_schemas() | {"AuthoringHistoricalSectionView": VIEW}
VALIDATOR = Draft202012Validator(
    {
        "$ref": "#/components/schemas/AuthoringHistoricalSectionView",
        "components": {"schemas": SCHEMAS},
    },
    format_checker=FormatChecker(),
)


def checked(value):
    if not VALIDATOR.is_valid(value):
        raise DomainError("AUTHORING_HISTORY_CORRUPT", "历史章节的完整身份或只读正文不能核验", 500)
    return value


def extend_openapi(document):
    if PATH not in document["paths"]:
        return
    document.setdefault("components", {}).setdefault("schemas", {}).update(deepcopy(SCHEMAS))
    operation = document["paths"][PATH]["get"]
    operation.update(
        operationId="getExactHistoricalAuthoringSection",
        security=[{"SessionCookie": []}],
        summary="按项目、草稿、章节、原修订及预期正文摘要读取完整历史正文",
    )
    operation["responses"]["200"] = {
        "description": "历史读取不授予当前来源使用或恢复权限；无当前头替代",
        "content": {"application/json": {"schema": ref("AuthoringHistoricalSectionView")}},
    }
