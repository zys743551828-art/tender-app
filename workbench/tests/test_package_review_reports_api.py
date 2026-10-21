"""Real PG/nonowner report jobs and real OOXML with explicit synthetic storage/model ports."""
# ruff: noqa: F401,F811

import os
from copy import deepcopy

import psycopg
import pytest
from test_package_review_decisions_api import TestPackageReviewDecisions as DecisionCases
from test_package_review_reports import text as docx_text
from test_package_review_runs_api import TestPackageReviewRuns as RunCases
from test_package_review_runs_api import api, database, headers, requirements, uid, world

from apps.worker import engine
from packages.contracts.package_review_reports_api import valid
from packages.domain import bid_package_reports as reports
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest
from packages.domain.runtime import Command, clean, sha

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires isolated PG17 report-copy checks",
)


def totals(case):
    return (
        case["w"]["database"]["owner"]
        .execute(
            """SELECT
        (SELECT count(*) FROM design.bid_package_report_exports WHERE bid_id=%s) AS exports,
        (SELECT count(*) FROM design.bid_package_report_artifacts WHERE bid_id=%s) AS artifacts,
        (SELECT count(*) FROM design.commands WHERE command_kind='package-scope-report-start' AND target_id=%s) AS commands,
        (SELECT count(*) FROM design.operations WHERE kind='package-scope-report' AND bid_id=%s) AS jobs,
        (SELECT count(*) FROM design.model_calls m JOIN design.operations o ON o.id=m.operation_id WHERE o.bid_id=%s) AS model_calls""",
            (
                case["scope"][0],
                case["scope"][0],
                case["run"]["id"],
                case["scope"][0],
                case["scope"][0],
            ),
        )
        .fetchone()
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageReviewReports:
    original_case = RunCases.original_case
    frozen_case = RunCases.frozen_case
    execution_case = RunCases.execution_case
    prepared_case = RunCases.prepared_case
    exact_inventory_proof_case = RunCases.exact_inventory_proof_case
    launch_case = RunCases.launch_case
    launch = RunCases.launch
    post = RunCases.post
    message = RunCases.message
    provider = RunCases.provider
    cancel = RunCases.cancel
    report_case = DecisionCases.report_case
    decide = DecisionCases.decide

    @pytest.fixture
    def export_case(self, report_case, monkeypatch):
        case = report_case
        monkeypatch.setenv("AUTHORING_RENDERER", "/unavailable/synthetic-report-converter")
        monkeypatch.setenv("AUTHORING_FONT_PATH", "/unavailable/synthetic-report-font")
        objects, writes = {}, []
        store_state = {"during_put": None, "corrupt_read": False}

        def no_open_runtime_transaction():
            rows = (
                case["w"]["database"]["owner"]
                .execute(
                    "SELECT xact_start FROM pg_stat_activity WHERE usename IN ('fusion_package_requirements_service','fusion_package_requirements_worker')"
                )
                .fetchall()
            )
            assert all(row["xact_start"] is None for row in rows)

        def put(key, data, media):
            no_open_runtime_transaction()
            objects[key] = data
            writes.append((key, media))
            if store_state["during_put"]:
                store_state["during_put"]()

        def get(key):
            no_open_runtime_transaction()
            return b"corrupt synthetic bytes" if store_state["corrupt_read"] else objects[key]

        monkeypatch.setattr(storage, "put", put)
        monkeypatch.setattr(storage, "get", get)
        return case | {
            "export_path": case["path"] + "/" + case["run"]["id"] + "/report-exports",
            "context_path": case["path"] + "/" + case["run"]["id"] + "/report-context",
            "objects": objects,
            "writes": writes,
            "store_state": store_state,
        }

    def start(self, case, *, body=None, request_headers=None):
        if body is None:
            response = case["w"]["client"].get(case["context_path"])
            assert response.status_code == 200, response.text
            body = {"context_digest": response.json()["context_digest"], "format": "docx"}
        return case["w"]["client"].post(
            case["export_path"],
            json=body,
            headers=headers(case["w"]) if request_headers is None else request_headers,
        )

    def export_message(self, case, value):
        return clean(
            case["w"]["database"]["owner"]
            .execute(
                "SELECT payload FROM design.outbox WHERE operation_id=%s AND topic='tender.task.export.v1'",
                (value["operation"]["id"],),
            )
            .fetchone()["payload"]
        )

    def current(self, case, value):
        response = case["w"]["client"].get(case["export_path"] + "/" + value["id"])
        assert response.status_code == 200, response.text
        assert valid("PackageReviewReportView", response.json())
        return response.json()

    def test_real_docx_publication_download_and_reuse_without_another_model_call(
        self, export_case, monkeypatch
    ):
        case = export_case
        first = self.start(case)
        assert first.status_code == 202, first.text
        queued = first.json()
        assert valid("PackageReviewReportView", queued) and queued["result"] is None
        message = self.export_message(case, queued)
        engine.handle_lane("export", message)
        value = self.current(case, queued)
        assert value["operation"]["state"] == "succeeded", value
        artifact = value["result"]
        raw = case["objects"]["blobs/" + artifact["blob_digest"]]
        content = docx_text(raw)
        assert sha(raw) == artifact["blob_digest"] and len(raw) == artifact["byte_size"]
        for row in case["run"]["result"]["manifest"]["matrix"]:
            assert row["requirement_statement"] in content
            assert all(
                q["quote"] in content for q in row["target_quotes"] + row["authority_quotes"]
            )
        assert "不是提交正文" in content and "尚未记录" in content
        assert len(case["calls"]) == 1 and len(case["writes"]) == 1
        engine.handle_lane("export", message)
        reused = self.start(case)
        assert reused.status_code == 202 and reused.json() == value, reused.text
        assert len(case["writes"]) == 1 and len(case["calls"]) == 1
        monkeypatch.setattr(storage, "sign", lambda key: "https://synthetic.invalid/" + key)
        download = case["w"]["client"].get(
            "/api/v1/artifacts/" + artifact["document_version_id"] + "/download"
        )
        assert download.status_code == 200, download.text
        assert download.json()["artifact_kind"] == "review_report"
        assert download.json()["filename"] == artifact["filename"]
        page = case["w"]["client"].get(case["export_path"]).json()
        assert valid("PackageReviewReportPage", page) and page["items"] == [value]
        assert not value["submission_eligible"] and not value["formal_scoring_eligible"]
        assert totals(case) == {
            "exports": 1,
            "artifacts": 1,
            "commands": 2,
            "jobs": 1,
            "model_calls": 1,
        }

    def test_frozen_human_snapshot_survives_new_opinion_withdrawal_and_closed_project(
        self, export_case
    ):
        case = export_case
        accepted = self.decide(case)
        assert accepted.status_code == 201, accepted.text
        first = self.start(case)
        assert first.status_code == 202, first.text
        old = accepted.json()
        changed_reason = "后来改变的合成意见不应回写已经申请的副本"
        changed = self.decide(
            case,
            case["body"]
            | {
                "state": "rejected",
                "reason": changed_reason,
                "expected_head": {"id": old["manifest"]["id"], "digest": old["digest"]},
            },
        )
        assert changed.status_code == 201, changed.text
        c = case["w"]["database"]["owner"]
        c.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        engine.handle_lane("export", self.export_message(case, first.json()))
        result = self.current(case, first.json())
        assert result["operation"]["state"] == "succeeded", result
        content = docx_text(case["objects"]["blobs/" + result["result"]["blob_digest"]])
        assert old["manifest"]["reason"] in content and changed_reason not in content
        assert "当前来源效力未在导出时重新核验" in content
        assert case["w"]["client"].get(case["path"] + "/" + case["run"]["id"]).json() == case["run"]
        # Creating a new historical copy is also allowed after work closure.
        second = self.start(case)
        assert second.status_code == 202 and second.json()["id"] != first.json()["id"], second.text

    def test_exact_ack_ignores_new_human_heads_and_missing_renderer_configuration(
        self, export_case, monkeypatch
    ):
        case = export_case
        context = case["w"]["client"].get(case["context_path"]).json()
        body = {"context_digest": context["context_digest"], "format": "docx"}
        original_headers = headers(case["w"])
        first = self.start(case, body=body, request_headers=original_headers)
        assert first.status_code == 202, first.text
        assert self.decide(case).status_code == 201
        engine.handle_lane("export", self.export_message(case, first.json()))
        monkeypatch.setattr(
            reports.policy,
            "method_profile",
            lambda: pytest.fail("ACK must not probe current renderer"),
        )
        replay = self.start(case, body=body, request_headers=original_headers)
        assert replay.status_code == 202 and replay.json() == first.json(), replay.text
        assert replay.headers["idempotent-replayed"] == "true"
        assert self.current(case, first.json())["operation"]["state"] == "succeeded"

    def test_stale_context_or_unavailable_pdf_never_queues_a_copy(self, export_case):
        case = export_case
        context = case["w"]["client"].get(case["context_path"]).json()
        assert valid("PackageReviewReportContext", context)
        assert (
            context["formats"] == ["docx"]
            and context["pdf_unavailable_code"] == "RENDERER_UNAVAILABLE"
        )
        before = totals(case)
        pdf = self.start(case, body={"context_digest": context["context_digest"], "format": "pdf"})
        assert pdf.status_code == 409 and pdf.json()["code"] == "RENDERER_UNAVAILABLE", pdf.text
        assert self.decide(case).status_code == 201
        stale = self.start(
            case, body={"context_digest": context["context_digest"], "format": "docx"}
        )
        assert (
            stale.status_code == 409
            and stale.json()["code"] == "PACKAGE_REVIEW_REPORT_CONTEXT_CHANGED"
        ), stale.text
        assert totals(case) == before

    def test_cancel_during_storage_prevents_artifact_and_explicit_retry_can_succeed(
        self, export_case
    ):
        case = export_case
        first = self.start(case)
        assert first.status_code == 202, first.text
        queued = first.json()
        case["store_state"]["during_put"] = lambda: self.cancel(case, queued)
        engine.handle_lane("export", self.export_message(case, queued))
        engine.reconcile(once=True)
        current = self.current(case, queued)
        assert current["operation"]["state"] == "cancelled" and current["result"] is None
        assert totals(case)["artifacts"] == 0 and len(case["calls"]) == 1
        case["store_state"]["during_put"] = None
        next_attempt = self.start(case)
        assert next_attempt.status_code == 202 and next_attempt.json()["id"] != queued["id"], (
            next_attempt.text
        )
        engine.handle_lane("export", self.export_message(case, next_attempt.json()))
        assert self.current(case, next_attempt.json())["operation"]["state"] == "succeeded"

    def test_corrupted_stored_bytes_fail_without_publishing_a_download(self, export_case):
        case = export_case
        response = self.start(case)
        assert response.status_code == 202, response.text
        case["store_state"]["corrupt_read"] = True
        message = self.export_message(case, response.json())
        lease = engine.acquire(message)
        assert lease is not None
        with pytest.raises(reports.DomainError) as error:
            engine.run_compute(message, lease)
        assert error.value.code == "PACKAGE_REPORT_OBJECT_CORRUPT"
        engine.finish(message, lease, None, error.value)
        value = self.current(case, response.json())
        assert value["operation"]["state"] == "failed" and value["result"] is None
        assert totals(case)["artifacts"] == 0

    def test_atomic_guard_requires_original_snapshot_ack_and_audit(self, export_case, monkeypatch):
        case = export_case
        before = totals(case)
        with monkeypatch.context() as patch:
            patch.setattr(reports, "audit", lambda *args, **kwargs: None)
            response = self.start(case)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "PACKAGE_REPORT_REQUEST_REJECTED"
        assert totals(case) == before
        original = Command.finish
        with monkeypatch.context() as patch:
            patch.setattr(
                Command, "finish", lambda self, body, status=200: original(self, body, 200)
            )
            response = self.start(case)
        assert response.status_code == 409 and totals(case) == before, response.text
        freeze = reports.policy.freeze
        with monkeypatch.context() as patch:

            def changed_snapshot(context, format):
                value = deepcopy(freeze(context, format))
                value["context"]["human_decisions"]["items"][0]["row_digest"] = "0" * 64
                value["context_digest"] = digest(value["context"])
                return value

            patch.setattr(reports.policy, "freeze", changed_snapshot)
            response = self.start(case)
        assert response.status_code == 409 and totals(case) == before, response.text

    def test_cross_scope_origin_and_nonowner_write_boundaries(self, export_case):
        case = export_case
        first = self.start(case)
        assert first.status_code == 202, first.text
        for selected in (*case["scope"][1:], *case["args"][1:], case["run"]["id"]):
            denied = case["w"]["client"].get(
                (case["export_path"] + "/" + first.json()["id"]).replace(selected, uid())
            )
            assert denied.status_code == 404, denied.text
        denied = self.start(
            case, request_headers=headers(case["w"]) | {"Origin": "https://foreign.invalid"}
        )
        assert denied.status_code == 403
        assert case["w"]["client"].get(case["export_path"], params={"limit": 51}).status_code == 422
        for role in ("api_dsn", "worker_dsn"):
            with psycopg.connect(case["w"]["database"][role], autocommit=True) as c:
                for statement in (
                    "UPDATE design.bid_package_report_exports SET input_digest=input_digest",
                    "DELETE FROM design.bid_package_report_exports",
                    "UPDATE design.bid_package_report_artifacts SET blob_digest=blob_digest",
                    "DELETE FROM design.bid_package_report_artifacts",
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        c.execute(statement)
                prohibited = (
                    "bid_package_report_artifacts"
                    if role == "api_dsn"
                    else "bid_package_report_exports"
                )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute("INSERT INTO design." + prohibited + " DEFAULT VALUES")
