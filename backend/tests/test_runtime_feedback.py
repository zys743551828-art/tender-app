"""Offline legacy protocol/observability checks; never call a cloud service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr

from bidwb.config import Settings
from bidwb.messaging import Consumer
from bidwb.runtime import Container
from bidwb.storage import ObjectStoreError, S3ObjectStore
from bidwb.tasks import Claim
from bidwb.util import utcnow
from bidwb.workers import runner as worker
from bidwb.workers.handlers import HandlerOutput


class Intercepted(Exception):
    """Stop real SDK serialization before any socket is used."""


def settings(**updates: Any) -> Settings:
    return Settings(
        _env_file=None,
        **(
            {
                "storage_endpoint_url": "https://oss-cn-hangzhou.aliyuncs.com",
                "storage_region": "cn-hangzhou",
                "storage_bucket": "synthetic-bucket",
                "storage_access_key_id": SecretStr("synthetic-access"),
                "storage_secret_access_key": SecretStr("synthetic-secret"),
                "storage_signature_version": "s3v4",
            }
            | updates
        ),
    )


@pytest.mark.parametrize("field", ["storage_endpoint_url", "storage_public_endpoint_url"])
def test_virtual_endpoint_rejects_bucket_prefix_before_signing(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        S3ObjectStore(settings(**{field: "https://synthetic-bucket.oss-cn-hangzhou.aliyuncs.com"}))


def test_region_endpoint_produces_one_bucket() -> None:
    store = S3ObjectStore(settings(storage_public_endpoint_url="https://oss-cn-hangzhou.aliyuncs.com"))
    assert (
        urlsplit(store.presign_part("staging/synthetic", "synthetic-upload", 1, 60)).hostname
        == "synthetic-bucket.oss-cn-hangzhou.aliyuncs.com"
    )


@pytest.mark.parametrize("operation", ["PutObject", "UploadPart"])
def test_sigv4_writes_do_not_use_optional_chunked_trailers(operation: str, monkeypatch: pytest.MonkeyPatch) -> None:
    store = S3ObjectStore(settings())
    observed = {}

    def capture(request: Any, **_: Any) -> None:
        observed.update({key.lower(): value.decode() if isinstance(value, bytes) else value for key, value in request.headers.items()})
        raise Intercepted

    store._client.meta.events.register("before-send.s3." + operation, capture)
    monkeypatch.setattr(store._client._endpoint.http_session, "send", Mock(side_effect=AssertionError("cloud I/O forbidden")))
    with pytest.raises(Intercepted):
        if operation == "PutObject":
            store.put("artifacts/synthetic", b"synthetic bytes", "text/plain")
        else:
            store.upload_part("staging/synthetic", "synthetic-upload", 1, b"synthetic bytes")
    assert "aws-chunked" not in str(observed.get("content-encoding", ""))
    assert "TRAILER" not in str(observed.get("x-amz-content-sha256", ""))
    assert "x-amz-trailer" not in observed
    assert store._client.meta.config.request_checksum_calculation == "when_required"
    assert store._signer.meta.config.response_checksum_validation == "when_required"


def test_artifact_store_failure_is_visible_without_private_exception_text(monkeypatch: pytest.MonkeyPatch) -> None:
    private = "synthetic-private-content-and-signed-query-must-not-be-logged"
    store = Mock()
    store.put.side_effect = ObjectStoreError(private)
    logger = Mock()
    monkeypatch.setattr(worker, "log", logger)
    release = Mock()
    monkeypatch.setattr(worker.WorkerRunner, "_release", release)
    transaction = Mock(side_effect=AssertionError("database commit forbidden"))
    monkeypatch.setattr(worker.db, "transaction", transaction)
    ctr = cast(Container, SimpleNamespace(store=store))
    runner = worker.WorkerRunner(ctr, "parse", cast(Consumer, None), {}, "synthetic-consumer")
    claim = Claim("synthetic-job", 2, "synthetic-fence", utcnow(), "parse", "synthetic-project", "a" * 64, {}, None)
    finalize = Mock()
    runner._succeed(claim, HandlerOutput(private.encode(), "application/json", "synthetic/1", finalize))
    release.assert_called_once_with(claim, "dependency_unavailable")
    transaction.assert_not_called()
    finalize.assert_not_called()
    logger.warning.assert_called_once_with(
        "job_transient_failure",
        job_id=claim.job_id,
        kind=claim.kind,
        attempt=claim.attempt,
        stage="artifact_store",
        error="ObjectStoreError",
    )
    assert private not in str(logger.mock_calls)


def test_rule_failure_classification_preserves_strict_validation_and_no_private_text() -> None:
    from bidwb.ai import prompts
    from bidwb.ai.rule_diagnostics import failed_rules_message

    private = "synthetic private excerpt must not be disclosed"
    raw = {
        "kind": "mandatory",
        "statement": "合成规则字段格式反例",
        "conditions": "not a list",
        "exceptions": [],
        "evidence_ids": ["synthetic"],
        "quote": "合成原文逐字依据",
    }
    valid, dropped = prompts.validate_items(prompts.RuleCandidate, [raw] * 37)
    assert valid == []
    message = failed_rules_message([*dropped, *[{"reason": "quote_not_found", "statement": private}] * 3])
    assert "conditions 37" in message and "逐字出处不符 3" in message
    assert "原文没有规则" in message and private not in message
    assert prompts.PROMPT_VERSION == "p4"
    assert failed_rules_message([{"reason": private, "statement": private}]).count(private) == 0


@pytest.mark.parametrize("bucket", ["s3", "oss-cn-hangzhou"])
def test_official_service_endpoint_is_not_mistaken_for_a_bucket(bucket: str) -> None:
    store = S3ObjectStore(settings(storage_bucket=bucket, storage_endpoint_url="https://s3.oss-cn-hangzhou.aliyuncs.com"))
    assert store._bucket == bucket
