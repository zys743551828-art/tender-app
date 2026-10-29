"""Bounded original verification, transaction boundaries and immutable record binding."""

# ruff: noqa: F401,F811
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_historical_import_delivery import ACTOR, BATCH, read_port, record

from apps.api import research_routes as routes
from packages.domain.runtime import DomainError, sha
from packages.research import import_history, import_originals


def test_shared_blob_is_read_once_and_corruption_is_kept_per_record(monkeypatch):
    calls = []

    def verify(document):
        calls.append(document["blob_id"])
        if document["blob_id"] == "bad":
            raise DomainError("ORIGINAL_BYTES_CORRUPTED", "synthetic corruption", 409)

    monkeypatch.setattr(import_originals.original_verification, "verify", verify)
    observation = {
        "records": {
            "one": {"error": None, "documents": [{"blob_id": "shared"}]},
            "two": {"error": None, "documents": [{"blob_id": "shared"}, {"blob_id": "bad"}]},
            "three": {"error": None, "documents": [{"blob_id": "bad"}]},
        }
    }
    value = import_originals.verify(observation)
    assert calls == ["shared", "bad"]
    assert value.errors == {
        "two": "IMPORT_ORIGINAL_CORRUPTED",
        "three": "IMPORT_ORIGINAL_CORRUPTED",
    }


def test_actual_record_and_current_metadata_must_match_verified_observation(monkeypatch):
    item = record()
    exact = [{"blob_id": "one", "digest": "a" * 64, "object_key": "synthetic-private"}]
    manifest = {"schema": "historical-import/1", "records": [item]}
    observation = {
        "batch_id": str(BATCH),
        "manifest_digest": sha(manifest),
        "records": {
            item["external_record_id"]: {
                "record_digest": sha(item),
                "source_digest": "b" * 64,
                "documents": exact,
            }
        },
    }
    value = import_originals.VerifiedOriginals(observation, {}, "2026-10-21T01:00:00Z")
    monkeypatch.setattr(import_originals, "documents", lambda *_args: deepcopy(exact))
    import_originals.assert_batch(value, BATCH, manifest)
    with pytest.raises(DomainError, match="确认需要本批原件"):
        import_originals.assert_batch({"verified": True}, BATCH, manifest)
    proof = import_originals.receipt(None, value, item, {"source_digest": "b" * 64})
    assert proof["documents"] == [{"blob_id": "one", "digest": "a" * 64}]
    assert not proof["platform_submission_verified"]
    for changed in (item | {"explanation": "changed"}, item | {"external_record_id": "other"}):
        with pytest.raises(DomainError) as caught:
            import_originals.receipt(None, value, changed, {"source_digest": "b" * 64})
        assert caught.value.code == "IMPORT_ORIGINAL_CHANGED"
    monkeypatch.setattr(import_originals, "documents", lambda *_args: exact + [{"blob_id": "new"}])
    with pytest.raises(DomainError) as caught:
        import_originals.receipt(None, value, item, {"source_digest": "b" * 64})
    assert caught.value.code == "IMPORT_ORIGINAL_CHANGED"


def test_unique_blob_byte_budget_is_enforced_before_network_io(monkeypatch):
    item = record()
    manifest = {"schema": "historical-import/1", "records": [item]}
    c = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(
            fetchall=lambda: [
                {"external_record_id": item["external_record_id"], "source_digest": "a" * 64}
            ]
        )
    )
    monkeypatch.setattr(import_originals, "MAX_VERIFICATION_BYTES", 10)
    monkeypatch.setattr(
        import_originals, "documents", lambda *_args: [{"blob_id": "same", "byte_size": 11}]
    )
    with pytest.raises(DomainError) as caught:
        import_originals.observe(c, BATCH, manifest)
    assert caught.value.code == "IMPORT_ORIGINAL_BUDGET_EXCEEDED"


def test_confirm_closes_read_transactions_before_manifest_and_original_io(monkeypatch, read_port):
    metadata, manifest, observed, verified = {}, {"records": []}, object(), object()
    monkeypatch.setattr(import_history, "replay", lambda *_args: None)
    monkeypatch.setattr(import_history, "source_metadata", lambda *_args: metadata)
    monkeypatch.setattr(routes, "require_read_committed", lambda *_args: None)

    def read(value):
        assert value is metadata and not read_port["open"]
        return manifest

    def observe(_c, identity, value):
        assert read_port["open"] and identity == BATCH and value is manifest
        return observed

    def verify(value):
        assert not read_port["open"] and value is observed
        return verified

    def confirm(_c, **kwargs):
        assert read_port["open"] and kwargs["originals"] is verified
        assert read_port["auth"] == [True, True]
        return {"id": str(BATCH), "revision": 2}

    monkeypatch.setattr(routes.batches, "read_manifest", read)
    monkeypatch.setattr(import_originals, "observe", observe)
    monkeypatch.setattr(import_originals, "verify", verify)
    monkeypatch.setattr(routes.importing, "confirm", confirm)
    monkeypatch.setattr(
        routes,
        "command",
        lambda *_args, **_kw: SimpleNamespace(
            id=ACTOR,
            replay=None,
            finish=lambda body, **kw: {"body": body, "status": 200, "headers": kw["headers"]},
        ),
    )
    result = routes.confirm_import(
        BATCH,
        SimpleNamespace(headers={"idempotency-key": "same-request", "if-match": '"original"'}),
        {},
    )
    assert result.status_code == 200
