"""Import acknowledgement recovery and source delivery without object IO in transactions."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import research_routes as routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError, sha
from packages.research import import_history
from packages.research.import_contracts import HistoricalImportRequest

ACTOR = UUID(int=71)
BATCH = UUID(int=72)


def record():
    return {
        "external_record_id": "original-row",
        "bid_id": str(UUID(int=1)),
        "actual_document_version_id": str(UUID(int=2)),
        "submitted_at": "2024-02-02T00:00:00.123456Z",
        "evidence_ref": str(UUID(int=3)),
        "explanation": "事后登记原实际提交资料",
        "score_kind": "technical_total",
        "value": "0",
        "maximum": "60.00",
        "source_version_id": str(UUID(int=4)),
        "known_at": "2024-02-05T00:00:00Z",
    }


def test_actual_import_operations_have_closed_receipts_and_do_not_call_preview_read_only():
    actual = implemented_openapi(app)
    schemas = actual["components"]["schemas"]
    for path, status in (
        ("/research/import-previews", "201"),
        ("/research/imports/{batch_id}/confirm", "200"),
    ):
        operation = actual["paths"]["/api/v1" + path]["post"]
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HistoricalImportReceipt"
        }
        required = {p["name"] for p in operation["parameters"] if p.get("required")}
        assert {"Origin", "X-CSRF-Token", "Idempotency-Key"} <= required
    assert "command" in schemas["HistoricalImportReceipt"]["required"]
    assert schemas["HistoricalImportReceipt"]["properties"]["standard_submission_gate_checked"] == {
        "const": False
    }
    for path in ("/research/imports", "/research/imports/{batch_id}/source"):
        assert actual["paths"]["/api/v1" + path]["get"]["security"] == [{"SessionCookie": []}]


@pytest.fixture
def read_port(monkeypatch):
    state = {"open": False, "auth": []}

    @contextmanager
    def connection():
        state["open"] = True
        try:
            yield SimpleNamespace(execute=lambda _sql: None)
        finally:
            state["open"] = False

    def auth(_request, write=False):
        state["auth"].append(write)
        return {"member_id": ACTOR}

    monkeypatch.setattr(routes, "auth", auth)
    monkeypatch.setattr(routes, "connection", connection)
    return state


@pytest.mark.parametrize("kind", ["preview", "confirm"])
def test_committed_replay_is_returned_before_any_private_object_access(
    monkeypatch, read_port, kind
):
    saved = {
        "body": {"id": str(BATCH), "original": "immutable-ack"},
        "status": 201,
        "headers": {"ETag": '"original"'},
    }
    request = SimpleNamespace(headers={"idempotency-key": "original-key", "if-match": '"original"'})
    body = HistoricalImportRequest(records=[record()])

    def prior(_c, actor, command_kind, target, key, value, condition=None):
        assert read_port["open"] and actor == ACTOR and key == "original-key"
        if kind == "preview":
            assert (command_kind, target, value, condition) == (
                import_history.PREVIEW_KIND,
                import_history.PREVIEW_TARGET,
                body.model_dump(mode="json"),
                None,
            )
        else:
            assert (command_kind, target, value, condition) == (
                import_history.CONFIRM_KIND,
                BATCH,
                {},
                '"original"',
            )
        return saved

    monkeypatch.setattr(import_history, "replay", prior)
    monkeypatch.setattr(
        routes.artifacts, "stage_json", lambda *_args: pytest.fail("Replay wrote an object")
    )
    monkeypatch.setattr(
        import_history, "source_metadata", lambda *_args: pytest.fail("Replay read object metadata")
    )
    monkeypatch.setattr(
        routes.batches, "read_manifest", lambda *_args: pytest.fail("Replay read an object")
    )
    response = (
        routes.preview_import(request, body)
        if kind == "preview"
        else routes.confirm_import(BATCH, request, {})
    )
    assert response.headers["Idempotent-Replayed"] == "true"
    assert json.loads(response.body) == saved["body"]
    assert not read_port["open"]


def test_source_delivery_closes_the_snapshot_then_reauthenticates(monkeypatch, read_port):
    metadata = {"id": UUID(int=73)}
    monkeypatch.setattr(
        import_history,
        "source_metadata",
        lambda _c, bid: metadata if bid == BATCH else pytest.fail("scope"),
    )

    def source(identity, value):
        assert identity == BATCH and value == metadata and not read_port["open"]
        return {"batch_id": str(BATCH)}

    monkeypatch.setattr(import_history, "source", source)
    response = routes.get_import_source(BATCH, None)
    assert read_port["auth"] == [False, False]
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("key", [None, "", "x" * 129, "bad\nkey"])
def test_invalid_request_keys_fail_before_object_staging(monkeypatch, key):
    monkeypatch.setattr(routes, "auth", lambda *_args: {"member_id": ACTOR})
    monkeypatch.setattr(routes, "connection", lambda: pytest.fail("Invalid key reached database"))
    monkeypatch.setattr(
        routes.artifacts, "stage_json", lambda *_args: pytest.fail("Invalid key staged input")
    )
    with pytest.raises(DomainError) as caught:
        routes.preview_import(
            SimpleNamespace(headers={"idempotency-key": key}),
            HistoricalImportRequest(records=[record()]),
        )
    assert caught.value.code == "IDEMPOTENCY_REQUIRED"


def test_receipt_digest_binds_normalized_input_actor_key_and_condition():
    body = HistoricalImportRequest(records=[record()]).model_dump(mode="json")
    binding = import_history.receipt(
        SimpleNamespace(id=UUID(int=75)),
        ACTOR,
        import_history.PREVIEW_KIND,
        import_history.PREVIEW_TARGET,
        "key",
        body,
    )
    assert binding["request_digest"] == sha({"body": body, "if_match": None})
    assert binding["actor_id"] == str(ACTOR) and binding["idempotency_key"] == "key"
    assert body["records"][0]["submitted_at"].endswith(".123456Z")
    assert body["records"][0]["value"] == "0" and body["records"][0]["maximum"] == "60.00"
    assert binding["request_digest"] != sha({"body": body, "if_match": '"later"'})


@pytest.mark.parametrize("changed", ["body", "etag"])
def test_recovery_rejects_a_changed_original_request(changed):
    body = {"records": [record()]}
    saved_hash = sha({"body": body, "if_match": '"base"'})
    port = SimpleNamespace(
        execute=lambda *_args: SimpleNamespace(
            fetchone=lambda: {
                "request_digest": saved_hash,
                "response": {"body": {"id": str(BATCH)}},
            }
        )
    )
    with pytest.raises(DomainError) as caught:
        import_history.replay(
            port,
            ACTOR,
            import_history.CONFIRM_KIND,
            BATCH,
            "key",
            {} if changed == "body" else body,
            '"later"' if changed == "etag" else '"base"',
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


def test_multibyte_manifest_limit_is_enforced_before_staging(monkeypatch):
    monkeypatch.setattr(import_history.batches, "MAX_MANIFEST_BYTES", 150)
    assert len("汉" * 60) < 150
    with pytest.raises(DomainError) as caught:
        import_history.manifest([{"explanation": "汉" * 60}])
    assert caught.value.code == "IMPORT_MANIFEST_TOO_LARGE"


def test_source_returns_exact_saved_records_and_refuses_corrupt_bytes(monkeypatch):
    from packages.domain import storage

    value = import_history.manifest(
        HistoricalImportRequest(records=[record()]).model_dump(mode="json")["records"]
    )
    raw = json.dumps(value, ensure_ascii=False).encode()
    metadata = {
        "id": UUID(int=73),
        "object_key": "synthetic/import.json",
        "byte_size": len(raw),
        "digest": sha(raw),
    }
    monkeypatch.setattr(storage, "get", lambda _key: raw)
    result = import_history.source(BATCH, metadata)
    assert result["request"]["records"] == value["records"]
    monkeypatch.setattr(storage, "get", lambda _key: raw + b" ")
    with pytest.raises(DomainError) as caught:
        import_history.source(BATCH, metadata)
    assert caught.value.code == "MANIFEST_CORRUPTED"
