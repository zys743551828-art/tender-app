"""Route a real generated build without claiming a synthetic renderer qualifies PDF."""

import pytest
from test_authoring_generated import snapshot as generated_snapshot

from packages.authoring import (
    build_repository,
    generated_docx,
    prebuilt_dispatch,
    prebuilt_generated,
)
from packages.word_intake import prebuilt


@pytest.mark.parametrize(
    "declared,expected_dispatch",
    [
        ("authoring-prebuilt-generated/1", True),
        ("authoring-generated-sandbox/1", False),
        ("unknown-generated-protocol/1", False),
    ],
)
def test_generated_build_requires_supported_matching_frozen_protocol(
    monkeypatch, declared, expected_dispatch
):
    snapshot = generated_snapshot.__wrapped__()
    identity = prebuilt._fixed()
    provider = {"identity": identity, "profile_digest": prebuilt.digest(identity)}
    profile = prebuilt_generated.profile_for(provider)
    manifest = {
        "writer_kind": "generated_text/2",
        "writer_digest": build_repository.generated_writer_digest(),
        "generator_identity": generated_docx.generator_identity(),
        "authoring_structure_digest": snapshot["authoring_structure"]["digest"],
        "formats": ["pdf"],
        "renderer_identity": profile,
        "render_protocol": declared,
    }
    calls, stored = [], {}

    def render(source, actual_snapshot, producer, actual_profile):
        assert source.startswith(b"PK") and actual_snapshot == snapshot
        assert actual_profile == profile and producer
        calls.append(declared)
        # A failed sentinel proves routing while retaining the renderer verdict.
        return {
            "state": "failed",
            "pdf": None,
            "chain": {},
            "gaps": ["SYNTHETIC_ROUTE_REACHED"],
            "coverage": "failed",
            "isolation": {},
        }

    monkeypatch.setattr(prebuilt_dispatch, "generated", render)
    monkeypatch.setattr(
        build_repository.storage, "put", lambda key, data, media: stored.__setitem__(key, data)
    )
    monkeypatch.setattr(build_repository.storage, "get", stored.__getitem__)
    result = build_repository.compute_prepared_build(
        {
            "input_id": "synthetic-routing-input",
            "snapshot": snapshot,
            "info": {"draft_snapshot_id": snapshot["snapshot_id"], "manifest": manifest},
        }
    )
    assert bool(calls) is expected_dispatch
    output = next(row for row in result["outputs"] if row["format"] == "pdf")
    assert output["state"] == "failed"
    expected_gap = "SYNTHETIC_ROUTE_REACHED" if expected_dispatch else "RENDER_PROTOCOL_UNSUPPORTED"
    assert expected_gap in output["gaps"]
    assert len(stored) == 1 and next(iter(stored.values())).startswith(b"PK")
