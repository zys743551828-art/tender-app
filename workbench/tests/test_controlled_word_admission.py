"""Actual relational SELECTs over synthetic SQLite records, not renderer acceptance."""

import copy
import json
import sqlite3
from types import SimpleNamespace
from uuid import UUID

import pytest

from packages.domain import controlled_word_admission as admission
from packages.domain.bid_packages import PackageError
from packages.domain.runtime import sha
from packages.word_intake.inspection import DOCX, PDF
from packages.word_intake.repository import REQUIRED_ISOLATION


def uid(number):
    return str(UUID(int=number))


@pytest.fixture
def world():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("ATTACH DATABASE ':memory:' AS design")
    tables = {
        "document_relations": "bid_id,document_version_id,source_document_version_id,kind,verification",
        "word_render_runs": "bid_id,operation_id,source_document_version_id,pdf_document_version_id,profile_digest,frozen_profile,outcome,created_at",
        "document_versions": "id,bid_id,blob_id,artifact_kind",
        "blobs": "id,digest,byte_size,media_type,object_key",
        "uploads": "id,bid_id,verified_version_id,state,role,declared_digest,declared_size",
        "operations": "id,bid_id,state,kind,handler_version,input_digest",
        "word_intake_receipts": "document_version_id,bid_id,upload_id,verify_operation_id,inspection_digest,inspection_report",
        "document_file_versions": "bid_id,version_id,file_id",
        "document_files": "id,bid_id,role,head_version_id",
        "audit_entries": "id,bid_id,event_type,payload,created_at,actor_id,command_id",
        "commands": "id,command_kind,target_id,actor_id,request_digest,response",
        "build_outputs": "bid_id,document_version_id",
        "material_snapshots": "id,bid_id,revision,manifest,digest",
        "material_assignments": "bid_id,snapshot_id,document_version_id,role",
        "bid_profiles": "bid_id,current_material_id,current_body_id",
    }
    for table, columns in tables.items():
        db.execute(f"CREATE TABLE design.{table} ({columns})")
    (
        bid,
        word,
        pdf,
        operation,
        verify,
        source_file,
        pdf_file,
        upload,
        before,
        after,
        selection,
        adopted,
    ) = [uid(i) for i in range(1, 13)]
    identity = {"renderer_digest": "1" * 64, "fontset_digest": "2" * 64, "options_digest": "3" * 64}
    profile = {"identity": identity, "profile_digest": sha(identity)}
    report = {"conversion_eligible": True}
    chain = dict(
        identity,
        source_docx_digest="a" * 64,
        pdf_digest="b" * 64,
        profile_digest=profile["profile_digest"],
    )
    outcome = {
        "protocol": "word-docker-render/1",
        "state": "succeeded",
        "coverage": "complete",
        "conversion_attempted": True,
        "gaps": [],
        "chain": chain,
        "isolation": dict.fromkeys(REQUIRED_ISOLATION, True),
    }

    def insert(table, *values):
        db.execute(
            f"INSERT INTO design.{table} VALUES ({','.join('?' for _ in values)})",
            tuple(json.dumps(v) if isinstance(v, dict) else v for v in values),
        )

    insert("document_relations", bid, pdf, word, "controlled_render", "verified")
    insert(
        "word_render_runs",
        bid,
        operation,
        word,
        pdf,
        profile["profile_digest"],
        profile,
        outcome,
        1,
    )
    insert("document_versions", word, bid, uid(20), "bid_body")
    insert("document_versions", pdf, bid, uid(21), "bid_body")
    insert("blobs", uid(20), "a" * 64, 5000, DOCX, "original/word")
    insert("blobs", uid(21), "b" * 64, 2000, PDF, "word-rendered/" + "b" * 64)
    insert("uploads", upload, bid, word, "verified", "body", "a" * 64, 5000)
    insert(
        "operations",
        operation,
        bid,
        "succeeded",
        "word-render",
        "word-render/1",
        sha({"id": word, "digest": "a" * 64, "render_profile_digest": profile["profile_digest"]}),
    )
    insert("operations", verify, bid, "succeeded", "verify-upload", "upload/1", "4" * 64)
    insert("word_intake_receipts", word, bid, upload, verify, sha(report), report)
    insert("document_file_versions", bid, word, source_file)
    insert("document_file_versions", bid, pdf, pdf_file)
    insert("document_files", source_file, bid, "body", word)
    insert("document_files", pdf_file, bid, "body", pdf)
    context = {
        "source_document_version_id": word,
        "source_sha256": "a" * 64,
        "file_id": source_file,
        "role": "body",
        "current_material_id": before,
        "material_revision": 3,
    }
    insert(
        "audit_entries",
        selection,
        bid,
        "word.material_selected",
        {"source_document_version_id": word, "context": context, "context_digest": sha(context)},
        1,
        uid(31),
        uid(32),
    )
    payload = {
        "state": "adopted",
        "document_version_id": pdf,
        "source_document_version_id": word,
        "conversion_operation_id": operation,
        "selection_id": selection,
        "material_snapshot_id": after,
        "material_revision": 4,
    }
    insert(
        "audit_entries",
        adopted,
        bid,
        "word.material_adoption_recorded",
        payload,
        2,
        uid(31),
        uid(30),
    )
    conversion = {
        "document_version_id": pdf,
        "file_id": pdf_file,
        "digest": "b" * 64,
        "byte_size": 2000,
        "object_key": "word-rendered/" + "b" * 64,
        "source_document_version_id": word,
        "operation_id": operation,
        "profile_digest": profile["profile_digest"],
    }
    insert(
        "commands",
        uid(30),
        "adopt_word_render",
        word,
        uid(31),
        sha(
            {
                "body": {
                    "selection_id": selection,
                    "context_digest": sha(context),
                    "conversion": conversion,
                },
                "if_match": None,
            }
        ),
        {"body": payload, "status": 200, "headers": {}},
    )
    entries = [{"document_version_id": pdf, "file_id": pdf_file, "role": "body"}]
    insert("material_snapshots", after, bid, 4, {"documents": entries}, sha(entries))
    insert("material_assignments", bid, before, word, "body")
    insert("material_assignments", bid, after, pdf, "body")
    insert("bid_profiles", bid, after, pdf)
    queries = []

    def execute(query, args=()):
        queries.append(query)
        assert query.lstrip().startswith("SELECT"), "admission observer must never write"
        if "to_regclass(" in query:
            rows = [{"ready": True, "authoring_ready": True}]
        else:
            rows = [
                dict(row) for row in db.execute(query.replace("%s", "?").replace("%%", "%"), args)
            ]
            for row in rows:
                for key in (
                    "frozen_profile",
                    "outcome",
                    "inspection_report",
                    "payload",
                    "manifest",
                    "response",
                ):
                    if key in row and row[key] is not None:
                        row[key] = json.loads(row[key])
        return SimpleNamespace(fetchone=lambda: rows[0] if rows else None, fetchall=lambda: rows)

    yield SimpleNamespace(
        db=db,
        c=SimpleNamespace(execute=execute),
        bid=bid,
        word=word,
        pdf=pdf,
        operation=operation,
        outcome=outcome,
        profile=profile,
        queries=queries,
        after=after,
        selection=selection,
    )
    db.close()


def observe(world, **kwargs):
    return admission.observe(world.c, world.bid, world.pdf, expected_digest="b" * 64, **kwargs)


def test_exact_current_and_historical_preserve_distinct_docx_pdf_id_size_digest(world):
    current = observe(world, current=True)
    assert current == observe(world)
    assert current["source_document_version_id"] == world.word != current["document_version_id"]
    assert current["source_sha256"] == "a" * 64 != current["pdf_sha256"]
    assert current["source_byte_size"] == 5000 and current["pdf_byte_size"] == 2000
    assert admission.eligible(world.c, world.bid, world.pdf)


@pytest.mark.parametrize(
    "fault",
    [
        "source_hash",
        "source_size",
        "pdf_hash",
        "pdf_size",
        "positive_pdf_size",
        "media",
        "upload",
        "verify",
        "relation",
        "missing_relation",
        "missing_run",
        "partial",
        "profile",
        "chain",
        "operation",
        "input",
        "unadopted",
        "adoption_scope",
        "selection",
        "snapshot",
        "role",
        "inspection",
        "command",
        "actor",
    ],
)
def test_missing_tampered_or_unadopted_chain_is_never_admitted(world, fault):
    db = world.db
    if fault == "source_hash":
        db.execute("UPDATE design.uploads SET declared_digest='wrong'")
    elif fault == "source_size":
        db.execute("UPDATE design.uploads SET declared_size=100")
    elif fault == "pdf_hash":
        db.execute("UPDATE design.blobs SET digest='wrong' WHERE media_type=?", (PDF,))
    elif fault == "pdf_size":
        db.execute("UPDATE design.blobs SET byte_size=0 WHERE media_type=?", (PDF,))
    elif fault == "positive_pdf_size":
        db.execute("UPDATE design.blobs SET byte_size=1999 WHERE media_type=?", (PDF,))
    elif fault == "media":
        db.execute("UPDATE design.blobs SET media_type='text/plain' WHERE media_type=?", (PDF,))
    elif fault == "upload":
        db.execute("UPDATE design.uploads SET state='quarantined'")
    elif fault == "verify":
        db.execute("UPDATE design.operations SET state='failed' WHERE kind='verify-upload'")
    elif fault == "relation":
        db.execute("UPDATE design.document_relations SET verification='unverified'")
    elif fault == "missing_relation":
        db.execute("DELETE FROM design.document_relations")
    elif fault == "missing_run":
        db.execute("DELETE FROM design.word_render_runs")
    elif fault in {"partial", "chain"}:
        outcome = copy.deepcopy(world.outcome)
        if fault == "partial":
            outcome.update(coverage="partial", gaps=["not proven"])
        else:
            outcome["chain"]["renderer_digest"] = "f" * 64
        db.execute("UPDATE design.word_render_runs SET outcome=?", (json.dumps(outcome),))
    elif fault == "profile":
        db.execute("UPDATE design.word_render_runs SET profile_digest=?", ("f" * 64,))
    elif fault == "operation":
        db.execute("UPDATE design.operations SET state='failed' WHERE kind='word-render'")
    elif fault == "input":
        db.execute("UPDATE design.operations SET input_digest='wrong' WHERE kind='word-render'")
    elif fault == "unadopted":
        db.execute(
            "DELETE FROM design.audit_entries WHERE event_type='word.material_adoption_recorded'"
        )
    elif fault == "adoption_scope":
        db.execute(
            "UPDATE design.audit_entries SET bid_id=? WHERE event_type='word.material_adoption_recorded'",
            (uid(99),),
        )
    elif fault == "selection":
        db.execute("DELETE FROM design.audit_entries WHERE event_type='word.material_selected'")
    elif fault == "snapshot":
        db.execute("UPDATE design.material_snapshots SET digest='wrong'")
    elif fault == "role":
        db.execute(
            "UPDATE design.document_files SET role='tender' WHERE id=(SELECT file_id FROM design.document_file_versions WHERE version_id=?)",
            (world.pdf,),
        )
    elif fault == "inspection":
        db.execute("UPDATE design.word_intake_receipts SET inspection_digest='wrong'")
    elif fault == "command":
        db.execute("UPDATE design.commands SET request_digest='wrong'")
    elif fault == "actor":
        db.execute("UPDATE design.commands SET actor_id=?", (uid(95),))
    with pytest.raises(PackageError, match=admission.ERROR):
        observe(world, current=True)
    assert admission.eligible(world.c, world.bid, world.pdf) is False


def test_later_failed_run_blocks_new_use_without_replacing_exact_frozen_history(world):
    before = observe(world)
    world.db.execute(
        "INSERT INTO design.word_render_runs VALUES(?,?,?,?,?,?,?,?)",
        (world.bid, uid(98), world.word, None, "f" * 64, "{}", "{}", 10),
    )
    with pytest.raises(PackageError):
        observe(world, current=True)
    assert observe(world) == before


def test_changed_current_body_blocks_new_member_but_not_existing_frozen_evidence(world):
    before = observe(world)
    world.db.execute("UPDATE design.bid_profiles SET current_body_id=?", (uid(97),))
    with pytest.raises(PackageError):
        observe(world, current=True)
    assert observe(world) == before


def test_cross_bid_or_unrelated_document_does_not_gain_a_source_qualification(world):
    assert admission.observe(world.c, uid(99), world.pdf, current=True) is None
    assert admission.observe(world.c, world.bid, uid(99), current=True) is None
    assert not admission.eligible(world.c, uid(99), world.pdf)


def test_missing_relation_and_run_is_not_hidden_as_an_ordinary_unproven_pdf(world):
    world.db.execute("DELETE FROM design.document_relations")
    world.db.execute("DELETE FROM design.word_render_runs")
    with pytest.raises(PackageError):
        observe(world)


def test_authoring_output_is_left_to_its_existing_build_admission_observer(world):
    world.db.execute("DELETE FROM design.word_intake_receipts")
    world.db.execute("DELETE FROM design.word_render_runs")
    world.db.execute("INSERT INTO design.build_outputs VALUES(?,?)", (world.bid, world.pdf))
    assert observe(world) is None  # Not granted qualification by this Word observer.


def test_a_build_output_label_cannot_hide_an_invalid_actual_word_run(world):
    world.db.execute("INSERT INTO design.build_outputs VALUES(?,?)", (world.bid, world.pdf))
    world.db.execute("UPDATE design.uploads SET declared_size=1")
    with pytest.raises(PackageError):
        observe(world)
