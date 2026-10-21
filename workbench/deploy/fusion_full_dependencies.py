"""Verify installed dependency pins and retain the actual local codec identities."""

from __future__ import annotations

import importlib.metadata
import platform
import sys

from deploy import fusion_full_spec as spec


def identity():
    from confluent_kafka import libversion
    from PIL import features
    from psycopg import pq
    from pypdfium2.version import PDFIUM_INFO

    pins = {}
    for filename in ("requirements.lock.txt", "deploy/fusion_full_requirements.txt"):
        for line in (spec.fresh.ROOT / filename).read_text().splitlines():
            if not line or line.startswith(("#", "-r ")):
                continue
            name, separator, wanted = line.partition("==")
            if not separator or not name or not wanted or name in pins:
                raise spec.ConfigurationError("FULL_DEPENDENCY_PIN_INVALID")
            try:
                actual = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                raise spec.ConfigurationError("FULL_DEPENDENCY_MISSING") from None
            if actual != wanted:
                raise spec.ConfigurationError("FULL_DEPENDENCY_VERSION_CHANGED")
            pins[name] = actual
    if sys.version_info < (3, 12) or platform.python_implementation() != "CPython":
        raise spec.ConfigurationError("FULL_PYTHON_RUNTIME_UNSUPPORTED")
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "packages": pins,
        "librdkafka": libversion()[0],
        "libpq": pq.version(),
        "pdfium": str(PDFIUM_INFO),
        "pillow_codecs": {
            name: features.version(name) for name in ("jpg", "jpg_2000", "zlib", "webp")
        },
    }
