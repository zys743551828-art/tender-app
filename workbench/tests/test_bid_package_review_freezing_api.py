"""Fresh full-schema PG, real auth/API and explicit memory objects; never a review job."""
# ruff: noqa: F401,F811

import os

import pytest
from test_bid_package_original_verification_api import (
    TestOriginalVerification as OriginalVerificationCases,
)
from test_bid_package_review_preview_api import (
    api,
    counts,
    database,
    headers,
    requirements,
    uid,
    world,
)

from packages.contracts.bid_package_requirements_api import valid
from packages.domain.bid_package_original_verification import read_input
from packages.domain.review_identity import digest

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"), reason="requires grouped isolated PG"
)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestFreezing:
    original_case = OriginalVerificationCases.original_case

    @pytest.fixture
    def frozen_case(self, original_case):
        w, preview, body, calls, state, path = original_case
        scope = (
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            preview["manifest"]["inventory"]["manifest"]["id"],
        )
        captured = read_input(*scope, body)
        return {
            "w": w,
            "scope": scope,
            "body": body | {"context_digest": captured.execution_context["semantic_digest"]},
            "calls": calls,
            "state": state,
            "path": path.replace("review-original-verification", "frozen-review-inputs"),
            "headers": headers(w),
        }

    def post(self, f, body=None, headers_override=None):
        return f["w"]["client"].post(
            f["path"],
            json=f["body"] if body is None else body,
            headers=f["headers"] if headers_override is None else headers_override,
        )

    def test_freeze_persists_self_contained_input_and_ack_without_review_job(self, frozen_case):
        import json

        f = frozen_case
        w = f["w"]
        c = w["database"]["owner"]
        before = counts(w)
        jobs = c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"]
        response = self.post(f)
        assert response.status_code == 201, response.text
        value = response.json()
        assert valid("PackageReviewFrozenInputView", value)
        assert digest(value["manifest"]) == value["digest"]
        assert value["manifest"]["kind"] == "frozen_input"
        assert value["manifest"]["review_ready"] is value["manifest"]["launch_available"] is False
        row = c.execute(
            "SELECT * FROM design.bid_package_review_inputs WHERE id=%s", (value["manifest"]["id"],)
        ).fetchone()
        root = json.loads(row["evidence_text"])
        assert root["selection"]["target"]["manifest"]["revision_id"] == f["scope"][2]
        assert root["context"]["facts"] and len(root["documents"]) == 2
        assert all("object_key" not in doc for doc in root["documents"])
        assert c.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"] == jobs
        assert counts(w)[-1] == before[-1] + 1
        loaded = w["client"].get(f["path"] + "/" + value["manifest"]["id"])
        assert loaded.status_code == 200 and loaded.json() == value

    def test_replay_and_historical_read_survive_source_withdrawal_close_and_store_unavailable(
        self, frozen_case, monkeypatch
    ):
        from packages.domain import storage
        from packages.domain.runtime import DomainError

        f = frozen_case
        w = f["w"]
        c = w["database"]["owner"]
        original = self.post(f)
        assert original.status_code == 201, original.text
        original_calls = len(f["calls"])
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (w["sources"][0],),
        )
        c.execute("UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (f["scope"][0],))

        def unavailable():
            raise DomainError("OBJECT_STORE_NOT_CONFIGURED", "synthetic disabled store", 503)

        monkeypatch.setattr(storage, "client", unavailable)
        replay = self.post(f)
        assert replay.status_code == 201, replay.text
        assert replay.headers.get("idempotent-replayed") == "true"
        assert replay.json() == original.json() and len(f["calls"]) == original_calls
        assert (
            w["client"].get(f["path"] + "/" + original.json()["manifest"]["id"]).json()
            == original.json()
        )

    def test_same_key_with_different_context_conflicts_before_io(self, frozen_case):
        f = frozen_case
        assert self.post(f).status_code == 201
        calls = len(f["calls"])
        result = self.post(f, f["body"] | {"context_digest": "0" * 64})
        assert result.status_code == 409 and result.json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(f["calls"]) == calls

    def test_wrong_context_and_missing_key_never_read_objects(self, frozen_case):
        f = frozen_case
        assert self.post(f, f["body"] | {"context_digest": "0" * 64}).status_code == 409
        assert (
            self.post(
                f,
                headers_override={
                    k: v for k, v in f["headers"].items() if k.lower() != "idempotency-key"
                },
            ).status_code
            == 428
        )
        assert not f["calls"]

    def test_changed_source_during_io_rolls_back_command_and_input(self, frozen_case):
        f = frozen_case
        w = f["w"]
        c = w["database"]["owner"]
        before = counts(w)
        f["state"]["during_read"] = lambda: c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (w["sources"][0],),
        )
        result = self.post(f)
        assert result.status_code == 409, result.text
        assert counts(w) == before
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.bid_package_review_inputs WHERE bid_id=%s",
                (f["scope"][0],),
            ).fetchone()["n"]
            == 0
        )

    def test_frozen_records_are_append_only_for_owner_and_unwritable_by_worker(self, frozen_case):
        import psycopg

        f = frozen_case
        w = f["w"]
        result = self.post(f)
        assert result.status_code == 201, result.text
        input_id = result.json()["manifest"]["id"]
        with pytest.raises(psycopg.Error):
            with w["database"]["owner"].transaction():
                w["database"]["owner"].execute(
                    "UPDATE design.bid_package_review_inputs SET evidence_text='{}' WHERE id=%s",
                    (input_id,),
                )
        with psycopg.connect(w["database"]["api_dsn"]) as reader:
            assert reader.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_review_inputs','SELECT'),has_table_privilege(current_user,'design.bid_package_review_inputs','INSERT'),has_table_privilege(current_user,'design.bid_package_review_inputs','UPDATE'),has_table_privilege(current_user,'design.bid_package_review_inputs','DELETE')"
            ).fetchone() == (True, True, False, False)
        with psycopg.connect(w["database"]["worker_dsn"]) as worker:
            assert worker.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_review_inputs','SELECT'),has_table_privilege(current_user,'design.bid_package_review_inputs','INSERT'),has_table_privilege(current_user,'design.bid_package_review_inputs','UPDATE'),has_table_privilege(current_user,'design.bid_package_review_inputs','DELETE')"
            ).fetchone() == (True, False, False, False)
            assert worker.execute(
                "SELECT id FROM design.bid_package_review_inputs WHERE id=%s", (input_id,)
            ).fetchone()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute(
                    "DELETE FROM design.bid_package_review_inputs WHERE id=%s", (input_id,)
                )

    def test_concurrent_same_key_saves_one_record_and_one_command(self, frozen_case, monkeypatch):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        from packages.domain import original_verification

        f = frozen_case
        f["state"]["assert_zero_connections"] = False
        before = counts(f["w"])
        barrier = threading.Barrier(2)
        local = threading.local()
        real_verify = original_verification.verify

        def together(document):
            if not getattr(local, "seen", False):
                local.seen = True
                barrier.wait(timeout=10)
            real_verify(document)

        monkeypatch.setattr(original_verification, "verify", together)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.post(f), range(2)))
        assert all(r.status_code == 201 for r in results), [r.text for r in results]
        assert results[0].json() == results[1].json()
        assert sum(r.headers.get("idempotent-replayed") == "true" for r in results) == 1
        assert counts(f["w"])[-1] == before[-1] + 1
        assert (
            f["w"]["database"]["owner"]
            .execute(
                "SELECT count(*) AS n FROM design.bid_package_review_inputs WHERE bid_id=%s",
                (f["scope"][0],),
            )
            .fetchone()["n"]
            == 1
        )

    def test_forged_stored_evidence_is_rejected_at_commit_with_no_command_ack(self, frozen_case):
        import json

        import psycopg
        from psycopg.rows import dict_row

        from packages.domain.bid_package_review_input_repository import KIND, insert
        from packages.domain.runtime import Command, sha

        f = frozen_case
        w = f["w"]
        original = self.post(f)
        assert original.status_code == 201, original.text
        before = counts(w)
        row = (
            w["database"]["owner"]
            .execute(
                "SELECT evidence_text FROM design.bid_package_review_inputs WHERE id=%s",
                (original.json()["manifest"]["id"],),
            )
            .fetchone()
        )
        root = json.loads(row["evidence_text"])
        root["documents"][0]["blocks"][0]["text_content"] = "forged synthetic evidence"
        evidence_text = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        manifest = original.json()["manifest"] | {
            "id": uid(),
            "evidence_digest": sha(evidence_text.encode("utf-8")),
        }
        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(w["database"]["api_dsn"], row_factory=dict_row) as c:
                c.execute("SET LOCAL search_path=design,public")
                command = Command(c, w["actor"], KIND, f["scope"][3], uid(), f["body"])
                manifest["command_id"] = str(command.id)
                value = insert(c, manifest, evidence_text)
                command.finish(value, 201)
        assert counts(w) == before

    def test_expiry_at_deferred_commit_rolls_back_input_and_ack(self, frozen_case, monkeypatch):
        import time

        from test_bid_package_requirements_api import inventory
        from test_bid_package_review_preview_api import check

        from apps.api.bid_package_requirement_routes import tag
        from packages.domain.runtime import Command

        f = frozen_case
        w = f["w"]
        owner = w["database"]["owner"]
        old = owner.execute(
            "SELECT digest FROM design.bid_package_requirement_inventories WHERE id=%s",
            (f["scope"][3],),
        ).fetchone()
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+interval '5 seconds' WHERE source_id=%s",
            (w["sources"][0],),
        )
        response = inventory(w, tag=tag(f["scope"][2], old["digest"]))
        assert response.status_code == 201, response.text
        saved = response.json()
        body = {
            "package_digest": saved["manifest"]["package_digest"],
            "inventory_digest": saved["digest"],
            "coverage_attempt_id": None,
            "coverage_digest": None,
        }
        preview = check(w, saved, body).json()
        scope = (*f["scope"][:3], saved["manifest"]["id"])
        body |= {"input_digest": preview["digest"]}
        captured = read_input(*scope, body)
        body |= {"context_digest": captured.execution_context["semantic_digest"]}
        f = f | {"scope": scope, "path": f["path"].replace(f["scope"][3], scope[3]), "body": body}
        before = counts(w)
        calls = []
        finish = Command.finish

        def delayed(command, *args, **kwargs):
            calls.append(True)
            time.sleep(6)
            return finish(command, *args, **kwargs)

        monkeypatch.setattr(Command, "finish", delayed)
        result = self.post(f)
        assert calls and result.status_code == 409, result.text
        assert counts(w) == before
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM design.bid_package_review_inputs WHERE bid_id=%s",
                (scope[0],),
            ).fetchone()["n"]
            == 0
        )

    def test_cross_project_frozen_input_is_not_readable_through_another_scope(self, frozen_case):
        f = frozen_case
        result = self.post(f)
        assert result.status_code == 201, result.text
        wrong = f["path"].replace(f["scope"][0], uid()) + "/" + result.json()["manifest"]["id"]
        assert f["w"]["client"].get(wrong).status_code == 404
