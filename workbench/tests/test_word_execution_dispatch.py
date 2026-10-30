"""Execution selection preserves complete producer input and legacy boundaries."""

import pytest

from packages.authoring import prebuilt_dispatch as producers
from packages.word_intake import conversion, execution_transport, prebuilt


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_transport_receives_complete_producer_arguments(monkeypatch, lane):
    monkeypatch.setattr(execution_transport, "enabled", lambda: True)
    observed = []
    result = {"state": "failed", "coverage": "failed"}
    monkeypatch.setattr(
        execution_transport,
        "call",
        lambda kind, **kw: observed.append((kind, kw)) or result,
    )
    protocols = {
        "external": prebuilt.PROTOCOL,
        "page": producers.prebuilt_generated.PROTOCOL,
        "rich": producers.prebuilt_rich.PROTOCOL,
    }
    profile = {"identity": {"protocol": protocols[lane]}}
    if lane == "external":
        actual = conversion.render(b"source", profile)
        expected = {"source": b"source", "profile": profile}
    elif lane == "page":
        actual = producers.generated(b"source", {"frozen": True}, {"manifest": True}, profile)
        expected = {
            "source": b"source",
            "snapshot": {"frozen": True},
            "producer_manifest": {"manifest": True},
            "profile": profile,
        }
    else:
        materials = [{"bytes": b"image"}]
        actual = producers.rich({"frozen": True}, materials, profile, mode="controlled")
        expected = {
            "snapshot": {"frozen": True},
            "materials": materials,
            "profile": profile,
            "mode": "controlled",
        }
    assert actual is result and observed == [(lane, expected)]


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_legacy_profile_never_uses_new_execution_channel(monkeypatch, lane):
    def forbidden():
        raise AssertionError("legacy profile must retain its original port")

    monkeypatch.setattr(execution_transport, "enabled", forbidden)
    result = {"state": "failed", "coverage": "failed"}
    if lane == "external":
        monkeypatch.setattr(conversion.renderer, "render", lambda *args: result)
        actual = conversion.render(b"source", {})
    elif lane == "page":
        monkeypatch.setattr(producers.generated_renderer, "render", lambda *args: result)
        actual = producers.generated(b"source", {}, {}, {})
    else:
        monkeypatch.setattr(producers.rich_renderer, "render", lambda *args, **kw: result)
        actual = producers.rich({}, [], {}, mode="controlled")
    assert actual is result
