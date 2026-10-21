"""Publish only the schema dependencies of operations mounted in an app."""

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

PREFIX = "#/components/schemas/"


def schema_references(value: Any) -> set[str]:
    """Find component roots, including references to a nested schema pointer."""
    pending = [value]
    references = set()
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            reference = item.get("$ref")
            if isinstance(reference, str) and reference.startswith(PREFIX):
                name = reference[len(PREFIX) :].split("/", 1)[0]
                references.add(name.replace("~1", "/").replace("~0", "~"))
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return references


def schema_closure(catalog: dict[str, Any], roots: Iterable[str]) -> dict[str, Any]:
    """Resolve cycles once and fail if an operation would publish a dangling ref."""
    pending = sorted(set(roots))
    result = {}
    while pending:
        name = pending.pop()
        if name in result:
            continue
        if name not in catalog:
            raise ValueError(f"OpenAPI schema dependency is missing: {name}")
        result[name] = deepcopy(catalog[name])
        pending.extend(sorted(schema_references(result[name]) - result.keys()))
    return {name: result[name] for name in sorted(result)}
