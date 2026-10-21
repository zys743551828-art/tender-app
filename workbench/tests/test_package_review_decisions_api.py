"""Real PG17/nonowner/ASGI human decisions after a genuinely committed synthetic-port run.

The existing grouped fixture owns bootstrap. Model/original adapters are explicit
synthetic ports; no paid call or semantic-quality claim is made by these tests.
"""
# ruff: noqa: F401,F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import psycopg
import pytest
from test_package_review_runs_api import TestPackageReviewRuns as RunCases
from test_package_review_runs_api import api, database, headers, requirements, uid, world

from apps.worker import engine
from packages.contracts.package_review_decisions_api import valid
from packages.domain import bid_package_review_decisions as decisions
from packages.domain import storage
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.review_identity import digest
from packages.domain.runtime import Command, connection

pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="requires grouped isolated PG17 human decision checks",
)


def counts(case):
    return (
        case["w"]["database"]["owner"]
        .execute(
            """SELECT
        (SELECT count(*) FROM design.bid_package_review_decisions WHERE run_id=%s) AS decisions,
        (SELECT count(*) FROM design.bid_package_review_decision_heads WHERE run_id=%s) AS heads,
        (SELECT count(*) FROM design.commands WHERE target_id=%s AND command_kind='package-scope-review-human-decision') AS commands,
        (SELECT count(*) FROM design.audit_entries WHERE bid_id=%s AND event_type='package.scope_review.human_decision') AS audits""",
            (case["run"]["id"], case["run"]["id"], case["run"]["id"], case["scope"][0]),
        )
        .fetchone()
    )


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestPackageReviewDecisions:
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

    @pytest.fixture
    def report_case(self, launch_case, monkeypatch):
        case = launch_case
        calls = self.provider(case, monkeypatch)
        response = self.launch(case)
        assert response.status_code == 202, response.text
        run = response.json()
        engine.handle_lane("review", self.message(case, run))
        response = case["w"]["client"].get(case["path"] + "/" + run["id"])
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["operation"]["state"] == "succeeded", run
        assert len(calls) == 1
        row = run["result"]["manifest"]["matrix"][0]
        path = case["path"] + "/" + run["id"]
        return case | {
            "run": run,
            "row": row,
            "calls": calls,
            "current_path": path + "/human-decisions",
            "decision_path": path + "/requirements/" + row["requirement_id"] + "/human-decisions",
            "body": {
                "result_digest": run["result"]["digest"],
                "row_digest": digest(row),
                "expected_head": None,
                "state": "confirmed",
                "reason": "合成人工意见：确认该判断只反映本轮已声明的核查范围。",
                "selected_quotes": deepcopy(row["target_quotes"] + row["authority_quotes"]),
            },
        }

    def decide(self, case, body=None, request_headers=None):
        return case["w"]["client"].post(
            case["decision_path"],
            json=case["body"] if body is None else body,
            headers=headers(case["w"]) if request_headers is None else request_headers,
        )

    def test_three_human_states_keep_machine_result_and_current_summary_small(self, report_case):
        case = report_case
        client = case["w"]["client"]
        current = client.get(case["current_path"])
        assert current.status_code == 200, current.text
        assert valid("PackageReviewHumanDecisionCurrent", current.json())
        assert all(item["current"] is None for item in current.json()["items"])
        previous = None
        saved = []
        for index, state in enumerate(("confirmed", "rejected", "needs_review"), 1):
            body = case["body"] | {"expected_head": previous, "state": state}
            response = self.decide(case, body)
            assert response.status_code == 201, response.text
            value = response.json()
            assert valid("PackageReviewHumanDecisionView", value)
            assert value["manifest"]["sequence_no"] == index
            assert value["manifest"]["previous_head"] == previous
            assert not any(value["manifest"][key] for key in decisions.policy.FLAGS)
            previous = {"id": value["manifest"]["id"], "digest": value["digest"]}
            saved.append(value)
        current = client.get(case["current_path"]).json()
        summary = next(
            item["current"]
            for item in current["items"]
            if item["requirement_id"] == case["row"]["requirement_id"]
        )
        assert summary["state"] == "needs_review" and summary["sequence_no"] == 3
        assert "selected_quotes" not in json.dumps(current) and "manifest" not in summary
        page = client.get(case["decision_path"], params={"limit": 2}).json()
        assert valid("PackageReviewHumanDecisionPage", page)
        assert page["items"] == list(reversed(saved[1:])) and page["has_more"]
        next_page = client.get(
            case["decision_path"], params={"limit": 2, "cursor": page["next_cursor"]}
        ).json()
        assert next_page["items"] == saved[:1] and not next_page["has_more"]
        assert client.get(case["decision_path"], params={"limit": 21}).status_code == 422
        assert client.get(case["path"] + "/" + case["run"]["id"]).json() == case["run"]
        assert len(case["calls"]) == 1
        assert counts(case) == {"decisions": 3, "heads": 1, "commands": 3, "audits": 3}

    def test_exact_ack_after_new_head_and_closed_work_needs_no_provider_or_current_sources(
        self, report_case, monkeypatch
    ):
        case = report_case
        original_headers = headers(case["w"])
        first = self.decide(case, request_headers=original_headers)
        assert first.status_code == 201, first.text
        value = first.json()
        head = {"id": value["manifest"]["id"], "digest": value["digest"]}
        second = self.decide(case, case["body"] | {"expected_head": head, "state": "rejected"})
        assert second.status_code == 201, second.text
        c = case["w"]["database"]["owner"]
        c.execute(
            "UPDATE design.bid_profiles SET phase='closed' WHERE bid_id=%s", (case["scope"][0],)
        )
        c.execute(
            "UPDATE retrieval.source_heads SET revision=revision+1,status='withdrawn' WHERE source_id=%s",
            (case["w"]["sources"][0],),
        )
        monkeypatch.setattr(
            storage, "client", lambda: pytest.fail("human history must not read originals")
        )
        monkeypatch.setattr(
            DeepSeekClient,
            "from_env",
            classmethod(lambda cls: pytest.fail("human history must not require provider")),
        )
        again = self.decide(case, request_headers=original_headers)
        assert again.status_code == 201 and again.json() == value, again.text
        assert again.headers["idempotent-replayed"] == "true"
        denied = self.decide(case)
        assert denied.status_code == 409 and denied.json()["code"] == "PROJECT_WORK_CLOSED"
        assert case["w"]["client"].get(case["current_path"]).status_code == 200
        assert len(case["w"]["client"].get(case["decision_path"]).json()["items"]) == 2
        assert counts(case) == {"decisions": 2, "heads": 1, "commands": 2, "audits": 2}

    def test_two_competing_first_decisions_have_one_cas_winner(self, report_case):
        case = report_case
        bodies = [case["body"] | {"state": state} for state in ("confirmed", "rejected")]
        request_headers = [headers(case["w"]), headers(case["w"])]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.decide, case, body, header)
                for body, header in zip(bodies, request_headers, strict=True)
            ]
            results = [future.result(timeout=30) for future in futures]
        assert sorted(value.status_code for value in results) == [201, 409], [
            r.text for r in results
        ]
        conflict = next(value for value in results if value.status_code == 409)
        assert conflict.json()["code"] == "PACKAGE_REVIEW_DECISION_HEAD_CHANGED"
        assert counts(case) == {"decisions": 1, "heads": 1, "commands": 1, "audits": 1}

    def test_wrong_basis_evidence_scope_or_write_origin_never_save_an_opinion(self, report_case):
        case = report_case
        bad_bodies = [
            case["body"] | {"result_digest": "0" * 64},
            case["body"] | {"row_digest": "0" * 64},
        ]
        foreign = deepcopy(case["body"])
        foreign["selected_quotes"][0]["member_id"] = "foreign-member"
        bad_bodies.extend([foreign, case["body"] | {"reason": " \t\n "}])
        for body in bad_bodies:
            response = self.decide(case, body)
            assert response.status_code in {409, 422}, response.text
        for selected_id in (
            *case["scope"][1:],
            case["args"][1],
            case["args"][2],
            case["row"]["requirement_id"],
        ):
            path = case["decision_path"].replace(selected_id, uid())
            response = case["w"]["client"].get(path)
            assert response.status_code == 404, response.text
        response = self.decide(
            case, request_headers=headers(case["w"]) | {"Origin": "https://foreign.example"}
        )
        assert response.status_code == 403
        assert counts(case) == {"decisions": 0, "heads": 0, "commands": 0, "audits": 0}

    def test_database_rejects_bypassed_machine_binding_quotes_and_qualification(
        self, report_case, monkeypatch
    ):
        case = report_case
        original = decisions.policy.make
        for field in ("scope", "row_digest", "quote", "actor", "sequence", "qualification"):

            def invalid(*args, selected=field, **kwargs):
                value = original(*args, **kwargs)
                m = value["manifest"]
                if selected == "scope":
                    m["scope"]["inventory_id"] = uid()
                elif selected == "row_digest":
                    m["row_digest"] = "0" * 64
                elif selected == "quote":
                    m["selected_quotes"][0]["member_id"] = "foreign-member"
                elif selected == "actor":
                    m["actor_id"] = uid()
                elif selected == "sequence":
                    m["sequence_no"] = 2
                else:
                    m["submission_eligible"] = True
                value["digest"] = digest(m)
                return value

            with monkeypatch.context() as patch:
                patch.setattr(decisions.policy, "make", invalid)
                response = self.decide(case)
            assert response.status_code == 409, (field, response.text)
            assert response.json()["code"] == "PACKAGE_REVIEW_DECISION_REJECTED"
            assert counts(case) == {"decisions": 0, "heads": 0, "commands": 0, "audits": 0}

    def test_database_requires_ack_and_audit_in_same_transaction(self, report_case, monkeypatch):
        case = report_case
        with monkeypatch.context() as patch:
            patch.setattr(decisions, "audit", lambda *args, **kwargs: None)
            response = self.decide(case)
        assert response.status_code == 409, response.text
        assert counts(case) == {"decisions": 0, "heads": 0, "commands": 0, "audits": 0}
        original = Command.finish
        with monkeypatch.context() as patch:
            patch.setattr(
                Command, "finish", lambda self, body, status=200: original(self, body, 200)
            )
            response = self.decide(case)
        assert response.status_code == 409, response.text
        assert counts(case) == {"decisions": 0, "heads": 0, "commands": 0, "audits": 0}

    def test_worker_has_no_human_table_permission_and_history_is_immutable(self, report_case):
        case = report_case
        response = self.decide(case)
        assert response.status_code == 201, response.text
        decision_id = response.json()["manifest"]["id"]
        for table in ("bid_package_review_decisions", "bid_package_review_decision_heads"):
            with connection(True) as c:
                assert not c.execute(
                    "SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE') AS allowed",
                    ("design." + table,),
                ).fetchone()["allowed"]
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection(True) as c:
                c.execute("SELECT * FROM design." + table)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection() as c:
            c.execute(
                "UPDATE design.bid_package_review_decisions SET digest=digest WHERE id=%s",
                (decision_id,),
            )
        with pytest.raises(psycopg.Error):
            case["w"]["database"]["owner"].execute(
                "DELETE FROM design.bid_package_review_decisions WHERE id=%s", (decision_id,)
            )
        assert counts(case) == {"decisions": 1, "heads": 1, "commands": 1, "audits": 1}

    def test_pending_run_has_no_human_decision_surface(self, launch_case):
        case = launch_case
        response = self.launch(case)
        assert response.status_code == 202, response.text
        path = case["path"] + "/" + response.json()["id"] + "/human-decisions"
        current = case["w"]["client"].get(path)
        assert (
            current.status_code == 409
            and current.json()["code"] == "PACKAGE_REVIEW_RESULT_UNAVAILABLE"
        )
