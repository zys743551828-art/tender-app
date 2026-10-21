"""Actual-input deduplication is independent of newly saved receipt navigation IDs."""
# ruff: noqa: F401,F811

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_package_fact_admission import case as admission_case
from test_package_scope_review import case, uid

from packages.domain import bid_package_scope_review as service
from packages.domain import package_fact_admission
from packages.domain import package_scope_review as review
from packages.domain import package_scope_review_identity as execution
from packages.domain.package_review_execution_identity import identify as prepared_identity
from packages.domain.review_identity import canonical, digest
from packages.domain.runtime import DomainError, sha


def sync(vector):
    m, records = vector["manifest"], vector["records"]
    original = m["execution_input"]["identity"]["binding"]
    m["scope"] = {
        key: original[key] for key in ("bid_id", "package_id", "revision_id", "inventory_id")
    }
    m["frozen_input"] = {
        "id": original["frozen_input_id"],
        "digest": original["frozen_digest"],
        "input_digest": original["input_digest"],
        "evidence_digest": original["evidence_digest"],
    }
    m["execution_input"]["identity"] = prepared_identity(
        original, m["execution_input"]["identity"]["rerun"]
    )
    for record in records:
        record["digest"] = digest(record["manifest"])
    m["fact_admission"]["fact_declarations"] = [
        {
            "fact_id": record["manifest"]["binding"]["fact_id"],
            "declaration_id": record["manifest"]["id"],
            "declaration_digest": record["digest"],
        }
        for record in records
    ]
    private = vector["proof"]
    by_id = {record["manifest"]["binding"]["fact_id"]: record for record in records}
    for selected in private["selected"]:
        if selected["fact_id"] in by_id:
            selected["declaration"] = deepcopy(by_id[selected["fact_id"]])
    m["fact_admission"]["proofs_digest"] = digest(private)
    m["executor_method"]["digest"] = digest(m["executor_method"]["profile"])
    return vector


@pytest.fixture
def vector(case, admission_case):
    admitted = package_fact_admission.admit(**admission_case)
    am = admitted.view()["manifest"]
    source = am["prepared"]
    original = admission_case["usage"].prepared_authority()["binding"]
    m = deepcopy(case["manifest"])
    m["execution_input"] = {
        "id": source["execution_input_id"],
        "digest": source["execution_input_digest"],
        "identity": prepared_identity(original),
    }
    m["usage_digest"] = am["usage_digest"]
    m["selected_facts_digest"] = am["selected_facts_digest"]
    m["fact_admission"] = {
        key: deepcopy(am[key])
        for key in ("content_digest", "proofs_digest", "policy_digest", "fact_declarations")
    }
    payload = review.model_input(case["root"], case["plan"], admitted)
    m["model_input_digest"] = review.model_digest(payload)
    return sync(
        {
            "manifest": m,
            "records": list(deepcopy(admission_case["declarations"]).values()),
            "proof": json.loads(admitted._proof_text),
            "payload": payload,
        }
    )


def key(vector):
    return execution.identify(vector["manifest"], vector["records"])


def test_new_equivalent_prepared_plan_and_scope_receipts_do_not_reexecute(vector):
    before = key(vector)
    other = deepcopy(vector)
    m = other["manifest"]
    m["execution_input"].update({"id": uid(9001), "digest": sha(b"new prepared receipt")})
    m["dependency_plan"] = {"id": uid(9002), "digest": sha(b"new plan receipt")}
    m["usage_digest"] = sha(b"new usage navigation")
    m["inventory_proof_digest"] = sha(b"new inventory proof navigation")
    m["fact_admission"]["content_digest"] = sha(b"new admission navigation")
    record = other["records"][0]["manifest"]
    record.update(
        {
            "id": uid(9003),
            "actor_id": uid(9004),
            "command_id": uid(9005),
            "recorded_at": "2026-10-21T04:00:00.000000Z",
            "reason": "重新保存相同事实用途",
        }
    )
    record["binding"].update(
        {
            "execution_input_id": m["execution_input"]["id"],
            "execution_input_digest": m["execution_input"]["digest"],
        }
    )
    sync(other)
    # This is the original gap: exact immutable input hashing sees new receipt IDs.
    assert digest(m) != digest(vector["manifest"])
    assert m["model_input_digest"] == vector["manifest"]["model_input_digest"]
    assert m["execution_input"]["identity"] == vector["manifest"]["execution_input"]["identity"]
    assert (
        m["fact_admission"]["proofs_digest"]
        != vector["manifest"]["fact_admission"]["proofs_digest"]
    )
    assert key(other) == before
    assert key(vector) == before
    serialized = json.dumps(before["manifest"], ensure_ascii=False)
    assert "new prepared receipt" not in serialized and "recorded_at" not in serialized
    assert "fact_item_digest" in serialized and "proof_digest" in serialized


def test_new_rerun_nonce_alone_changes_execution_identity(vector):
    first = key(vector)
    vector["manifest"]["execution_input"]["identity"]["rerun"] = {
        "nonce": uid(9100),
        "reason": "明确再次执行本次冻结输入",
    }
    sync(vector)
    rerun = key(vector)
    vector["manifest"]["execution_input"]["identity"]["rerun"]["nonce"] = uid(9101)
    sync(vector)
    next_run = key(vector)
    assert len({first["digest"], rerun["digest"], next_run["digest"]}) == 3
    assert {key: value for key, value in rerun["manifest"].items() if key != "rerun"} == {
        key: value for key, value in next_run["manifest"].items() if key != "rerun"
    }


@pytest.mark.parametrize("change", ["full_text", "geometry", "dependency", "fact_value"])
def test_every_consumed_model_value_changes_key_even_if_prepared_identity_is_unchanged(
    vector, change
):
    old = key(vector)
    old_prepared = deepcopy(vector["manifest"]["execution_input"]["identity"])
    payload = vector["payload"]
    if change == "full_text":
        payload["documents"][0]["blocks"][1]["text_content"] += "完整第二页新增条件"
    elif change == "geometry":
        payload["documents"][0]["blocks"][0]["bbox"] = [0.0, -0.0, 10.000000000000002, 20.125]
    elif change == "dependency":
        payload["requirements"][0]["dependency"]["reason"] = "明确变更实际送模的依赖说明"
    else:
        payload["selected_facts"][0]["value_jsonb_text"] = "999.01"
    vector["manifest"]["model_input_digest"] = review.model_digest(payload)
    assert key(vector)["digest"] != old["digest"]
    assert vector["manifest"]["execution_input"]["identity"] == old_prepared


@pytest.mark.parametrize(
    "change",
    ["method", "policy", "selected_facts", "subject", "proof", "original_evidence", "context"],
)
def test_method_source_fact_and_scope_semantics_remain_in_key(vector, change):
    old = key(vector)
    m = vector["manifest"]
    record = vector["records"][0]["manifest"]
    if change == "method":
        m["executor_method"]["profile"]["source_digest"] = sha(b"changed executor implementation")
    elif change == "policy":
        m["fact_admission"]["policy_digest"] = sha(b"changed admission implementation")
    elif change == "selected_facts":
        m["selected_facts_digest"] = sha(b"changed complete fact and decision basis")
    elif change == "subject":
        record["subject"]["kind"] = "bidder"
        record["subject"]["id"] = uid(9200)
    elif change == "proof":
        record["binding"]["proof_digest"] = sha(b"changed exact source closure and lineage")
    else:
        field = "evidence_digest" if change == "original_evidence" else "context_digest"
        m["execution_input"]["identity"]["binding"][field] = sha(change.encode())
        record["binding"][field] = m["execution_input"]["identity"]["binding"][field]
    sync(vector)
    assert key(vector)["digest"] != old["digest"]


def test_declaration_receipt_audit_history_does_not_invent_another_model_execution(vector):
    old = key(vector)
    record = vector["records"][0]["manifest"]
    record.update(
        {
            "id": uid(9300),
            "previous_digest": sha(b"old head"),
            "actor_id": uid(9301),
            "command_id": uid(9302),
            "recorded_at": "2026-10-21T04:00:00.000000Z",
            "reason": "再次说明同一用途",
        }
    )
    sync(vector)
    assert key(vector) == old


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "withdrawn",
        "digest",
        "foreign_prepared",
        "foreign_original",
        "wrong_fact",
        "wrong_reference",
    ],
)
def test_unbound_withdrawn_or_corrupt_declarations_cannot_produce_execution_key(vector, change):
    record = vector["records"][0]["manifest"]
    if change == "missing":
        vector["records"].clear()
    elif change == "duplicate":
        vector["records"].append(deepcopy(vector["records"][0]))
    elif change == "digest":
        vector["records"][0]["digest"] = "0" * 64
    elif change == "wrong_reference":
        vector["manifest"]["fact_admission"]["fact_declarations"][0]["declaration_id"] = uid(9400)
    else:
        if change == "withdrawn":
            record["action"] = "withdraw"
        elif change == "foreign_prepared":
            record["binding"]["execution_input_id"] = uid(9401)
        elif change == "foreign_original":
            record["binding"]["frozen_input_id"] = uid(9402)
        else:
            record["binding"]["fact_id"] = uid(9403)
        vector["records"][0]["digest"] = digest(record)
        vector["manifest"]["fact_admission"]["fact_declarations"][0]["declaration_digest"] = vector[
            "records"
        ][0]["digest"]
    with pytest.raises(DomainError) as error:
        key(vector)
    assert error.value.code == "PACKAGE_SCOPE_EXECUTION_KEY_INVALID"


def test_empty_selection_is_stable_across_receipt_ids_but_cannot_hide_selected_facts(case):
    m = deepcopy(case["manifest"])
    first = execution.identify(m, [])
    m["execution_input"].update({"id": uid(9500), "digest": sha(b"another empty prepared")})
    m["dependency_plan"] = {"id": uid(9501), "digest": sha(b"another empty plan")}
    m["usage_digest"] = sha(b"another empty usage")
    m["fact_admission"]["content_digest"] = sha(b"another empty admission")
    m["fact_admission"]["proofs_digest"] = sha(b"another empty navigation")
    m["inventory_proof_digest"] = sha(b"another empty inventory proof")
    assert execution.identify(m, []) == first
    m["selected_facts_digest"] = sha(b"nonempty selected projection")
    with pytest.raises(DomainError):
        execution.identify(m, [])


def test_sorted_fact_semantics_do_not_depend_on_record_lookup_order(vector):
    second = deepcopy(vector["records"][0])
    second["manifest"]["id"] = uid(9600)
    second["manifest"]["binding"]["fact_id"] = uid(9601)
    vector["records"].append(second)
    sync(vector)
    first = key(vector)
    vector["records"].reverse()
    sync(vector)
    assert key(vector) == first


def verified(vector):
    m = vector["manifest"]
    observation = service.ObservedScopeReview(
        tuple(m["scope"].values()),
        m["frozen_input"]["id"],
        m["execution_input"]["id"],
        False,
        "{}",
        None,
        None,
        "{}",
        "{}",
        SimpleNamespace(_proof_text=canonical(vector["proof"]).decode()),
        canonical(m).decode(),
    )
    return service.VerifiedScopeReview(observation)


def test_private_adapter_is_io_free_and_binds_the_exact_verified_input(vector, monkeypatch):
    token = verified(vector)
    monkeypatch.setattr(
        service, "connection", lambda *args: pytest.fail("identity must not open a transaction")
    )
    assert service.execution_key(token, deepcopy(vector["manifest"])) == key(vector)["digest"]
    other = deepcopy(vector["manifest"])
    other["dependency_plan"]["id"] = uid(9700)
    with pytest.raises(DomainError) as error:
        service.execution_key(token, other)
    assert error.value.code == "PACKAGE_SCOPE_EXECUTION_KEY_INVALID"
    with pytest.raises(TypeError):
        service.execution_key(token._observed, vector["manifest"])


def test_private_adapter_rejects_proof_snapshot_not_bound_to_input(vector):
    vector["proof"]["selected"] = []
    with pytest.raises(DomainError) as error:
        service.execution_key(verified(vector), vector["manifest"])
    assert error.value.code == "PACKAGE_SCOPE_EXECUTION_KEY_INVALID"
