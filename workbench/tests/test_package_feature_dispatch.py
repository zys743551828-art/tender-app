"""Fixed plans and bounded dispatch against a simulated native channel.

Actual /3 material consumers run in the pipeline test; SQL authority/transactions
still require the separate opt-in PG acceptance environment.
"""
# ruff: noqa: F811

import json
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import psycopg
import pytest
from test_package_feature_evaluation import evaluation_base  # noqa: F401
from test_package_feature_final import material_base  # noqa: F401
from test_package_feature_training_io import cohort  # noqa: F401

from deploy import package_history_dispatcher as cli
from packages.domain.review_identity import canonical, digest
from packages.model_governance import package_feature_dispatch as feature
from packages.model_governance import package_history_dispatch as dispatch
from packages.model_governance import package_history_runtime as runtime
from packages.model_governance.common import GovernanceError
from packages.storage.private_cas import PrivateContentStore


def private(path, value):
    path.write_bytes(canonical(value))
    path.chmod(0o600)
    return path


def plan_file(tmp_path, purpose="train", methods=None):
    store = tmp_path / "store"
    index = tmp_path / "index"
    store.mkdir(mode=0o700, exist_ok=True)
    index.mkdir(mode=0o700, exist_ok=True)
    row = {
        "job_id": str(uuid4()),
        "cohort_id": str(uuid4()),
        "membership_digest": "a" * 64,
        "reference_digest": "b" * 64,
        "candidate_digest": None if purpose == "train" else "c" * 64,
        "methods": methods or feature.methods(),
        "references": str(tmp_path / "references"),
        "material_store": str(store),
        "artifact_dir": str(index),
    }
    document = {"version": feature.VERSION, "purpose": purpose, "jobs": [row]}
    return private(tmp_path / "plan", document), document


def test_plan_is_exact_snapshot_and_default_cli_has_no_feature_mode(tmp_path):
    path, document = plan_file(tmp_path)
    loaded = feature.load(path, digest(document), "train")
    path.write_bytes(b"{}")
    assert loaded.raw == canonical(document) and loaded.digest == digest(document)
    args = cli.arguments(["--purpose", "train", "--owned-child"])
    assert args.feature_plan is None and args.cycles == 1 and args.batch_size == 5
    with pytest.raises(GovernanceError):
        feature.load(path, digest(document), "train")


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "method",
        "unknown",
        "version",
        "purpose",
        "relative",
        "traversal",
        "nul",
        "candidate",
        "job",
        "count",
        "labels",
        "exposed",
    ],
)
def test_plan_rejects_ambiguous_or_unpinned_configuration(tmp_path, change):
    path, doc = plan_file(tmp_path)
    row = doc["jobs"][0]
    if change == "duplicate":
        doc["jobs"].append(deepcopy(row))
    elif change == "method":
        row["methods"]["training"] = "f" * 64
    elif change == "unknown":
        row["credential"] = "forbidden"
    elif change == "version":
        doc["version"] = "future/2"
    elif change == "purpose":
        doc["purpose"] = "evaluate"
    elif change == "relative":
        row["references"] = "relative"
    elif change == "traversal":
        row["artifact_dir"] = "/tmp/../private"
    elif change == "nul":
        row["references"] = "/tmp/\x00"
    elif change == "candidate":
        row["candidate_digest"] = "c" * 64
    elif change == "job":
        row["job_id"] = "not-a-job"
    elif change == "count":
        doc["jobs"] = []
    elif change == "labels":
        doc["labels"] = {"target": "80"}
    elif change == "exposed":
        doc["exposed"] = True
    private(path, doc)
    with pytest.raises(GovernanceError):
        feature.load(path, digest(doc), "train")


def test_plan_symlink_and_insecure_mode_refused(tmp_path):
    path, doc = plan_file(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises((GovernanceError, OSError)):
        feature.load(link, digest(doc), "train")
    path.chmod(0o644)
    with pytest.raises(GovernanceError):
        feature.load(path, digest(doc), "train")


@pytest.mark.parametrize(
    "flags", [["--feature-plan", "/tmp/plan"], ["--expected-feature-plan-digest", "a" * 64]]
)
def test_plan_cli_requires_independent_digest(flags):
    with pytest.raises(SystemExit):
        cli.arguments(["--purpose", "train", "--owned-child", *flags])


def test_method_cli_is_credential_free():
    result = subprocess.run(
        [
            sys.executable,
            "deploy/package_history_worker.py",
            "--purpose",
            "feature-dispatch-method",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"]["methods"] == feature.methods()


@pytest.fixture
def plans(tmp_path, cohort, material_base, evaluation_base):
    root, index, _, _, _, _, refs = cohort
    final_refs = material_base[3]
    result = {}
    for purpose, references, number in [("train", refs, 1), ("evaluate", final_refs, 2)]:
        path, doc = plan_file(tmp_path, purpose)
        row = doc["jobs"][0]
        row.update(
            job_id=str(UUID(int=number)),
            cohort_id=references["cohort_id"],
            membership_digest=references["membership_digest"],
            reference_digest=digest(references),
            candidate_digest=references.get("candidate_digest"),
            references=str(private(tmp_path / (purpose + "-refs"), references)),
            material_store=str(root),
            artifact_dir=str(index),
        )
        path = private(tmp_path / (purpose + "-plan"), doc)
        result[purpose] = (feature.load(path, digest(doc), purpose), row)
    return result


class NativeChannel:
    """Simulated existing queue/lease/binding boundary, not native acceptance."""

    def __init__(self, plans, cohort, evaluation_base):
        self.nodes = {
            purpose: {
                "row": row,
                "state": "queued",
                "generation": 1,
                "binding": None,
                "frozen": None,
                "result": None,
            }
            for purpose, (_, row) in plans.items()
        }
        self.export = cohort[5]
        self.final = deepcopy(evaluation_base)
        self.events = []
        self.exposed = False
        self.fault = None

    @contextmanager
    def connection(self, purpose):
        channel = self

        class Connection:
            def execute(self, query, args):
                node = channel.nodes[purpose]
                if "dispatch_candidates" in query:
                    candidate = {
                        "job_id": node["row"]["job_id"],
                        "generation": node["generation"],
                        "created_at": "2026-10-26T00:00:00+00:00",
                    }
                    self.value = (
                        [candidate]
                        if node["state"] == "queued"
                        and (args[2] is None or UUID(candidate["job_id"]) > args[2])
                        else []
                    )
                elif "claim_job" in query:
                    if channel.fault == "lease":
                        raise psycopg.errors.ObjectNotInPrerequisiteState("synthetic live lease")
                    assert str(args[0]) == node["row"]["job_id"] and args[1] == node["generation"]
                    channel.events.append((purpose, "claim"))
                    self.value = {
                        "job_id": node["row"]["job_id"],
                        "state": node["state"] if node["state"] == "succeeded" else "running",
                        "generation": node["generation"],
                        "fence": node["generation"],
                        "dispatch_binding": deepcopy(node["binding"]),
                    }
                    if node["state"] == "succeeded":
                        self.value["result_digest"] = digest(node["result"])
                    elif purpose == "evaluate":
                        self.value.update(
                            feature_final_input=deepcopy(channel.final["feature_final"]["input"]),
                            feature_final_frozen=deepcopy(node["frozen"]),
                        )
                elif "read_training" in query:
                    assert node["binding"] is not None
                    channel.events.append((purpose, "material"))
                    self.value = deepcopy(channel.export)
                elif "finish_job" in query:
                    payload = deepcopy(args[-2].obj)
                    if payload.get("schema") == feature.BINDING:
                        if node["binding"] is not None:
                            assert node["binding"] == payload
                        if purpose == "evaluate":
                            assert (
                                payload["methods"] == channel.nodes["train"]["binding"]["methods"]
                            )
                        node["binding"] = payload
                        channel.events.append((purpose, "bound"))
                        if channel.fault == "binding_ack":
                            channel.fault = None
                            raise psycopg.OperationalError("synthetic committed binding ACK loss")
                    elif payload.get("schema") == "package-history-feature-final-predictions/1":
                        assert node["binding"] is not None and not channel.exposed
                        node["frozen"] = payload
                        node["state"] = "queued"
                        channel.events.append((purpose, "frozen"))
                        if channel.fault == "freeze_ack":
                            channel.fault = None
                            raise psycopg.OperationalError("synthetic committed freeze ACK loss")
                    else:
                        assert node["binding"] is not None
                        node["result"] = payload
                        node["state"] = "succeeded"
                        channel.events.append((purpose, "result"))
                elif "open_final" in query:
                    assert node["frozen"] is not None and node["binding"] is not None
                    channel.exposed = True
                    channel.events.append((purpose, "exposed"))
                elif "read_final" in query:
                    assert channel.exposed
                    self.value = deepcopy(channel.final)
                    self.value["feature_final"]["predictions"] = deepcopy(node["frozen"])
                    self.value["feature_final"]["predictions_digest"] = digest(node["frozen"])
                elif "renew_job" not in query:
                    pytest.fail(query)
                return self

            def fetchone(self):
                return {"value": self.value}

        yield Connection()


def test_actual_consumers_progress_train_freeze_then_evaluate_without_refit(
    plans, cohort, evaluation_base, monkeypatch
):
    channel = NativeChannel(plans, cohort, evaluation_base)
    monkeypatch.setattr(runtime, "connection", channel.connection)
    train, train_row = plans["train"]
    final, final_row = plans["evaluate"]
    _, result = dispatch.cycle("train", feature_plan=train)
    assert result["schema"] == "package-history-dispatch-cycle/2" and result["completed"] == 1
    assert channel.events.index(("train", "bound")) < channel.events.index(("train", "material"))
    assert (
        channel.nodes["train"]["result"]["complete_feature_training"]
        == evaluation_base["feature_final"]["input"]["candidate"]
    )
    receipt = train.run(UUID(train_row["job_id"]), 1)
    assert receipt["state"] == "succeeded" and channel.events.count(("train", "material")) == 1
    cursor, result = dispatch.cycle("evaluate", feature_plan=final)
    assert result["staged"] == 1 and result["completed"] == 0 and not channel.exposed
    cursor, empty = dispatch.cycle("evaluate", feature_plan=final, after=cursor)
    assert cursor is None and empty["scanned"] == 0
    _, result = dispatch.cycle("evaluate", feature_plan=final)
    assert result["completed"] == 1 and channel.exposed
    assert channel.events.count(("evaluate", "frozen")) == 1
    assert (
        channel.nodes["evaluate"]["result"]["feature_final_evaluation"]["formal_prediction"] is None
    )
    with PrivateContentStore(train_row["material_store"]) as store:
        assert store.get_object(train.digest) == train.raw
        assert store.get_object(final.digest) == final.raw


@pytest.mark.parametrize("fault", ["binding_ack", "freeze_ack", "lease"])
def test_retry_recovers_original_binding_and_frozen_stage(
    plans, cohort, evaluation_base, monkeypatch, fault
):
    channel = NativeChannel(plans, cohort, evaluation_base)
    train, train_row = plans["train"]
    final, final_row = plans["evaluate"]
    channel.nodes["train"]["binding"] = feature.binding(train_row, "train")
    channel.nodes["train"]["state"] = "succeeded"
    channel.fault = fault
    monkeypatch.setattr(runtime, "connection", channel.connection)
    # Frozen projection output itself is already checked with actual /3 above.
    from packages.model_governance import package_feature_final as frozen

    monkeypatch.setattr(
        frozen, "run", lambda *a: deepcopy(evaluation_base["feature_final"]["predictions"])
    )
    if fault == "lease":
        _, result = dispatch.cycle("evaluate", feature_plan=final)
        assert (
            result["outcomes"][0]["state"] == "deferred"
            and channel.nodes["evaluate"]["binding"] is None
        )
        channel.fault = None
    else:
        with pytest.raises(psycopg.OperationalError):
            final.run(UUID(final_row["job_id"]), 1)
    channel.nodes["evaluate"]["generation"] = 2
    receipt = final.run(UUID(final_row["job_id"]), 2)
    assert receipt["state"] == ("succeeded" if fault == "freeze_ack" else "predictions_frozen")
    assert channel.nodes["evaluate"]["binding"] == feature.binding(final_row, "evaluate")


def test_unknown_job_never_falls_back_to_baseline_and_stop_is_respected(
    plans, cohort, evaluation_base, monkeypatch
):
    channel = NativeChannel(plans, cohort, evaluation_base)
    channel.nodes["train"]["row"] = dict(channel.nodes["train"]["row"], job_id=str(uuid4()))
    monkeypatch.setattr(runtime, "connection", channel.connection)
    _, result = dispatch.cycle("train", feature_plan=plans["train"][0])
    assert result["outcomes"][0]["state"] == "deferred" and channel.events == []
    stopped = Event()
    stopped.set()
    _, result = dispatch.cycle("train", feature_plan=plans["train"][0], stopped=stopped)
    assert result["attempted"] == 0 and channel.events == []


def test_bound_job_cannot_run_without_original_plan(plans, cohort, evaluation_base, monkeypatch):
    channel = NativeChannel(plans, cohort, evaluation_base)
    channel.nodes["train"]["binding"] = feature.binding(plans["train"][1], "train")
    monkeypatch.setattr(runtime, "connection", channel.connection)
    _, result = dispatch.cycle("train")
    assert result["schema"] == "package-history-dispatch-cycle/1"
    assert (
        result["outcomes"][0]["state"] == "deferred" and ("train", "material") not in channel.events
    )


@pytest.mark.parametrize("change", ["references", "methods", "binding", "completed_unbound"])
def test_stale_configuration_cannot_rebind_or_adopt_completed_work(
    plans, cohort, evaluation_base, monkeypatch, change
):
    channel = NativeChannel(plans, cohort, evaluation_base)
    plan, row = plans["train"]
    channel.nodes["train"]["binding"] = feature.binding(row, "train")
    monkeypatch.setattr(runtime, "connection", channel.connection)
    if change == "references":
        Path(row["references"]).write_bytes(b"{}")
    elif change == "methods":
        old = feature.methods()
        monkeypatch.setattr(feature, "methods", lambda: old | {"training": "f" * 64})
    elif change == "binding":
        channel.nodes["train"]["binding"]["reference_digest"] = "f" * 64
    else:
        channel.nodes["train"].update(state="succeeded", binding=None, result={})
    with pytest.raises(GovernanceError):
        plan.run(UUID(row["job_id"]), 1)
    assert ("train", "material") not in channel.events


def test_launcher_passes_plan_and_pin_without_adding_credentials(tmp_path, monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(
        "deploy.package_history_worker.environment",
        lambda *a: {"PACKAGE_HISTORY_TRAIN_DSN": "synthetic-test-only", "LANG": "C.UTF-8"},
    )
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=0),
    )
    result = cli.main(
        [
            "--purpose",
            "train",
            "--profile",
            str(tmp_path / "unused-profile"),
            "--feature-plan",
            str(tmp_path / "plan"),
            "--expected-feature-plan-digest",
            "a" * 64,
        ]
    )
    assert result == 0
    command, kwargs = calls[0]
    assert command[command.index("--feature-plan") + 1] == str(tmp_path / "plan")
    assert command[command.index("--expected-feature-plan-digest") + 1] == "a" * 64
    assert "--profile" not in command and set(kwargs["env"]) == {
        "PACKAGE_HISTORY_TRAIN_DSN",
        "LANG",
    }


def test_invalid_plan_stops_child_before_queue_or_private_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.signal, "signal", lambda *a: None)
    monkeypatch.setattr(
        dispatch, "cycle", lambda *a, **kw: pytest.fail("invalid plan reached queue")
    )
    path = private(tmp_path / "bad", {"private": "must-not-be-printed"})
    result = cli.main(
        [
            "--purpose",
            "train",
            "--owned-child",
            "--feature-plan",
            str(path),
            "--expected-feature-plan-digest",
            "a" * 64,
        ]
    )
    output = capsys.readouterr().out
    assert result == 2 and "PACKAGE_HISTORY_DISPATCH_UNAVAILABLE" in output
    assert "must-not-be-printed" not in output and str(path) not in output


def test_unavailable_binding_extension_cannot_fall_back_to_materials(
    plans, cohort, evaluation_base, monkeypatch
):
    channel = NativeChannel(plans, cohort, evaluation_base)
    original = channel.connection

    @contextmanager
    def old_connection(purpose):
        with original(purpose) as c:
            fetch = c.fetchone

            def read():
                result = fetch()
                if isinstance(result["value"], dict):
                    result["value"].pop("dispatch_binding", None)
                return result

            c.fetchone = read
            yield c

    monkeypatch.setattr(runtime, "connection", old_connection)
    row = plans["train"][1]
    with pytest.raises(GovernanceError, match="Native binding extension"):
        plans["train"][0].run(UUID(row["job_id"]), 1)
    assert ("train", "material") not in channel.events
