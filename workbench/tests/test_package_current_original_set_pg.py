"""Complete native file set, real HTTP and mid-read invalidation in isolated PG."""
# ruff: noqa: F401,F811

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from psycopg.pq import TransactionStatus
from test_package_current_original_pg import api, database, exact, requirements, saved, world

from packages.domain.providers import original_bytes as byte_port
from packages.domain.review_identity import digest
from packages.model_governance import package_current_original as original
from packages.model_governance import package_current_original_set as collection
from packages.model_governance import package_current_scope as scope

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_CURRENT_ORIGINAL_SET_PG") != "1",
    reason="explicit isolated native original set required",
)


@pytest.fixture
def wire(saved):
    w = saved
    state = {"attempts": 0, "callback": None, "corrupt": False, "idle_checks": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path.startswith("/synthetic-bucket/")
            assert all(
                w["database"][key].info.transaction_status == TransactionStatus.IDLE
                for key in ("scope_verifier", "original_verifier")
            )
            state["idle_checks"] += 1
            state["attempts"] += 1
            if state["callback"]:
                state["callback"]()
            body = w["io"]["data"]
            if state["corrupt"]:
                body = b"!" + body[1:]
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            w,
            state,
            lambda locator: f"http://127.0.0.1:{server.server_port}/synthetic-bucket/"
            + quote(locator, safe=""),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def args(w, url, **changes):
    return {
        "bid_id": w["technical_scope"][0],
        "scope_id": w["saved_scope"]["manifest"]["id"],
        "expected_scope_digest": w["saved_scope"]["digest"],
        "expected_method_digest": collection.method_digest(),
        "profile": "development_s3",
        "url_for_locator": url,
    } | changes


def collect(w, url, **changes):
    return asyncio.run(
        collection.collect(
            w["database"]["scope_verifier"],
            w["database"]["original_verifier"],
            **args(w, url, **changes),
        )
    )


def test_native_scope_drives_every_original_and_final_observations(wire):
    w, state, url = wire
    result = collect(w, url)
    files = w["saved_scope"]["manifest"]["original_verification"]["files"]
    assert len(files) == 2
    assert set(result.originals) == {row["document_version_id"] for row in files}
    assert all(raw == w["io"]["data"] for raw in result.originals.values())
    assert state["attempts"] == state["idle_checks"] == len(files)
    assert result.metadata["file_count"] == 2 and result.metadata["total_bytes"] == 122
    assert result.scope_facts["scope"] == w["saved_scope"]
    assert result.metadata["digest"] == digest(
        {k: v for k, v in result.metadata.items() if k != "digest"}
    )
    assert w["io"]["data"].decode() not in json.dumps(result.metadata)
    assert w["io"]["data"].decode() not in repr(result)
    for row in result.metadata["files"]:
        assert row["initial_locator_observation"]["native_current_original_locator_checked"] is True
        assert row["final_locator_observation"]["native_current_original_locator_checked"] is True
        assert row["byte_receipt"]["native_permission_verified"] is False
    for key in (
        "native_parse_content_reverified",
        "necessary_scope_verified",
        "input_authority_granted",
        "execution_authorized",
        "historical_existence_verified",
    ):
        assert result.metadata[key] is False
    evidence = os.environ.get("FUSION_CURRENT_ORIGINAL_EVIDENCE")
    if evidence:
        (Path(evidence) / "original-set-native-proof.json").write_text(
            json.dumps(
                {
                    "collection": result.metadata,
                    "wire_attempts": state["attempts"],
                    "idle_network_checks": state["idle_checks"],
                    "synthetic_content": True,
                    "raw_originals_or_locator_exported": False,
                    "real_oss_or_s3_reads": 0,
                    "formal_binding_registered": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def test_withdrawal_during_first_get_discards_entire_collection(wire):
    w, state, url = wire
    root = w["saved_scope"]["manifest"]["preview"]["manifest"]["source_snapshot"][0]["source_id"]
    state["callback"] = lambda: w["database"]["owner"].execute(
        "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
        (root,),
    )
    with pytest.raises(original.CurrentOriginalError, match="SOURCES_CHANGED"):
        collect(w, url)
    assert state["attempts"] == 1


def test_changed_scope_during_last_get_discards_all_completed_bytes(wire):
    w, state, url = wire

    def change():
        if state["attempts"] == 2:
            w["database"]["owner"].execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                (w["technical_scope"][0],),
            )

    state["callback"] = change
    with pytest.raises(scope.CurrentScopeError, match="NOT_CURRENT_PREBID"):
        collect(w, url)
    assert state["attempts"] == 2


def test_corrupted_first_object_stops_without_returning_partial_bytes(wire):
    w, state, url = wire
    state["corrupt"] = True
    with pytest.raises(byte_port.OriginalReadError, match="BYTES_MISMATCH"):
        collect(w, url)
    assert state["attempts"] == 1


@pytest.mark.parametrize("field", ["expected_scope_digest", "expected_method_digest"])
def test_stale_scope_or_method_makes_no_http_attempt(wire, field):
    w, state, url = wire
    with pytest.raises((collection.CurrentOriginalSetError, scope.CurrentScopeError)):
        collect(w, url, **{field: "0" * 64})
    assert state["attempts"] == 0


def test_total_bytes_limit_is_checked_before_signing_or_reading(wire, monkeypatch):
    w, state, url = wire
    monkeypatch.setattr(collection, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(collection.CurrentOriginalSetError, match="ORIGINAL_LIMIT"):
        collect(w, url)
    assert state["attempts"] == 0


def test_private_signer_failure_has_no_native_context_or_network(wire):
    w, state, url = wire

    def fail_signer(locator):
        raise RuntimeError("synthetic-private-signed-url")

    with pytest.raises(
        collection.CurrentOriginalSetError, match="URL_PREPARATION_FAILED"
    ) as caught:
        collect(w, fail_signer)
    assert caught.value.__context__ is None and "synthetic-private" not in str(caught.value)
    assert state["attempts"] == 0


def test_cancellation_during_get_leaves_both_native_connections_idle(saved):
    w = saved

    async def run():
        entered = asyncio.Event()

        async def blocked(request):
            entered.set()
            await asyncio.Event().wait()

        client = byte_port.OriginalByteClient(transport=httpx.MockTransport(blocked))
        task = asyncio.create_task(
            collection.collect(
                w["database"]["scope_verifier"],
                w["database"]["original_verifier"],
                **args(
                    w, lambda locator: "http://127.0.0.1:8333/synthetic-object", byte_client=client
                ),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert all(
        w["database"][key].info.transaction_status == TransactionStatus.IDLE
        for key in ("scope_verifier", "original_verifier")
    )
