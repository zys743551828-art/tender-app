"""Pure whole-package task identity; references are not evidence or launch permission."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.review_identity import digest

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "contracts/schemas/package-review-execution.schema.json"
    ).read_text(encoding="utf-8")
)


def _validate(name: str, value: Any):
    schema = {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value):
        raise ValueError("package_execution_identity_contract")


def identify(binding: dict[str, Any], rerun: dict[str, Any] | None = None) -> dict[str, Any]:
    _validate("Binding", binding)
    if rerun is not None:
        _validate("RerunIntent", rerun)
        if rerun["reason"] != rerun["reason"].strip():
            raise ValueError("package_execution_rerun_reason_whitespace")
    content = {"version": "package-review-content/1", "binding": deepcopy(binding)}
    content_digest = digest(content)
    execution = {
        "version": "package-review-execution/1",
        "content_digest": content_digest,
        "rerun": deepcopy(rerun),
    }
    return {
        "version": execution["version"],
        "kind": "identity",
        "binding": content["binding"],
        "rerun": execution["rerun"],
        "content_digest": content_digest,
        "execution_digest": digest(execution),
    }


def verify(value: dict[str, Any]) -> dict[str, Any]:
    _validate("Identity", value)
    rebuilt = identify(value["binding"], value["rerun"])
    if rebuilt != value:
        raise ValueError("package_execution_identity_digest")
    return rebuilt
