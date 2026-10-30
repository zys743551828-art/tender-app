"""Business producers stay local; only their converter uses the execution port."""

from contextlib import contextmanager
from pathlib import Path

import pytest

from packages.authoring import prebuilt_dispatch as producers
from packages.word_intake import conversion, execution_transport, prebuilt


@pytest.mark.parametrize("lane,seconds", [("external", 120), ("page", 120), ("rich", 240)])
def test_complete_producer_arguments_execute_locally_with_bounded_budget(
    monkeypatch, lane, seconds
):
    observed = []
    receipts = []
    result = {"state": "failed", "coverage": "failed"}

    @contextmanager
    def budget(value):
        observed.append(("enter", value))
        yield
        observed.append(("exit", value))

    monkeypatch.setattr(execution_transport, "deadline_budget", budget)

    def local(*args, receipt, **kwargs):
        assert isinstance(receipt, Path) and receipt.parent.is_dir()
        receipts.append(receipt)
        observed.append(("producer", args, kwargs))
        return result

    protocols = {
        "external": prebuilt.PROTOCOL,
        "page": producers.prebuilt_generated.PROTOCOL,
        "rich": producers.prebuilt_rich.PROTOCOL,
    }
    profile = {"identity": {"protocol": protocols[lane]}}
    if lane == "external":
        monkeypatch.delenv("WORD_RENDER_TEST_RECEIPT_DIRECTORY", raising=False)
        monkeypatch.setattr(prebuilt, "render", local)
        actual = conversion.render(b"source", profile)
        expected = ((b"source", profile), {})
    elif lane == "page":
        monkeypatch.setattr(producers.prebuilt_generated, "render", local)
        actual = producers.generated(b"source", {"frozen": True}, {"manifest": True}, profile)
        expected = ((b"source", {"frozen": True}, {"manifest": True}, profile), {})
    else:
        monkeypatch.setattr(producers.prebuilt_rich, "render", local)
        materials = [{"bytes": b"image"}]
        actual = producers.rich({"frozen": True}, materials, profile, mode="controlled")
        expected = (({"frozen": True}, materials, profile), {"mode": "controlled"})
    assert actual is result
    assert observed == [("enter", seconds), ("producer", *expected), ("exit", seconds)]
    assert len(receipts) == 1 and not receipts[0].parent.exists()


@pytest.mark.parametrize("lane", ["external", "page", "rich"])
def test_legacy_profile_never_uses_new_execution_budget(monkeypatch, lane):
    def forbidden(*args):
        raise AssertionError("legacy profile must retain its original port")

    monkeypatch.setattr(execution_transport, "deadline_budget", forbidden)
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
