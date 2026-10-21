"""Opt-in fresh loopback Kafka/S3 + nonowner PG, using synthetic PDF bytes only.

This requires an explicitly provisioned disposable transport cluster. It does not
start infrastructure, discover credentials, call a model, or touch business data.
Run serially: the imported PG fixture owns its one fixed disposable database.
"""
# ruff: noqa: F401,F811

import json
import os
import re
import stat
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.admin import AdminClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from test_authoring_package_adoptions_pg import database, env
from test_document_parses_pg import parsed_file, request, task

from apps.worker import engine
from deploy.initialize_topics import DEFAULT_POLICY, initialize
from packages.domain import document_parses, storage
from packages.domain.runtime import connection, sha

REAL_CLIENT, REAL_GET, REAL_PUT, REAL_BUCKET = (
    storage.client,
    storage.get,
    storage.put,
    storage.bucket,
)
PROFILE = os.environ.get("FUSION_TRANSPORT_PROFILE")
pytestmark = pytest.mark.skipif(
    not PROFILE or not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires explicit fresh isolated loopback Kafka/S3/PG technical fixture",
)


@pytest.fixture(scope="module", autouse=True)
def loopback_only():
    """Check all destinations before the module's disposable DB fixture starts."""
    profile = json.loads(Path(PROFILE).read_text())
    endpoint = urlparse(profile["s3_endpoint"])
    assert profile["only_synthetic"] is True
    assert endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
    assert not (endpoint.username or endpoint.password or endpoint.path or endpoint.query)
    assert endpoint.port and 0 < endpoint.port < 65536
    bootstrap = profile["kafka_bootstrap"]
    assert re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", bootstrap)
    assert int(bootstrap.rsplit(":", 1)[1]) < 65536
    admin = conninfo_to_dict(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"])
    assert admin.get("host") == "127.0.0.1" and admin.get("dbname") == "postgres"


@pytest.fixture
def transport(monkeypatch):
    profile = json.loads(Path(PROFILE).read_text())
    credentials_path = Path(profile["credentials_path"])
    assert stat.S_IMODE(credentials_path.stat().st_mode) == 0o600
    identity = json.loads(credentials_path.read_text())["identities"][0]["credentials"][0]
    values = {
        "OBJECT_STORE_BACKEND": "s3",
        "OBJECT_STORE_ENDPOINT": profile["s3_endpoint"],
        "OBJECT_STORE_ACCESS_KEY": identity["accessKey"],
        "OBJECT_STORE_SECRET_KEY": identity["secretKey"],
        "OBJECT_STORE_BUCKET": "synthetic-transport-" + uuid4().hex,
        "KAFKA_BOOTSTRAP_SERVERS": profile["kafka_bootstrap"],
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(storage, "client", REAL_CLIENT)
    monkeypatch.setattr(storage, "get", REAL_GET)
    monkeypatch.setattr(storage, "put", REAL_PUT)
    monkeypatch.setattr(storage, "bucket", REAL_BUCKET)
    admin = AdminClient({"bootstrap.servers": profile["kafka_bootstrap"]})
    initialized = initialize(
        admin,
        json.loads(DEFAULT_POLICY.read_text()),
        expected_cluster_id=profile["cluster_id"],
    )
    assert initialized["topics_verified"] == 9
    client = storage.client()
    bucket = storage.bucket()
    client.create_bucket(Bucket=bucket)
    yield profile | {"client": client, "bucket": bucket}
    for item in client.list_objects_v2(Bucket=bucket).get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    client.delete_bucket(Bucket=bucket)


def eventually(predicate, *, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("isolated transport condition did not complete before deadline")


def test_real_outbox_kafka_consumer_s3_pdf_parse_and_duplicate_delivery(
    parsed_file, transport, monkeypatch
):
    fixture = parsed_file
    original = fixture["objects"][fixture["object_key"]]
    storage.put(fixture["object_key"], original, "application/pdf")
    downloaded = storage.get(fixture["object_key"])
    assert downloaded == original and sha(downloaded) == sha(original)
    with monkeypatch.context() as bad_identity:
        bad_identity.setenv("OBJECT_STORE_SECRET_KEY", "explicit-wrong-synthetic-key")
        with pytest.raises(ClientError) as denied:
            storage.client().get_object(Bucket=storage.bucket(), Key=fixture["object_key"])
        assert denied.value.response["ResponseMetadata"]["HTTPStatusCode"] == 403

    ack, _ = request(fixture)
    message = task(ack)
    calls = []
    original_compute = engine.run_compute

    def observed_compute(payload, lease):
        calls.append(payload["operation_id"])
        return original_compute(payload, lease)

    monkeypatch.setattr(engine, "run_compute", observed_compute)
    consumer_errors = []

    def consume():
        try:
            engine.consume("document")
        except BaseException as error:
            consumer_errors.append(error)

    engine.STOP.clear()
    thread = threading.Thread(target=consume, name="synthetic-real-document-consumer")
    thread.start()
    probe = Consumer(
        {
            "bootstrap.servers": transport["kafka_bootstrap"],
            "group.id": "tender-document-worker-v1",
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
        }
    )
    try:
        engine.relay(once=True)

        def succeeded():
            assert not consumer_errors
            value = document_parses.read(fixture["bid"], fixture["document"], ack["request"]["id"])
            return value["operation"]["state"] == "succeeded"

        eventually(succeeded)
        with connection(True) as c:
            row = c.execute(
                "SELECT published_at FROM outbox WHERE operation_id=%s AND topic='tender.task.document.v1'",
                (message["operation_id"],),
            ).fetchone()
            assert row["published_at"] is not None

        delivered = []
        producer = engine.producer()
        producer.produce(
            "tender.task.document.v1",
            key=f"{message['operation_id']}:{message['step_key']}",
            value=json.dumps(message),
            on_delivery=lambda error, event: delivered.append((error, event)),
        )
        assert producer.flush(10) == 0 and len(delivered) == 1 and delivered[0][0] is None
        duplicate = delivered[0][1]

        def committed_duplicate():
            assert not consumer_errors
            offsets = probe.committed(
                [TopicPartition(duplicate.topic(), duplicate.partition())], timeout=5
            )
            return offsets[0].offset >= duplicate.offset() + 1

        eventually(committed_duplicate)
        assert calls == [message["operation_id"]]
        value = document_parses.read(fixture["bid"], fixture["document"], ack["request"]["id"])
        assert value["result"]["page_count"] == 2
        assert value["result"]["coverage"] == "partial"
        with connection(True) as c:
            for table in ("step_receipts", "effect_receipts", "document_parse_results"):
                count = c.execute(
                    sql.SQL("SELECT count(*) AS n FROM design.{} WHERE operation_id=%s").format(
                        sql.Identifier(table)
                    ),
                    (message["operation_id"],),
                ).fetchone()["n"]
                assert count == 1
            assert (
                c.execute(
                    "SELECT count(*) AS n FROM model_calls WHERE operation_id=%s",
                    (message["operation_id"],),
                ).fetchone()["n"]
                == 0
            )
    finally:
        engine.STOP.set()
        thread.join(timeout=15)
        probe.close()
        assert not thread.is_alive(), "test consumer did not stop"
        engine.STOP.clear()
    assert not consumer_errors
