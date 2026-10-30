"""Compose versioned producer ports without changing frozen legacy renderers."""

import tempfile
from pathlib import Path

from packages.authoring import generated_renderer, prebuilt_generated, prebuilt_rich, rich_renderer
from packages.word_intake import execution_transport


def protocol(profile):
    return (profile or {}).get("identity", {}).get("protocol")


def generated(source, snapshot, manifest, profile):
    if protocol(profile) == prebuilt_generated.PROTOCOL:
        if execution_transport.enabled():
            return execution_transport.call(
                "page",
                source=source,
                snapshot=snapshot,
                producer_manifest=manifest,
                profile=profile,
            )
        with tempfile.TemporaryDirectory(prefix="authoring-prebuilt-page-") as directory:
            return prebuilt_generated.render(
                source, snapshot, manifest, profile, receipt=Path(directory) / "resources.json"
            )
    return generated_renderer.render(source, snapshot, manifest, profile)


def rich(snapshot, materials, profile, *, mode):
    if protocol(profile) == prebuilt_rich.PROTOCOL:
        if execution_transport.enabled():
            return execution_transport.call(
                "rich", snapshot=snapshot, materials=materials, profile=profile, mode=mode
            )
        with tempfile.TemporaryDirectory(prefix="authoring-prebuilt-rich-") as directory:
            return prebuilt_rich.render(
                snapshot, materials, profile, mode=mode, receipt=Path(directory) / "resources.json"
            )
    return rich_renderer.render(snapshot, materials, profile, mode=mode)
