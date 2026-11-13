"""Synthetic B5 -> B6 -> B7 history through real, quarantined PG17/S3 recovery.

This extends acceptance evidence only. The existing frozen SQL plan, archive
format, restore implementation and runtime permissions are not changed. A
restored archive remains offline: preserved proofs do not grant current use.
"""

# These imports expose the existing native fixture dependency chain to pytest.
# ruff: noqa: F401,F811
import os
from copy import deepcopy
from uuid import UUID

import psycopg
import pytest
from authoring_package_input_fixtures import ADMIN_DSN, world
from authoring_package_job_fixtures import case, input_database, queued
from authoring_package_job_fixtures import database as job_database
from extended_recovery_helpers import BASE, drill, install_remaining, proof
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from test_authoring_exact_builds_pg import adopted
from test_authoring_exact_builds_pg import database as build_database
from test_authoring_exact_marked_text_edits_pg import body, exact
from test_authoring_exact_marked_text_edits_pg import database as marked_database
from test_authoring_exact_revisions_pg import database as revision_database
from test_authoring_exact_revisions_pg import published, qualified
from test_authoring_exact_text_edits_pg import database as single_database
from test_authoring_exact_text_edits_pg import edit
from test_bid_package_requirements_api import requirements
from test_stable_lot_identity import api

from deploy import authoring_candidate, completion_recovery, extended_recovery
from deploy.backups import run
from packages.authoring import exact_marked_text_edits, exact_sources, repository
from packages.authoring.exact_marked_text_edit_contracts import (
    AuthoringExactMarkedManualRevisionView,
)
from packages.domain.runtime import clean, connection, sha

pytestmark = pytest.mark.skipif(
    os.environ.get("FUSION_EXTENDED_RECOVERY_PG") != "1" or not ADMIN_DSN,
    reason="explicit disposable B7 authoring and extended recovery PG17/S3 required",
)

FUNCTIONS = (
    "authoring_exact_check_candidate_revision",
    "authoring_exact_check_single_text_record",
    "authoring_exact_check_multi_text_record",
    "authoring_exact_check_marked_text_record",
    "authoring_exact_check_manual_record",
    "authoring_exact_check_revision",
    "authoring_exact_assert_revision",
    "authoring_exact_snapshot_proof",
)


def authoring_definitions(c):
    # Definition rendering depends on name visibility. Use the same local
    # catalog-only display context for source and quarantined reader, without
    # rewriting identifiers or changing persistent session/server settings.
    with c.transaction():
        c.execute("SET LOCAL search_path=pg_catalog")
        functions = c.execute(
            "SELECT p.proname,pg_get_function_identity_arguments(p.oid) AS arguments,"
            "pg_get_functiondef(p.oid) AS definition FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='design' AND p.proname=ANY(%s) ORDER BY p.proname,arguments",
            (list(FUNCTIONS),),
        ).fetchall()
        assert {row["proname"] for row in functions} == set(FUNCTIONS)
        view = c.execute(
            "SELECT pg_get_viewdef('design.authoring_exact_revision_records'::regclass,true) AS definition"
        ).fetchone()["definition"]
    return clean({"functions": functions, "qualification_view": view})


@pytest.fixture(scope="module")
def database(marked_database):
    # The existing B7 fixture installs B1-B5, then B6, then B7. Complete the
    # old recovery prerequisites without reinstalling B5 over the B7 dispatcher.
    owner = marked_database["owner"]
    before = authoring_definitions(owner)
    install_remaining(owner, BASE | set(authoring_candidate.OPTIONAL_SQL))
    assert authoring_definitions(owner) == before
    return marked_database


def history(c, bid, draft):
    """Read immutable records directly; never execute restored domain functions."""
    queries = {
        "draft": "SELECT * FROM design.drafts WHERE bid_id=%s AND id=%s ORDER BY id",
        "sections": "SELECT * FROM design.sections WHERE bid_id=%s AND draft_id=%s ORDER BY id",
        "revisions": "SELECT * FROM design.section_revisions WHERE bid_id=%s AND draft_id=%s ORDER BY id",
        "snapshots": "SELECT * FROM design.draft_snapshots WHERE bid_id=%s AND draft_id=%s ORDER BY revision",
        "snapshot_sections": "SELECT * FROM design.draft_snapshot_sections WHERE bid_id=%s AND draft_id=%s ORDER BY snapshot_id,ordinal",
        # The union view exposes the revision number only inside its manifest.
        # Numeric ordering is intentional: revision 10 must follow revision 9.
        "qualifications": "SELECT * FROM design.authoring_exact_revision_records WHERE bid_id=%s AND draft_id=%s ORDER BY (manifest->>'section_revision')::bigint,id",
        "manual_revisions": "SELECT * FROM design.authoring_exact_manual_revisions WHERE bid_id=%s AND draft_id=%s ORDER BY draft_revision",
        "commands": "SELECT cmd.* FROM design.commands cmd JOIN design.authoring_exact_revision_records q ON q.command_id=cmd.id WHERE q.bid_id=%s AND q.draft_id=%s ORDER BY cmd.id",
    }
    return clean(
        {name: c.execute(query, (bid, draft)).fetchall() for name, query in queries.items()}
    )


def queue_state(c, bid):
    # Fixed queries also prove exact operation/outbox/receipt/call rows are not
    # advanced by inspecting the archive. No scheduler or restored consumer runs.
    queries = {
        "operations": "SELECT * FROM design.operations WHERE bid_id=%s ORDER BY id",
        "outbox": "SELECT o.* FROM design.outbox o JOIN design.operations p ON p.id=o.operation_id WHERE p.bid_id=%s ORDER BY o.id",
        "effects": "SELECT e.* FROM design.effect_receipts e JOIN design.operations p ON p.id=e.operation_id WHERE p.bid_id=%s ORDER BY e.operation_id,e.effect_key",
        "model_calls": "SELECT m.* FROM design.model_calls m JOIN design.operations p ON p.id=m.operation_id WHERE p.bid_id=%s ORDER BY m.id",
    }
    return clean({name: c.execute(query, (bid,)).fetchall() for name, query in queries.items()})


def assert_immutable_chain(saved, qualifications, requests, expected_contents):
    records = saved["qualifications"]
    assert len(records) == 4 and len(saved["manual_revisions"]) == 3
    assert len(saved["commands"]) == 4
    assert [row["manifest"]["protocol"] for row in records] == [
        "authoring-exact-revision/1",
        "authoring-exact-manual-revision/1",
        "authoring-exact-manual-revision/2",
        "authoring-exact-manual-revision/3",
    ]
    by_revision = {row["id"]: row for row in saved["revisions"]}
    snapshots = {row["revision"]: row for row in saved["snapshots"]}
    for index, (record, qualification, content) in enumerate(
        zip(records, qualifications, expected_contents, strict=True)
    ):
        m = record["manifest"]
        assert {"manifest": m, "digest": record["digest"]} == qualification
        assert record["digest"] == sha(m)
        assert m["origin"]["before_action_digest"] == sha(record["before_action"])
        assert m["content_correctness_certified"] is False
        assert by_revision[m["section_revision_id"]]["content"] == content
        assert by_revision[m["section_revision_id"]]["digest"] == sha(content)
        assert m["section_digest"] == sha(content)
        assert m["source_refs_digest"] == sha(content["attrs"]["source_refs"])
        assert m["rule_ids_digest"] == sha(content["attrs"]["rule_ids"])
        snapshot = snapshots[m["draft_revision"]]
        extension = snapshot["manifest"]["authoring_exact_sections"]
        assert extension["digest"] == sha({k: v for k, v in extension.items() if k != "digest"})
        assert any(
            binding["section_revision_id"] == m["section_revision_id"]
            and binding["qualification_id"] == m["id"]
            and binding["qualification_digest"] == record["digest"]
            for binding in extension["sections"]
        )
        if index:
            parent = qualifications[index - 1]
            assert m["candidate_adopted"] is False
            assert m["origin"]["parent_qualification_id"] == parent["manifest"]["id"]
            assert m["origin"]["parent_qualification_digest"] == parent["digest"]
            assert m["origin"]["root_qualification_id"] == qualifications[0]["manifest"]["id"]
            assert m["origin"]["root_qualification_digest"] == qualifications[0]["digest"]
            assert m["input"] == qualifications[0]["manifest"]["input"]
            assert record["before_action"]["request"] == requests[index - 1]
            assert record["request_condition"] == repository.draft_etag(
                m["draft_id"], requests[index - 1]["base_draft_revision"]
            )
    marked = qualifications[-1]
    AuthoringExactMarkedManualRevisionView.model_validate(marked)
    marks = expected_contents[0]["content"][1]["content"][0]["marks"]
    assert marks == [{"type": "italic"}, {"type": "bold"}]
    assert all(
        content["content"][1]["content"][0]["marks"] == marks for content in expected_contents
    )
    assert marked["manifest"]["origin"]["preserved_marks_digest"] == sha(marks)


def test_b5_b6_b7_native_history_survives_dump_restore_without_resuming_consumers(
    adopted, monkeypatch, tmp_path
):
    w = adopted
    # Both existing fixture families must refer to this one disposable cluster.
    assert conninfo_to_dict(ADMIN_DSN) == conninfo_to_dict(
        os.environ["FUSION_REQUIREMENTS_ADMIN_DSN"]
    )
    monkeypatch.setattr(run, "ARCHIVE_ROOT", tmp_path / "archives")
    policy = exact_marked_text_edits.policy()
    plan = completion_recovery.plan_receipt(extended_recovery.frozen_plan())
    root = qualified(w)
    qualifications = [{"manifest": clean(root["manifest"]), "digest": root["digest"]}]
    requests, contents = [], []
    with connection() as c:
        contents.append(
            c.execute(
                "SELECT content FROM design.section_revisions WHERE id=%s",
                (root["section_revision_id"],),
            ).fetchone()["content"]
        )
    for version in (1, 2, 3):
        request, original = body(w, qualifications[-1], plain=version != 3)
        assert original == contents[-1]
        if version == 2:
            request = {
                "protocol": "authoring-exact-multi-text-edit/1",
                "base_draft_revision": request["base_draft_revision"],
                "section_revision_id": request["section_revision_id"],
                "edits": [
                    {
                        "node_id": node["attrs"]["id"],
                        "before_node_digest": sha(node),
                        "replacement_text": f"Synthetic B6 recovery text {index}",
                    }
                    for index, node in enumerate((original["content"][0], original["content"][2]))
                ],
                "reason": request["reason"],
            }
        request["reason"] = f"Synthetic B{version + 4} recovery acceptance; no production authority"
        reply = edit(w, request)
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result["protocol"] == f"authoring-exact-text-edit-result/{version}"
        w["saved"] = result
        qualifications.append(result["qualification"])
        requests.append(request)
        expected = deepcopy(original)
        changes = request.get("edits", [request])
        for change in changes:
            node = next(n for n in expected["content"] if n["attrs"]["id"] == change["node_id"])
            assert len(node["content"]) == 1 and node["content"][0]["type"] == "text"
            node["content"][0]["text"] = change["replacement_text"]
        contents.append(expected)
        with connection() as c:
            assert (
                exact_sources.load(c, UUID(w["bid"]), UUID(result["section_revision_id"]))
                == result["qualification"]
            )
    assert len(w["calls"]) == 1  # Existing fixture uses only an in-memory MockTransport.
    bid, draft = w["bid"], w["saved"]["draft_id"]
    with connection() as c:
        expected_history = history(c, bid, draft)
        expected_queues = queue_state(c, bid)
        expected_definitions = authoring_definitions(c)
    assert expected_queues["operations"] and expected_queues["outbox"]
    pending_outbox = sum(row["published_at"] is None for row in expected_queues["outbox"])
    assert pending_outbox > 0  # Genuine undelivered rows, not an empty-queue assertion.
    assert_immutable_chain(expected_history, qualifications, requests, contents)
    observed = []
    real_restore = extended_recovery.restore_database

    def inspect_actual_restore(values, directory, **options):
        # Observe the real successful restore before drill's existing teardown.
        # The corrupt-original negative control still calls and fails in the real
        # implementation; no receipt or database action is replaced or simulated.
        receipt = real_restore(values, directory, **options)
        assert receipt["definitions_and_acl_preserved_before_quarantine"] is True
        assert receipt["all_table_rows_sha256_verified"] is True
        assert receipt["exact_authoring_qualification_view_sha256_verified"] is True
        for field in (
            "old_queue_resume_qualified",
            "full_application_restore_qualified",
            "production_rpo_rto_qualified",
        ):
            assert receipt[field] is False
        with psycopg.connect(
            make_conninfo(values["API_DATABASE_DSN"], dbname=receipt["database"]),
            autocommit=True,
            row_factory=dict_row,
        ) as target:
            assert target.execute("SHOW default_transaction_read_only").fetchone() == {
                "default_transaction_read_only": "on"
            }
            actual = history(target, bid, draft)
            assert actual == expected_history
            assert_immutable_chain(actual, qualifications, requests, contents)
            assert authoring_definitions(target) == expected_definitions
            assert queue_state(target, bid) == expected_queues
            assert target.execute(
                "SELECT has_function_privilege(current_user,'design.authoring_exact_check_revision(uuid)','EXECUTE') AS allowed"
            ).fetchone() == {"allowed": False}
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                target.execute(
                    "SELECT design.authoring_exact_check_revision(%s)",
                    (qualifications[-1]["manifest"]["section_revision_id"],),
                )
            assert queue_state(target, bid) == expected_queues
        observed.append(receipt["database"])
        return receipt

    monkeypatch.setattr(extended_recovery, "restore_database", inspect_actual_restore)
    result = drill(
        w["database"],
        "authoring-marked",
        {
            "design.authoring_package_inputs",
            "design.authoring_exact_revisions",
            "design.authoring_exact_manual_revisions",
            "design.draft_snapshots",
            "design.draft_snapshot_sections",
        },
        extra_login_dsn=w["database"]["worker_dsn"],
    )
    assert len(observed) == 1
    assert exact_marked_text_edits.policy() == policy
    assert completion_recovery.plan_receipt(extended_recovery.frozen_plan()) == plan
    for field in (
        "old_queue_resume_qualified",
        "full_application_restore_qualified",
        "production_rpo_rto_qualified",
        "native_oss_qualified",
        "restored_consumer_started",
    ):
        assert result[field] is False
    with connection() as c:
        assert history(c, bid, draft) == expected_history
        assert queue_state(c, bid) == expected_queues
    proof(
        "authoring-marked",
        result
        | {
            "chain_protocols": [q["manifest"]["protocol"] for q in qualifications],
            "complete_authoring_history_sha256": sha(expected_history),
            "queue_state_sha256": sha(expected_queues),
            "preserved_unpublished_outbox_rows": pending_outbox,
            "marked_policy_sha256": sha(policy),
            "b5_b6_b7_immutable_chain_and_snapshots_preserved": True,
            "original_marks_array_and_order_preserved": True,
            "b7_functions_and_qualification_view_definition_preserved": True,
            "restored_domain_proof_execution_denied": True,
            "production_eligible": False,
        },
    )
