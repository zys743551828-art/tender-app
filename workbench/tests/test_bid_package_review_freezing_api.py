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
        history = w["client"].get(f["path"])
        assert history.status_code == 200 and valid("PackageReviewFrozenInputPage", history.json())
        assert history.json()["items"][0]["id"] == original.json()["manifest"]["id"]
        assert len(f["calls"]) == original_calls

    def test_directory_pages_newest_first_and_refresh_discovers_later_saves(self, frozen_case):
        f = frozen_case
        w = f["w"]
        records = []
        for _ in range(3):
            response = self.post(f, headers_override=headers(w))
            assert response.status_code == 201, response.text
            records.append(response.json())
        first = w["client"].get(f["path"], params={"limit": 1})
        assert first.status_code == 200 and valid("PackageReviewFrozenInputPage", first.json())
        page = first.json()
        assert page["items"][0]["id"] == records[-1]["manifest"]["id"]
        assert page["has_more"] and page["next_cursor"]
        latest = self.post(f, headers_override=headers(w))
        assert latest.status_code == 201, latest.text
        before, calls = counts(w), len(f["calls"])
        seen = page["items"]
        while page["has_more"]:
            response = w["client"].get(
                f["path"], params={"limit": 1, "cursor": page["next_cursor"]}
            )
            assert response.status_code == 200 and valid(
                "PackageReviewFrozenInputPage", response.json()
            )
            page = response.json()
            seen += page["items"]
        assert page["next_cursor"] is None
        assert [item["id"] for item in seen] == [r["manifest"]["id"] for r in reversed(records)]
        for summary, record in zip(seen, reversed(records), strict=True):
            assert summary["digest"] == record["digest"]
            for key in ("actor_id", "input_digest", "context_digest"):
                assert summary[key] == record["manifest"][key]
            assert "manifest" not in summary and "evidence_text" not in summary
        fresh = w["client"].get(f["path"]).json()
        assert (
            len(fresh["items"]) == 4 and fresh["items"][0]["id"] == latest.json()["manifest"]["id"]
        )
        assert counts(w) == before and len(f["calls"]) == calls

    def test_empty_directory_auth_scope_and_query_bounds(self, frozen_case):
        from fastapi.testclient import TestClient

        f = frozen_case
        w = f["w"]
        empty = w["client"].get(f["path"])
        assert empty.status_code == 200 and valid("PackageReviewFrozenInputPage", empty.json())
        assert empty.json()["items"] == [] and empty.json()["next_cursor"] is None
        with TestClient(w["app"]) as anonymous:
            assert anonymous.get(f["path"]).status_code == 401
        for field in f["scope"]:
            assert w["client"].get(f["path"].replace(field, uid(), 1)).status_code == 404
        for params in ({"limit": 0}, {"limit": 101}, {"cursor": "broken"}, {"cursor": "x" * 4097}):
            assert w["client"].get(f["path"], params=params).status_code == 422
        assert not f["calls"]

    def test_cursor_is_signed_and_bound_to_exact_inventory_not_current_head(self, frozen_case):
        from test_bid_package_requirements_api import inventory

        from apps.api.bid_package_requirement_routes import tag
        from packages.domain.runtime import sha
        from packages.identity import pagination

        f = frozen_case
        w = f["w"]
        for _ in range(2):
            assert self.post(f, headers_override=headers(w)).status_code == 201
        first = w["client"].get(f["path"], params={"limit": 1}).json()
        token = first["next_cursor"]
        invalid = w["client"].get(f["path"], params={"cursor": token + "x"})
        assert invalid.status_code == 422 and invalid.json()["code"] == "INVALID_CURSOR"
        binding = sha({"directory": "package-review-frozen-inputs/1", "scope": f["scope"]})
        for date in ("not-a-date", "2026-10-19T00:00:00"):
            bad = pagination.encode(binding, [date, first["items"][0]["id"]])
            response = w["client"].get(f["path"], params={"cursor": bad})
            assert response.status_code == 422 and response.json()["code"] == "INVALID_CURSOR"
        created = inventory(w, tag=tag(f["scope"][2], f["body"]["inventory_digest"]))
        assert created.status_code == 201, created.text
        new_path = f["path"].replace(f["scope"][3], created.json()["manifest"]["id"])
        response = w["client"].get(new_path, params={"cursor": token})
        assert response.status_code == 422 and response.json()["code"] == "INVALID_CURSOR"
        old = w["client"].get(f["path"])
        assert old.status_code == 200 and len(old.json()["items"]) == 2

    def test_same_key_with_different_context_conflicts_before_io(self, frozen_case):
        f = frozen_case
        assert self.post(f).status_code == 201
        calls = len(f["calls"])
        result = self.post(f, f["body"] | {"context_digest": "0" * 64})
        assert result.status_code == 409 and result.json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(f["calls"]) == calls

    def test_execution_check_is_current_readonly_observation_not_original_or_publication_proof(
        self, frozen_case, monkeypatch
    ):
        from packages.domain import storage

        f = frozen_case
        saved = self.post(f)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        before, calls = counts(f["w"]), len(f["calls"])

        def unavailable():
            raise AssertionError("eligibility must not read object storage")

        monkeypatch.setattr(storage, "client", unavailable)
        path = f["path"] + "/" + value["manifest"]["id"] + "/execution-check"
        response = f["w"]["client"].post(
            path,
            json={"frozen_digest": value["digest"]},
            headers={k: v for k, v in f["headers"].items() if k.lower() != "idempotency-key"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert valid("PackageReviewEligibilityObservation", result)
        assert (
            result["frozen_digest"] == value["digest"]
            and result["input_digest"] == value["manifest"]["input_digest"]
        )
        assert (
            result["parse_evidence_status"] == "matched"
            and result["original_verification"] == "not_performed"
        )
        assert (
            result["publication_authorized"]
            is result["launch_available"]
            is result["review_ready"]
            is False
        )
        assert (
            "PACKAGE_REVIEW_FACTS_UNPROVEN" in result["blockers"]
            and "PACKAGE_REVIEW_EXECUTOR_NOT_READY" in result["blockers"]
        )
        assert counts(f["w"]) == before and len(f["calls"]) == calls
        assert f["w"]["client"].get(path.removesuffix("/execution-check")).json() == value

    def verify_frozen(self, f, value):
        from packages.domain.bid_package_frozen_originals import verify
        from packages.domain.bid_package_review_eligibility import inspect

        context = inspect(f["scope"], value["manifest"]["id"], value["digest"])
        return verify(
            f["scope"],
            value["manifest"]["id"],
            value["digest"],
            context["current_context"]["semantic_digest"],
        )

    def test_frozen_originals_stream_without_connections_preserve_history_and_still_block_publication(
        self, frozen_case
    ):
        import json

        from packages.domain.bid_package_frozen_originals import recheck_for_publication
        from packages.domain.runtime import DomainError, connection

        f = frozen_case
        value = self.post(f).json()
        before, calls = counts(f["w"]), len(f["calls"])
        receipt = self.verify_frozen(f, value)
        result = receipt.observation()
        assert len(f["calls"]) - calls == len(result["originals"]) == 2
        assert {d["role"] for d in result["originals"]} == {"target", "authority"}
        assert result["original_verification"] == "verified_at_observation"
        assert result["publication_authorized"] is result["launch_available"] is False
        assert "object_key" not in json.dumps(result) and "text_content" not in json.dumps(result)
        assert "object_key" not in repr(receipt) and "synthetic-original" not in repr(receipt)
        result["originals"].clear()
        assert len(receipt.observation()["originals"]) == 2
        with pytest.raises(DomainError) as error, connection() as c:
            recheck_for_publication(c, receipt)
        assert error.value.code == "PACKAGE_REVIEW_EXECUTION_BLOCKED"
        assert len(f["calls"]) - calls == 2 and counts(f["w"]) == before
        assert f["w"]["client"].get(f["path"] + "/" + value["manifest"]["id"]).json() == value

    @pytest.mark.parametrize("change", ["close", "source", "facts", "method", "policy"])
    def test_frozen_originals_reject_change_during_lock_free_io(
        self, frozen_case, monkeypatch, change
    ):
        from packages.domain import package_review_method as method
        from packages.domain.runtime import DomainError

        f = frozen_case
        value = self.post(f).json()
        owner = f["w"]["database"]["owner"]

        def mutate():
            if change == "close":
                owner.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (f["scope"][0],),
                )
            elif change == "source":
                owner.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (f["w"]["sources"][0],),
                )
            elif change == "facts":
                OriginalVerificationCases.seed_fact(self, f["w"])
            elif change == "method":
                monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-race-model")
            else:
                monkeypatch.setitem(method.POLICY, "version", "synthetic-race-policy")

        f["state"]["during_read"] = mutate
        with pytest.raises(DomainError) as error:
            self.verify_frozen(f, value)
        assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
        assert f["w"]["client"].get(f["path"] + "/" + value["manifest"]["id"]).json() == value

    @pytest.mark.parametrize("change", ["close", "source", "facts", "method"])
    def test_publication_rechecks_after_original_receipt_without_repeating_io(
        self, frozen_case, monkeypatch, change
    ):
        from packages.domain.bid_package_frozen_originals import recheck_for_publication
        from packages.domain.runtime import DomainError, connection

        f = frozen_case
        value = self.post(f).json()
        receipt = self.verify_frozen(f, value)
        calls = len(f["calls"])
        owner = f["w"]["database"]["owner"]
        if change == "close":
            owner.execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (f["scope"][0],)
            )
        elif change == "source":
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (f["w"]["sources"][0],),
            )
        elif change == "facts":
            OriginalVerificationCases.seed_fact(self, f["w"])
        else:
            monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-before-publication")
        before = counts(f["w"])
        with pytest.raises(DomainError) as error, connection() as c:
            recheck_for_publication(c, receipt)
        assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"
        assert len(f["calls"]) == calls and counts(f["w"]) == before

    @pytest.mark.parametrize(
        "payload", [b"synthetic-corrupted", b"", b"synthetic-original-v1-overlong"]
    )
    def test_frozen_originals_fail_on_corrupt_stream_without_receipt(self, frozen_case, payload):
        from packages.domain.runtime import DomainError

        f = frozen_case
        value = self.post(f).json()
        f["state"]["bytes"] = payload
        before = counts(f["w"])
        with pytest.raises(DomainError) as error:
            self.verify_frozen(f, value)
        assert error.value.code == "ORIGINAL_BYTES_CORRUPTED"
        assert counts(f["w"]) == before

    def test_frozen_originals_reject_context_before_io_and_publication_requires_fresh_transaction(
        self, frozen_case
    ):
        from packages.domain.bid_package_frozen_originals import recheck_for_publication, verify
        from packages.domain.runtime import DomainError, connection

        f = frozen_case
        value = self.post(f).json()
        calls = len(f["calls"])
        with pytest.raises(DomainError) as error:
            verify(f["scope"], value["manifest"]["id"], value["digest"], "0" * 64)
        assert error.value.code == "PACKAGE_REVIEW_CONTEXT_CHANGED" and len(f["calls"]) == calls
        receipt = self.verify_frozen(f, value)
        with pytest.raises(ValueError), connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            recheck_for_publication(c, receipt)

    def test_execution_check_observes_close_source_method_policy_and_facts_without_changing_history(
        self, frozen_case, monkeypatch
    ):
        from packages.domain import package_review_method as method

        f = frozen_case
        saved = self.post(f)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        w = f["w"]
        c = w["database"]["owner"]
        OriginalVerificationCases.seed_fact(self, w)
        c.execute("UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (f["scope"][0],))
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (w["sources"][0],),
        )
        monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-after-freeze")
        monkeypatch.setitem(method.POLICY, "version", "synthetic-policy-after-freeze")
        path = f["path"] + "/" + value["manifest"]["id"]
        response = w["client"].post(
            path + "/execution-check", json={"frozen_digest": value["digest"]}, headers=f["headers"]
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert valid("PackageReviewEligibilityObservation", result)
        assert {
            "PROJECT_WORK_CLOSED",
            "PACKAGE_REVIEW_SOURCE_CHANGED",
            "PACKAGE_REVIEW_SOURCE_NOT_EFFECTIVE",
            "PACKAGE_REVIEW_METHOD_CHANGED",
            "PACKAGE_REVIEW_POLICY_CHANGED",
            "PACKAGE_REVIEW_FACTS_CHANGED",
        } <= set(result["blockers"])
        assert result["parse_evidence_status"] == "matched"
        assert w["client"].get(path).json() == value

    def test_execution_check_rechecks_full_parse_metadata_and_preserves_old_root(self, frozen_case):
        f = frozen_case
        saved = self.post(f)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        w = f["w"]
        parse = w["own"]["manifest"]["members"][0]["parse"]["parse_run_id"]
        owner = w["database"]["owner"]
        # Corruption injection only in the dedicated test DB, never a business repair.
        assert owner.info.dbname == "fusion_package_requirements_api"
        with owner.transaction():
            owner.execute("SET LOCAL session_replication_role=replica")
            assert (
                owner.execute(
                    "UPDATE design.pages SET width=width+1 WHERE parse_id=%s", (parse,)
                ).rowcount
                > 0
            )
        path = f["path"] + "/" + value["manifest"]["id"]
        response = w["client"].post(
            path + "/execution-check", json={"frozen_digest": value["digest"]}, headers=f["headers"]
        )
        assert response.status_code == 200, response.text
        assert response.json()["parse_evidence_status"] == "mismatch"
        assert "PACKAGE_REVIEW_EVIDENCE_CHANGED" in response.json()["blockers"]
        assert w["client"].get(path).json() == value

    def test_execution_check_requires_exact_record_scope_auth_and_strict_body(self, frozen_case):
        from fastapi.testclient import TestClient

        f = frozen_case
        saved = self.post(f)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        w = f["w"]
        path = f["path"] + "/" + value["manifest"]["id"] + "/execution-check"
        with TestClient(w["app"]) as anonymous:
            assert (
                anonymous.post(
                    path, json={"frozen_digest": value["digest"]}, headers=f["headers"]
                ).status_code
                == 401
            )
        assert (
            w["client"]
            .post(path, json={"frozen_digest": "0" * 64}, headers=f["headers"])
            .status_code
            == 409
        )
        assert (
            w["client"]
            .post(
                path,
                json={"frozen_digest": value["digest"], "review_ready": True},
                headers=f["headers"],
            )
            .status_code
            == 422
        )
        assert (
            w["client"]
            .post(
                path.replace(f["scope"][0], uid(), 1),
                json={"frozen_digest": value["digest"]},
                headers=f["headers"],
            )
            .status_code
            == 404
        )

    def test_consumer_owns_full_frozen_root_and_never_borrows_current_context(
        self, frozen_case, monkeypatch
    ):
        import psycopg
        from psycopg.rows import dict_row

        from packages.domain.bid_package_review_input_repository import load_input

        f = frozen_case
        response = self.post(f)
        assert response.status_code == 201, response.text
        value = response.json()
        before, calls = counts(f["w"]), len(f["calls"])
        monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-changed-after-freeze")
        with psycopg.connect(f["w"]["database"]["api_dsn"], row_factory=dict_row) as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            packet = load_input(c, f["scope"], value["manifest"]["id"])
        assert packet.view() == value
        root = packet.evidence()
        original = packet.evidence()
        assert (
            len(root["documents"]) == 2
            and root["selection"]["target"]["manifest"]["revision_id"] == f["scope"][2]
        )
        root["documents"][0]["blocks"][0]["text_content"] = "caller mutation"
        packet.view()["manifest"]["blockers"].clear()
        assert packet.evidence() == original and packet.view() == value
        assert original["documents"][0]["blocks"][0]["text_content"] not in repr(packet)
        assert counts(f["w"]) == before and len(f["calls"]) == calls

    def test_consumer_rejects_inconsistent_resealed_structure_without_database_or_io(
        self, frozen_case
    ):
        import json
        from copy import deepcopy

        from packages.domain.package_review_frozen_input import consume
        from packages.domain.runtime import sha

        f = frozen_case
        response = self.post(f)
        assert response.status_code == 201, response.text
        input_id = response.json()["manifest"]["id"]
        row = (
            f["w"]["database"]["owner"]
            .execute(
                "SELECT manifest,digest,evidence_text,evidence_digest FROM design.bid_package_review_inputs WHERE id=%s",
                (input_id,),
            )
            .fetchone()
        )
        assert consume(row, f["scope"], input_id).view() == response.json()
        for part in (
            "version",
            "document_role",
            "missing_document",
            "parse",
            "text",
            "page",
            "duplicate_block",
            "object_key",
            "context",
            "summary",
            "selection",
            "scope",
            "raw_checksum",
            "duplicate_json_key",
        ):
            altered = deepcopy(row)
            root = json.loads(altered["evidence_text"])
            doc = root["documents"][0]
            if part == "version":
                root["version"] = "package-review-evidence/other"
            if part == "document_role":
                doc["package_role"] = "authority"
            if part == "missing_document":
                root["documents"].pop()
            if part == "parse":
                doc["parse_id"] = uid()
            if part == "text":
                doc["blocks"][0]["text_content"] = "forged synthetic text"
            if part == "page":
                doc["pages"].clear()
            if part == "duplicate_block":
                doc["blocks"].append(deepcopy(doc["blocks"][0]))
            if part == "object_key":
                doc["object_key"] = "forbidden synthetic locator"
            if part == "context":
                root["context"]["method"]["purpose"] = "formal_scoring"
            if part == "summary":
                altered["manifest"]["execution_context"]["fact_count"] += 1
            if part == "selection":
                root["selection"]["target"]["digest"] = "0" * 64
            if part == "scope":
                altered["manifest"]["bid_id"] = uid()
            text = json.dumps(root, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if part == "duplicate_json_key":
                text = '{"version":"duplicate",' + text[1:]
            altered["evidence_text"] = text
            altered["evidence_digest"] = altered["manifest"]["evidence_digest"] = sha(
                text.encode("utf-8")
            )
            altered["digest"] = digest(altered["manifest"])
            if part == "raw_checksum":
                altered["evidence_text"] += " "
            with pytest.raises(ValueError, match="PACKAGE_REVIEW_FROZEN_INPUT_CORRUPT"):
                consume(altered, f["scope"], input_id)

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
