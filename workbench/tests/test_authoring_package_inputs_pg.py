"""Actual B1 PG17/S3/auth guards; synthetic upstream inputs, no model quality claim."""
# ruff: noqa: F401,F811

import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import psycopg
import pytest
from authoring_package_input_fixtures import (
    ADMIN_DSN,
    RAW,
    database,
    exact,
    save,
    saved,
    status,
    world,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api, headers, uid

from packages.authoring import package_admission as admission
from packages.authoring import package_input as service
from packages.authoring import package_input_repository as repository
from packages.domain import original_verification, storage
from packages.domain.runtime import DomainError, connection, sha

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires isolated B1 PG17 and real S3")


def test_base_only_unavailable_and_nonowner_grants(database):
    assert database["base_capabilities"]["blocking_reasons"] == [
        "AUTHORING_PACKAGE_INPUT_NOT_CONFIGURED"
    ]
    assert all(
        not database["base_capabilities"][name]
        for name in (
            "generation_available",
            "publication_available",
            "apply_available",
            "build_available",
        )
    )
    for kind in ("api", "worker"):
        with psycopg.connect(database[kind + "_dsn"], row_factory=dict_row) as c:
            role = c.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            assert not role["rolsuper"] and not role["rolbypassrls"]
            rights = c.execute(
                "SELECT has_table_privilege(current_user,'design.authoring_package_inputs','SELECT') AS readable,has_table_privilege(current_user,'design.authoring_package_inputs','INSERT') AS insertable,has_table_privilege(current_user,'design.authoring_package_inputs','UPDATE') AS mutable"
            ).fetchone()
            assert rights == {
                "readable": kind == "api",
                "insertable": kind == "api",
                "mutable": False,
            }


def test_capture_exact_full_inputs_no_work_dispatch_and_safe_read(exact, monkeypatch):
    w = exact
    seen = []
    verify = original_verification.verify

    def real_io(document):
        owner = w["database"]["owner"]
        assert not owner.execute(
            "SELECT FROM pg_stat_activity WHERE datname=current_database() AND usename=%s AND state='idle in transaction'",
            ("fusion_authoring_package_inputs_api",),
        ).fetchone()
        seen.append(document["parse_id"])
        verify(document)

    monkeypatch.setattr(original_verification, "verify", real_io)
    owner = w["database"]["owner"]
    before = owner.execute(
        "SELECT (SELECT count(*) FROM design.operations) AS operations,(SELECT count(*) FROM design.model_calls) AS calls,(SELECT count(*) FROM design.outbox) AS outbox"
    ).fetchone()
    value = saved(w)
    m = value["manifest"]
    assert len(seen) == 2 and len(set(seen)) == 2
    assert m["selection"] == w["input_body"]
    assert m["counts"]["logical_members"] == 2 and m["counts"]["physical_pages"] == 4
    assert m["counts"]["evidence_blocks"] == 4 and m["counts"]["facts"] == 5
    assert m["counts"]["requirements"] == 1
    assert all(
        m[name] is False
        for name in (
            "generation_available",
            "publication_authorized",
            "apply_available",
            "build_available",
            "formal_decisions_allowed",
        )
    )
    assert len(m["fact_declarations"]) == 1
    assert m["fact_declarations"][0]["manifest"]["purpose"] == "authoring"
    after = owner.execute(
        "SELECT (SELECT count(*) FROM design.operations) AS operations,(SELECT count(*) FROM design.model_calls) AS calls,(SELECT count(*) FROM design.outbox) AS outbox"
    ).fetchone()
    assert before == after
    path = w["input_base"] + "/" + m["id"]
    assert w["client"].get(path).json() == value
    public = w["client"].get(path + "/context").json()
    assert public["original_bytes_reverified"] is False
    assert all("object_key" not in doc for doc in public["context"]["documents"])
    current = status(w, value)
    assert current.status_code == 200, current.text
    assert current.json()["current_input_matches"] is True
    assert current.json()["original_bytes_reverified"] is False
    assert current.json()["blocking_reasons"] == ["AUTHORING_PACKAGE_EXECUTOR_NOT_READY"]


def test_schema_and_digest_are_explicit_no_latest_fallback(exact):
    body = deepcopy(exact["input_body"])
    del body["package_context"]["target"]["revision_id"]
    assert save(exact, body=body).status_code == 422
    body = deepcopy(exact["input_body"])
    body["generation_mode"] = "exact_package_authoring"
    assert save(exact, body=body).status_code == 422
    body = deepcopy(exact["input_body"])
    body["target_section"]["snapshot_digest"] = "0" * 64
    response = save(exact, body=body)
    assert (
        response.status_code == 409 and response.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    )
    body = deepcopy(exact["input_body"])
    body["facts"]["uses"][0]["subject"]["id"] = uid()
    response = save(exact, body=body)
    assert (
        response.status_code == 409
        and response.json()["code"] == "AUTHORING_PACKAGE_FACT_DECLARATION_MISMATCH"
    )


@pytest.mark.parametrize("change", ["missing", "corrupt", "extra_byte"])
def test_original_bytes_fail_closed_without_partial_input(exact, change):
    w = exact
    if change == "missing":
        storage.client().delete_object(Bucket=storage.bucket(), Key=w["blob"]["object_key"])
    else:
        raw = b"X" * len(RAW) if change == "corrupt" else RAW + b"!"
        storage.put(w["blob"]["object_key"], raw, "application/pdf")
    response = save(w)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == (
        "ORIGINAL_NOT_AVAILABLE" if change == "missing" else "ORIGINAL_BYTES_CORRUPTED"
    )
    assert (
        not w["database"]["owner"]
        .execute("SELECT FROM design.authoring_package_inputs WHERE bid_id=%s", (w["bid"],))
        .fetchone()
    )


def test_replay_preserves_original_ack_after_object_lost(exact):
    w, key = exact, uid()
    first = save(w, key=key)
    assert first.status_code == 201, first.text
    storage.client().delete_object(Bucket=storage.bucket(), Key=w["blob"]["object_key"])
    second = save(w, key=key)
    assert second.status_code == 201 and second.json() == first.json()
    changed = deepcopy(w["input_body"])
    changed["target_section"]["before_node_digest"] = "0" * 64
    conflict = save(w, key=key, body=changed)
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_final_auth_revocation_rolls_back(exact):
    def revoked():
        raise DomainError("AUTH_REQUIRED", "synthetic final session revocation", 401)

    with pytest.raises(DomainError, match="synthetic final session revocation"):
        service.save(exact["actor"], exact["bid"], uid(), exact["input_body"], final_auth=revoked)
    assert (
        not exact["database"]["owner"]
        .execute("SELECT FROM design.authoring_package_inputs WHERE bid_id=%s", (exact["bid"],))
        .fetchone()
    )


def mutate_authority(w, change):
    from packages.domain.bid_package_service import lock_bid
    from packages.domain.fact_sets import replace_set
    from packages.domain.human_decisions import append_decision
    from packages.knowledge.sources import lock_graph
    from packages.lifecycle.service import change as change_lifecycle
    from packages.rag.indexing import original_source_id

    with connection() as c:
        lock_bid(c, w["bid"])
        if change == "source":
            lock_graph(c)
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (original_source_id(UUID(w["member"].document_version_id)),),
            )
        elif change == "facts":
            replace_set(
                c,
                UUID(w["bid"]),
                UUID(w["actor"]),
                "Synthetic changed fact authority",
                kind="withdraw",
                removed_id=w["input_body"]["facts"]["identity_fact_ids"][0],
            )
        elif change == "rule":
            append_decision(
                c,
                w["bid"],
                w["actor"],
                "rule",
                w["rule"],
                {
                    "decision": "rejected",
                    "reason": "Synthetic rule withdrawal",
                    "evidence_ids": [w["evidence"]],
                },
            )
        elif change == "closed":
            change_lifecycle(
                c, w["bid"], w["actor"], "terminate", "Synthetic project termination", None
            )
        else:
            raise AssertionError(change)


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_authority_changes_during_object_io_reject_new_input(exact, monkeypatch, change):
    verify = original_verification.verify
    changed = False

    def during_io(document):
        nonlocal changed
        verify(document)
        if not changed:
            changed = True
            mutate_authority(exact, change)

    monkeypatch.setattr(original_verification, "verify", during_io)
    response = save(exact)
    assert changed and response.status_code == 409, response.text
    assert response.json()["code"] in {
        "SOURCE_NOT_EFFECTIVE",
        "AUTHORING_PACKAGE_FACT_HEAD_CHANGED",
        "AUTHORING_PACKAGE_RULES_CHANGED",
        "PROJECT_WORK_CLOSED",
    }
    assert (
        not exact["database"]["owner"]
        .execute("SELECT FROM design.authoring_package_inputs WHERE bid_id=%s", (exact["bid"],))
        .fetchone()
    )


@pytest.mark.parametrize("change", ["source", "facts", "rule", "closed"])
def test_saved_history_readable_but_check_never_requalifies_changed_input(exact, change):
    value = saved(exact)
    mutate_authority(exact, change)
    check = status(exact, value)
    assert check.status_code == 200, check.text
    assert check.json()["current_input_matches"] is False
    assert check.json()["generation_available"] is False
    assert exact["client"].get(exact["input_base"] + "/" + value["manifest"]["id"]).json() == value


def test_natural_expiry_during_io_rejected_without_revision_change(exact, monkeypatch):
    from packages.knowledge.sources import lock_graph
    from packages.rag.indexing import original_source_id

    authority_version = (
        exact["database"]["owner"]
        .execute(
            "SELECT document_version_id FROM design.parse_runs WHERE id=(SELECT (manifest#>>'{members,0,parse,parse_run_id}')::uuid FROM design.bid_package_revisions WHERE id=%s)",
            (exact["input_body"]["package_context"]["authority"]["revision_id"],),
        )
        .fetchone()["document_version_id"]
    )
    source = original_source_id(authority_version)
    with connection() as c:
        lock_graph(c)
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+interval '1.5 seconds' WHERE source_id=%s",
            (source,),
        )
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()["revision"]
    verify = original_verification.verify
    calls = []

    def expires(document):
        verify(document)
        if not calls:
            calls.append(True)
            time.sleep(1.6)

    monkeypatch.setattr(original_verification, "verify", expires)
    response = save(exact)
    assert calls and response.status_code == 409, response.text
    assert response.json()["code"] == "SOURCE_NOT_EFFECTIVE"
    assert (
        exact["database"]["owner"]
        .execute("SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,))
        .fetchone()["revision"]
        == revision
    )


def add_new_parse(w):
    from packages.rag.indexing import ensure_parse_sources

    old = w["member"].parse.parse_run_id
    newer = uid()
    with connection(True) as c:
        c.execute(
            "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) SELECT %s,bid_id,document_version_id,%s,config_digest,page_count,coverage,gaps FROM design.parse_runs WHERE id=%s",
            (newer, "9" * 64, old),
        )
        c.execute(
            "INSERT INTO design.pages(bid_id,parse_id,physical_page,printed_label,width,height,rotation,quality,gaps) SELECT bid_id,%s,physical_page,printed_label,width,height,rotation,quality,gaps FROM design.pages WHERE parse_id=%s",
            (newer, old),
        )
        c.execute(
            "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,bbox,structure,digest) SELECT gen_random_uuid(),bid_id,%s,physical_page,ordinal,kind,text_content,bbox,structure,digest FROM design.evidence_blocks WHERE parse_id=%s",
            (newer, old),
        )
        ensure_parse_sources(c, UUID(w["bid"]), UUID(newer), publish_readable=True)
    return newer


def test_new_parse_does_not_replace_or_invalidate_selected_old_parse(exact):
    value = saved(exact)
    newer = add_new_parse(exact)
    checked = status(exact, value)
    assert checked.status_code == 200 and checked.json()["current_input_matches"], checked.text
    another = saved(exact)
    assert another["manifest"]["context_digest"] == value["manifest"]["context_digest"]
    with connection() as c:
        context = repository.public_context(
            repository.load(c, exact["bid"], another["manifest"]["id"])
        )["context"]
    assert newer not in {d["parse_id"] for d in context["documents"]}
    assert str(exact["member"].parse.parse_run_id) in {d["parse_id"] for d in context["documents"]}


def test_fact_declaration_withdrawal_is_input_specific_and_allowed_after_close(exact):
    w = exact
    first, second = saved(w), saved(w)
    mutate_authority(w, "closed")
    declaration = first["manifest"]["fact_declarations"][0]
    path = w["input_base"] + "/" + first["manifest"]["id"] + "/fact-withdrawals"
    body = {
        "input_digest": first["digest"],
        "fact_id": declaration["manifest"]["fact_id"],
        "declaration_digest": declaration["digest"],
        "reason": "  Explicit purpose withdrawal after closure  ",
    }
    key = uid()
    response = w["client"].post(path, json=body, headers=headers(w, key=key))
    assert response.status_code == 201, response.text
    assert response.json()["manifest"]["action"] == "withdraw"
    assert w["client"].post(path, json=body, headers=headers(w, key=key)).json() == response.json()
    assert (
        "AUTHORING_PACKAGE_FACT_DECLARATION_WITHDRAWN"
        in status(w, first).json()["blocking_reasons"]
    )
    with connection() as c:
        repository.declarations_match(c, repository.load(c, w["bid"], second["manifest"]["id"]))
    assert w["client"].get(w["input_base"] + "/" + first["manifest"]["id"]).json() == first


def test_directory_pagination_scope_digest_and_auth(exact):
    w = exact
    one, two = saved(w), saved(w)
    first = w["client"].get(w["input_base"], params={"limit": 1})
    assert first.status_code == 200 and first.json()["has_more"]
    second = w["client"].get(
        w["input_base"], params={"limit": 1, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200 and not second.json()["has_more"]
    assert {v["manifest"]["id"] for v in first.json()["items"] + second.json()["items"]} == {
        one["manifest"]["id"],
        two["manifest"]["id"],
    }
    assert (
        w["client"]
        .get(w["input_base"], params={"cursor": first.json()["next_cursor"] + "tampered"})
        .status_code
        == 422
    )
    other = w["input_base"].replace(w["bid"], uid())
    assert w["client"].get(other + "/" + one["manifest"]["id"]).status_code == 404
    wrong = w["client"].post(
        w["input_base"] + "/" + one["manifest"]["id"] + "/check",
        json={"input_digest": "0" * 64},
        headers=headers(w),
    )
    assert wrong.status_code == 409
    assert (
        w["client"]
        .post(w["input_base"], json=w["input_body"], headers={"Origin": "http://identity-v2.test"})
        .status_code
        == 403
    )
    w["client"].cookies.clear()
    assert w["client"].get(w["input_base"]).status_code == 401


def test_same_key_concurrent_save_returns_one_native_input(exact):
    key = uid()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: save(exact, key=key), range(2)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    assert (
        exact["database"]["owner"]
        .execute(
            "SELECT count(*) AS n FROM design.authoring_package_inputs WHERE bid_id=%s",
            (exact["bid"],),
        )
        .fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize(
    "attack",
    [
        "partial_blocks",
        "wrong_parse",
        "node_digest",
        "invented_fact_value",
        "invented_source",
        "partial_extraction",
        "duplicate_source",
        "duplicate_fact",
        "implicit_selection_policy",
    ],
)
def test_sql_rejects_forged_private_context_even_with_fresh_hashes(exact, monkeypatch, attack):
    original = admission.recheck

    def forge(c, verified):
        observed = original(c, verified)
        context = observed.context()
        if attack == "partial_blocks":
            context["documents"][0]["blocks"].pop()
        elif attack == "wrong_parse":
            context["documents"][0]["parse_id"] = uid()
        elif attack == "node_digest":
            context["request"]["target_section"]["before_node_digest"] = "0" * 64
        elif attack == "invented_fact_value":
            fact = context["facts"]["items"][0]
            fact["item"]["fact"]["value_jsonb_text"] = '"invented business identity"'
            fact["item_digest"] = sha(fact["item"])
        elif attack == "invented_source":
            context["sources"][0]["source_id"] = uid()
        elif attack == "partial_extraction":
            receipt = context["inventory"]["native_receipt"]["run"]
            receipt["result"]["extraction_coverage"] = "partial"
            receipt["result_digest"] = sha(receipt["result"])
        elif attack == "duplicate_source":
            context["sources"][1] = deepcopy(context["sources"][0])
        elif attack == "duplicate_fact":
            context["facts"]["items"][1] = deepcopy(context["facts"]["items"][0])
        elif attack == "implicit_selection_policy":
            context["method"]["implicit_source_selection"] = True
            context["method_digest"] = sha(context["method"])
        return replace(
            observed,
            _request_text=admission.encoded(context["request"]),
            _context_text=admission.encoded(context),
        )

    monkeypatch.setattr(admission, "recheck", forge)
    response = save(exact)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "AUTHORING_PACKAGE_INPUT_REJECTED"
    assert (
        not exact["database"]["owner"]
        .execute("SELECT FROM design.authoring_package_inputs WHERE bid_id=%s", (exact["bid"],))
        .fetchone()
    )
