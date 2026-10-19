"""Real PG/ASGI, explicit in-memory object streams; no real OSS claim."""
# ruff: noqa: F401,F811

import os

import pytest
from test_bid_package_review_preview_api import (
    api,
    check,
    counts,
    database,
    headers,
    prepare,
    requirements,
    uid,
    url,
    world,
)

from packages.contracts.bid_package_requirements_api import valid

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"), reason="requires grouped isolated PG"
)


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestOriginalVerification:
    @pytest.fixture
    def original_case(self, requirements, monkeypatch):
        from io import BytesIO

        from packages.domain import storage

        w = requirements
        _, inv, body = prepare(w)
        preview = check(w, inv, body).json()
        request = body | {"input_digest": preview["digest"]}
        calls = []
        state = {"bytes": b"synthetic-original-v1", "during_read": None}
        owner = w["database"]["owner"]
        keys = {
            row["object_key"]
            for row in owner.execute(
                "SELECT b.object_key FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id WHERE v.bid_id=%s",
                (w["scope"].bid_id,),
            ).fetchall()
        }

        class Client:
            def get_object(self, *, Bucket, Key):
                # Real PG verifies there is no service transaction during provider IO.
                assert (
                    owner.execute(
                        "SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database() AND usename='fusion_package_requirements_service'"
                    ).fetchone()["n"]
                    == 0
                )
                assert Key in keys
                calls.append(Key)
                if state["during_read"]:
                    action, state["during_read"] = state["during_read"], None
                    action()
                return {"Body": BytesIO(state["bytes"])}

        monkeypatch.setattr(storage, "client", Client)
        monkeypatch.setattr(storage, "bucket", lambda: "explicit-in-memory-test")
        path = url(w, inv).replace("review-input-preview", "review-original-verification")
        return w, preview, request, calls, state, path

    def post(self, case, body=None):
        w, _, request, _, _, path = case
        return w["client"].post(
            path,
            json=body if body is not None else request,
            headers={k: v for k, v in headers(w).items() if k.lower() != "idempotency-key"},
        )

    def test_success_is_unpersisted_observation_with_no_locator_or_new_job(self, original_case):
        import json

        w, preview, _, calls, _, _ = original_case
        before = counts(w)
        owner = w["database"]["owner"]
        jobs = owner.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"]
        response = self.post(original_case)
        assert response.status_code == 200, response.text
        value = response.json()
        assert valid("PackageReviewOriginalVerification", value)
        assert value["input_digest"] == preview["digest"]
        assert value["kind"] == "observation"
        assert value["originals_verified"] is True
        assert value["review_ready"] is value["launch_available"] is False
        assert len(value["originals"]) == len(calls) == 2
        assert {x["role"] for x in value["originals"]} == {"target", "authority"}
        assert "object_key" not in json.dumps(value)
        assert counts(w) == before
        assert owner.execute("SELECT count(*) AS n FROM design.operations").fetchone()["n"] == jobs

    @pytest.mark.parametrize(
        "changed", [b"synthetic-original-v2", b"short", b"synthetic-original-v1-extra"]
    )
    def test_corrupt_bytes_cannot_receive_verified_observation(self, original_case, changed):
        w, _, _, _, state, _ = original_case
        before = counts(w)
        state["bytes"] = changed
        response = self.post(original_case)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "ORIGINAL_BYTES_CORRUPTED"
        assert counts(w) == before

    def test_wrong_preview_digest_never_reads_provider(self, original_case):
        _, _, body, calls, _, _ = original_case
        response = self.post(original_case, body | {"input_digest": "0" * 64})
        assert response.status_code == 422
        assert calls == []

    @pytest.mark.parametrize("change", ["source", "project", "package"])
    def test_context_changes_during_io_cannot_receive_stale_success(self, original_case, change):
        w, _, _, _, state, _ = original_case

        def change_context():
            owner = w["database"]["owner"]
            if change == "source":
                owner.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (w["sources"][0],),
                )
            elif change == "project":
                owner.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (w["scope"].bid_id,),
                )
            else:
                from packages.domain.bid_package_repository import load_revision, save_revision

                original = load_revision(
                    owner, w["scope"].bid_id, w["own"]["manifest"]["revision_id"]
                )
                save_revision(
                    owner,
                    original.next_revision(uid(), original.members),
                    expected_digest=original.manifest_digest,
                )

        state["during_read"] = change_context
        response = self.post(original_case)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "PACKAGE_REVIEW_INPUT_CHANGED"

    def test_configuration_missing_does_not_fabricate_success(self, original_case, monkeypatch):
        from packages.domain import storage

        w, _, _, _, _, _ = original_case

        def unavailable():
            from packages.domain.runtime import DomainError

            raise DomainError("OBJECT_STORE_NOT_CONFIGURED", "尚未配置对象存储", 503)

        monkeypatch.setattr(storage, "client", unavailable)
        response = self.post(original_case)
        assert response.status_code == 503
        assert response.json()["code"] == "OBJECT_STORE_NOT_CONFIGURED"

    @pytest.mark.parametrize("change", ["fact_head", "decision", "model"])
    def test_execution_context_changes_during_io_are_rejected(
        self, original_case, change, monkeypatch
    ):
        w, _, _, _, state, _ = original_case
        owner = w["database"]["owner"]
        fact = self.seed_fact(w) if change == "decision" else None

        def mutate():
            if change == "fact_head":
                self.seed_fact(w)
            elif change == "model":
                monkeypatch.setenv("DEEPSEEK_MODEL", "explicit-synthetic-changed-model")
            else:
                from packages.domain.human_decisions import append_decision

                with owner.transaction():
                    owner.execute("SET LOCAL search_path=design,public")
                    append_decision(
                        owner,
                        w["scope"].bid_id,
                        w["actor"],
                        "fact",
                        fact,
                        {
                            "decision": "confirmed",
                            "reason": "synthetic confirmation, not qualification",
                            "evidence_ids": [],
                        },
                    )

        state["during_read"] = mutate
        response = self.post(original_case)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "PACKAGE_REVIEW_INPUT_CHANGED"

    def seed_fact(self, w, evidence_ids=()):
        from psycopg.types.json import Jsonb

        from packages.domain.review_identity import digest

        owner = w["database"]["owner"]
        fact_set, fact = uid(), uid()
        with owner.transaction():
            owner.execute(
                "INSERT INTO design.fact_sets(id,bid_id,digest) VALUES(%s,%s,%s)",
                (fact_set, w["scope"].bid_id, digest(fact_set)),
            )
            owner.execute(
                "INSERT INTO design.fact_items(id,bid_id,fact_set_id,subject,scope,name,value,evidence_ids) VALUES(%s,%s,%s,'synthetic subject','synthetic scope','synthetic fact',%s,%s::uuid[])",
                (fact, w["scope"].bid_id, fact_set, Jsonb({"amount": 1.25}), list(evidence_ids)),
            )
            owner.execute(
                "INSERT INTO design.fact_heads(bid_id,fact_set_id,revision) VALUES(%s,%s,1) ON CONFLICT(bid_id) DO UPDATE SET fact_set_id=EXCLUDED.fact_set_id,revision=fact_heads.revision+1",
                (w["scope"].bid_id, fact_set),
            )
        return fact

    def test_fact_json_values_and_unconfirmed_items_are_captured_without_qualification(
        self, original_case
    ):
        from packages.domain.bid_package_original_verification import read_input

        w, preview, body, _, _, _ = original_case
        self.seed_fact(w)
        response = self.post(original_case)
        assert response.status_code == 200, response.text
        context = response.json()["execution_context"]
        assert context["fact_count"] == 1 and context["confirmed_fact_count"] == 0
        assert context["facts_binding"] == "unproven"
        assert context["executor_available"] is context["formal_scoring_eligible"] is False
        assert context["input_digest"] == preview["digest"]
        selected = read_input(
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            preview["manifest"]["inventory"]["manifest"]["id"],
            body,
        )
        value = selected.execution_context["manifest"]["facts"]["items"][0]
        assert value["fact"]["value_jsonb_text"] == '{"amount": 1.25}'
        assert value["decision"] is None and value["scope_binding"] == "unproven"

    @pytest.mark.parametrize("in_package", [True, False])
    def test_fact_scope_records_exact_selected_package_parse_membership(
        self, original_case, in_package
    ):
        from test_bid_package_repository import add_document

        from packages.domain.bid_package_original_verification import read_input

        w, preview, body, _, _, _ = original_case
        owner = w["database"]["owner"]
        if in_package:
            parse = w["member"].parse.parse_run_id
        else:
            with owner.transaction():
                owner.execute("SET LOCAL search_path=design,public")
                extra = add_document(
                    owner, w["scope"], w["actor"], raw=b"synthetic outside selected package"
                )
            parse = extra.parse.parse_run_id
        evidence = owner.execute(
            "SELECT id::text FROM design.evidence_blocks WHERE parse_id=%s ORDER BY physical_page LIMIT 1",
            (parse,),
        ).fetchone()["id"]
        self.seed_fact(w, [evidence])
        response = self.post(original_case)
        assert response.status_code == 200, response.text
        captured = read_input(
            w["scope"].bid_id,
            w["own"]["manifest"]["package_id"],
            w["own"]["manifest"]["revision_id"],
            preview["manifest"]["inventory"]["manifest"]["id"],
            body,
        )
        item = captured.execution_context["manifest"]["facts"]["items"][0]
        assert item["scope_binding"] == ("selected_frozen_parse" if in_package else "unproven")
        assert response.json()["execution_context"]["facts_binding"] == "unproven"

    def test_session_csrf_and_shape_are_required_before_io(self, original_case):
        w, _, body, calls, _, path = original_case
        assert w["client"].post(path, json=body).status_code == 403
        assert self.post(original_case, body | {"originals_verified": True}).status_code == 422
        assert not calls
