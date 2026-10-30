"""Compose versioned producer ports without changing frozen legacy renderers."""

import tempfile
from pathlib import Path

from packages.authoring import generated_renderer, prebuilt_generated, prebuilt_rich, rich_renderer


def protocol(profile):
    return (profile or {}).get("identity", {}).get("protocol")


def generated(source, snapshot, manifest, profile):
    if protocol(profile) == prebuilt_generated.PROTOCOL:
        with tempfile.TemporaryDirectory(prefix="authoring-prebuilt-page-") as directory:
            return prebuilt_generated.render(
                source, snapshot, manifest, profile, receipt=Path(directory) / "resources.json"
            )
    return generated_renderer.render(source, snapshot, manifest, profile)


def rich(snapshot, materials, profile, *, mode):
    if protocol(profile) == prebuilt_rich.PROTOCOL:
        with tempfile.TemporaryDirectory(prefix="authoring-prebuilt-rich-") as directory:
            return prebuilt_rich.render(
                snapshot, materials, profile, mode=mode, receipt=Path(directory) / "resources.json"
            )
    return rich_renderer.render(snapshot, materials, profile, mode=mode)
