"""Exact package-run references remain project scoped and do not modify frozen reviews."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api import knowledge_routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app
from packages.domain.runtime import DomainError
from packages.knowledge import bridge
from packages.knowledge.contracts import validate_actual

BID, RUN = UUID(int=1), UUID(int=2)


def test_package_review_reference_is_explicit_and_closed():
    value = {
        "bid_id": str(BID),
        "version_id": str(UUID(int=3)),
        "purpose": "assist",
        "target_kind": "package_review_run",
        "target_object_id": str(RUN),
        "excerpt": "与确切原文相同的知识摘录",
        "applicability_reason": "作为这次核查的另行参考",
    }
    validate_actual("KnowledgeReferenceRequest", value)
    for changed in (
        value | {"purpose": "formal_score"},
        value | {"project_fact_created": True},
        value | {"target_kind": "anything_else"},
    ):
        with pytest.raises(DomainError):
            validate_actual("KnowledgeReferenceRequest", changed)


@pytest.mark.parametrize("belongs", [True, False])
def test_lookup_requires_both_exact_run_and_its_project(belongs):
    calls = []

    def execute(statement, parameters):
        calls.append((statement.as_string(None), parameters))
        return SimpleNamespace(fetchone=lambda: {"id": RUN} if belongs else None)

    port = SimpleNamespace(execute=execute)
    if belongs:
        bridge.require_reference_target(port, BID, "package_review_run", RUN)
    else:
        with pytest.raises(DomainError) as caught:
            bridge.require_reference_target(port, BID, "package_review_run", RUN)
        assert caught.value.code == "NOT_FOUND"
    assert calls == [
        ('SELECT id FROM "bid_package_review_runs" WHERE id=%s AND bid_id=%s', (RUN, BID))
    ]


def test_unknown_target_kind_and_foreign_project_never_select_an_arbitrary_table():
    port = SimpleNamespace(execute=lambda *_args: pytest.fail("Untrusted target reached SQL"))
    for kind, target in (("anything; DROP TABLE bids", RUN), ("project", RUN)):
        with pytest.raises(DomainError):
            bridge.require_reference_target(port, BID, kind, target)


def test_actual_target_directory_is_authenticated_and_does_not_admit_formal_use(monkeypatch):
    calls = []

    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda sql: calls.append(sql))

    value = {
        "bid_id": str(BID),
        "items": [],
        "next_offset": None,
        "reference_only": True,
        "changes_frozen_result": False,
        "formal_score_allowed": False,
    }
    monkeypatch.setattr(knowledge_routes, "auth", lambda request: calls.append("auth"))
    monkeypatch.setattr(knowledge_routes, "connection", connection)

    def targets(_c, bid, *, limit, offset):
        assert (bid, limit, offset) == (BID, 7, 14)
        return value

    monkeypatch.setattr(bridge, "package_review_targets", targets)
    response = knowledge_routes.reference_targets(BID, None, limit=7, offset=14)
    assert calls == ["auth", "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"]
    assert response.headers["Cache-Control"] == "private, no-store"
    validate_actual("KnowledgePackageReviewTargetPage", value)
    actual = implemented_openapi(app)
    operation = actual["paths"]["/api/v1/bids/{bid_id}/knowledge-reference-targets"]["get"]
    assert operation["security"] == [{"SessionCookie": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "KnowledgePackageReviewTargetPage"
    )
