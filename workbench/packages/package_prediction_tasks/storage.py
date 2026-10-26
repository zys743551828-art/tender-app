"""Unregistered private objects, never public document grants or audit payloads."""

import json

from packages.domain import storage
from packages.domain.review_identity import digest
from packages.package_model_registry.artifact import fail


class Objects:
    def put(self, value):
        reference = digest(value)
        data = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(data) > 32 * 1024 * 1024:
            fail()
        storage.put("blobs/" + reference, data, "application/json")
        if self.get(reference) != value:
            fail()
        return reference

    def get(self, reference):
        if (
            not isinstance(reference, str)
            or len(reference) != 64
            or any(c not in "0123456789abcdef" for c in reference)
        ):
            fail()
        data = storage.get("blobs/" + reference)
        if len(data) > 32 * 1024 * 1024:
            fail()
        try:
            value = json.loads(data)
            valid = digest(value) == reference
        except (ValueError, TypeError, UnicodeError):
            fail()
        if not valid:
            fail()
        return value
