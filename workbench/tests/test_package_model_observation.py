"""Controlled synthetic observations; native PG authority is NOT simulated acceptance."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from test_package_feature_training_io import cohort  # noqa: F401 -- actual private CAS fixture
from test_package_model_registry import source

from packages.domain.review_identity import canonical, digest
from packages.model_governance.common import GovernanceError
from packages.package_model_observation import application, execution
from packages.package_model_registry import artifact
from packages.storage.private_cas import PrivateContentStore


def request(document):
    return {
        "version": application.VERSION,
        "command_id": str(uuid4()),
        "model_id": document["model_id"],
        "admission_id": str(uuid4()),
        "artifact_digest": digest(document),
        "method_digest": execution.method_digest(),
        "reference": dict.fromkeys(application.shape.REFERENCE, "a" * 64),
    }


class NativeChannel:
    """Only tests transaction orchestration, not native lock/role semantics."""

    def __init__(self):
        self.document = artifact.build(source())
        self.source_value = {"document": self.document, "revision": 1}
        self.receipt = None
        self.saved_request = None
        self.opens = 0
        self.active = False
        self.revoked = False

    @contextmanager
    def transactions(self):
        self.opens += 1
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def replay(self, actor, body):
        if actor != "owner":
            raise PermissionError("actor")
        if self.receipt and body != self.saved_request:
            raise ValueError("command reused")
        return self.receipt

    def source(self, actor, body):
        if self.revoked:
            raise ValueError("revoked")
        return deepcopy(self.source_value)

    def record(self, actor, body, pinned, result):
        if self.revoked or digest(self.source_value) != pinned:
            raise ValueError("source changed")
        if previous := self.replay(actor, body):
            return previous
        self.saved_request = deepcopy(body)
        self.receipt = {
            "result_digest": digest(result),
            "formal_eligibility": "unavailable",
            "historical_receipt": True,
        }
        return self.receipt


def test_short_transactions_replay_after_ack_loss_and_revocation():
    native = NativeChannel()
    body = request(native.document)
    calls = []

    def execute(snapshot, request):
        assert not native.active
        calls.append(request)
        return {"value": 12}

    service = application.Observations(native.transactions, execute)
    first = service.execute("owner", body)
    native.revoked = True
    assert service.execute("owner", body) == first
    assert len(calls) == 1 and native.opens == 3 and not native.active
    with pytest.raises(PermissionError):
        service.execute("other", body)
    with pytest.raises(ValueError):
        service.execute("owner", dict(body, artifact_digest="b" * 64))
    assert "value" not in first


@pytest.mark.parametrize(
    "attack", ["revoke", "drift", "mutate_snapshot", "mutate_request", "cpu_failure", "cancel"]
)
def test_concurrent_changes_and_failures_never_persist(attack):
    native = NativeChannel()

    def execute(snapshot, request):
        assert not native.active
        if attack == "revoke":
            native.revoked = True
        elif attack == "drift":
            native.source_value["revision"] += 1
        elif attack == "mutate_snapshot":
            snapshot["revision"] += 1
        elif attack == "mutate_request":
            request["artifact_digest"] = "c" * 64
        elif attack == "cpu_failure":
            raise ValueError("CPU failed")
        else:
            raise KeyboardInterrupt()
        return {"value": 12}

    service = application.Observations(native.transactions, execute)
    with pytest.raises((ValueError, GovernanceError, KeyboardInterrupt)):
        service.execute("owner", request(native.document))
    assert native.receipt is None and not native.active


@pytest.mark.parametrize("field", ["verified", "prediction", "value", "certification_issued"])
def test_client_cannot_supply_results(field):
    native = NativeChannel()
    body = request(native.document) | {field: True}
    with pytest.raises(GovernanceError):
        application.Observations(native.transactions, lambda *_: None).execute("owner", body)
    assert native.opens == 0


@pytest.fixture(scope="module")
def material(cohort):  # noqa: F811
    root, index, _, selection, _, export, _ = cohort
    # Deliberately independent synthetic model fixture, not this export's candidate.
    doc = artifact.build(source())
    body = request(doc)
    binding = deepcopy(export["material_bindings"][0])
    body["admission_id"] = binding["admission_id"]
    body["reference"] = selection["members"][0]["reference"]
    packet = {
        "schema": "package-native-observation-source/1",
        "document": doc,
        "binding": binding,
        "closure": [],
        "label_document_ids": [binding.pop("label_document_id")],
        "label_file_digests": [binding.pop("label_file_digest")],
    }
    return root, index, packet, body


def test_actual_private_material_is_consumed_without_provider_or_label_values(material):
    root, index, packet, body = material
    with PrivateContentStore(root) as store:
        result = execution.consume(packet, body, store, index)
        legacy_research = artifact.consume(
            packet["document"],
            store,
            index,
            body["reference"],
            expected_input_digest=body["reference"]["expected_input_digest"],
        )
    assert result["value"] == legacy_research["value"]
    assert result["intervals"] == legacy_research["intervals"]
    assert result["source_digest"] == digest(packet)
    assert result["mode"] == "retrospective_internal"
    assert not result["certification_issued"] and result["formal_eligibility"] == "unavailable"


@pytest.mark.parametrize(
    "attack",
    [
        "method",
        "model",
        "artifact",
        "scope",
        "manifest",
        "time",
        "original_digest",
        "original_size",
        "duplicate_original",
        "label_id",
        "label_digest",
        "origin",
        "reference",
        "input",
    ],
)
def test_original_identity_and_version_attacks_fail_closed(material, attack):
    root, index, packet, body = deepcopy(material)
    binding = packet["binding"]
    if attack in {"method", "artifact"}:
        body[attack + "_digest"] = "b" * 64
    elif attack == "model":
        body["model_id"] = str(uuid4())
    elif attack == "scope":
        binding["scope_id"] = str(uuid4())
    elif attack == "manifest":
        binding["scope_manifest"] = {}
    elif attack == "time":
        binding["submitted_at"] = "2000-01-01T00:00:00Z"
    elif attack == "original_digest":
        binding["originals"][0]["digest"] = "a" * 64
    elif attack == "original_size":
        binding["originals"][0]["byte_size"] += 1
    elif attack == "duplicate_original":
        binding["originals"].append(binding["originals"][0])
    elif attack == "label_id":
        packet["label_document_ids"].append(binding["originals"][0]["document_version_id"])
    elif attack == "label_digest":
        packet["label_file_digests"].append(binding["originals"][0]["digest"])
    elif attack == "origin":
        binding["origin"] = "external_evidence"
    elif attack == "reference":
        body["reference"]["expected_binding_digest"] = "e" * 64
    else:
        body["reference"]["expected_input_digest"] = "e" * 64
    with PrivateContentStore(root) as store, pytest.raises(GovernanceError):
        execution.consume(packet, body, store, index)


def test_cli_real_use_case_wiring_and_redacted_errors(monkeypatch, tmp_path, capsys):
    from deploy import package_model_observation as cli
    from packages.package_model_observation import infrastructure

    doc = artifact.build(source())
    body = request(doc)
    path = tmp_path / "request"
    path.write_bytes(canonical(body))
    path.chmod(0o600)
    calls = []

    def execute(self, actor, document):
        assert isinstance(self.transactions, infrastructure.NativeTransactions)
        assert isinstance(self.executor, execution.LocalExecutor)
        calls.append((actor, document))
        return {"historical_receipt": True, "formal_eligibility": "unavailable"}

    monkeypatch.setattr(application.Observations, "execute", execute)
    actor = str(uuid4())
    monkeypatch.setattr(
        "sys.argv",
        [
            "observe",
            "--request",
            str(path),
            "--expected-request-digest",
            digest(body),
            "--actor",
            actor,
            "--store",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path),
        ],
    )
    assert cli.main() == 0
    assert calls == [(actor, body)]
    assert "unavailable" in capsys.readouterr().out
    path.chmod(0o644)
    assert cli.main() == 2
    output = capsys.readouterr()
    assert str(path) not in output.out and not output.err
    assert len(calls) == 1


def test_application_architecture_and_sql_authority_boundary():
    root = Path(__file__).parents[1]
    tree = ast.parse((root / "packages/package_model_observation/application.py").read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name
        and any(
            part in name for part in ("psycopg", "fastapi", "infrastructure", "platform_runtime")
        )
        for name in imports
    )
    sql = (root / "deploy/sql/package-model-observation.sql").read_text()
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "current_proof(a.proof_id)" in sql and "package_model_registry.read(model,actor)" in sql
    assert sql.index("lock_scope(seeds)") < sql.index("registered:=package_model_registry.read")
    assert "related_entities(members) &&" in sql and "has_foreign_exposure" in sql
    assert "a.created_by IS DISTINCT FROM actor" in sql
    assert "source(actor,(body->>'model_id')" in sql
    assert "snapshot) IS DISTINCT FROM pinned" in sql
    assert "GRANT SELECT" not in sql and "GRANT INSERT" not in sql
    assert "label,value" not in sql and "label,maximum" not in sql
    assert "'historical_receipt',true,'current_authority_checked',false" in sql
