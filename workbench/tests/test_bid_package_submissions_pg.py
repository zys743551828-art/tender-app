"""Exact complete-package facts against isolated nonowner PostgreSQL, without paid calls."""
# ruff: noqa: F401,F811

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_bid_package_api import world as package_world
from test_bid_package_requirements_api import database as base_database
from test_bid_package_requirements_api import inventory, requirements
from test_package_review_runs_api import TestPackageReviewRuns as _RunCases
from test_stable_lot_identity import api, catalog, headers, post, uid

from apps.api.views import bid_etag
from packages.contracts.package_submissions_api import valid
from packages.domain import bid_package_submissions as service
from packages.domain import storage
from packages.domain.runtime import DomainError, connection, sha

ADMIN_DSN = os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN")
pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="isolated nonowner F05 PG17 required")
ROOT = Path(__file__).resolve().parents[1]
RAW = b"%PDF-1.7\nSynthetic F05 exact package member.\n%%EOF\n"
EVIDENCE = b"Synthetic F05 already-happened submission receipt attachment."


@pytest.fixture(scope="module")
def database():
    source = base_database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        if (
            owner.execute(
                "SELECT to_regclass('design.bid_package_submission_bindings') AS name"
            ).fetchone()["name"]
            is None
        ):
            owner.execute((ROOT / "packages/contracts/sql/bid-package-submissions.sql").read_text())
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


@pytest.fixture
def world(api, request):
    return package_world.__wrapped__(api, SimpleNamespace(param=getattr(request, "param", RAW)))


@pytest.fixture
def exact(requirements, monkeypatch):
    w = requirements
    with connection() as c:
        assert (
            c.execute("SELECT current_user AS name").fetchone()["name"]
            == "fusion_package_requirements_service"
        )
        version, blob = uid(), uid()
        c.execute(
            "INSERT INTO design.blobs(id,digest,byte_size,object_key,media_type) VALUES(%s,%s,%s,%s,'text/plain') ON CONFLICT(digest) DO NOTHING",
            (blob, sha(EVIDENCE), len(EVIDENCE), "synthetic/f05-evidence/" + blob),
        )
        blob = str(
            c.execute("SELECT id FROM design.blobs WHERE digest=%s", (sha(EVIDENCE),)).fetchone()[
                "id"
            ]
        )
        c.execute(
            "INSERT INTO design.document_versions(id,bid_id,blob_id,original_name,obtained_at,artifact_kind,created_by) VALUES(%s,%s,%s,'synthetic-receipt.txt',now(),'source_original',%s)",
            (version, w["scope"].bid_id, blob, w["actor"]),
        )
    selection = {
        "package_id": w["own"]["manifest"]["package_id"],
        "revision_id": w["own"]["manifest"]["revision_id"],
        "package_digest": w["own"]["digest"],
        "inventory": None,
        "coverage": None,
        "review_run": None,
    }
    scope = (w["scope"].bid_id, selection["package_id"], selection["revision_id"])
    state = {
        "calls": [],
        "callback": None,
        "corrupt": False,
        "concurrent": False,
        "unavailable": False,
        "data": {sha(RAW): RAW, sha(EVIDENCE): EVIDENCE},
    }

    class Objects:
        def get_object(self, *, Bucket, Key):
            if state["unavailable"]:
                raise OSError("synthetic storage unavailable")
            if not state["concurrent"]:
                sessions = (
                    w["database"]["owner"]
                    .execute(
                        "SELECT xact_start,(SELECT count(*) FROM pg_locks l WHERE l.pid=a.pid AND l.granted) AS held_locks FROM pg_stat_activity a WHERE datname=current_database() AND usename='fusion_package_requirements_service'"
                    )
                    .fetchall()
                )
                assert all(
                    row["xact_start"] is None and row["held_locks"] == 0 for row in sessions
                ), sessions
            state["calls"].append(Key)
            if state["callback"]:
                callback, state["callback"] = state["callback"], None
                callback()
            row = (
                w["database"]["owner"]
                .execute("SELECT digest FROM design.blobs WHERE object_key=%s", (Key,))
                .fetchone()
            )
            data = state["data"][row["digest"]]
            return {"Body": io.BytesIO(data + (b"corrupt" if state["corrupt"] else b""))}

    monkeypatch.setattr(storage, "client", lambda: Objects())
    monkeypatch.setattr(storage, "bucket", lambda: "synthetic-f05")
    return w | {
        "submission_scope": scope,
        "selection": selection,
        "attachment": {
            "document_version_id": version,
            "digest": sha(EVIDENCE),
            "byte_size": len(EVIDENCE),
        },
        "io": state,
    }


def preview(w, selection=None):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return service.prepare(
            c, w["submission_scope"], selection or w["selection"], bid_etag_fn=bid_etag
        )


def request(w, *, selection=None, supersedes=None):
    value = preview(w, selection)
    body = {
        "kind": "offline_fact",
        "selection": value["selection_request"],
        "input_digest": value["input_digest"],
        "evidence": w["attachment"],
        "submitted_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "explanation": "Synthetic actual package was submitted outside this system; receipt is a user declaration.",
        "expected_head": {key: value["current_submission_head"][key] for key in ("id", "revision")}
        if supersedes
        else None,
        "correction_reason": "Synthetic correction of actual package selection."
        if supersedes
        else None,
    }
    return value, body


def register(w, body, tag, *, key=None, supersedes=None):
    return service.register(
        w["submission_scope"],
        w["actor"],
        key or uid(),
        body,
        tag,
        supersedes=supersedes,
        bid_etag_fn=bid_etag,
        final_auth=lambda: w["actor"],
    )


def counts(w):
    with connection() as c:
        return tuple(
            c.execute(
                f"SELECT count(*) AS n FROM design.{table} WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            for table in (
                "submission_records",
                "submission_heads",
                "bid_package_submission_bindings",
            )
        )


def test_exact_offline_package_native_head_and_original_ack(exact):
    p, body = request(exact)
    assert p["selection"]["inventory"] is None
    assert p["gate"]["manifest"]["allowed"] is False
    assert p["gate"]["manifest"]["gates"]["mandatory_confirmation"]["state"] == "unknown"
    key = uid()
    saved, replay = register(exact, body, p["bid_etag"], key=key)
    assert not replay and saved["status"] == 201
    assert valid("PackageSubmissionAppliedView", saved["body"])
    record = saved["body"]["submission"]
    m = record["package_binding"]["manifest"]
    assert record["subject_kind"] == "bid_package"
    assert record["body_version_id"] is record["review_id"] is None
    assert m["selection"]["target"] == exact["own"]
    assert m["original_bytes_verified"] and not m["pre_submission_system_check_verified"]
    assert len(exact["io"]["calls"]) == 2
    assert counts(exact) == (1, 1, 1)
    again, replay = register(exact, body, p["bid_etag"], key=key)
    assert replay and again == saved
    assert len(exact["io"]["calls"]) == 2
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        assert service.load(c, exact["scope"].bid_id, record["id"]) == record


def test_exact_inventory_preserved_but_standard_remains_blocked(exact):
    response = inventory(exact)
    assert response.status_code == 201, response.text
    inv = response.json()
    selection = exact["selection"] | {
        "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]}
    }
    p, body = request(exact, selection=selection)
    assert p["selection"]["inventory"] == inv
    assert not p["gate"]["manifest"]["inventory_complete"]
    with pytest.raises(DomainError, match="整包完整性") as error:
        register(exact, body | {"kind": "standard"}, p["bid_etag"])
    assert error.value.code == "PACKAGE_SUBMISSION_GATE_BLOCKED"
    assert exact["io"]["calls"] == [] and counts(exact) == (0, 0, 0)
    saved, _ = register(exact, body, p["bid_etag"])
    assert (
        saved["body"]["submission"]["package_binding"]["manifest"]["selection"]["inventory"] == inv
    )
    assert len(exact["io"]["calls"]) == 3


def test_closed_archived_expired_sources_allow_fact_and_ack_replay(exact):
    with connection() as c:
        c.execute(
            "UPDATE design.bid_profiles SET phase='closed',archived_at=clock_timestamp() WHERE bid_id=%s",
            (exact["scope"].bid_id,),
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=ANY(%s::uuid[])",
            (exact["sources"],),
        )
    p, body = request(exact)
    assert p["gate"]["manifest"]["gates"]["current_input"]["state"] == "blocked"
    key = uid()
    saved, _ = register(exact, body, p["bid_etag"], key=key)
    with connection() as c:
        value = c.execute(
            "SELECT phase,archived_at FROM design.bid_profiles WHERE bid_id=%s",
            (exact["scope"].bid_id,),
        ).fetchone()
        assert value["phase"] == "closed" and value["archived_at"] is not None
    exact["io"]["unavailable"] = True
    again, replay = register(exact, body, p["bid_etag"], key=key)
    assert replay and saved == again


@pytest.mark.parametrize("change", ["bytes", "source", "head", "future"])
def test_new_registration_rejects_changes_and_rolls_back(exact, change):
    p, body = request(exact)
    if change == "bytes":
        exact["io"]["corrupt"] = True
    elif change == "source":

        def callback():
            with connection() as c:
                c.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (exact["sources"][0],),
                )

        exact["io"]["callback"] = callback
    elif change == "head":

        def callback():
            with connection() as c:
                c.execute(
                    "UPDATE design.bids SET revision=revision+1 WHERE id=%s",
                    (exact["scope"].bid_id,),
                )

        exact["io"]["callback"] = callback
    else:
        body["submitted_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    with pytest.raises(DomainError) as error:
        register(exact, body, p["bid_etag"])
    assert error.value.code in {
        "ORIGINAL_BYTES_CORRUPTED",
        "PACKAGE_SUBMISSION_INPUT_CHANGED",
        "PACKAGE_SUBMISSION_CONTEXT_CHANGED",
        "REVISION_CONFLICT",
        "PACKAGE_SUBMISSION_FUTURE_TIME",
    }
    assert counts(exact) == (0, 0, 0)


def test_multi_member_package_correction_keeps_old_ack_and_rejects_downgrade(exact):
    from test_bid_package_api import attach
    from test_bid_package_repository import add_document

    p, body = request(exact)
    original_key = uid()
    saved, _ = register(exact, body, p["bid_etag"], key=original_key)
    first_id = saved["body"]["submission"]["id"]
    raw = RAW + b"Synthetic separate commercial attachment.\n"
    exact["io"]["data"][sha(raw)] = raw
    owner = exact["database"]["owner"]
    with owner.transaction():
        second = add_document(owner, exact["scope"], exact["actor"], category="commercial", raw=raw)
        attach(owner, exact["scope"].bid_id, exact["actor"], second)
    item = {
        "member_id": "commercial-original",
        "document_version_id": second.document_version_id,
        "parse_run_id": second.parse.parse_run_id,
        "purposes": ["commercial"],
        "parts": [
            {
                "part_id": "commercial",
                "category": "commercial",
                "first_page": 1,
                "last_page": 2,
                "shared_attachment": False,
                "heading_path": [],
            }
        ],
    }
    path = exact["base"] + "/" + exact["selection"]["package_id"]
    current = exact["client"].get(path)
    changed = exact["client"].post(
        path + "/revisions",
        json={"members": [exact["item"], item]},
        headers=headers(exact, etag=current.headers["etag"]),
    )
    assert changed.status_code == 201, changed.text
    own = changed.json()
    second_scope = (
        exact["scope"].bid_id,
        own["manifest"]["package_id"],
        own["manifest"]["revision_id"],
    )
    second_world = exact | {
        "submission_scope": second_scope,
        "selection": exact["selection"]
        | {"revision_id": second_scope[2], "package_digest": own["digest"]},
    }
    next_preview, correction = request(second_world, supersedes=first_id)
    result, _ = register(second_world, correction, next_preview["bid_etag"], supersedes=first_id)
    second_record = result["body"]["submission"]
    assert (
        len(
            second_record["package_binding"]["manifest"]["selection"]["target"]["manifest"][
                "members"
            ]
        )
        == 2
    )
    assert second_record["package_binding"]["manifest"]["head_revision"] == 2
    assert counts(exact) == (2, 1, 2)
    with connection() as c:
        assert service.load(c, exact["scope"].bid_id, first_id)["current"] is False
    exact["io"]["unavailable"] = True
    repeated, replay = register(exact, body, p["bid_etag"], key=original_key)
    assert replay and repeated == saved
    with pytest.raises(psycopg.errors.CheckViolation, match="cannot_become_single_body"):
        with connection() as c:
            c.execute(
                "INSERT INTO design.submission_records(id,bid_id,body_version_id,kind,evidence,submitted_at,created_by,supersedes_id) VALUES(%s,%s,%s,'offline_fact','{}',now(),%s,%s)",
                (
                    uid(),
                    exact["scope"].bid_id,
                    exact["member"].document_version_id,
                    exact["actor"],
                    second_record["id"],
                ),
            )


def test_explicit_single_body_to_package_correction_is_one_native_head(exact):
    old = uid()
    with connection() as c:
        c.execute(
            "INSERT INTO design.submission_records(id,bid_id,body_version_id,kind,evidence,submitted_at,created_by) VALUES(%s,%s,%s,'offline_fact','{}',now()-interval '1 hour',%s)",
            (old, exact["scope"].bid_id, exact["member"].document_version_id, exact["actor"]),
        )
        c.execute(
            "INSERT INTO design.submission_heads(bid_id,submission_id,revision) VALUES(%s,%s,1)",
            (exact["scope"].bid_id, old),
        )
    p, body = request(exact, supersedes=old)
    assert p["current_submission_head"]["subject_kind"] == "single_body"
    saved, _ = register(exact, body, p["bid_etag"], supersedes=old)
    assert saved["body"]["submission"]["supersedes_id"] == old
    assert counts(exact) == (2, 1, 1)


def test_concurrent_identical_key_one_fact_and_changed_requests_conflict(exact):
    p, body = request(exact)
    key = uid()
    exact["io"]["concurrent"] = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: register(exact, body, p["bid_etag"], key=key), range(2)))
    assert values[0][0] == values[1][0]
    assert sorted(value[1] for value in values) == [False, True]
    assert counts(exact) == (1, 1, 1)
    for changed_body, tag in (
        (body | {"explanation": "Changed original request"}, p["bid_etag"]),
        (body, '"wrong-original-etag"'),
    ):
        with pytest.raises(DomainError) as error:
            register(exact, changed_body, tag, key=key)
        assert error.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(DomainError) as error:
        register(exact, body, p["bid_etag"])
    assert error.value.status == 412


@pytest.mark.parametrize("change", ["native-evidence", "command-ack"])
def test_deferred_guards_reject_resealed_write_path_mismatches(exact, monkeypatch, change):
    from packages.domain import bid_package_submission_repository as repository
    from packages.domain.runtime import Command

    p, body = request(exact)
    if change == "native-evidence":
        original = repository.native_evidence
        monkeypatch.setattr(
            repository,
            "native_evidence",
            lambda value: original(value) | {"platform_submission_verified": True},
        )
    else:
        original_finish = Command.finish

        def changed_finish(self, value, status=200, headers=None):
            value = deepcopy(value)
            value["command"]["request_digest"] = "f" * 64
            return original_finish(self, value, status, headers)

        monkeypatch.setattr(Command, "finish", changed_finish)
    with pytest.raises(psycopg.errors.CheckViolation) as error:
        register(exact, body, p["bid_etag"])
    assert "package_submission_" in str(error.value)
    assert counts(exact) == (0, 0, 0)


def test_direct_sql_without_binding_or_fake_standard_cannot_create_package_fact(exact):
    for kind, expected in (("offline_fact", "binding_missing"), ("standard", "gate_unproven")):
        with pytest.raises(psycopg.errors.CheckViolation, match=expected):
            with connection() as c:
                c.execute(
                    "INSERT INTO design.submission_records(id,bid_id,subject_kind,kind,gate_snapshot,evidence,submitted_at,created_by) VALUES(%s,%s,'bid_package',%s,'{}','{}',now(),%s)",
                    (uid(), exact["scope"].bid_id, kind, exact["actor"]),
                )
    assert counts(exact) == (0, 0, 0)


def test_old_legacy_critical_and_dismissed_risks_survive_another_package_selection(exact):
    from test_bid_package_api import create

    with connection() as c:
        bid, actor = exact["scope"].bid_id, exact["actor"]
        command, operation, frozen, review = [uid() for _ in range(4)]
        material = c.execute(
            "SELECT material_id FROM design.rule_sets WHERE id=%s",
            (exact["inventory_body"]["rule_set_id"],),
        ).fetchone()["material_id"]
        c.execute(
            "INSERT INTO design.commands(id,actor_id,command_kind,target_id,idempotency_key,request_digest) VALUES(%s,%s,'synthetic-f05-legacy-risk',%s,%s,%s)",
            (command, actor, bid, uid(), sha({})),
        )
        c.execute(
            "INSERT INTO design.operations(id,bid_id,command_id,kind,input_digest,state,handler_version,finished_at) VALUES(%s,%s,%s,'synthetic-legacy-review',%s,'succeeded','synthetic/1',now())",
            (operation, bid, command, sha({})),
        )
        c.execute(
            "INSERT INTO design.blobs(id,digest,byte_size,object_key,media_type) VALUES(%s,%s,2,%s,'application/json') ON CONFLICT(digest) DO NOTHING",
            (uid(), sha({}), "synthetic/f05-legacy-archive/" + uid()),
        )
        archive = c.execute("SELECT id FROM design.blobs WHERE digest=%s", (sha({}),)).fetchone()[
            "id"
        ]
        c.execute(
            "INSERT INTO design.review_inputs(id,bid_id,material_snapshot_id,body_version_id,input_digest,method_digest,manifest,frozen_at,evidence_manifest_blob_id,manifest_digest,as_of,evaluation_context_digest) VALUES(%s,%s,%s,%s,%s,%s,'{}',now(),%s,%s,now(),%s)",
            (
                frozen,
                bid,
                material,
                exact["member"].document_version_id,
                sha({}),
                sha({}),
                archive,
                sha({}),
                sha({}),
            ),
        )
        c.execute(
            "INSERT INTO design.review_runs(id,bid_id,input_id,operation_id) VALUES(%s,%s,%s,%s)",
            (review, bid, frozen, operation),
        )
        ids = [uid(), uid()]
        for identity in ids:
            c.execute(
                "INSERT INTO design.findings(id,bid_id,review_id,rule_id,category,severity,verdict,statement,searched_ranges,evidence_ids) VALUES(%s,%s,%s,%s,'response','critical','violated','Synthetic retained historical critical risk','[]',%s)",
                (identity, bid, review, exact["rule"], [exact["evidence"]]),
            )
        decision = uid()
        c.execute(
            "INSERT INTO design.decisions(id,bid_id,object_kind,object_id,object_revision,decision,reason,evidence_ids,actor_id) VALUES(%s,%s,'finding',%s,1,'dismiss','Synthetic human opinion is not a recheck',%s,%s)",
            (decision, bid, ids[1], [exact["evidence"]], actor),
        )
        c.execute(
            "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'finding',%s,1,%s)",
            (bid, ids[1], decision),
        )
    before = preview(exact)
    risk = before["gate"]["manifest"]["gates"]["known_blocking_risks"]
    assert risk["state"] == "blocked" and risk["blocked_count"] == 2
    assert {row["finding"]["lifecycle"] for row in risk["risks"]} == {"open", "dismissed"}
    newer = create(exact).json()
    other = exact | {
        "submission_scope": (
            bid,
            newer["manifest"]["package_id"],
            newer["manifest"]["revision_id"],
        ),
        "selection": exact["selection"]
        | {
            "package_id": newer["manifest"]["package_id"],
            "revision_id": newer["manifest"]["revision_id"],
            "package_digest": newer["digest"],
        },
    }
    p, body = request(other)
    assert p["gate"]["manifest"]["gates"]["known_blocking_risks"]["blocked_count"] == 2
    saved, _ = register(other, body, p["bid_etag"])
    assert saved["body"]["submission"]["open_risk_snapshot"]["blocked_count"] == 2


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestExactReviewBinding:
    original_case = _RunCases.original_case
    frozen_case = _RunCases.frozen_case
    execution_case = _RunCases.execution_case
    prepared_case = _RunCases.prepared_case
    exact_inventory_proof_case = _RunCases.exact_inventory_proof_case
    launch_case = _RunCases.launch_case
    post = _RunCases.post
    launch = _RunCases.launch
    message = _RunCases.message
    provider = _RunCases.provider

    def test_real_partial_review_and_proof_are_frozen_without_granting_standard(
        self, launch_case, monkeypatch
    ):
        from apps.worker import engine

        case = launch_case
        calls = self.provider(case, monkeypatch)
        launched = self.launch(case)
        assert launched.status_code == 202, launched.text
        run = launched.json()
        engine.handle_lane("review", self.message(case, run))
        actual = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert actual.status_code == 200, actual.text
        run = actual.json()
        assert run["operation"]["state"] == "succeeded" and len(calls) == 1
        assert run["result"]["manifest"]["overall_coverage"] == "partial"
        inv = case["w"]["client"].get(case["w"]["requirement_base"] + "/" + case["scope"][3]).json()
        w = case["w"] | {
            "submission_scope": case["scope"][:3],
            "selection": {
                "package_id": case["scope"][1],
                "revision_id": case["scope"][2],
                "package_digest": case["w"]["own"]["digest"],
                "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]},
                "coverage": None,
                "review_run": {
                    "id": run["id"],
                    "input_digest": run["input_digest"],
                    "result_digest": run["result"]["digest"],
                },
            },
            "attachment": {
                "document_version_id": case["w"]["member"].document_version_id,
                "digest": case["w"]["member"].file_digest,
                "byte_size": len(b"synthetic-original-v1"),
            },
        }
        p, body = request(w)
        assert p["gate"]["manifest"]["gates"]["core_coverage"]["extraction_range_proven"]
        assert not p["gate"]["manifest"]["allowed"]
        with pytest.raises(DomainError) as error:
            register(w, body | {"kind": "standard"}, p["bid_etag"])
        assert error.value.code == "PACKAGE_SUBMISSION_GATE_BLOCKED"
        saved, _ = register(w, body, p["bid_etag"])
        m = saved["body"]["submission"]["package_binding"]["manifest"]
        assert m["review_run"] == run
        assert m["inventory_proof"]["manifest"]["extraction_receipt_state"] == "matched"
        assert m["context"]["risk_history"]["complete"] is True
        assert m["context"]["risk_history"]["package_runs"] == [run]
        target = Path("/tmp/tender-completion-runtime/package-submissions-browser")
        target.mkdir(parents=True, exist_ok=True)
        for name, value in {
            "package": w["own"],
            "inventory": inv,
            "preview": p,
            "request": body,
            "applied": saved["body"],
            "headers": saved["headers"],
            "run": run,
            "scope": {
                "bid_id": w["scope"].bid_id,
                "actor_id": w["actor"],
                "scope": list(w["submission_scope"]),
                "synthetic_only": True,
                "paid_calls": False,
            },
        }.items():
            (target / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2))
