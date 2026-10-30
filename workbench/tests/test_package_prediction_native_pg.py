"""Disposable native prediction SQL acceptance; never a real model certification."""
# ruff: noqa: F811 -- shared pytest fixtures

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import test_package_history_pg as history
from test_package_prediction_reports import cohort, material, mirror  # noqa: F401

from deploy.extended_recovery import MATERIAL_SQL
from packages.domain.errors import DomainError
from packages.domain.runtime import connection
from packages.model_governance.common import GovernanceError
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks.storage import Objects
from packages.prediction_sandbox.application import Sandbox
from packages.prediction_sandbox.native import Transactions as SandboxTransactions

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_PREDICTION_NATIVE_PG") != "1",
    reason="explicit disposable prediction PG17 cluster required",
)

EXTENSIONS = (
    *MATERIAL_SQL,
    "deploy/sql/material-qualification.sql",
    "deploy/sql/material-qualified-execution.sql",
    "deploy/sql/package-history-complete-material.sql",
    "deploy/sql/package-history-feature-final.sql",
    "deploy/sql/package-history-feature-evaluation.sql",
    "deploy/sql/package-history-exposure-bridge.sql",
    "deploy/sql/package-model-registry.sql",
    "deploy/sql/package-model-admission.sql",
    "deploy/sql/package-model-observation.sql",
    "deploy/sql/package-model-route-v2.sql",
    "deploy/sql/package-business-shadow.sql",
    "deploy/sql/package-model-certification.sql",
    "deploy/sql/package-formal-prediction.sql",
    "deploy/sql/package-prediction-selection.sql",
)


@pytest.fixture(scope="module")
def database():
    source = history.database.__wrapped__()
    value = next(source)
    try:
        from deploy import extended_recovery
        from deploy.schema_plan import BASE_SQL

        installed = set(BASE_SQL) | set(history.EXTENSIONS)
        for item in extended_recovery.frozen_plan(prediction=True):
            if item.path not in installed:
                value["owner"].execute(item.content.decode())
        yield value
    finally:
        source.close()


def test_native_prediction_install_and_worker_cannot_read_results(database):
    with psycopg.connect(database["worker_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM package_prediction.results")


@pytest.fixture
def api(database):
    from test_stable_lot_identity import api as original

    source = original.__wrapped__(database)
    try:
        yield next(source)
    finally:
        source.close()


def native_bid(api):
    from test_stable_lot_identity import catalog, post

    project, lot, round_value, bidder = catalog(api)
    response = post(
        api,
        "/bids",
        {
            "title": "Synthetic prediction transport",
            "engineering_project_id": project["id"],
            "lot_id": lot["id"],
            "round_id": round_value["id"],
            "bidder_id": bidder["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_native_http_missing_certificate_never_queues(api, monkeypatch):
    from uuid import uuid4

    from test_stable_lot_identity import headers

    from packages.domain.runtime import connection
    from packages.package_prediction_tasks.application import Jobs
    from packages.package_prediction_tasks.native import Transactions
    from packages.package_prediction_tasks.storage import Objects

    monkeypatch.setattr(
        api["app"].state,
        "package_prediction_jobs",
        Jobs(Transactions(connection), Objects()),
        raising=False,
    )
    bid = native_bid(api)
    scope, certificate, command = [str(uuid4()) for _ in range(3)]
    with connection() as c:
        before = c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"]
    path = f"/api/v1/bids/{bid}/technical-scopes/{scope}/prediction-tasks"
    body = {"certificate_id": certificate, "command_id": command}
    for _ in range(2):
        response = api["client"].post(path, json=body, headers=headers(api))
        assert response.status_code in {403, 409}, response.text
    with connection() as c:
        assert c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"] == before
        assert (
            api["database"]["owner"]
            .execute("SELECT count(*) AS n FROM package_prediction.results")
            .fetchone()["n"]
            == 0
        )


def test_native_selection_denies_unknown_actor(database):
    from uuid import uuid4

    with psycopg.connect(database["api_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(
                "SELECT package_prediction.eligible_certificates(%s,%s,%s,%s,%s)",
                (uuid4(), uuid4(), uuid4(), "a" * 64, "b" * 64),
            )


def test_real_private_objects_roundtrip_and_corruption(monkeypatch):
    if os.environ.get("FUSION_PREDICTION_NATIVE_TRANSPORT") != "1":
        pytest.skip("real isolated S3 required")
    from packages.domain import storage
    from packages.model_governance.common import GovernanceError
    from packages.package_prediction_tasks.storage import Objects

    store = Objects()
    value = {"source": "synthetic transport fixture", "result": "not certified"}
    reference = store.put(value)
    assert store.get(reference) == value
    assert storage.client().head_object(Bucket=storage.bucket(), Key="blobs/" + reference)
    storage.put("blobs/" + reference, b"{}", "application/json")
    with pytest.raises(GovernanceError):
        store.get(reference)


def test_real_outbox_kafka_worker_rejects_unconfigured_prediction(api, database, monkeypatch):
    """Transport injection is explicit; this is NOT an approved prediction submission."""
    if os.environ.get("FUSION_PREDICTION_NATIVE_TRANSPORT") != "1":
        pytest.skip("real isolated S3/Kafka required")
    import json
    import time
    from uuid import uuid4

    from confluent_kafka import Consumer

    from apps.worker import engine
    from packages.domain.runtime import connection
    from packages.package_prediction_tasks import worker
    from packages.package_prediction_tasks.native import Transaction
    from packages.package_prediction_tasks.storage import Objects

    monkeypatch.setenv("WORKER_DATABASE_DSN", database["worker_dsn"])
    monkeypatch.setattr(worker, "_executor", None)
    monkeypatch.setattr(worker, "_store", None)
    body = {k: str(uuid4()) for k in ("bid", "scope", "certificate", "command")}
    body["actor"] = api["actor"]
    body["bid"] = native_bid(api)
    reference = Objects().put({"schema": "synthetic-transport-only/1"})
    with connection() as c:
        # Exercise native enqueue/outbox without claiming an absent certificate is valid.
        queued = Transaction(c).enqueue(body, reference, "a" * 64)
    consumer = Consumer(
        {
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "group.id": "prediction-native-" + uuid4().hex,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    try:
        consumer.subscribe(["tender.task.review.v1"])
        engine.relay(once=True)
        deadline = time.monotonic() + 30
        message = None
        while time.monotonic() < deadline:
            delivered = consumer.poll(1)
            if delivered is not None and not delivered.error():
                candidate = json.loads(delivered.value())
                if candidate["operation_id"] == queued["operation_id"]:
                    message = candidate
                    break
        assert message is not None
        engine.handle(message)
        engine.handle(message)  # duplicate delivery must not create a result
        assert engine.acquire(message) is None
        with connection() as c:
            row = c.execute(
                "SELECT o.state,r.output->>'error_code' AS error_code FROM design.operations o JOIN design.step_receipts r ON r.operation_id=o.id WHERE o.id=%s",
                (queued["operation_id"],),
            ).fetchone()
            assert row["state"] == "failed", row
            assert row["error_code"] == "PREDICTION_WORKER_DISABLED"
            assert (
                api["database"]["owner"]
                .execute("SELECT count(*) AS n FROM package_prediction.results")
                .fetchone()["n"]
                == 0
            )
        consumer.commit(asynchronous=False)
    finally:
        consumer.close()


def test_native_route_v2_valid_actor_rejects_malformed_command(api):
    from psycopg.types.json import Jsonb

    from packages.domain.runtime import connection

    with connection() as c:
        with pytest.raises(psycopg.errors.InvalidParameterValue, match="request_invalid"):
            c.execute("SELECT package_model_route.prepare(%s,%s)", (api["actor"], Jsonb({})))


def test_native_prediction_offline_restore_includes_private_refs(
    api, database, monkeypatch, tmp_path
):
    """Real pg_dump/restore and S3; synthetic pending/results, never resume a queue."""
    if not os.environ.get("FUSION_PREDICTION_PG_CONTAINER"):
        pytest.skip("disposable launcher-owned PG and real S3 required")
    import secrets
    import subprocess
    from uuid import uuid4

    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg.types.json import Jsonb

    from deploy import completion_recovery, extended_recovery, prediction_recovery_profile
    from deploy.backups import run
    from packages.domain import storage
    from packages.domain.runtime import connection
    from packages.package_prediction_tasks.native import Transaction
    from packages.package_prediction_tasks.storage import Objects

    monkeypatch.setattr(run, "ARCHIVE_ROOT", tmp_path)
    body = {key: str(uuid4()) for key in ("scope", "certificate", "command")}
    body.update(actor=api["actor"], bid=native_bid(api))
    inputs, results = {"synthetic": "private input"}, {"synthetic": "private output"}
    source_ref, result_ref = Objects().put(inputs), Objects().put(results)
    with connection() as c:
        queued = Transaction(c).enqueue(body, source_ref, "a" * 64)
        c.execute(
            "INSERT INTO design.effect_receipts(operation_id,effect_key,result) VALUES(%s,%s,%s)",
            (
                queued["operation_id"],
                "compute-package-prediction",
                Jsonb({"input_ref": source_ref, "result_ref": result_ref}),
            ),
        )
        c.execute(
            "INSERT INTO design.step_receipts(operation_id,step_key,input_digest,fence,attempt_count,state,output) VALUES(%s,%s,%s,1,1,'succeeded',%s)",
            (
                queued["operation_id"],
                "compute-package-prediction",
                source_ref,
                Jsonb({"input_ref": source_ref, "result_ref": result_ref}),
            ),
        )
        c.execute(
            "UPDATE design.operations SET state='succeeded',finished_at=clock_timestamp() WHERE id=%s",
            (queued["operation_id"],),
        )
    reader = "prediction_recovery_reader_" + uuid4().hex[:10]
    password = secrets.token_urlsafe(32)
    owner = database["owner"]
    owner_dsn = make_conninfo(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], dbname=owner.info.dbname)
    reader_dsn = make_conninfo(owner_dsn, user=reader, password=password)
    target = None
    restored_bucket = None
    owner.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(reader), sql.Literal(password)
        )
    )
    for row in owner.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'"
    ).fetchall():
        schema = sql.Identifier(row["nspname"])
        owner.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, sql.Identifier(reader))
        )
        owner.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                schema, sql.Identifier(reader)
            )
        )
        owner.execute(
            sql.SQL("GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                schema, sql.Identifier(reader)
            )
        )

    def tool(container, executable, dsn, args, **kwargs):
        assert executable in {"pg_dump", "pg_restore"}
        values = conninfo_to_dict(dsn)
        assert values["host"] == "127.0.0.1"
        env = os.environ | {"PGPASSWORD": values["password"]}
        command = [
            "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD",
            os.environ["FUSION_PREDICTION_PG_CONTAINER"],
            executable,
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            values["user"],
        ]
        if executable == "pg_dump":
            command += ["--dbname=" + values["dbname"]]
        return subprocess.run(command + args, env=env, check=True, **kwargs)

    directory = tmp_path / "archive"
    values = {"API_DATABASE_DSN": reader_dsn, "OWNER_DATABASE_DSN": owner_dsn}
    client, bucket = storage.client(), storage.bucket()
    try:
        manifest = extended_recovery.snapshot(
            values,
            directory,
            extended_recovery.frozen_plan(prediction=True),
            prediction=True,
            object_client=client,
            object_bucket=bucket,
            tool=tool,
        )
        keys = {row["key"] for row in manifest["objects"]}
        assert {"blobs/" + source_ref, "blobs/" + result_ref} <= keys
        assert {"package_prediction", "package_model_admission", "package_model_registry"} <= {
            table["schema"] for table in manifest["tables"]
        }
        originals = completion_recovery.archive_originals(directory, manifest, client, bucket)
        damaged = directory / originals["objects"][0]["file"]
        original_bytes = damaged.read_bytes()
        damaged.write_bytes(original_bytes + b"tampered")
        with pytest.raises(run.BackupError, match="ORIGINAL_BYTES_CHANGED"):
            extended_recovery.restore_database(values, directory, tool=tool)
        damaged.write_bytes(original_bytes)
        receipt = extended_recovery.restore_database(values, directory, tool=tool)
        target = receipt["database"]
        from extended_recovery_helpers import s3

        admin_client = s3(admin=True)
        object_receipt = extended_recovery.restore_objects(directory, admin_client, bucket)
        restored_bucket = object_receipt["target_bucket"]
        for reference in (source_ref, result_ref):
            content = admin_client.get_object(Bucket=restored_bucket, Key="blobs/" + reference)[
                "Body"
            ].read()
            assert run.digest(content) == reference
        assert receipt["format"] == prediction_recovery_profile.FORMAT
        assert receipt["all_table_rows_sha256_verified"]
        assert receipt["all_runtime_write_and_execute_privileges_removed"]
        assert not receipt["old_queue_resume_qualified"]
        with psycopg.connect(make_conninfo(reader_dsn, dbname=target)) as c:
            assert c.execute("SELECT count(*) FROM package_prediction.results").fetchone() == (0,)
            assert c.execute("SHOW transaction_read_only").fetchone() == ("on",)
            assert c.execute(
                "SELECT has_table_privilege(current_user,'package_prediction.results','DELETE')"
            ).fetchone() == (False,)
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                c.execute("DELETE FROM package_prediction.results")
    finally:
        if restored_bucket:
            for item in admin_client.list_objects_v2(Bucket=restored_bucket).get("Contents", []):
                admin_client.delete_object(Bucket=restored_bucket, Key=item["Key"])
            admin_client.delete_bucket(Bucket=restored_bucket)
        with psycopg.connect(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], autocommit=True) as c:
            if target:
                c.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(target)))
        owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(reader)))
        owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(reader)))


def test_real_worker_restart_preserves_private_computation(api, database, mirror, monkeypatch):
    """Synthetic source computes in a fresh process; absent certification still blocks publish."""
    import json
    import subprocess
    import sys
    from uuid import uuid4

    from packages.domain.review_identity import digest
    from packages.domain.runtime import connection
    from packages.package_model_certification.policy import method_digest as certificate_method
    from packages.package_prediction.application import method_digest
    from packages.package_prediction_tasks.application import HANDLER, task_method
    from packages.package_prediction_tasks.native import Transaction
    from packages.package_prediction_tasks.storage import Objects

    if os.environ.get("FUSION_PREDICTION_NATIVE_TRANSPORT") != "1":
        pytest.skip("real isolated services required")
    root, index, material_packet = mirror
    assert material_packet["source"]["mode"] == "synthetic"
    body = {k: str(uuid4()) for k in ("scope", "certificate", "command")}
    body.update(actor=api["actor"], bid=native_bid(api))
    packet = {
        "authority": {
            "source": {
                "current_source": material_packet["source"],
                "model": material_packet["artifact"],
            }
        },
        "reference": material_packet["reference"],
    }
    frozen = {
        "schema": HANDLER,
        "task_method": task_method(),
        "body": body,
        "packet": packet,
        "prediction_method": method_digest(),
        "certificate_method": certificate_method(),
    }
    reference = Objects().put(frozen)
    with connection() as c:
        queued = Transaction(c).enqueue(body, reference, digest(packet))
        message = c.execute(
            "SELECT payload FROM design.outbox WHERE operation_id=%s", (queued["operation_id"],)
        ).fetchone()["payload"]
    child = """
import json,sys
from apps.worker import engine
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks import worker
worker.configure(Executor(sys.argv[1], sys.argv[2]))
engine.handle(json.loads(sys.stdin.read()))
"""
    environment = os.environ | {"WORKER_DATABASE_DSN": database["worker_dsn"]}
    for _ in range(2):
        subprocess.run(
            [sys.executable, "-c", child, str(root), str(index)],
            input=json.dumps(message),
            text=True,
            env=environment,
            check=True,
            capture_output=True,
        )
    with connection() as c:
        assert (
            c.execute(
                "SELECT state FROM design.operations WHERE id=%s", (queued["operation_id"],)
            ).fetchone()["state"]
            == "succeeded"
        )
        effects = c.execute(
            "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='compute-package-prediction'",
            (queued["operation_id"],),
        ).fetchall()
        assert len(effects) == 1
        result = Objects().get(effects[0]["result"]["result_ref"])
        assert result["mode"] == "synthetic" and result["formal_eligibility"] == "unavailable"
        assert not result["certification_issued"]

    api_child = r"""
import json,sys
from fastapi.testclient import TestClient
from apps.api.main import app
from packages.domain.runtime import connection
from packages.package_prediction_tasks.application import Jobs
from packages.package_prediction_tasks.native import Transactions
from packages.package_prediction_tasks.storage import Objects
value=json.loads(sys.stdin.read()); body=value['body']
app.state.package_prediction_jobs=Jobs(Transactions(connection),Objects())
path=f"/api/v1/bids/{body['bid']}/technical-scopes/{body['scope']}/prediction-tasks/{body['command']}"
with TestClient(app) as client:
    client.cookies.update(value['cookies'])
    if value['advance']:
        response=client.post(path+'/advance',json={},headers={'Origin':'http://identity-v2.test','X-CSRF-Token':value['csrf']})
    else:
        response=client.get(path)
    assert response.status_code==200,response.text
    print(json.dumps(response.json()))
"""
    payload = {"body": body, "cookies": dict(api["client"].cookies), "csrf": api["csrf"]}
    recovered = []
    for advance in (True, False):
        completed = subprocess.run(
            [sys.executable, "-c", api_child],
            input=json.dumps(payload | {"advance": advance}),
            text=True,
            env=environment,
            check=True,
            capture_output=True,
        )
        recovered.append(json.loads(completed.stdout))
    assert all(value["state"] == "blocked" and not value["prediction_ready"] for value in recovered)
    assert recovered[0] == recovered[1]
    assert (
        api["database"]["owner"]
        .execute("SELECT count(*) AS n FROM package_prediction.results")
        .fetchone()["n"]
        == 0
    )


@pytest.fixture(scope="module")
def installed(database):
    database["owner"].execute((ROOT / "deploy/sql/prediction-sandbox.sql").read_text())
    return database


@pytest.fixture
def sandbox(api, installed, mirror):
    root, index, packet = mirror
    bid = packet["source"]["bid_id"]
    # Source and CAS identity are unchanged. Only this new disposable database is seeded.
    template = native_bid(api)
    owner = installed["owner"]
    owner.execute(
        "INSERT INTO design.bids(id,title,settings,created_by) SELECT %s,'synthetic sandbox',settings,created_by FROM design.bids WHERE id=%s ON CONFLICT DO NOTHING",
        (bid, template),
    )
    owner.execute(
        "INSERT INTO design.bid_profiles(bid_id,round_id,bidder_id,phase) SELECT %s,round_id,bidder_id,'working' FROM design.bid_profiles WHERE bid_id=%s ON CONFLICT DO NOTHING",
        (bid, template),
    )
    service = Sandbox(SandboxTransactions(connection), Objects(), Executor(root, index))
    certificate = service.issue(
        api["actor"],
        bid,
        uuid4(),
        Objects().put(packet),
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    body = {
        "actor": api["actor"],
        "bid": bid,
        "scope": packet["source"]["scope_id"],
        "certificate": certificate["id"],
        "command": str(uuid4()),
    }
    return service, certificate, body


def child(args, value, *, worker=False):
    completed = subprocess.run(
        [sys.executable, *args],
        input=json.dumps(value),
        text=True,
        capture_output=True,
        env=os.environ | ({"WORKER_DATABASE_DSN": value["worker_dsn"]} if worker else {}),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_test_only_success_restart_duplicates_and_formal_refusal(
    sandbox, api, database, mirror, monkeypatch
):
    from test_stable_lot_identity import headers

    from packages.package_prediction_tasks.application import Jobs
    from packages.package_prediction_tasks.native import Transactions

    service, certificate, body = sandbox
    cancelled = body | {"command": str(uuid4())}
    service.submit(cancelled)
    assert service.cancel(cancelled)["state"] == "cancelled"
    with pytest.raises((DomainError, GovernanceError)):
        service.advance(cancelled)
    assert (
        service.issue(
            body["actor"],
            body["bid"],
            certificate["request"]["command_id"],
            certificate["request"]["source_ref"],
            certificate["request"]["valid_until"],
        )
        == certificate
    )
    queued = service.submit(body)
    assert service.submit(body) == queued  # lost submit ACK
    with connection() as c:
        message = c.execute(
            "SELECT payload FROM design.outbox WHERE operation_id=%s", (queued["operation_id"],)
        ).fetchone()["payload"]
    # Positive computation uses a broker-delivered outbox message, not a fabricated
    # direct transport. The uncommitted consumer ACK is deliberately recoverable.
    import time

    from confluent_kafka import Consumer

    from apps.worker import engine

    monkeypatch.setenv("WORKER_DATABASE_DSN", database["worker_dsn"])
    consumer = Consumer(
        {
            "bootstrap.servers": os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            "group.id": "prediction-test-success-" + uuid4().hex,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    try:
        consumer.subscribe(["tender.task.review.v1"])
        engine.relay(once=True)
        delivered_payload = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            delivered = consumer.poll(1)
            if delivered is not None and not delivered.error():
                candidate = json.loads(delivered.value())
                if candidate["operation_id"] == queued["operation_id"]:
                    delivered_payload = candidate
                    break
        assert delivered_payload == message
        message = delivered_payload
    finally:
        consumer.close()
    with connection() as c:
        assert (
            c.execute(
                "SELECT published_at IS NOT NULL AS published FROM design.outbox WHERE operation_id=%s",
                (queued["operation_id"],),
            ).fetchone()["published"]
            is True
        )
    root, index, _ = mirror
    program = """
import json,sys
from apps.worker import engine
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks import worker
v=json.loads(sys.stdin.read())
worker.configure(Executor(v['root'],v['index']))
engine.handle(v['message'])
"""
    for _ in range(2):
        child(
            ["-c", program],
            {
                "root": str(root),
                "index": str(index),
                "message": message,
                "worker_dsn": database["worker_dsn"],
            },
            worker=True,
        )
    # Two fresh application consumers resume the persisted operation and publication.
    arguments = [
        "-m",
        "packages.prediction_sandbox.cli",
        "--store",
        str(root),
        "--index",
        str(index),
    ]
    for key, value in body.items():
        arguments += ["--" + key, value]
    api_program = r"""
import json,sys
from fastapi.testclient import TestClient
from apps.api.prediction_sandbox import create_app
from packages.domain.runtime import connection
from packages.package_model_live.producer import Executor
from packages.package_prediction_tasks.storage import Objects
from packages.prediction_sandbox.application import Sandbox
from packages.prediction_sandbox.native import Transactions
v=json.loads(sys.stdin.read());b=v['body']
app=create_app(Sandbox(Transactions(connection),Objects(),Executor(v['root'],v['index'])))
with TestClient(app) as client:
    client.cookies.update(v['cookies'])
    base=f"/test-only/bids/{b['bid']}/tasks"
    payload={'command_id':b['command'],'scope_id':b['scope'],'certificate_id':b['certificate']}
    if v['advance']:
        response=client.post(base+'/advance',json=payload,headers={'Origin':'http://identity-v2.test','X-CSRF-Token':v['csrf']})
    else:
        response=client.get(base+'/'+b['command'],params={'scope_id':b['scope'],'certificate_id':b['certificate']})
    assert response.status_code==200,response.text
    assert response.headers['X-Prediction-Test-Only']=='true'
    assert response.headers['Cache-Control']=='private, no-store'
    print(json.dumps(response.json()))
"""
    application_input = {
        "root": str(root),
        "index": str(index),
        "body": body,
        "cookies": dict(api["client"].cookies),
        "csrf": api["csrf"],
    }
    published = [
        json.loads(child(["-c", api_program], application_input | {"advance": advance}))
        for advance in (True, False)
    ]
    assert json.loads(child(arguments + ["advance"], {})) == published[0]

    assert published[0] == published[1] == service.read(body)
    assert published[0]["state"] == "test_published"
    assert published[0]["result"]["test_only"] is True
    assert published[0]["result"]["production_eligible"] is False
    from packages.package_prediction.infrastructure import NativeTransactions
    from packages.package_prediction_reports.application import Reports

    for format in ("json", "docx"):
        with pytest.raises(GovernanceError):
            Reports(
                NativeTransactions(connection),
                lambda *args: pytest.fail("test result reached formal projector"),
            ).render(
                body["actor"],
                body["bid"],
                body["scope"],
                body["command"],
                format,
            )
    assert float(published[0]["result"]["value"]) >= 0
    assert certificate["test_only"] and not certificate["production_eligible"]
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.effect_receipts WHERE operation_id=%s",
                (queued["operation_id"],),
            ).fetchone()["n"]
            == 1
        )
    # Unmodified production consumer cannot promote the same task/certificate/result.
    api["app"].state.package_prediction_jobs = Jobs(Transactions(connection), Objects())
    path = f"/api/v1/bids/{body['bid']}/technical-scopes/{body['scope']}"
    response = api["client"].post(
        path + "/prediction-tasks",
        json={"command_id": str(uuid4()), "certificate_id": certificate["id"]},
        headers=headers(api),
    )
    assert response.status_code in {403, 409}
    assert (
        database["owner"]
        .execute("SELECT count(*) AS n FROM package_prediction.results")
        .fetchone()["n"]
        == 0
    )
    assert (
        database["owner"]
        .execute("SELECT count(*) AS n FROM package_model_admission.certificates")
        .fetchone()["n"]
        == 0
    )
    command = str(uuid4())
    service.revoke(body, command, "synthetic revocation")
    service.revoke(body, command, "synthetic revocation")
    assert service.read(body)["result"] is None
    with pytest.raises(DomainError):
        service.advance(body)


def test_permissions_identity_closed_request_and_cancellation(sandbox, database):
    service, certificate, body = sandbox
    with psycopg.connect(database["worker_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM prediction_sandbox.results")
    with psycopg.connect(database["api_dsn"]) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO prediction_sandbox.results DEFAULT VALUES")
    with pytest.raises(DomainError):
        service.submit(body | {"actor": str(uuid4())})
    with pytest.raises(DomainError):
        service.submit(body | {"scope": str(uuid4())})
    with service.transactions(body) as tx:
        with pytest.raises(DomainError):
            service.call(tx, body, "issue", {"verified": True})


def test_sandbox_expiry_and_dump_restore_cannot_rebind(sandbox, database):
    """Actual pg_dump/restore preserves evidence but cannot rebind its environment."""
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row

    service, certificate, body = sandbox
    container = os.environ["FUSION_PREDICTION_PG_CONTAINER"]
    source_name = database["owner"].info.dbname
    # No credentials in argv; tools use the disposable container's local socket.
    dump = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-U", "postgres", "-Fc", source_name],
        check=True,
        capture_output=True,
    ).stdout
    target = "fusion_sandbox_restore_" + uuid4().hex[:10]
    with psycopg.connect(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target))
        )
        try:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--exit-on-error",
                    "-d",
                    target,
                ],
                input=dump,
                check=True,
                capture_output=True,
            )
            with psycopg.connect(
                make_conninfo(database["api_dsn"], dbname=target), row_factory=dict_row
            ) as restored:
                with pytest.raises(
                    psycopg.errors.ObjectNotInPrerequisiteState, match="sandbox_environment_changed"
                ):
                    restored.execute(
                        "SELECT prediction_sandbox.operate(%s,%s,%s,'prepare','{}')",
                        (body["actor"], body["bid"], certificate["id"]),
                    )
            with psycopg.connect(
                make_conninfo(os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"], dbname=target)
            ) as restored:
                assert restored.execute(
                    "SELECT count(*) FROM package_prediction.results"
                ).fetchone() == (0,)
                assert restored.execute(
                    "SELECT count(*) FROM package_model_admission.certificates"
                ).fetchone() == (0,)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH(FORCE)").format(sql.Identifier(target)))
    # Expiry is tested with a server-evaluated deadline, not by changing authority rows.
    import time

    expiring = service.issue(
        body["actor"],
        body["bid"],
        uuid4(),
        certificate["request"]["source_ref"],
        (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat(),
    )
    # Deadline is frozen before material verification; CI needs a verification budget.
    # Still wait beyond the actual deadline and exercise the unmodified server clock.
    time.sleep(15.05)
    with pytest.raises(DomainError):
        service.submit(body | {"certificate": expiring["id"]})
