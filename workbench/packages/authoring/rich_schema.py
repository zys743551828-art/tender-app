"""Explicit opt-in build request for the closed RICH producer and pagination mode."""

from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from packages.authoring.structure_schema import SCHEMAS
from packages.domain.runtime import DomainError

BUILD = deepcopy(SCHEMAS["AuthoringStructuredBuildRequest"])
BUILD["properties"]["pagination_mode"] = {
    "enum": ["chapter_start_new_page", "continuous"],
    "description": "每章另起一页会增加物理页数；连续排版的章末页仍可能未知。",
}
BUILD["required"].append("pagination_mode")
BUILD["allOf"] = [
    {
        "if": {"properties": {"follow_up": {"const": "review"}}},
        "then": {"properties": {"formats": {"contains": {"const": "pdf"}}}},
    }
]


def validate_build(value):
    if (
        isinstance(value, dict)
        and value.get("follow_up") == "review"
        and isinstance(value.get("formats"), list)
        and "pdf" not in value.get("formats", [])
    ):
        raise DomainError("AUTHORING_FOLLOW_UP_REQUIRES_PDF", "后续核对须明确生成PDF正文", 422)
    if not Draft202012Validator(BUILD, format_checker=FormatChecker()).is_valid(value):
        raise DomainError("AUTHORING_RICH_BUILD_INVALID", "表图构建须明确双模板与章页排版模式", 422)
    return value
