"""Opt-in real SIGKILL, natural leases, Kafka redelivery, and S3 restart.

Only the fresh fusion_full_native --suite transport-faults launcher can supply
the private process identities used here. Source records are synthetic fixtures
inserted through the nonowner API role; original bytes use real private S3.
No owner is used for business setup or recovery, and no lease clock is edited.
"""
# ruff: noqa: F401,F811

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess  # nosec B404
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from confluent_kafka import Consumer, TopicPartition
from psycopg import sql
from test_bid_package_api import attach
from test_fusion_full_native import DIRECTORY, RECEIPT, _pdf, native

from apps.worker import engine
from deploy import fusion_full_probe as probe
from deploy import fusion_full_runtime as runtime
from deploy import fusion_full_spec as spec
from packages.domain import document_parses, storage
from packages.domain.runtime import connection, sha

pytestmark = pytest.mark.skipif(
    not DIRECTORY
    or not RECEIPT
    or os.environ.get("FUSION_FULL_NATIVE_SUITE") != "transport-faults",
    reason="explicit fresh synthetic transport-faults native launcher required",
)

IDENTITY_FILES = (
    "apps/worker/engine.py",
    "apps/worker/document_parse_handlers.py",
    "packages/domain/document_parses.py",
    "packages/domain/document_parse_policy.py",
    "packages/domain/runtime.py",
    "packages/domain/storage.py",
    "packages/contracts/sql/worker-functions.sql",
    "tests/transport_fault_child.py",
    "tests/test_real_transport_fault_recovery.py",
)


def identities():
    return {name: sha((spec.fresh.ROOT / name).read_bytes()) for name in IDENTITY_FILES}


def eventually(callback, *, seconds=45, processes=()):
    deadline = time.monotonic() + seconds
    while True:
        assert all(process.poll() is None for process in processes), "runtime process exited"
        value = callback()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError("synthetic transport recovery deadline exceeded")
        time.sleep(0.1)


def phase(name):
    print(json.dumps({"transport_fault_phase": name}), flush=True)


@pytest.fixture(scope="module")
def fault_runtime(native):
    resources = spec.load_private_json(Path(os.environ["FUSION_FULL_NATIVE_RESOURCES"]))
    daemon_directory = Path(resources["daemon_directory"])
    assert daemon_directory.is_absolute() and daemon_directory.is_dir()
    assert daemon_directory.name.startswith("tender-full-daemons-")
    allowed = {
        component: runtime.environment(native["profiles"][spec.COMMANDS[component][0]], component)
        for component in ("api", "document", "relay", "reconcile")
    }
    for role in ("api", "worker", "relay", "reconcile"):
        assert probe.check(native["profiles"][role])["ready"]
    before = identities()
    # The API role creates fixtures; each subprocess gets only its own runtime
    # profile. The parent also observes stale-fence rejection as the worker.
    with pytest.MonkeyPatch.context() as patch:
        for key in tuple(os.environ):
            if key.endswith("_DSN") or key.startswith(("DEEPSEEK_", "PARSING_", "RAG_")):
                patch.delenv(key, raising=False)
        for key, value in allowed["api"].items():
            patch.setenv(key, value)
        patch.setenv("WORKER_DATABASE_DSN", allowed["document"]["WORKER_DATABASE_DSN"])
        phase("fresh_roles_and_real_transports_ready")
        yield native | {"resources": resources, "environments": allowed, "before": before}
    assert identities() == before, "tested worker/parser/fixture sources changed during acceptance"


def fixture_original():
    actor, bid, project, lot, round_id, bidder, document, blob = (uuid4() for _ in range(8))
    raw = _pdf() + f"\n% synthetic fault case {document}\n".encode()
    object_key = "synthetic-fault-original/" + str(blob)
    storage.put(object_key, raw, "application/pdf")
    assert storage.get(object_key) == raw
    with connection() as c:
        assert c.execute(
            "SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AS isolated FROM pg_roles WHERE rolname=current_user"
        ).fetchone()["isolated"]
        c.execute(
            "INSERT INTO members(id,display_name) VALUES(%s,'Synthetic fault operator')", (actor,)
        )
        c.execute(
            "INSERT INTO engineering_projects(id,title) VALUES(%s,'Synthetic fault project')",
            (project,),
        )
        c.execute(
            "INSERT INTO engineering_lots(id,engineering_project_id,label) VALUES(%s,%s,'Synthetic fault lot')",
            (lot, project),
        )
        c.execute(
            "INSERT INTO bid_rounds(id,engineering_project_id,lot_id,round_no) VALUES(%s,%s,%s,1)",
            (round_id, project, lot),
        )
        c.execute("INSERT INTO bidders(id,name) VALUES(%s,'Synthetic fault bidder')", (bidder,))
        c.execute(
            "INSERT INTO bids(id,title,settings,created_by) VALUES(%s,'Synthetic transport fault','{}',%s)",
            (bid, actor),
        )
        c.execute(
            "INSERT INTO bid_profiles(bid_id,round_id,bidder_id,phase) VALUES(%s,%s,%s,'working')",
            (bid, round_id, bidder),
        )
        c.execute("INSERT INTO stream_heads(id,bid_id) VALUES(%s,%s)", (uuid4(), bid))
        c.execute("INSERT INTO review_slots(bid_id,revision) VALUES(%s,1)", (bid,))
        c.execute(
            "INSERT INTO blobs(id,digest,object_key,byte_size,media_type) VALUES(%s,%s,%s,%s,'application/pdf')",
            (blob, sha(raw), object_key, len(raw)),
        )
        c.execute(
            "INSERT INTO document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic-fault.pdf',now(),'source_original',%s)",
            (document, bid, blob, actor),
        )
        attach(c, bid, actor, SimpleNamespace(document_version_id=document, file_digest=sha(raw)))
    context = document_parses.read_context(bid, document)
    ack, replayed = document_parses.start(
        bid,
        document,
        actor,
        uuid4().hex,
        {
            "context_digest": context["context_digest"],
            "reason": "Synthetic real transport fault acceptance",
        },
    )
    assert ack["status"] == 202 and not replayed
    request = ack["body"]["request"]
    return {
        "bid": str(bid),
        "document": str(document),
        "request": request["id"],
        "operation": request["operation"]["id"],
        "source_sha256": sha(raw),
        "object_key": object_key,
    }


@contextmanager
def processes(runtime_value):
    children, handles = [], []

    def spawn(mode, case):
        component = (
            "relay"
            if mode.startswith("relay")
            else "reconcile"
            if mode == "reconcile"
            else "document"
        )
        marker = runtime_value["directory"] / ("fault-" + uuid4().hex + ".json")
        log = os.fdopen(
            os.open(marker.with_suffix(".log"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        )
        handles.append(log)
        child = subprocess.Popen(
            [
                sys.executable,
                str(spec.fresh.ROOT / "tests/transport_fault_child.py"),
                mode,
                case["operation"],
                str(marker),
            ],
            cwd=spec.fresh.ROOT,
            env=runtime_value["environments"][component] | {"FUSION_SYNTHETIC_FAULT_CHILD": "1"},
            stdout=log,
            stderr=log,
        )  # nosec B603
        children.append(child)
        return child, marker

    try:
        yield spawn
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        for handle in handles:
            handle.close()


def snapshot(case):
    with connection() as c:
        return c.execute(
            """SELECT o.state,s.state AS receipt_state,s.attempt_count,s.fence,s.lease_until,s.output,
            s.lease_until<=clock_timestamp() AS lease_expired,p.dispatch_generation,
            (SELECT count(*) FROM document_parse_results r WHERE r.operation_id=o.id) AS result_count
            FROM operations o JOIN operation_steps p ON p.operation_id=o.id
            LEFT JOIN step_receipts s ON s.operation_id=p.operation_id AND s.step_key=p.step_key
            AND s.input_digest=p.input_digest WHERE o.id=%s""",
            (case["operation"],),
        ).fetchone()


def outbox(case):
    with connection() as c:
        return c.execute(
            """SELECT *,lease_until<=clock_timestamp() AS lease_expired,
            available_at<=clock_timestamp() AS due FROM outbox
            WHERE operation_id=%s ORDER BY (payload->>'generation')::integer DESC LIMIT 1""",
            (case["operation"],),
        ).fetchone()


def succeeded(case):
    state = snapshot(case)
    assert state["state"] not in {"failed", "cancelled"}, state
    return state if state["state"] == "succeeded" else None


def exactly_one(case, attempts):
    value = document_parses.read(case["bid"], case["document"], case["request"])
    assert value["operation"]["state"] == "succeeded"
    assert value["result"]["page_count"] == 2 and value["result"]["coverage"] == "partial"
    counts = {}
    with connection() as c:
        for table in ("step_receipts", "effect_receipts", "document_parse_results", "model_calls"):
            counts[table] = c.execute(
                sql.SQL("SELECT count(*) AS n FROM design.{} WHERE operation_id=%s").format(
                    sql.Identifier(table)
                ),
                (case["operation"],),
            ).fetchone()["n"]
        assert counts == {
            "step_receipts": 1,
            "effect_receipts": 1,
            "document_parse_results": 1,
            "model_calls": 0,
        }
        assert (
            c.execute(
                "SELECT count(*) AS n FROM audit_entries WHERE bid_id=%s AND event_type='operation.succeeded' AND payload->>'operation_id'=%s",
                (case["bid"], case["operation"]),
            ).fetchone()["n"]
            == 1
        )
        assert c.execute(
            "SELECT current_body_id,current_review_id FROM bid_profiles WHERE bid_id=%s",
            (case["bid"],),
        ).fetchone() == {"current_body_id": None, "current_review_id": None}
    assert snapshot(case)["attempt_count"] == attempts
    return counts


def marker(path, child):
    eventually(path.exists, processes=(child,))
    return json.loads(path.read_text())


def relay_once(spawn, case):
    child, path = spawn("relay-once", case)
    assert child.wait(timeout=45) == 0
    assert path.exists(), "actual relay did not ACK the expected operation"
    return json.loads(path.read_text())


def test_broker_ack_then_relay_sigkill_redelivers_once_after_real_claim_expiry(fault_runtime):
    phase("relay_sigkill_after_actual_broker_ack")
    case = fixture_original()
    with processes(fault_runtime) as spawn:
        worker, _ = spawn("worker", case)
        relay, path = spawn("relay-after-ack", case)
        first = marker(path, relay)
        relay.kill()
        assert relay.wait(timeout=5) == -signal.SIGKILL
        pending = outbox(case)
        assert pending["published_at"] is None and pending["publish_attempts"] == 1
        assert pending["lease_until"] is not None and not pending["lease_expired"]
        eventually(lambda: succeeded(case), processes=(worker,))
        started = time.monotonic()
        eventually(lambda: outbox(case)["lease_expired"], seconds=40, processes=(worker,))
        waited = time.monotonic() - started
        second = relay_once(spawn, case)
        assert second["partition"] == first["partition"] and second["offset"] > first["offset"]
        observer = Consumer(
            {
                "bootstrap.servers": fault_runtime["environments"]["document"][
                    "KAFKA_BOOTSTRAP_SERVERS"
                ],
                "group.id": "tender-document-worker-v1",
                "enable.auto.commit": False,
            }
        )
        try:
            eventually(
                lambda: observer.committed(
                    [TopicPartition(second["topic"], second["partition"])], timeout=5
                )[0].offset
                >= second["offset"] + 1,
                processes=(worker,),
            )
        finally:
            observer.close()
        settled = outbox(case)
        assert settled["published_at"] is not None and settled["publish_attempts"] == 2
        counts = exactly_one(case, 1)
    fault_runtime["checks"]["relay_crash_after_broker_ack"] = {
        "process_exit_signal": "SIGKILL",
        "broker_ack_observed_before_crash": True,
        "database_ack_missing_after_crash": True,
        "natural_claim_wait_seconds": round(waited, 3),
        "publish_attempts": 2,
        "actual_duplicate_offset_committed": True,
        "result_counts": counts,
    }


def test_worker_sigkill_after_real_compute_recovers_after_natural_lease_and_fences_old_result(
    fault_runtime,
):
    phase("worker_sigkill_after_actual_original_compute")
    case = fixture_original()
    with processes(fault_runtime) as spawn:
        crashed, path = spawn("worker-after-compute", case)
        relay_once(spawn, case)
        completed = marker(path, crashed)
        assert completed["actual_original_computed"] and completed["page_count"] == 2
        crashed.kill()
        assert crashed.wait(timeout=5) == -signal.SIGKILL
        before = snapshot(case)
        assert before["state"] == "running" and before["attempt_count"] == 1
        assert before["result_count"] == 0 and before["lease_until"] is not None
        assert not before["lease_expired"]
        worker, _ = spawn("worker", case)
        started = time.monotonic()
        phase("waiting_for_real_120_second_worker_lease")
        eventually(lambda: snapshot(case)["lease_expired"], seconds=135, processes=(worker,))
        waited = time.monotonic() - started
        assert waited >= 100, "real lease was shortened or recovery was delayed before observation"
        old_lease = completed["lease"] | {"owner": UUID(completed["lease"]["owner"])}
        assert engine.finish(completed["message"], old_lease, None) is False
        assert snapshot(case)["result_count"] == 0
        reconcile, _ = spawn("reconcile", case)
        eventually(
            lambda: outbox(case)["payload"]["generation"] == 2, processes=(worker, reconcile)
        )
        relay_once(spawn, case)
        after = eventually(lambda: succeeded(case), seconds=70, processes=(worker, reconcile))
        assert after["dispatch_generation"] == 2 and after["fence"] > before["fence"]
        assert engine.finish(completed["message"], old_lease, None) is False
        counts = exactly_one(case, 2)
    fault_runtime["checks"]["worker_crash_after_compute"] = {
        "process_exit_signal": "SIGKILL",
        "original_s3_and_pdf_computation_finished_before_crash": True,
        "unpublished_result_count_after_crash": 0,
        "natural_lease_wait_seconds": round(waited, 3),
        "ordinary_reconcile_and_new_kafka_delivery": True,
        "dispatch_generation": 2,
        "attempt_count": 2,
        "old_fence_rejected_before_and_after_recovery": True,
        "result_counts": counts,
    }


def test_real_private_s3_process_outage_records_retry_then_restart_preserves_original(
    fault_runtime,
):
    phase("actual_private_s3_process_outage")
    case = fixture_original()
    resources = fault_runtime["resources"]
    pid, directory = resources["s3_pid"], Path(resources["daemon_directory"])
    assert type(pid) is int and pid > 1
    command = (
        (Path("/proc") / str(pid) / "cmdline").read_bytes().rstrip(b"\x00").decode().split("\x00")
    )
    expected_weed = json.loads(os.environ["FUSION_FULL_NATIVE_TOOLS"])["weed"]
    assert command[0] == expected_weed and command[1] == "server"
    assert "-dir=" + str(directory) in command
    assert "-s3.config=" + str(directory / "s3-identities.json") in command
    assert (Path("/proc") / str(pid)).stat().st_uid == resources["uid"]
    endpoint = urlsplit(fault_runtime["environments"]["api"]["OBJECT_STORE_ENDPOINT"])
    assert endpoint.hostname == "127.0.0.1"
    replacement, log = None, None
    try:
        with processes(fault_runtime) as spawn:
            worker, _ = spawn("worker", case)
            os.kill(pid, signal.SIGKILL)

            def unavailable():
                with socket.socket() as client:
                    client.settimeout(0.2)
                    return client.connect_ex(("127.0.0.1", endpoint.port)) != 0

            eventually(unavailable, seconds=10)
            relay_once(spawn, case)

            def retry_recorded():
                value = snapshot(case)
                assert value["result_count"] == 0 and value["state"] != "succeeded"
                return value if value["receipt_state"] == "failed" else None

            failed = eventually(retry_recorded, seconds=90, processes=(worker,))
            assert (
                failed["attempt_count"] == 1
                and failed["output"]["error_code"] == "OBJECT_STORE_UNAVAILABLE"
            )
            assert failed["dispatch_generation"] == 2
            log = os.fdopen(
                os.open(
                    directory / "fault-s3-restart.log", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                ),
                "wb",
            )
            replacement = subprocess.Popen(
                command,
                cwd=directory,
                env={"PATH": os.defpath, "LANG": "C.UTF-8"},
                user=resources["uid"],
                group=resources["gid"],
                extra_groups=[],
                stdout=log,
                stderr=log,
            )  # nosec B603

            def restored():
                try:
                    return sha(storage.get(case["object_key"])) == case["source_sha256"]
                except Exception:
                    return False

            eventually(restored, seconds=45, processes=(worker, replacement))
            eventually(lambda: outbox(case)["due"], processes=(worker, replacement))
            relay_once(spawn, case)
            eventually(lambda: succeeded(case), processes=(worker, replacement))
            counts = exactly_one(case, 2)
        fault_runtime["checks"]["object_store_process_outage"] = {
            "actual_private_process_killed": True,
            "real_connection_failure": True,
            "persisted_error_code": "OBJECT_STORE_UNAVAILABLE",
            "result_count_during_outage": 0,
            "original_sha256_preserved_after_restart": True,
            "bounded_attempt_count": 2,
            "result_counts": counts,
        }
    finally:
        if replacement is not None:
            replacement.terminate()
            try:
                replacement.wait(timeout=15)
            except subprocess.TimeoutExpired:
                replacement.kill()
                replacement.wait(timeout=5)
        if log is not None:
            log.close()


def test_emit_fault_receipt_after_all_real_recovery_cases(fault_runtime):
    assert set(fault_runtime["checks"]) == {
        "relay_crash_after_broker_ack",
        "worker_crash_after_compute",
        "object_store_process_outage",
    }
    assert identities() == fault_runtime["before"]
    spec.write_private(
        Path(RECEIPT),
        {
            "version": "fusion-real-transport-fault-recovery/1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "plan_digest": fault_runtime["receipt"]["plan_digest"],
            "ordered_sql": fault_runtime["receipt"]["ordered_sql"],
            "runtime": fault_runtime["receipt"]["runtime"],
            "source_sha256": fault_runtime["before"],
            "checks": fault_runtime["checks"],
            "fixture_provenance": "synthetic source records through nonowner API role; real S3 bytes, Kafka and ordinary worker",
            "only_synthetic_originals": True,
            "shared_pg55441_used": False,
            "lease_or_database_clock_modified": False,
            "provider_calls": 0,
            "paid_failure_semantics_verified": False,
            "docker_execution_verified": False,
            "production_rpo_rto_verified": False,
            "production_qualification": False,
        },
    )
