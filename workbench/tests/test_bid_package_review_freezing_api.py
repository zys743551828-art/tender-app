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

    @pytest.fixture
    def execution_case(self, frozen_case):
        from packages.domain.bid_package_review_eligibility import inspect

        f = frozen_case
        old = self.post(f).json()
        OriginalVerificationCases.seed_fact(self, f["w"])
        context = inspect(f["scope"], old["manifest"]["id"], old["digest"])
        path = f["path"] + "/" + old["manifest"]["id"] + "/execution-inputs"
        body = {
            "frozen_digest": old["digest"],
            "context_digest": context["current_context"]["semantic_digest"],
            "rerun": None,
        }
        return f, old, path, body, headers(f["w"])

    def test_prepared_input_persists_full_current_context_but_no_job_or_outbox(
        self, execution_case
    ):
        import json

        f, old, path, body, h = execution_case
        c = f["w"]["database"]["owner"]
        before = c.execute(
            "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        ).fetchone()
        response = f["w"]["client"].post(path, json=body, headers=h)
        assert response.status_code == 201, response.text
        value = response.json()
        assert valid("PackageExecutionInputView", value)
        assert (
            value["manifest"]["kind"] == "prepared_input"
            and value["manifest"]["publication_authorized"] is False
        )
        row = c.execute(
            "SELECT snapshot_text FROM design.bid_package_execution_inputs WHERE id=%s",
            (value["manifest"]["id"],),
        ).fetchone()
        snapshot = json.loads(row["snapshot_text"])
        assert len(snapshot["context"]["manifest"]["facts"]["items"]) == 1
        assert snapshot["context"]["manifest"]["facts"]["qualification"] == "not_validated"
        assert "object_key" not in response.text and "text_content" not in response.text
        assert f["w"]["client"].get(path + "/" + value["manifest"]["id"]).json() == value
        assert (
            c.execute(
                "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
            ).fetchone()
            == before
        )
        assert f["w"]["client"].get(f["path"] + "/" + old["manifest"]["id"]).json() == old

    @pytest.fixture
    def prepared_case(self, execution_case):
        f, frozen, path, body, h = execution_case
        saved = f["w"]["client"].post(path, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        return f, frozen, path, saved.json()

    def test_dependency_assessment_reads_exact_packets_without_objects_commands_or_jobs(
        self, prepared_case, monkeypatch
    ):
        from packages.domain import storage
        from packages.domain.bid_package_execution_input_repository import load_packet
        from packages.domain.bid_package_input_dependencies import observe
        from packages.domain.package_fact_usage import select
        from packages.domain.runtime import connection

        f, frozen, _, value = prepared_case
        c = f["w"]["database"]["owner"]
        statement = "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        before = c.execute(statement).fetchone()
        calls = len(f["calls"])
        selection = {"purpose": "prebid_compliance", "fact_ids": []}
        with connection() as reader:
            reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            packet = load_packet(
                reader, f["scope"], frozen["manifest"]["id"], value["manifest"]["id"]
            )
            usage = select(packet, selection)

        def no_objects():
            raise AssertionError("dependency assessment cannot read original objects")

        monkeypatch.setattr(storage, "client", no_objects)
        result = observe(
            f["scope"],
            frozen["manifest"]["id"],
            value["manifest"]["id"],
            value["digest"],
            selection,
            {"purpose": "prebid_compliance", "usage_digest": usage.digest, "dependencies": []},
        ).view()
        m = result["manifest"]
        assert m["requirement_count"] > 0 and m["required_facts_assessment"] == "unknown"
        assert m["dependency_review_status"] == "incomplete" and m["selected_fact_count"] == 0
        assert (
            m["inventory_complete"]
            is m["review_ready"]
            is m["launch_available"]
            is m["publication_authorized"]
            is False
        )
        assert "value_jsonb_text" not in str(result) and "text_content" not in str(result)
        assert digest(m) == result["digest"] and len(f["calls"]) == calls
        assert c.execute(statement).fetchone() == before

    @pytest.mark.parametrize("invalid", ["prepared_digest", "usage_digest", "foreign_requirement"])
    def test_dependency_assessment_rejects_wrong_input_and_foreign_annotation(
        self, prepared_case, invalid
    ):
        from packages.domain.bid_package_execution_input_repository import load_packet
        from packages.domain.bid_package_input_dependencies import observe
        from packages.domain.package_fact_usage import select
        from packages.domain.runtime import DomainError, connection

        f, frozen, _, value = prepared_case
        selection = {"purpose": "prebid_compliance", "fact_ids": []}
        with connection() as reader:
            reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            packet = load_packet(
                reader, f["scope"], frozen["manifest"]["id"], value["manifest"]["id"]
            )
            usage = select(packet, selection)
        body = {"purpose": "prebid_compliance", "usage_digest": usage.digest, "dependencies": []}
        if invalid == "usage_digest":
            body["usage_digest"] = "a" * 64
        if invalid == "foreign_requirement":
            body["dependencies"] = [
                {
                    "requirement_id": str(uid()),
                    "requirement_digest": "a" * 64,
                    "state": "not_needed",
                    "fact_ids": [],
                    "evidence_ids": [str(uid())],
                    "reason": "合成外部要求",
                }
            ]
        with pytest.raises(DomainError) as error:
            observe(
                f["scope"],
                frozen["manifest"]["id"],
                value["manifest"]["id"],
                "a" * 64 if invalid == "prepared_digest" else value["digest"],
                selection,
                body,
            )
        assert error.value.status == (422 if invalid == "foreign_requirement" else 409)

    def test_fact_check_explains_unproven_input_without_objects_commands_or_jobs(
        self, prepared_case, monkeypatch
    ):
        from packages.domain import storage

        f, frozen, path, value = prepared_case
        c = f["w"]["database"]["owner"]
        statement = "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        before = c.execute(statement).fetchone()
        calls = len(f["calls"])

        def unavailable():
            raise AssertionError("fact observation cannot read original objects")

        monkeypatch.setattr(storage, "client", unavailable)
        response = f["w"]["client"].post(
            path + "/" + value["manifest"]["id"] + "/fact-check",
            json={"execution_input_digest": value["digest"]},
            headers=f["headers"],
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert valid("PackageExecutionFactCheck", result)
        assert result["matches_prepared_context"] is True
        assert result["fact_count"] == 1 and result["provenance_verified_count"] == 0
        assert {
            "FACT_DECISION_UNCONFIRMED",
            "FACT_DECISION_BASIS_UNPROVEN",
            "FACT_SCOPE_MAPPING_REQUIRED",
        } <= set(result["fact_checks"][0]["blockers"])
        assert (
            result["facts_qualified"]
            is result["review_ready"]
            is result["launch_available"]
            is result["publication_authorized"]
            is False
        )
        assert result["original_verification"] == "not_performed"
        assert (
            "object_key" not in response.text
            and "synthetic subject" not in response.text
            and "amount" not in response.text
        )
        assert c.execute(statement).fetchone() == before and len(f["calls"]) == calls

    def test_fact_check_is_bound_to_prepared_digest_scope_and_csrf(self, prepared_case):
        f, frozen, path, value = prepared_case
        client = f["w"]["client"]
        url = path + "/" + value["manifest"]["id"] + "/fact-check"
        body = {"execution_input_digest": value["digest"]}
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(
                url, json=body | {"launch_available": True}, headers=f["headers"]
            ).status_code
            == 422
        )
        wrong = client.post(url, json={"execution_input_digest": "0" * 64}, headers=f["headers"])
        assert (
            wrong.status_code == 409 and wrong.json()["code"] == "PACKAGE_EXECUTION_INPUT_CHANGED"
        )
        assert (
            client.post(
                url.replace(value["manifest"]["id"], uid()), json=body, headers=f["headers"]
            ).status_code
            == 404
        )
        assert (
            client.post(
                url.replace(f["scope"][1], uid()), json=body, headers=f["headers"]
            ).status_code
            == 404
        )

    def test_fact_check_observes_new_facts_without_rewriting_prepared_history(self, prepared_case):
        f, frozen, path, value = prepared_case
        OriginalVerificationCases.seed_fact(self, f["w"])
        response = f["w"]["client"].post(
            path + "/" + value["manifest"]["id"] + "/fact-check",
            json={"execution_input_digest": value["digest"]},
            headers=f["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["matches_prepared_context"] is False
        assert (
            response.json()["observed_facts_digest"]
            != value["manifest"]["execution_context"]["facts_digest"]
        )
        assert f["w"]["client"].get(path + "/" + value["manifest"]["id"]).json() == value

    @pytest.fixture
    def provenance_case(self, frozen_case, request):
        from packages.domain.bid_package_review_eligibility import inspect
        from packages.domain.fact_sets import identity
        from packages.domain.human_decisions import append_decision
        from packages.domain.review_data import source_closure
        from packages.domain.runtime import clean, connection, sha
        from packages.rag.indexing import ensure_parse_sources

        f = frozen_case
        w = f["w"]
        frozen = self.post(f).json()
        fact = OriginalVerificationCases.seed_fact(self, w, [w["evidence"]])
        with connection() as c:
            row = c.execute("SELECT * FROM design.fact_items WHERE id=%s", (fact,)).fetchone()
            evidence = c.execute(
                "SELECT e.parse_id,p.document_version_id FROM design.evidence_blocks e JOIN design.parse_runs p ON p.bid_id=e.bid_id AND p.id=e.parse_id WHERE e.bid_id=%s AND e.id=%s",
                (w["scope"].bid_id, w["evidence"]),
            ).fetchone()
            _, source = ensure_parse_sources(
                c, w["scope"].bid_id, evidence["parse_id"], publish_readable=True
            )
            if getattr(request, "param", None):
                c.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+%s::integer*interval '1 second' WHERE source_id=%s",
                    (request.param, source),
                )
            revision = c.execute(
                "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
            ).fetchone()["revision"]
            refs = clean(
                [
                    {
                        "source_id": source,
                        "source_revision": revision,
                        "evidence_id": w["evidence"],
                        "document_version_id": evidence["document_version_id"],
                    }
                ]
            )
            basis = {
                "fact_identity": identity(row),
                "evidence": {
                    "references": refs,
                    "source_closure_digest": sha(source_closure(c, [{"id": str(source)}])),
                },
            }
            append_decision(
                c,
                w["scope"].bid_id,
                w["actor"],
                "fact",
                fact,
                {
                    "decision": "confirmed",
                    "reason": "synthetic evidence confirmation",
                    "evidence_ids": [w["evidence"]],
                },
                basis=basis,
            )
        current = inspect(f["scope"], frozen["manifest"]["id"], frozen["digest"])
        path = f["path"] + "/" + frozen["manifest"]["id"] + "/execution-inputs"
        saved = w["client"].post(
            path,
            json={
                "frozen_digest": frozen["digest"],
                "context_digest": current["current_context"]["semantic_digest"],
                "rerun": None,
            },
            headers=headers(w),
        )
        assert saved.status_code == 201, saved.text
        value = saved.json()
        return f, frozen, path, value, str(fact), str(source)

    @pytest.mark.parametrize("withdraw", [False, True])
    def test_fact_check_valid_decision_basis_proves_provenance_but_not_package_scope(
        self, provenance_case, withdraw
    ):
        from packages.rag.indexing import parse_source_id

        f, frozen, path, value, fact, source = provenance_case
        w = f["w"]
        if withdraw:
            owner = w["database"]["owner"]
            parse = owner.execute(
                "SELECT parse_id FROM design.evidence_blocks WHERE id=%s", (w["evidence"],)
            ).fetchone()["parse_id"]
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (parse_source_id(parse),),
            )
        response = w["client"].post(
            path + "/" + value["manifest"]["id"] + "/fact-check",
            json={"execution_input_digest": value["digest"]},
            headers=headers(w),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert valid("PackageExecutionFactCheck", result)
        assert result["provenance_verified_count"] == (0 if withdraw else 1)
        item = result["fact_checks"][0]
        assert (
            item["facts_qualified"] is False and "FACT_SCOPE_MAPPING_REQUIRED" in item["blockers"]
        )
        if withdraw:
            assert "FACT_SOURCE_NOT_EFFECTIVE" in item["blockers"]
        else:
            assert item["blockers"] == ["FACT_SCOPE_MAPPING_REQUIRED"]

    def scope_body(self, provenance_case):
        f, frozen, path, value, fact, source = provenance_case
        return {
            "execution_input_digest": value["digest"],
            "fact_id": fact,
            "action": "bind",
            "subject": {"kind": "lot", "id": str(f["w"]["scope"].lot_id)},
            "reason": "明确事实属于本标段",
            "previous_digest": None,
        }

    def fact_change_body(self, case):
        f, frozen, path, prepared, fact, source = case
        head = (
            f["w"]["database"]["owner"]
            .execute(
                "SELECT fact_set_id::text AS id,revision FROM design.fact_heads WHERE bid_id=%s",
                (f["scope"][0],),
            )
            .fetchone()
        )
        return dict(
            frozen_digest=frozen["digest"],
            expected_head=head or dict(id=None, revision=0),
            replaces_fact_id=None,
            confirmation="confirmed",
            fact=dict(
                subject="本工程",
                scope="本标段",
                name="新增明确事实",
                value="180",
                unit="天",
                evidence_ids=[str(f["w"]["evidence"])],
                reason="按本次冻结原页人工确认",
            ),
        )

    def fact_change_counts(self, case):
        f = case[0]
        owner = f["w"]["database"]["owner"]
        rows = tuple(
            owner.execute("SELECT count(*) AS n FROM design." + name).fetchone()["n"]
            for name in (
                "fact_sets",
                "fact_items",
                "decisions",
                "decision_heads",
                "fact_set_changes",
                "audit_entries",
                "commands",
                "stream_events",
                "operations",
                "outbox",
            )
        )
        head = owner.execute(
            "SELECT fact_set_id::text,revision FROM design.fact_heads WHERE bid_id=%s",
            (f["scope"][0],),
        ).fetchone()
        return rows, head

    def test_old_fact_change_receipt_remains_exact_history_without_invented_request_binding(
        self, provenance_case, monkeypatch
    ):
        from copy import deepcopy

        from packages.domain import bid_package_fact_changes as changes

        f, frozen, path, prepared, fact, source = provenance_case
        original = changes.policy.seal

        def legacy_seal(manifest):
            value = deepcopy(manifest)
            value["version"] = "package-fact-change/1"
            value.pop("request_digest")
            return original(value)

        monkeypatch.setattr(changes.policy, "seal", legacy_seal)
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])
        body = self.fact_change_body(provenance_case)
        key = str(uid())
        saved, _ = changes.confirm(*args, key, body)
        monkeypatch.setattr(changes.policy, "seal", original)
        record = saved["body"]
        assert (
            record["manifest"]["version"] == "package-fact-change/1"
            and "request_digest" not in record["manifest"]
        )
        assert (
            changes.load(f["scope"], frozen["manifest"]["id"], record["manifest"]["command_id"])
            == record
        )
        assert changes.confirm(*args, key, body) == (saved, True)

    def test_fact_change_http_requires_explicit_intent_csrf_and_key_and_exposes_exact_history(
        self, provenance_case
    ):
        f, frozen, path, prepared, fact, source = provenance_case
        client = f["w"]["client"]
        base = path.removesuffix("/execution-inputs")
        url = base + "/fact-confirmations"
        body = self.fact_change_body(provenance_case)
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(
                url,
                json=body,
                headers={
                    k: v for k, v in headers(f["w"]).items() if k.lower() != "idempotency-key"
                },
            ).status_code
            == 428
        )
        assert (
            client.post(
                url, json=body | {"launch_available": True}, headers=headers(f["w"])
            ).status_code
            == 422
        )
        assert (
            client.post(
                url, json=body | {"confirmation": "automatic"}, headers=headers(f["w"])
            ).status_code
            == 422
        )
        h = headers(f["w"])
        saved = client.post(url, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        assert valid("PackageFactChangeView", record)
        replay = client.post(url, json=body, headers=h)
        assert (
            replay.status_code == 201
            and replay.json() == record
            and replay.headers.get("Idempotent-Replayed") == "true"
        )
        history = base + "/fact-changes/" + record["manifest"]["command_id"]
        assert client.get(history).json() == record
        assert client.get(history.replace(f["scope"][1], str(uid()))).status_code == 404
        client.cookies.clear()
        assert client.get(history).status_code == 401
        assert (
            client.get(
                base + "/fact-context", params={"frozen_digest": frozen["digest"]}
            ).status_code
            == 401
        )
        assert client.post(url, json=body, headers=h).status_code == 401

    def test_current_fact_http_directory_is_bounded_and_cursor_tracks_exact_head(
        self, provenance_case
    ):
        from packages.domain.bid_package_fact_changes import confirm

        f, frozen, path, prepared, fact, source = provenance_case
        client = f["w"]["client"]
        base = path.removesuffix("/execution-inputs")
        url = base + "/fact-context"
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])
        body = self.fact_change_body(provenance_case)
        confirm(*args, str(uid()), body)
        response = client.get(url, params={"frozen_digest": frozen["digest"], "limit": 1})
        assert response.status_code == 200, response.text
        page = response.json()
        assert valid("PackageCurrentFactPage", page)
        assert page["fact_count"] == 2 and page["has_more"] and page["next_cursor"]
        assert {row["role"] for row in page["source_packages"]} == {"target", "authority"}
        target = next(row for row in page["source_packages"] if row["role"] == "target")
        assert (
            target["package_id"] == f["scope"][1]
            and target["revision_id"] == f["scope"][2]
            and target["digest"] == f["body"]["package_digest"]
        )
        assert (
            page["facts_qualified"] is False
            and page["required_facts_assessment"] == "not_performed"
        )
        assert (
            "decision_basis_jsonb_text" not in response.text and "object_key" not in response.text
        )
        next_page = client.get(
            url,
            params={"frozen_digest": frozen["digest"], "limit": 1, "cursor": page["next_cursor"]},
        ).json()
        assert valid("PackageCurrentFactPage", next_page) and not next_page["has_more"]
        assert next_page["items"][0]["fact_id"] != page["items"][0]["fact_id"]
        owner = f["w"]["database"]["owner"]
        old_clone = owner.execute(
            "SELECT id FROM design.fact_items WHERE fact_set_id=%s AND name='synthetic fact'",
            (page["head"]["id"],),
        ).fetchone()["id"]
        detail = client.get(
            base + "/facts/" + str(old_clone), params={"frozen_digest": frozen["digest"]}
        )
        assert detail.status_code == 200, detail.text
        assert valid("PackageCurrentFactDetail", detail.json())
        assert (
            detail.json()["editability"] == "unsupported_or_oversized"
            and detail.json()["editable_fact"] is None
        )
        assert detail.json()["evidence_references"][0]["frozen_parse_member"] is True
        confirm(*args, str(uid()), self.fact_change_body(provenance_case))
        stale = client.get(
            url, params={"frozen_digest": frozen["digest"], "cursor": page["next_cursor"]}
        )
        assert stale.status_code == 422 and stale.json()["code"] == "INVALID_CURSOR"
        assert (
            client.get(
                base + "/facts/" + str(old_clone), params={"frozen_digest": frozen["digest"]}
            ).status_code
            == 404
        )
        assert client.get(url, params={"frozen_digest": "0" * 64}).status_code == 409
        assert (
            client.get(
                url, params={"frozen_digest": frozen["digest"], "cursor": "forged.signature"}
            ).status_code
            == 422
        )
        assert (
            client.get(url, params={"frozen_digest": frozen["digest"], "limit": 101}).status_code
            == 422
        )

    @pytest.mark.parametrize("value", [True, None, "😀" * 300])
    def test_current_fact_detail_preserves_scalar_type_and_exact_evidence_reference(
        self, provenance_case, value
    ):
        f, frozen, path, prepared, fact, source = provenance_case
        body = self.fact_change_body(provenance_case)
        body["fact"]["value"] = value
        body["fact"]["name"] = "😀" * 300
        client = f["w"]["client"]
        base = path.removesuffix("/execution-inputs")
        saved = client.post(base + "/fact-confirmations", json=body, headers=headers(f["w"]))
        assert saved.status_code == 201, saved.text
        record = saved.json()
        response = client.get(
            base + "/facts/" + record["manifest"]["fact_id"],
            params={"frozen_digest": frozen["digest"]},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert valid("PackageCurrentFactDetail", result)
        assert result["editable_fact"]["value"] == value and result["editability"] == "editable"
        assert (
            result["summary"]["name"] == "😀" * 240
            and result["summary"]["preview_truncated"] is True
        )
        assert (
            result["summary"]["confirmation_recorded"] == "confirmed"
            and result["facts_qualified"] is False
        )
        assert result["evidence_references"][0]["id"] == str(f["w"]["evidence"])
        assert result["evidence_references"][0]["frozen_parse_member"] is True

    def test_fact_withdraw_http_recovers_original_confirmation_and_history_after_source_loss(
        self, provenance_case
    ):
        f, frozen, path, prepared, fact, source = provenance_case
        body = self.fact_change_body(provenance_case)
        client = f["w"]["client"]
        base = path.removesuffix("/execution-inputs")
        h = headers(f["w"])
        saved = client.post(base + "/fact-confirmations", json=body, headers=h)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        owner = f["w"]["database"]["owner"]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (source,),
        )
        change = dict(
            frozen_digest=frozen["digest"],
            expected_head=record["manifest"]["head"],
            fact_id=record["manifest"]["fact_id"],
            reason="明确撤回本次事实",
        )
        removed = client.post(base + "/fact-withdrawals", json=change, headers=headers(f["w"]))
        assert removed.status_code == 201, removed.text
        assert (
            valid("PackageFactChangeView", removed.json())
            and removed.json()["manifest"]["action"] == "withdrawn"
        )
        assert client.post(base + "/fact-confirmations", json=body, headers=h).json() == record
        assert (
            client.get(base + "/fact-changes/" + record["manifest"]["command_id"]).json() == record
        )
        assert (
            client.post(
                base + "/fact-withdrawals", json=change, headers=headers(f["w"])
            ).status_code
            == 409
        )
        assert client.get(path + "/" + prepared["manifest"]["id"]).json() == prepared

    def test_shared_fact_writer_keeps_existing_human_api_default_policy(self, frozen_case):
        f = frozen_case
        assert self.post(f).status_code == 201
        owner = f["w"]["database"]["owner"]
        bid = f["scope"][0]
        owner.execute(
            "UPDATE design.bid_profiles SET current_body_id=(SELECT p.document_version_id FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id WHERE e.id=%s) WHERE bid_id=%s",
            (str(f["w"]["evidence"]), bid),
        )
        client = f["w"]["client"]
        url = "/api/v1/bids/" + bid + "/facts"
        before = client.get(url)
        assert before.status_code == 200, before.text
        body = dict(
            replaces_fact_id=None,
            fact=dict(
                subject="本工程",
                scope="本标段",
                name="legacy default policy",
                value="180",
                unit="天",
                evidence_ids=[str(f["w"]["evidence"])],
                reason="保留旧接口默认策略",
            ),
        )
        response = client.post(
            url, json=body, headers=headers(f["w"]) | {"If-Match": before.headers["etag"]}
        )
        assert response.status_code == 200, response.text
        response = client.post(
            url,
            json=body | {"fact": body["fact"] | {"name": "legacy second confirmation"}},
            headers=headers(f["w"]) | {"If-Match": response.headers["etag"]},
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["facts"]) == 2
        assert all(item["confirmation"] == "confirmed" for item in response.json()["facts"])

    def test_package_fact_confirmation_preserves_existing_decision_without_legacy_heads(
        self, provenance_case
    ):
        from packages.domain.bid_package_fact_changes import confirm
        from packages.domain.bid_package_fact_provenance import read_proof
        from packages.domain.package_review_context import read_facts
        from packages.domain.runtime import connection

        f, frozen, path, prepared, old_fact, source = provenance_case
        owner = f["w"]["database"]["owner"]
        bid = f["scope"][0]
        original = owner.execute(
            "SELECT decision_id FROM design.decision_heads WHERE bid_id=%s AND object_kind='fact' AND object_id=%s",
            (bid, old_fact),
        ).fetchone()["decision_id"]
        owner.execute(
            "UPDATE design.bid_profiles SET current_body_id=NULL,current_material_id=NULL WHERE bid_id=%s",
            (bid,),
        )
        before = owner.execute(
            "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        ).fetchone()
        body = self.fact_change_body(provenance_case)
        key = str(uid())
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])
        saved, replay = confirm(*args, key, body)
        assert saved["status"] == 201 and replay is False
        m = saved["body"]["manifest"]
        assert m["action"] == "confirmed" and m["facts_qualified"] is False
        assert m["head"]["revision"] == body["expected_head"]["revision"] + 1
        assert confirm(*args, key, body) == (saved, True)
        with connection() as c:
            parse = c.execute(
                "SELECT parse_id::text, p.document_version_id::text FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id AND p.bid_id=e.bid_id WHERE e.id=%s",
                (str(f["w"]["evidence"]),),
            ).fetchone()
            current = read_facts(c, bid, {(parse["document_version_id"], parse["parse_id"])})
            old_clone = [item for item in current["items"] if item["fact"]["id"] != m["fact_id"]][0]
            assert old_clone["decision"]["id"] == str(original)
            proof = read_proof(c, bid, old_clone, m["recorded_at"])
            assert (
                proof["decision_binding"] is True
                and proof["decision_lineage"][0]["from_fact_id"] == old_fact
            )
        assert (
            owner.execute(
                "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
            ).fetchone()
            == before
        )
        assert f["w"]["client"].get(path + "/" + prepared["manifest"]["id"]).json() == prepared

    def test_package_fact_replace_withdraw_and_replay_preserve_history_after_source_loss(
        self, provenance_case
    ):
        from packages.domain.bid_package_fact_changes import confirm, load, withdraw
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, old_fact, source = provenance_case
        body = self.fact_change_body(provenance_case) | {"replaces_fact_id": old_fact}
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])
        key = str(uid())
        saved, _ = confirm(*args, key, body)
        m = saved["body"]["manifest"]
        owner = f["w"]["database"]["owner"]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (source,),
        )
        withdrawal = dict(
            frozen_digest=frozen["digest"],
            expected_head=m["head"],
            fact_id=m["fact_id"],
            reason="来源停用后撤回事实",
        )
        removed, _ = withdraw(*args, str(uid()), withdrawal)
        assert removed["body"]["manifest"]["action"] == "withdrawn"
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM design.fact_items WHERE fact_set_id=%s",
                (removed["body"]["manifest"]["head"]["id"],),
            ).fetchone()["n"]
            == 0
        )
        owner.execute(
            "UPDATE design.bid_profiles SET archived_at=clock_timestamp() WHERE bid_id=%s",
            (f["scope"][0],),
        )
        assert confirm(*args, key, body) == (saved, True)
        assert load(f["scope"], frozen["manifest"]["id"], m["command_id"]) == saved["body"]
        with pytest.raises(DomainError):
            confirm(*args, str(uid()), body)
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM design.fact_items WHERE id=%s", (old_fact,)
            ).fetchone()["n"]
            == 1
        )

    @pytest.mark.parametrize("corrupt", ["resealed", "empty", "headers", "request"])
    def test_package_fact_resealed_ack_cannot_replace_immutable_audit_history(
        self, provenance_case, corrupt
    ):
        from copy import deepcopy

        from psycopg.types.json import Jsonb

        from packages.domain.bid_package_fact_changes import confirm, load
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, fact, source = provenance_case
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])
        body = self.fact_change_body(provenance_case)
        key = str(uid())
        saved, _ = confirm(*args, key, body)
        forged = deepcopy(saved)
        forged["body"]["manifest"]["reason"] = "forged but resealed"
        forged["body"]["digest"] = digest(forged["body"]["manifest"])
        if corrupt == "empty":
            forged = {}
        if corrupt == "headers":
            forged = deepcopy(saved) | {"headers": {"X-Forged": "blocked"}}
        if corrupt == "request":
            forged = deepcopy(saved)
            forged["body"]["manifest"]["request_digest"] = "0" * 64
            forged["body"]["digest"] = digest(forged["body"]["manifest"])
        owner = f["w"]["database"]["owner"]
        command_id = saved["body"]["manifest"]["command_id"]
        owner.execute(
            "UPDATE design.commands SET response=%s WHERE id=%s", (Jsonb(forged), command_id)
        )
        before = self.fact_change_counts(provenance_case)
        with pytest.raises(DomainError) as error:
            confirm(*args, key, body)
        assert error.value.code == "PACKAGE_FACT_CHANGE_CORRUPT"
        with pytest.raises(DomainError) as error:
            load(f["scope"], frozen["manifest"]["id"], command_id)
        assert error.value.code == "PACKAGE_FACT_CHANGE_CORRUPT"
        assert self.fact_change_counts(provenance_case) == before
        assert (
            owner.execute(
                "SELECT payload FROM design.audit_entries WHERE command_id=%s AND event_type='package.fact_confirmed'",
                (command_id,),
            ).fetchone()["payload"]
            == saved["body"]
        )

    @pytest.mark.parametrize("same_key", [False, True])
    def test_package_fact_concurrent_confirmations_have_one_head_and_recoverable_ack(
        self, provenance_case, same_key
    ):
        from concurrent.futures import ThreadPoolExecutor

        from packages.domain.bid_package_fact_changes import confirm
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, fact, source = provenance_case
        body = self.fact_change_body(provenance_case)
        key = str(uid())
        args = (str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"])

        def run(index):
            try:
                return confirm(*args, key if same_key or index == 0 else str(uid()), body)
            except DomainError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        if same_key:
            assert results[0][0] == results[1][0] and sum(row[1] for row in results) == 1
        else:
            assert (
                sum(isinstance(row, tuple) for row in results) == 1
                and "FACT_HEAD_CHANGED" in results
            )

    @pytest.mark.parametrize(
        "change", ["stale", "wrong_digest", "outside_evidence", "source_withdrawn", "wrong_scope"]
    )
    def test_package_fact_failed_confirmation_rolls_back_command_and_facts(
        self, provenance_case, change
    ):
        from packages.domain.bid_package_fact_changes import confirm
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, fact, source = provenance_case
        body = self.fact_change_body(provenance_case)
        scope = f["scope"]
        owner = f["w"]["database"]["owner"]
        if change == "stale":
            body["expected_head"]["revision"] += 1
        if change == "wrong_digest":
            body["frozen_digest"] = "0" * 64
        if change == "outside_evidence":
            body["fact"]["evidence_ids"] = [str(uid())]
        if change == "source_withdrawn":
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (source,),
            )
        if change == "wrong_scope":
            scope = (scope[0], str(uid()), *scope[2:])
        before = self.fact_change_counts(provenance_case)
        with pytest.raises((DomainError, ValueError)):
            confirm(str(f["w"]["actor"]), scope, frozen["manifest"]["id"], str(uid()), body)
        assert self.fact_change_counts(provenance_case) == before

    def test_package_fact_natural_expiry_after_append_rolls_back_every_write(
        self, provenance_case, monkeypatch
    ):
        import time

        from packages.domain import bid_package_fact_changes as changes
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, fact, source = provenance_case
        body = self.fact_change_body(provenance_case)
        owner = f["w"]["database"]["owner"]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,valid_until=clock_timestamp()+interval '5 seconds' WHERE source_id=%s",
            (source,),
        )
        original = changes.replace_set
        called = []

        def append_then_expire(c, *args, **kwargs):
            result = original(c, *args, **kwargs)
            called.append(True)
            remaining = c.execute(
                "SELECT extract(epoch from valid_until-clock_timestamp()) AS remaining FROM retrieval.source_heads WHERE source_id=%s",
                (source,),
            ).fetchone()["remaining"]
            time.sleep(max(0, float(remaining)) + 0.1)
            return result

        monkeypatch.setattr(changes, "replace_set", append_then_expire)
        before = self.fact_change_counts(provenance_case)
        with pytest.raises(DomainError) as error:
            changes.confirm(
                str(f["w"]["actor"]), f["scope"], frozen["manifest"]["id"], str(uid()), body
            )
        assert error.value.code == "SOURCE_NOT_EFFECTIVE" and called == [True]
        assert self.fact_change_counts(provenance_case) == before

    def test_package_fact_clone_preserves_postgres_json_precision_without_confirming_pending_value(
        self, provenance_case
    ):
        from packages.domain.bid_package_fact_changes import confirm

        f, frozen, path, prepared, fact, source = provenance_case
        owner = f["w"]["database"]["owner"]
        bid = f["scope"][0]
        pending_set, pending_fact = uid(), uid()
        owner.execute(
            "INSERT INTO design.fact_sets(id,bid_id,digest) VALUES(%s,%s,%s)",
            (pending_set, bid, "d" * 64),
        )
        owner.execute(
            "INSERT INTO design.fact_items(id,bid_id,fact_set_id,subject,scope,name,value,unit,evidence_ids) VALUES(%s,%s,%s,'pending','pending','precision','{\"n\":9007199254740993.123456789012345678901}'::jsonb,NULL,ARRAY[]::uuid[])",
            (pending_fact, bid, pending_set),
        )
        owner.execute(
            "UPDATE design.fact_heads SET fact_set_id=%s,revision=revision+1 WHERE bid_id=%s",
            (pending_set, bid),
        )
        exact = owner.execute(
            "SELECT value::text AS value FROM design.fact_items WHERE id=%s", (pending_fact,)
        ).fetchone()["value"]
        saved, _ = confirm(
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            str(uid()),
            self.fact_change_body(provenance_case),
        )
        clone = owner.execute(
            "SELECT f.id,f.value::text AS value,h.decision_id FROM design.fact_items f LEFT JOIN design.decision_heads h ON h.bid_id=f.bid_id AND h.object_kind='fact' AND h.object_id=f.id WHERE f.fact_set_id=%s AND f.name='precision'",
            (saved["body"]["manifest"]["head"]["id"],),
        ).fetchone()
        assert clone["value"] == exact and clone["decision_id"] is None

    @pytest.mark.parametrize(
        "change",
        [
            "newer_parse",
            "withdrawn",
            "wrong_scope",
            "wrong_digest",
            "extra_parent",
            "repeatable_read",
        ],
    )
    def test_frozen_fact_basis_has_independent_exact_source_port(self, provenance_case, change):
        from packages.domain.bid_package_fact_evidence import read_basis
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, prepared, fact, source = provenance_case
        owner = f["w"]["database"]["owner"]
        bid = f["scope"][0]
        evidence = str(f["w"]["evidence"])
        old = owner.execute(
            "SELECT parse_id FROM design.evidence_blocks WHERE id=%s", (evidence,)
        ).fetchone()["parse_id"]
        if change == "newer_parse":
            owner.execute(
                "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps,created_at) SELECT %s,bid_id,document_version_id,parser_digest,config_digest,page_count,'failed','[\"synthetic newer failed parse\"]'::jsonb,clock_timestamp() FROM design.parse_runs WHERE id=%s",
                (uid(), old),
            )
            owner.execute(
                "UPDATE design.bid_profiles SET current_body_id=NULL,current_material_id=NULL WHERE bid_id=%s",
                (bid,),
            )
        if change == "withdrawn":
            owner.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (source,),
            )
        if change == "extra_parent":
            parent = owner.execute(
                "SELECT n.id FROM retrieval.source_nodes n JOIN design.document_versions v ON v.id=n.document_version_id JOIN design.parse_runs p ON p.document_version_id<>v.id AND p.bid_id=v.bid_id WHERE p.id=%s AND n.policy_class='prebid_content' LIMIT 1",
                (old,),
            ).fetchone()["id"]
            owner.execute(
                "INSERT INTO retrieval.lineage_edges(child_id,parent_id) VALUES(%s,%s)",
                (source, parent),
            )
        before = counts(f["w"])
        scope = f["scope"] if change != "wrong_scope" else (bid, str(uid()), *f["scope"][2:])
        fd = frozen["digest"] if change != "wrong_digest" else "0" * 64
        with connection() as c:
            if change == "repeatable_read":
                c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if change != "newer_parse":
                with pytest.raises((DomainError, ValueError)):
                    read_basis(c, scope, frozen["manifest"]["id"], fd, [evidence])
            else:
                observed = read_basis(c, scope, frozen["manifest"]["id"], fd, [evidence])
                assert observed.view()["selection"]["selected"][0]["parse_run_id"] == str(old)
                assert observed.basis()["references"][0]["evidence_id"] == evidence
                assert observed.view()["facts_qualified"] is False
                assert not c.closed and not c.autocommit
        assert counts(f["w"]) == before

    def test_duplicate_root_decision_audit_cannot_authorize_new_scope_or_admission(
        self, provenance_case
    ):
        from packages.domain.bid_package_fact_admission import observe
        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.runtime import DomainError, audit, connection

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        saved, _ = save(*args, str(uid()), self.scope_body(provenance_case))
        with connection() as c:
            row = c.execute(
                "SELECT a.payload FROM design.audit_entries a JOIN design.decision_heads h ON h.bid_id=a.bid_id AND h.decision_id::text=a.payload->>'decision_id' WHERE h.object_kind='fact' AND h.object_id=%s AND a.event_type='human.decision_recorded'",
                (fact,),
            ).fetchone()
            audit(c, f["w"]["actor"], f["scope"][0], "human.decision_recorded", row["payload"])
        response = f["w"]["client"].post(
            path + "/" + prepared["manifest"]["id"] + "/fact-check",
            json={"execution_input_digest": prepared["digest"]},
            headers=headers(f["w"]),
        )
        assert response.status_code == 200, response.text
        assert "FACT_DECISION_BASIS_UNPROVEN" in response.json()["fact_checks"][0]["blockers"]
        with pytest.raises(DomainError):
            save(
                *args,
                str(uid()),
                self.scope_body(provenance_case) | {"previous_digest": saved["body"]["digest"]},
            )
        with pytest.raises(DomainError) as denied:
            observe(
                *args[1:], prepared["digest"], {"purpose": "prebid_compliance", "fact_ids": [fact]}
            )
        assert denied.value.code == "PACKAGE_SELECTED_FACTS_UNPROVEN"
        record_id = saved["body"]["manifest"]["id"]
        assert (
            f["w"]["client"]
            .get(path + "/" + prepared["manifest"]["id"] + "/fact-scope-declarations/" + record_id)
            .json()
            == saved["body"]
        )

    def test_scope_provenance_carryover_requires_same_bid_and_fact_set(self, provenance_case):
        from packages.domain.fact_sets import decision_basis
        from packages.domain.runtime import audit, connection

        f, frozen, path, prepared, old_fact, source = provenance_case
        bid = f["scope"][0]
        new_set, new_fact = str(uid()), str(uid())
        with connection() as c:
            old = c.execute(
                "SELECT decision_id FROM design.decision_heads WHERE bid_id=%s AND object_kind='fact' AND object_id=%s",
                (bid, old_fact),
            ).fetchone()["decision_id"]
            basis = decision_basis(c, old)
            c.execute(
                "INSERT INTO design.fact_sets(id,bid_id,digest) VALUES(%s,%s,%s)",
                (new_set, bid, digest({"synthetic": "carryover"})),
            )
            c.execute(
                "INSERT INTO design.fact_items(id,bid_id,fact_set_id,subject,scope,name,value,unit,evidence_ids) SELECT %s,bid_id,%s,subject,scope,name,value,unit,evidence_ids FROM design.fact_items WHERE bid_id=%s AND id=%s",
                (new_fact, new_set, bid, old_fact),
            )
            c.execute(
                "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'fact',%s,1,%s)",
                (bid, new_fact, old),
            )
            c.execute(
                "UPDATE design.fact_heads SET fact_set_id=%s,revision=revision+1 WHERE bid_id=%s",
                (new_set, bid),
            )
            payload = {
                "fact_set_id": new_set,
                "carryovers": [
                    {
                        "new_fact_id": new_fact,
                        "from_fact_id": old_fact,
                        "from_decision_id": str(old),
                        "equivalence_digest": digest(basis),
                    }
                ],
            }
            # A plausible audit from a different scope must never confer equivalence.
            audit(c, f["w"]["actor"], None, "facts.set_replaced", payload)

        def check():
            response = f["w"]["client"].post(
                path + "/" + prepared["manifest"]["id"] + "/fact-check",
                json={"execution_input_digest": prepared["digest"]},
                headers=headers(f["w"]),
            )
            assert response.status_code == 200, response.text
            return response.json()

        assert "FACT_DECISION_BINDING_UNPROVEN" in check()["fact_checks"][0]["blockers"]
        with connection() as c:
            audit(
                c, f["w"]["actor"], bid, "facts.set_replaced", payload | {"fact_set_id": str(uid())}
            )
        assert "FACT_DECISION_BINDING_UNPROVEN" in check()["fact_checks"][0]["blockers"]
        with connection() as c:
            audit(c, f["w"]["actor"], bid, "facts.set_replaced", payload)
        result = check()
        assert (
            result["provenance_verified_count"] == 1 and result["matches_prepared_context"] is False
        )
        assert result["fact_checks"][0]["blockers"] == ["FACT_SCOPE_MAPPING_REQUIRED"]

        # A second exact edge resolves the same original decision, never by date/name.
        from packages.domain.bid_package_fact_scope_repository import load_packet
        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.bid_package_review_eligibility import inspect

        second_set, second_fact = str(uid()), str(uid())
        with connection() as c:
            c.execute(
                "INSERT INTO design.fact_sets(id,bid_id,digest) VALUES(%s,%s,%s)",
                (second_set, bid, digest({"synthetic": "second_carryover"})),
            )
            c.execute(
                "INSERT INTO design.fact_items(id,bid_id,fact_set_id,subject,scope,name,value,unit,evidence_ids) SELECT %s,bid_id,%s,subject,scope,name,value,unit,evidence_ids FROM design.fact_items WHERE bid_id=%s AND id=%s",
                (second_fact, second_set, bid, new_fact),
            )
            c.execute(
                "INSERT INTO design.decision_heads(bid_id,object_kind,object_id,revision,decision_id) VALUES(%s,'fact',%s,1,%s)",
                (bid, second_fact, old),
            )
            c.execute(
                "UPDATE design.fact_heads SET fact_set_id=%s,revision=revision+1 WHERE bid_id=%s",
                (second_set, bid),
            )
            audit(
                c,
                f["w"]["actor"],
                bid,
                "facts.set_replaced",
                {
                    "fact_set_id": second_set,
                    "previous_set_id": new_set,
                    "carryovers": [
                        {
                            "new_fact_id": second_fact,
                            "from_fact_id": new_fact,
                            "from_decision_id": str(old),
                            "equivalence_digest": digest(basis),
                        }
                    ],
                },
            )
        assert check()["provenance_verified_count"] == 1
        current = inspect(f["scope"], frozen["manifest"]["id"], frozen["digest"])
        prepared_response = f["w"]["client"].post(
            path,
            json={
                "frozen_digest": frozen["digest"],
                "context_digest": current["current_context"]["semantic_digest"],
                "rerun": None,
            },
            headers=headers(f["w"]),
        )
        assert prepared_response.status_code == 201, prepared_response.text
        prepared2 = prepared_response.json()
        body = self.scope_body((f, frozen, path, prepared2, second_fact, source))
        stored, _ = save(
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared2["manifest"]["id"],
            str(uid()),
            body,
        )
        with connection() as c:
            packet = load_packet(
                c,
                f["scope"],
                frozen["manifest"]["id"],
                prepared2["manifest"]["id"],
                stored["body"]["manifest"]["id"],
            )
            assert [edge["from_fact_id"] for edge in packet.proof()["decision_lineage"]] == [
                new_fact,
                old_fact,
            ]
            assert packet.proof()["decision_lineage"][1]["previous_set_recorded"] is False

    def test_scope_http_explicit_save_observation_and_exact_history(self, provenance_case):
        f, frozen, path, prepared, fact, source = provenance_case
        client = f["w"]["client"]
        base = path + "/" + prepared["manifest"]["id"]
        url = base + "/fact-scope-declarations"
        observe = base + "/facts/" + fact + "/scope-declaration"
        result = client.get(observe)
        assert result.status_code == 200, result.text
        observation = result.json()
        assert valid("PackageFactScopeObservation", observation)
        assert observation["head"] is None and observation["matches_prepared_input"] is True
        assert (
            observation["provenance_status"] == "verified"
            and len(observation["subject_choices"]) == 4
        )
        body = self.scope_body(provenance_case)
        assert client.post(url, json=body).status_code == 403
        assert (
            client.post(
                url, json=body | {"launch_available": True}, headers=headers(f["w"])
            ).status_code
            == 422
        )
        assert (
            client.post(
                url,
                json=body,
                headers={
                    k: v for k, v in headers(f["w"]).items() if k.lower() != "idempotency-key"
                },
            ).status_code
            == 428
        )
        h = headers(f["w"])
        saved = client.post(url, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        record = saved.json()
        assert valid("PackageFactScopeView", record)
        replay = client.post(url, json=body, headers=h)
        assert (
            replay.status_code == 201
            and replay.json() == record
            and replay.headers["idempotent-replayed"] == "true"
        )
        observed = client.get(observe).json()
        assert valid("PackageFactScopeObservation", observed)
        assert observed["head"] == record and observed["binding_status"] == "matches_current_input"
        history = url + "/" + record["manifest"]["id"]
        assert client.get(history).json() == record
        assert client.get(history.replace(f["scope"][1], uid())).status_code == 404
        assert client.get(observe.replace(fact, uid())).status_code == 404
        owner = f["w"]["database"]["owner"]
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (source,),
        )
        changed = client.get(observe).json()
        assert valid("PackageFactScopeObservation", changed)
        assert changed["head"] == record and changed["binding_status"] == "unproven"
        assert (
            changed["matches_prepared_input"] is False
            and changed["provenance_status"] == "unproven"
        )
        withdrawn = client.post(
            url,
            json=body
            | {"action": "withdraw", "subject": None, "previous_digest": record["digest"]},
            headers=headers(f["w"]),
        )
        assert withdrawn.status_code == 201, withdrawn.text
        assert client.get(observe).json()["binding_status"] == "withdrawn"
        assert client.get(history).json() == record

    def test_scope_http_deferred_bad_ack_returns_conflict_without_saved_record(
        self, provenance_case, monkeypatch
    ):
        from packages.domain.runtime import Command

        f, frozen, path, prepared, fact, source = provenance_case
        before = counts(f["w"])
        finish = Command.finish

        def bad_ack(command, value, status=200, headers=None):
            if value.get("manifest", {}).get("kind") == "fact_scope_declaration":
                value = value | {"digest": "0" * 64}
            return finish(command, value, status, headers)

        monkeypatch.setattr(Command, "finish", bad_ack)
        result = f["w"]["client"].post(
            path + "/" + prepared["manifest"]["id"] + "/fact-scope-declarations",
            json=self.scope_body(provenance_case),
            headers=headers(f["w"]),
        )
        assert (
            result.status_code == 409 and result.json()["code"] == "PACKAGE_FACT_SCOPE_REJECTED"
        ), result.text
        assert counts(f["w"]) == before
        assert (
            f["w"]["database"]["owner"]
            .execute(
                "SELECT count(*) AS n FROM design.bid_package_fact_scopes WHERE execution_input_id=%s",
                (prepared["manifest"]["id"],),
            )
            .fetchone()["n"]
            == 0
        )

    def test_original_prepared_fact_directory_survives_current_head_and_source_changes(
        self, provenance_case
    ):
        import json

        f, frozen, path, prepared, fact, source = provenance_case
        client = f["w"]["client"]
        url = path + "/" + prepared["manifest"]["id"] + "/facts?limit=1"
        owner = f["w"]["database"]["owner"]
        row = owner.execute(
            "SELECT snapshot_text FROM design.bid_package_execution_inputs WHERE id=%s",
            (prepared["manifest"]["id"],),
        ).fetchone()
        original = json.loads(row["snapshot_text"])["context"]["manifest"]["facts"]["items"][0]
        calls = len(f["calls"])
        before = counts(f["w"])
        response = client.get(url)
        assert response.status_code == 200, response.text
        page = response.json()
        assert valid("PackagePreparedFactPage", page)
        assert page["fact_count"] == 1 and page["execution_input_digest"] == prepared["digest"]
        item = page["items"][0]
        assert item["fact_id"] == fact and item["name"] == original["fact"]["name"]
        assert item["fact_item_digest"] == digest(original)
        assert (
            "decision_basis_jsonb_text" not in response.text and "object_key" not in response.text
        )
        assert counts(f["w"]) == before and len(f["calls"]) == calls
        OriginalVerificationCases.seed_fact(self, f["w"])
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (source,),
        )
        assert client.get(url).json() == page

    def test_selected_fact_admission_recheck_and_unused_pool_do_not_create_tasks(
        self, provenance_case
    ):
        from psycopg.pq import TransactionStatus
        from psycopg.types.json import Jsonb

        from packages.domain import bid_package_fact_admission as admission
        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, prepared, fact, source = provenance_case
        scope = f["scope"]
        frozen_id = frozen["manifest"]["id"]
        input_id = prepared["manifest"]["id"]
        save(
            str(f["w"]["actor"]),
            scope,
            frozen_id,
            input_id,
            str(uid()),
            self.scope_body(provenance_case),
        )
        before = counts(f["w"])
        calls = len(f["calls"])
        observed = admission.observe(
            scope,
            frozen_id,
            input_id,
            prepared["digest"],
            {"purpose": "prebid_compliance", "fact_ids": [fact]},
        )
        m = observed.view()["manifest"]
        assert m["facts_qualified"] is True and m["selected_count"] == 1
        assert (
            m["admission"] == "verified_for_selected_use"
            and m["required_facts_assessment"] == "not_performed"
        )
        assert all(
            m[key] is False
            for key in ("review_ready", "launch_available", "publication_authorized")
        )
        assert "synthetic subject" not in str(observed.view()) + repr(observed)
        with connection() as c:
            fresh = admission.recheck(c, observed)
            assert fresh.view()["manifest"]["content_digest"] == m["content_digest"]
            assert c.info.transaction_status == TransactionStatus.INTRANS
        with connection() as c:
            c.execute(
                "INSERT INTO design.fact_items(id,bid_id,fact_set_id,subject,scope,name,value,unit,evidence_ids) SELECT %s,bid_id,fact_set_id,subject,scope,'unused unconfirmed',%s,unit,evidence_ids FROM design.fact_items WHERE bid_id=%s AND id=%s",
                (str(uid()), Jsonb("unused-private"), scope[0], fact),
            )
            c.execute(
                "UPDATE design.fact_heads SET revision=revision+1 WHERE bid_id=%s", (scope[0],)
            )
        with connection() as c:
            fresh = admission.recheck(c, observed)
            assert fresh.view()["manifest"]["content_digest"] == m["content_digest"]
            assert len(fresh.selected_items()) == 1 and "unused-private" not in str(
                fresh.selected_items()
            )
        with connection() as c:
            c.rollback()
            c.autocommit = True
            with pytest.raises(ValueError, match="requires a transaction"):
                admission.recheck(c, observed)
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            with pytest.raises(DomainError) as denied:
                admission.recheck(c, observed)
            assert denied.value.code == "CURRENT_AUTHORITY_REQUIRES_READ_COMMITTED"
        assert counts(f["w"]) == before and len(f["calls"]) == calls
        assert f["w"]["client"].get(path + "/" + input_id).json() == prepared

    def test_empty_selected_admission_does_not_read_or_approve_unconfirmed_company_pool(
        self, prepared_case, monkeypatch
    ):
        from packages.domain import bid_package_fact_admission as admission

        f, frozen, path, prepared = prepared_case

        def forbidden(*args, **kwargs):
            raise AssertionError("empty selection must not inspect current fact pool")

        monkeypatch.setattr(admission, "read_facts", forbidden)
        monkeypatch.setattr(admission, "read_proof", forbidden)
        result = admission.observe(
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
            prepared["digest"],
            {"purpose": "prebid_compliance", "fact_ids": []},
        )
        assert result.view()["manifest"]["admission"] == "not_used"
        assert (
            result.view()["manifest"]["facts_qualified"] is False and result.selected_items() == []
        )
        assert result.view()["manifest"]["required_facts_assessment"] == "not_performed"

    @pytest.mark.parametrize("change", ["withdraw", "replace"])
    def test_selected_admission_rejects_changed_scope_or_fact_but_preserves_old_receipt(
        self, provenance_case, change
    ):
        from packages.domain import bid_package_fact_admission as admission
        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        body = self.scope_body(provenance_case)
        saved, _ = save(*args, str(uid()), body)
        observed = admission.observe(
            *args[1:], prepared["digest"], {"purpose": "prebid_compliance", "fact_ids": [fact]}
        )
        old = observed.view()
        if change == "withdraw":
            save(
                *args,
                str(uid()),
                body
                | {
                    "action": "withdraw",
                    "subject": None,
                    "previous_digest": saved["body"]["digest"],
                },
            )
        else:
            OriginalVerificationCases.seed_fact(self, f["w"])
        with connection() as c:
            with pytest.raises(DomainError) as denied:
                admission.recheck(c, observed)
            assert denied.value.code in (
                "PACKAGE_SELECTED_FACTS_UNPROVEN",
                "PACKAGE_SELECTED_FACT_NOT_CURRENT",
            )
        assert observed.view() == old

    @pytest.mark.parametrize("provenance_case", [8], indirect=True)
    def test_selected_admission_expiry_is_rechecked_without_source_head_changes(
        self, provenance_case
    ):
        import time

        from packages.domain import bid_package_fact_admission as admission
        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        save(*args, str(uid()), self.scope_body(provenance_case))
        observed = admission.observe(
            *args[1:], prepared["digest"], {"purpose": "prebid_compliance", "fact_ids": [fact]}
        )
        owner = f["w"]["database"]["owner"]
        state = owner.execute(
            "SELECT revision,extract(epoch from valid_until-clock_timestamp()) AS remaining FROM retrieval.source_heads WHERE source_id=%s",
            (source,),
        ).fetchone()
        assert state["remaining"] > 0
        time.sleep(float(state["remaining"]) + 0.15)
        assert (
            owner.execute(
                "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
            ).fetchone()["revision"]
            == state["revision"]
        )
        with connection() as c:
            with pytest.raises(DomainError) as denied:
                admission.recheck(c, observed)
            assert denied.value.code == "PACKAGE_SELECTED_FACTS_UNPROVEN"

    def test_prepared_fact_directory_auth_scope_and_cursor_validation(self, provenance_case):
        f, frozen, path, prepared, fact, source = provenance_case
        client = f["w"]["client"]
        url = path + "/" + prepared["manifest"]["id"] + "/facts"
        assert client.get(url + "?limit=101").status_code == 422
        assert client.get(url + "?cursor=forged.signature").status_code == 422
        assert client.get(url.replace(f["scope"][1], uid())).status_code == 404
        assert client.get(url.replace(prepared["manifest"]["id"], uid())).status_code == 404
        client.cookies.clear()
        assert client.get(url).status_code == 401

    def test_scope_declaration_append_ack_withdrawal_and_immutable_history(self, provenance_case):
        import psycopg

        from packages.domain import bid_package_fact_scope_repository as repository
        from packages.domain import bid_package_fact_scopes as service
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        owner = f["w"]["database"]["owner"]
        before = owner.execute(
            "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        ).fetchone()
        old_prepared = f["w"]["client"].get(path + "/" + prepared["manifest"]["id"]).json()
        body = self.scope_body(provenance_case)
        key = str(uid())
        saved, replay = service.save(*args, key, body)
        assert saved["status"] == 201 and not replay
        record = saved["body"]
        assert record["manifest"]["binding"]["fact_id"] == fact
        assert record["manifest"]["facts_qualified"] is False
        assert service.save(*args, key, body) == (saved, True)
        with pytest.raises(DomainError, match="同一幂等键"):
            service.save(*args, key, body | {"reason": "不同意图"})
        with connection() as c:
            assert repository.head(c, args[1][0], args[3], fact) == record
            assert repository.load(c, args[1], args[2], args[3], record["manifest"]["id"]) == record
        owner.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (source,),
        )
        assert service.save(*args, key, body) == (saved, True)
        frozen_proof = owner.execute(
            "SELECT proof_text,proof_snapshot_digest FROM design.bid_package_fact_scopes WHERE id=%s",
            (record["manifest"]["id"],),
        ).fetchone()
        withdrawal = body | {
            "action": "withdraw",
            "subject": None,
            "previous_digest": record["digest"],
            "reason": "来源停用后撤回适用声明",
        }
        removed, replay = service.save(*args, str(uid()), withdrawal)
        assert not replay and removed["body"]["manifest"]["action"] == "withdraw"
        assert (
            owner.execute(
                "SELECT proof_text,proof_snapshot_digest FROM design.bid_package_fact_scopes WHERE id=%s",
                (removed["body"]["manifest"]["id"],),
            ).fetchone()
            == frozen_proof
        )
        with pytest.raises(DomainError, match="已变化"):
            service.save(*args, str(uid()), body)
        with connection() as c:
            assert repository.head(c, args[1][0], args[3], fact) == removed["body"]
            assert repository.load(c, args[1], args[2], args[3], record["manifest"]["id"]) == record
            assert c.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_fact_scopes','INSERT') AS i,has_table_privilege(current_user,'design.bid_package_fact_scopes','UPDATE') AS u,has_table_privilege(current_user,'design.bid_package_fact_scopes','DELETE') AS d"
            ).fetchone() == {"i": True, "u": False, "d": False}
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection() as c:
                c.execute(
                    "DELETE FROM design.bid_package_fact_scopes WHERE id=%s",
                    (record["manifest"]["id"],),
                )
        assert f["w"]["client"].get(path + "/" + prepared["manifest"]["id"]).json() == old_prepared
        assert (
            owner.execute(
                "SELECT (SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
            ).fetchone()
            == before
        )

    @pytest.mark.parametrize("same_key", [False, True])
    def test_scope_concurrent_same_intent_has_one_record_and_ack(self, provenance_case, same_key):
        from concurrent.futures import ThreadPoolExecutor

        from packages.domain.bid_package_fact_scopes import save
        from packages.domain.runtime import DomainError

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        body = self.scope_body(provenance_case)
        key = str(uid())

        def run(index):
            try:
                return save(*args, key if same_key or index == 0 else str(uid()), body)
            except DomainError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        if same_key:
            assert results[0][0] == results[1][0] and sum(x[1] for x in results) == 1
        else:
            assert sum(isinstance(x, tuple) for x in results) == 1
            assert "PACKAGE_FACT_SCOPE_CHANGED" in results
        assert (
            f["w"]["database"]["owner"]
            .execute(
                "SELECT count(*) AS n FROM design.bid_package_fact_scopes WHERE execution_input_id=%s",
                (args[3],),
            )
            .fetchone()["n"]
            == 1
        )

    @pytest.mark.parametrize("corrupt", ["ack", "subject", "fact", "predecessor", "fork", "proof"])
    def test_scope_deferred_guard_rejects_resealed_record_and_rolls_back_command(
        self, provenance_case, corrupt
    ):
        import psycopg

        from packages.domain import bid_package_fact_scope_repository as repository
        from packages.domain import bid_package_fact_scopes as service
        from packages.domain.runtime import Command, connection

        f, frozen, path, prepared, fact, source = provenance_case
        args = (
            str(f["w"]["actor"]),
            f["scope"],
            frozen["manifest"]["id"],
            prepared["manifest"]["id"],
        )
        body = self.scope_body(provenance_case)
        original, _ = service.save(*args, str(uid()), body)
        record = original["body"]
        owner = f["w"]["database"]["owner"]
        before = counts(f["w"])
        with pytest.raises(psycopg.IntegrityError):
            with connection() as c:
                command = Command(
                    c,
                    args[0],
                    repository.KIND,
                    args[3],
                    str(uid()),
                    body | {"previous_digest": record["digest"]},
                )
                m = record["manifest"] | {
                    "id": str(uid()),
                    "command_id": str(command.id),
                    "previous_digest": record["digest"],
                }
                if corrupt == "subject":
                    m["subject"] = {"kind": "lot", "id": str(uid())}
                if corrupt == "fact":
                    m["binding"] = m["binding"] | {"fact_id": str(uid())}
                if corrupt == "predecessor":
                    m["previous_digest"] = "0" * 64
                if corrupt == "fork":
                    m["previous_digest"] = None
                value = {"manifest": m, "digest": digest(m)}
                proof_text = repository.head_packet(c, args[1][0], args[3], fact).snapshot_text()
                if corrupt == "proof":
                    import json

                    proof = json.loads(proof_text)
                    proof["proof"]["decision_binding"] = False
                    proof_text = json.dumps(proof)
                repository.append(c, value, proof_text)
                command.finish(value | {"digest": "f" * 64} if corrupt == "ack" else value, 201)
        assert counts(f["w"]) == before
        assert (
            owner.execute(
                "SELECT count(*) AS n FROM design.bid_package_fact_scopes WHERE execution_input_id=%s",
                (args[3],),
            ).fetchone()["n"]
            == 1
        )

    def test_prepared_internal_consumer_retains_private_context_and_refuses_task_shortcut(
        self, prepared_case
    ):
        from packages.domain import bid_package_execution_input_repository as inputs
        from packages.domain import bid_package_prepared_originals as prepared
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, value = prepared_case
        args = (f["scope"], frozen["manifest"]["id"], value["manifest"]["id"], value["digest"])
        c = f["w"]["database"]["owner"]
        statement = "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.operations) AS jobs,(SELECT count(*) FROM design.outbox) AS events"
        before = c.execute(statement).fetchone()
        with connection() as reader:
            packet = inputs.load_packet(reader, *args[:-1])
        assert packet.view() == value
        assert len(packet.snapshot()["context"]["manifest"]["facts"]["items"]) == 1
        packet.snapshot()["context"]["manifest"]["facts"]["items"].clear()
        packet.view()["manifest"]["identity"].clear()
        assert packet.view() == value
        assert len(packet.snapshot()["context"]["manifest"]["facts"]["items"]) == 1
        assert "object_key" not in repr(packet) and "text_content" not in repr(packet)
        calls = len(f["calls"])
        receipt = prepared.verify(*args)
        assert len(f["calls"]) == calls + 2
        assert "object_key" not in repr(receipt) and "text_content" not in repr(receipt)
        with pytest.raises(DomainError) as error, connection() as publisher:
            prepared.recheck_for_publication(publisher, receipt)
        assert error.value.code == "PACKAGE_REVIEW_EXECUTION_BLOCKED"
        assert c.execute(statement).fetchone() == before
        assert f["w"]["client"].get(path + "/" + value["manifest"]["id"]).json() == value

    def test_prepared_internal_wrong_reference_rejected_before_object_io(self, prepared_case):
        from packages.domain import bid_package_prepared_originals as prepared
        from packages.domain.runtime import DomainError

        f, frozen, path, value = prepared_case
        frozen_id, input_id = frozen["manifest"]["id"], value["manifest"]["id"]
        calls = len(f["calls"])
        for scope, fid, pid, digest_value in (
            (f["scope"], frozen_id, input_id, "0" * 64),
            (f["scope"], frozen_id, uid(), value["digest"]),
            (f["scope"], uid(), input_id, value["digest"]),
            ((f["scope"][0], uid(), *f["scope"][2:]), frozen_id, input_id, value["digest"]),
        ):
            with pytest.raises(DomainError) as error:
                prepared.verify(scope, fid, pid, digest_value)
            assert error.value.code in {
                "PACKAGE_EXECUTION_INPUT_CHANGED",
                "PACKAGE_EXECUTION_INPUT_NOT_FOUND",
            }
        assert len(f["calls"]) == calls

    @pytest.mark.parametrize("change", ["method", "source", "lifecycle"])
    def test_prepared_internal_new_state_cannot_replace_saved_input(
        self, prepared_case, monkeypatch, change
    ):
        from packages.domain import bid_package_prepared_originals as prepared
        from packages.domain.runtime import DomainError

        f, frozen, path, value = prepared_case
        c = f["w"]["database"]["owner"]
        if change == "method":
            monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-after-prepare")
        elif change == "source":
            c.execute(
                "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                (f["w"]["sources"][0],),
            )
        else:
            c.execute(
                "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (f["scope"][0],)
            )
        with pytest.raises(DomainError) as error:
            prepared.verify(
                f["scope"], frozen["manifest"]["id"], value["manifest"]["id"], value["digest"]
            )
        assert error.value.code in {
            "PACKAGE_REVIEW_CONTEXT_CHANGED",
            "PACKAGE_REVIEW_INPUT_CHANGED",
        }
        assert f["w"]["client"].get(path + "/" + value["manifest"]["id"]).json() == value

    def test_prepared_internal_late_change_and_unsafe_transactions_never_publish(
        self, prepared_case, monkeypatch
    ):
        from packages.domain import bid_package_prepared_originals as prepared
        from packages.domain.runtime import DomainError, connection

        f, frozen, path, value = prepared_case
        receipt = prepared.verify(
            f["scope"], frozen["manifest"]["id"], value["manifest"]["id"], value["digest"]
        )
        with connection() as c:
            c.rollback()
            c.autocommit = True
            with pytest.raises(ValueError, match="transaction"):
                prepared.recheck_for_publication(c, receipt)
        with connection() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            with pytest.raises(ValueError, match="read-committed"):
                prepared.recheck_for_publication(c, receipt)
        monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-after-verification")
        with pytest.raises(DomainError) as error, connection() as c:
            prepared.recheck_for_publication(c, receipt)
        assert error.value.code == "PACKAGE_REVIEW_INPUT_CHANGED"

    def test_prepared_internal_rerun_keeps_exact_saved_execution_identity(self, execution_case):
        from packages.domain import bid_package_prepared_originals as prepared

        f, frozen, path, body, h = execution_case
        rerun = {"nonce": uid(), "reason": "explicit prepared rerun"}
        response = f["w"]["client"].post(path, json=body | {"rerun": rerun}, headers=h)
        assert response.status_code == 201, response.text
        value = response.json()
        receipt = prepared.verify(
            f["scope"], frozen["manifest"]["id"], value["manifest"]["id"], value["digest"]
        )
        assert receipt._originals.execution_identity(rerun) == value["manifest"]["identity"]

    def test_prepared_replay_and_history_survive_closed_work_withdrawal_and_no_store(
        self, execution_case, monkeypatch
    ):
        from packages.domain import storage

        f, old, path, body, h = execution_case
        saved = f["w"]["client"].post(path, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        c = f["w"]["database"]["owner"]
        c.execute("UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (f["scope"][0],))
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (f["w"]["sources"][0],),
        )
        calls = len(f["calls"])

        def unavailable():
            raise AssertionError("historical replay cannot read storage")

        monkeypatch.setattr(storage, "client", unavailable)
        monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-after-save")
        replay = f["w"]["client"].post(path, json=body, headers=h)
        assert replay.status_code == 201 and replay.headers.get("idempotent-replayed") == "true"
        assert replay.json() == value
        assert f["w"]["client"].get(path + "/" + value["manifest"]["id"]).json() == value
        assert len(f["calls"]) == calls

    def test_prepared_strict_request_idempotency_conflict_and_scope(self, execution_case):
        f, old, path, body, h = execution_case
        client = f["w"]["client"]
        calls = len(f["calls"])
        assert (
            client.post(path, json=body | {"launch_available": True}, headers=h).status_code == 422
        )
        assert (
            client.post(
                path,
                json=body,
                headers={k: v for k, v in h.items() if k.lower() != "idempotency-key"},
            ).status_code
            == 428
        )
        assert (
            client.post(path, json=body | {"context_digest": "0" * 64}, headers=h).status_code
            == 409
        )
        assert len(f["calls"]) == calls
        saved = client.post(path, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        calls = len(f["calls"])
        assert (
            client.post(
                path,
                json=body | {"rerun": {"nonce": uid(), "reason": "explicit changed intent"}},
                headers=h,
            ).status_code
            == 409
        )
        assert len(f["calls"]) == calls
        detail = path + "/" + saved.json()["manifest"]["id"]
        assert client.get(detail.replace(f["scope"][1], uid())).status_code == 404

    @pytest.mark.parametrize("change", ["close", "source", "facts", "method"])
    def test_prepared_race_during_io_leaves_no_input_or_command(
        self, execution_case, monkeypatch, change
    ):
        f, old, path, body, h = execution_case
        c = f["w"]["database"]["owner"]
        before = c.execute(
            "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.bid_package_execution_inputs) AS inputs"
        ).fetchone()

        def mutate():
            if change == "close":
                c.execute(
                    "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s",
                    (f["scope"][0],),
                )
            elif change == "source":
                c.execute(
                    "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
                    (f["w"]["sources"][0],),
                )
            elif change == "facts":
                OriginalVerificationCases.seed_fact(self, f["w"])
            else:
                monkeypatch.setenv("DEEPSEEK_MODEL", "synthetic-io-race")

        f["state"]["during_read"] = mutate
        response = f["w"]["client"].post(path, json=body, headers=h)
        assert response.status_code == 409, response.text
        assert (
            c.execute(
                "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.bid_package_execution_inputs) AS inputs"
            ).fetchone()
            == before
        )

    def test_prepared_rerun_changes_execution_only_and_permissions_are_append_only(
        self, execution_case
    ):
        import psycopg

        f, old, path, body, h = execution_case
        client = f["w"]["client"]
        first = client.post(path, json=body, headers=h)
        second = client.post(
            path,
            json=body | {"rerun": {"nonce": uid(), "reason": "explicit rerun"}},
            headers=headers(f["w"]),
        )
        assert first.status_code == second.status_code == 201, (first.text, second.text)
        a, b = first.json()["manifest"], second.json()["manifest"]
        assert a["identity"]["content_digest"] == b["identity"]["content_digest"]
        assert a["identity"]["execution_digest"] != b["identity"]["execution_digest"]
        with psycopg.connect(f["w"]["database"]["api_dsn"]) as c:
            assert (
                c.execute(
                    "SELECT has_table_privilege(current_user,'design.bid_package_execution_inputs','UPDATE')"
                ).fetchone()[0]
                is False
            )
        with psycopg.connect(f["w"]["database"]["worker_dsn"]) as c:
            assert c.execute(
                "SELECT has_table_privilege(current_user,'design.bid_package_execution_inputs','SELECT'),has_table_privilege(current_user,'design.bid_package_execution_inputs','INSERT')"
            ).fetchone() == (True, False)

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

    def test_prepared_bad_ack_rolls_back_record_and_command(self, execution_case, monkeypatch):
        from copy import deepcopy

        from packages.domain.runtime import Command

        f, old, path, body, h = execution_case
        c = f["w"]["database"]["owner"]
        before = c.execute(
            "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.bid_package_execution_inputs) AS inputs"
        ).fetchone()
        finish = Command.finish

        def corrupt(command, value, status=200, headers=None):
            changed = deepcopy(value)
            changed["manifest"]["publication_authorized"] = True
            return finish(command, changed, status, headers)

        monkeypatch.setattr(Command, "finish", corrupt)
        response = f["w"]["client"].post(path, json=body, headers=h)
        assert response.status_code == 409, response.text
        assert (
            c.execute(
                "SELECT (SELECT count(*) FROM design.commands) AS commands,(SELECT count(*) FROM design.bid_package_execution_inputs) AS inputs"
            ).fetchone()
            == before
        )

    def test_prepared_concurrent_same_key_returns_one_record(self, execution_case):
        from concurrent.futures import ThreadPoolExecutor

        f, old, path, body, h = execution_case
        # Other concurrent requests may own connections; single-flight IO tests still assert zero.
        f["state"]["assert_zero_connections"] = False

        def send():
            return f["w"]["client"].post(path, json=body, headers=h)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: send(), range(2)))
        assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
        assert responses[0].json() == responses[1].json()
        assert sum(r.headers.get("idempotent-replayed") == "true" for r in responses) == 1
        c = f["w"]["database"]["owner"]
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.bid_package_execution_inputs WHERE frozen_input_id=%s",
                (old["manifest"]["id"],),
            ).fetchone()["n"]
            == 1
        )

    def test_prepared_history_rejects_resealed_private_snapshot_corruption(self, execution_case):
        import json
        from copy import deepcopy

        from packages.domain import bid_package_review_input_repository as roots
        from packages.domain.package_execution_input import consume
        from packages.domain.runtime import DomainError, connection, sha

        f, old, path, body, h = execution_case
        saved = f["w"]["client"].post(path, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        value = saved.json()
        with connection() as c:
            packet = roots.load_input(c, f["scope"], old["manifest"]["id"])
            row = dict(
                c.execute(
                    "SELECT * FROM design.bid_package_execution_inputs WHERE id=%s",
                    (value["manifest"]["id"],),
                ).fetchone()
            )
        for change in ("context", "document", "identity", "source"):
            changed = deepcopy(row)
            s = json.loads(row["snapshot_text"])
            if change == "context":
                s["context"]["manifest"]["facts"]["qualification"] = "validated"
            elif change == "document":
                s["documents"][0]["blocks"][0]["text_content"] = "synthetic changed text"
            elif change == "identity":
                s["binding"]["identity_digest"] = "a" * 64
            else:
                s["observations"]["sources"] = []
            changed["snapshot_text"] = json.dumps(
                s, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            changed["snapshot_digest"] = sha(changed["snapshot_text"].encode())
            changed["manifest"]["snapshot_digest"] = changed["snapshot_digest"]
            changed["digest"] = digest(changed["manifest"])
            with pytest.raises(DomainError) as error:
                consume(changed, f["scope"], old["manifest"]["id"], value["manifest"]["id"], packet)
            assert error.value.code == "PACKAGE_EXECUTION_INPUT_CORRUPT"

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

    def test_execution_identity_comes_from_verified_root_and_current_context_not_caller_body(
        self, frozen_case
    ):
        from packages.domain.package_review_execution_identity import verify

        f = frozen_case
        value = self.post(f).json()
        receipt = self.verify_frozen(f, value)
        before = counts(f["w"])
        initial = receipt.execution_identity()
        assert verify(initial) == initial
        binding = initial["binding"]
        assert (
            tuple(binding[k] for k in ("bid_id", "package_id", "revision_id", "inventory_id"))
            == f["scope"]
        )
        assert binding["frozen_input_id"] == value["manifest"]["id"]
        assert binding["frozen_digest"] == value["digest"]
        assert binding["input_digest"] == value["manifest"]["input_digest"]
        assert binding["evidence_digest"] == value["manifest"]["evidence_digest"]
        assert binding["identity_digest"] == f["w"]["own"]["identity"]["digest"]
        assert binding["context_digest"] == receipt.context_digest
        assert binding["method_digest"] == receipt.observation()["current_context"]["method_digest"]
        rerun = receipt.execution_identity({"nonce": uid(), "reason": "synthetic explicit rerun"})
        assert rerun["content_digest"] == initial["content_digest"]
        assert rerun["execution_digest"] != initial["execution_digest"]
        binding.clear()
        assert receipt.execution_identity()["binding"]
        assert counts(f["w"]) == before and receipt.observation()["publication_authorized"] is False

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
