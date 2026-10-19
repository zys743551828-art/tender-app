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

    def test_session_csrf_and_shape_are_required_before_io(self, original_case):
        w, _, body, calls, _, path = original_case
        assert w["client"].post(path, json=body).status_code == 403
        assert self.post(original_case, body | {"originals_verified": True}).status_code == 422
        assert not calls
