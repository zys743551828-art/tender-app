"""M1 software entrypoints/read projections; no rendering, model or database claims."""

from contextlib import contextmanager
from uuid import UUID

from apps.api import authoring, history_routes
from apps.api.export_openapi import implemented_openapi
from apps.api.main import app


def identity(n):
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


def test_rich_routes_are_actually_registered_and_contracts_follow_registration():
    actual = implemented_openapi(app)
    paths = actual["paths"]
    assert "/api/v1/authoring/rich-capabilities" in paths
    assert "/api/v1/bids/{bid_id}/authoring-images" in paths
    assert "AuthoringRichBuildRequest" in actual["components"]["schemas"]
    assert "identity" in actual["components"]["schemas"]["BuildView"]["required"]


def test_build_history_exposes_real_draft_filter_with_cursor_scope():
    operation = implemented_openapi(app)["paths"]["/api/v1/bids/{bid_id}/builds"]["get"]
    assert any(p.get("name") == "draft_id" for p in operation["parameters"])


def test_exact_output_adoption_and_independent_parse_are_real_registered_routes():
    actual = implemented_openapi(app)
    base = "/api/v1/bids/{bid_id}/documents/{document_version_id}"
    for path, verb in (
        ("/api/v1/bids/{bid_id}/builds/{build_id}/package-adoptions", "post"),
        (base + "/parse-context", "get"),
        (base + "/parse-requests", "post"),
        (base + "/parse-requests", "get"),
        (base + "/parse-requests/{request_id}", "get"),
    ):
        assert verb in actual["paths"][path]
    for name in (
        "AdoptAuthoringOutput",
        "AuthoringOutputAdopted",
        "DocumentParseContext",
        "StartDocumentParse",
        "DocumentParseView",
        "DocumentParseStarted",
        "DocumentParsePage",
    ):
        assert name in actual["components"]["schemas"]


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class BuildReadFixture:
    """Controlled immutable DB observations; executes actual list/detail projections."""

    def execute(self, sql, params=()):
        if sql.startswith("SET TRANSACTION"):
            return Rows([])
        if "FROM builds b JOIN build_inputs" in sql:
            return Rows(
                [
                    {
                        "id": identity(1),
                        "bid_id": identity(2),
                        "input_id": identity(3),
                        "operation_id": identity(4),
                        "draft_snapshot_id": identity(5),
                        "draft_id": identity(6),
                        "draft_revision": 8,
                        "snapshot_digest": "a" * 64,
                        "input_digest": "b" * 64,
                        "operation_kind": "build",
                        "manifest": {
                            "writer_kind": "generated_rich/3",
                            "snapshot_digest": "a" * 64,
                            "directory_template_version_id": str(identity(7)),
                            "style_template_version_id": str(identity(8)),
                            "formats": ["docx", "pdf"],
                            "follow_up": "none",
                            "pagination_mode": "chapter_start_new_page",
                        },
                    }
                ]
            )
        if "FROM build_outputs" in sql:
            return Rows([])
        if "FROM audit_entries" in sql:
            return Rows([])
        raise AssertionError(sql)


def test_list_and_single_build_share_exact_frozen_identity_and_layout(monkeypatch):
    fixture = BuildReadFixture()

    @contextmanager
    def connection():
        yield fixture

    monkeypatch.setattr(authoring, "connection", connection)
    monkeypatch.setattr(authoring, "auth", lambda *_args: {})
    listed = history_routes.build_view(fixture, identity(1))
    single = authoring.get_build(identity(1), None)
    assert listed == single
    assert listed["identity"]["draft_revision"] == 8
    assert listed["identity"]["draft_id"] == str(identity(6))
    assert listed["identity"]["snapshot_digest"] == "a" * 64
    assert listed["identity"]["request"]["pagination_mode"] == "chapter_start_new_page"
    assert listed["layout"]["state"] == "pending"
    assert listed["layout"]["page_count"] is None
