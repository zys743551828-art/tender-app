"""Native PG17/nonowner/authenticated HTTP, with explicitly synthetic originals and model ports."""
# ruff: noqa: F401,F811

import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from test_package_outcomes_pg import (
    api,
    catalog,
    exact,
    headers,
    inventory,
    register,
    request,
    requirements,
    setup,
    uid,
    verify,
    world,
)
from test_package_outcomes_pg import database as base_database
from test_package_review_runs_api import TestPackageReviewRuns as _RunCases

from packages.contracts import package_retrospectives_api as contract
from packages.domain.runtime import connection, now, sha
from packages.knowledge import repository as knowledge
from packages.rag.indexing import ensure_parse_sources, original_source_id, parse_source_id
from packages.retrospectives import observations, policy, repository

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    not os.environ.get("FUSION_REQUIREMENTS_ADMIN_DSN"),
    reason="isolated nonowner retrospective PG17 required",
)


@pytest.fixture(scope="module")
def database():
    source = base_database.__wrapped__()
    value = next(source)
    try:
        owner = value["owner"]
        if (
            owner.execute("SELECT to_regclass('design.package_retrospectives') AS name").fetchone()[
                "name"
            ]
            is None
        ):
            owner.execute((ROOT / "packages/contracts/sql/package-retrospectives.sql").read_text())
        from apps.api.main import app
        from apps.api.package_retrospective_routes import router

        if not any(getattr(route, "path", None) == contract.BASE for route in app.routes):
            app.include_router(router)
            app.openapi_schema = None
        yield value
    finally:
        try:
            next(source)
        except StopIteration:
            pass


def chosen(w, *, official=True, runs=None):
    return {
        "submission_id": w["submission"]["id"],
        "outcome_id": w["result"]["id"] if official else None,
        "outcome_missing_reason": None
        if official
        else "Synthetic official original is not yet available",
        "business_result_id": None,
        "business_result_missing_reason": "Synthetic award notice is not yet available",
        "baseline_run_id": runs[0]["id"] if runs else None,
        "submitted_run_id": runs[1]["id"] if runs else None,
        "reviews_missing_reason": None
        if runs
        else "Synthetic comparison requires another completed review",
    }


def prepare(w, selected=None):
    base = f"/api/v1/bids/{w['scope'].bid_id}/package-retrospectives"
    selected = selected or chosen(w)
    response = w["client"].post(base + "/preview", json=selected, headers=headers(w))
    assert response.status_code == 200, response.text
    assert contract.valid("PackageRetrospectivePreview", response.json()), response.json()
    body = {
        "selection": selected,
        "preview_digest": response.json()["digest"],
        "title": "合成整包待核复盘",
        "notes": {
            "observations": "合成总分仅记录原值；没有逐项扣分事实。",
            "hypotheses": "成员假设：需要另查原页，尚无结论。",
            "next_actions": "补齐官方逐项资料并人工复核。",
            "additional_missing_materials": "真实工程师标注尚未提供。",
        },
    }
    return base, response, body


def freeze(w, selected=None):
    base, preview, body = prepare(w, selected)
    h = headers(w, etag=preview.headers["etag"])
    saved = w["client"].post(base, json=body, headers=h)
    assert saved.status_code == 201, saved.text
    assert contract.valid("PackageRetrospectiveApplied", saved.json()), saved.json()
    return base, saved, body, h


def handoff(w, base, saved):
    frozen = saved.json()["retrospective"]
    path = base + "/" + frozen["manifest"]["id"] + "/knowledge-candidate"
    body = {"retrospective_digest": frozen["digest"], "reason": "成员明确建立待核企业知识候选"}
    h = headers(w, etag=saved.headers["etag"])
    response = w["client"].post(path, json=body, headers=h)
    assert response.status_code == 201, response.text
    assert contract.valid("PackageRetrospectiveKnowledgeApplied", response.json())
    return path, response, body, h


def published_sources(w):
    with connection() as c:
        # The original F05 fixture deliberately registers an unparsed receipt.
        # Exercise the existing explicit parse/source publication path before
        # asking for a reusable knowledge candidate; production never invents it.
        version = w["attachment"]["document_version_id"]
        receipt = c.execute(
            "SELECT id FROM design.parse_runs WHERE document_version_id=%s ORDER BY created_at,id LIMIT 1",
            (version,),
        ).fetchone()
        if receipt is None:
            from test_bid_package_submissions_pg import EVIDENCE

            parse, block = uid(), uid()
            c.execute(
                "INSERT INTO design.parse_runs(id,bid_id,document_version_id,parser_digest,config_digest,page_count,coverage,gaps) VALUES(%s,%s,%s,%s,%s,1,'complete','[]')",
                (
                    parse,
                    w["scope"].bid_id,
                    version,
                    sha("synthetic-receipt-parser"),
                    sha("synthetic"),
                ),
            )
            c.execute(
                "INSERT INTO design.pages(bid_id,parse_id,physical_page,width,height,rotation,quality,gaps) VALUES(%s,%s,1,100,100,0,'usable','[]')",
                (w["scope"].bid_id, parse),
            )
            c.execute(
                "INSERT INTO design.evidence_blocks(id,bid_id,parse_id,physical_page,ordinal,kind,text_content,digest) VALUES(%s,%s,%s,1,0,'text',%s,%s)",
                (block, w["scope"].bid_id, parse, EVIDENCE.decode(), sha(EVIDENCE)),
            )
        else:
            parse = str(receipt["id"])
        ensure_parse_sources(c, UUID(w["scope"].bid_id), UUID(parse), publish_readable=True)
        for selected in w["submission"]["package_binding"]["manifest"]["selection"].values():
            if (
                isinstance(selected, dict)
                and "manifest" in selected
                and "members" in selected["manifest"]
            ):
                for member in selected["manifest"]["members"]:
                    ensure_parse_sources(
                        c,
                        UUID(w["scope"].bid_id),
                        UUID(member["parse"]["parse_run_id"]),
                        publish_readable=True,
                    )


def test_missing_data_stays_pending_null_and_explicit_candidate_never_publishes(exact):
    w = setup(exact)
    published_sources(w)
    base, saved, body, h = freeze(w, chosen(w, official=False))
    frozen = saved.json()["retrospective"]
    assert frozen["manifest"]["state"] == "pending_review"
    assert frozen["manifest"]["preview"]["manifest"]["outcome"] is None
    assert all(frozen["manifest"][key] is False for key in policy.FLAGS)
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.package_retrospective_knowledge_links WHERE retrospective_id=%s",
                (frozen["manifest"]["id"],),
            ).fetchone()["n"]
            == 0
        )
    replay = w["client"].post(base, json=body, headers=h)
    assert replay.json() == saved.json() and replay.headers["idempotent-replayed"] == "true"
    path, candidate, candidate_body, candidate_headers = handoff(w, base, saved)
    item = candidate.json()["link"]
    replay = w["client"].post(path, json=candidate_body, headers=candidate_headers)
    assert replay.json() == candidate.json() and replay.headers["idempotent-replayed"] == "true"
    duplicate = w["client"].post(
        path, json=candidate_body, headers=headers(w, etag=saved.headers["etag"])
    )
    assert (
        duplicate.status_code == 409
        and duplicate.json()["code"] == "PACKAGE_RETROSPECTIVE_KNOWLEDGE_EXISTS"
    )
    viewed = w["client"].get("/api/v1/knowledge/" + item["knowledge_id"])
    assert viewed.status_code == 200 and viewed.json()["workflow"] == "candidate"
    assert viewed.json()["published_version_id"] is None
    assert "成员假设（尚无结论）" in viewed.json()["content"]
    submit = w["client"].post(
        "/api/v1/knowledge/" + item["knowledge_id"] + "/submit",
        json={
            "decision": "submit",
            "reason": "Synthetic insufficient candidate",
            "evidence_ids": [],
        },
        headers=headers(w, etag=viewed.headers["etag"]),
    )
    assert submit.status_code == 409 and submit.json()["code"] == "KNOWLEDGE_NOT_READY"
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT n.policy_class FROM retrieval.knowledge_versions v JOIN retrieval.source_nodes n ON n.id=v.source_id WHERE v.id=%s",
                (item["knowledge_version_id"],),
            ).fetchone()["policy_class"]
            == "derived_mixed"
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM retrieval.source_ancestors a JOIN retrieval.source_nodes n ON n.id=a.ancestor_id WHERE a.source_id=(SELECT source_id FROM retrieval.knowledge_versions WHERE id=%s) AND n.policy_class='post_outcome'",
                (item["knowledge_version_id"],),
            ).fetchone()["n"]
            >= 1
        )


def test_verified_zero_is_preserved_and_total_never_generates_item_deductions(exact):
    w = setup(exact)
    verify(w)
    published_sources(w)
    base, saved, _, _ = freeze(w)
    p = saved.json()["retrospective"]["manifest"]["preview"]["manifest"]
    assert p["outcome"]["value"] == "0" and p["outcome"]["verification"] == "verified"
    assert p["outcome"]["evidence_refs"] == w["verification"]["evidence_refs"]
    assert "item_deductions_unavailable" in {g["code"] for g in p["gaps"]}
    _, result, _, _ = handoff(w, base, saved)
    read = w["client"].get("/api/v1/knowledge/" + result.json()["link"]["knowledge_id"]).json()
    assert "分数：0" in read["content"] and "不能从总分反推" in read["content"]


def test_changed_official_verification_rejects_stale_freeze_and_preserves_existing_history(exact):
    w = setup(exact)
    published_sources(w)
    base, preview, body = prepare(w)
    verify(w)
    rejected = w["client"].post(base, json=body, headers=headers(w, etag=preview.headers["etag"]))
    assert rejected.status_code == 412, rejected.text
    base, saved, original_body, original_headers = freeze(w)
    newer = w["client"].post(
        "/api/v1/outcomes/" + w["result"]["id"] + "/corrections",
        json=w["result_request"] | {"value": "1"},
        headers=headers(w, etag=w["result_headers"]["etag"]),
    )
    assert newer.status_code == 201, newer.text
    detail = w["client"].get(base + "/" + saved.json()["retrospective"]["manifest"]["id"])
    assert (
        detail.status_code == 200
        and detail.json()["retrospective"] == saved.json()["retrospective"]
    )
    assert detail.json()["current"]["unchanged"] is False
    replay = w["client"].post(base, json=original_body, headers=original_headers)
    assert replay.json() == saved.json(), replay.text
    refused = w["client"].post(
        base + "/" + saved.json()["retrospective"]["manifest"]["id"] + "/knowledge-candidate",
        json={
            "retrospective_digest": saved.json()["retrospective"]["digest"],
            "reason": "Must not publish stale association",
        },
        headers=headers(w, etag=saved.headers["etag"]),
    )
    assert (
        refused.status_code == 409
        and refused.json()["code"] == "PACKAGE_RETROSPECTIVE_SOURCE_CHANGED"
    )


@pytest.mark.parametrize("field", ["submission_id", "outcome_id", "baseline_run_id"])
def test_foreign_or_missing_exact_records_are_not_replaced_by_latest(exact, field):
    w = setup(exact)
    selected = chosen(w)
    selected[field] = uid()
    if field == "baseline_run_id":
        selected["submitted_run_id"] = uid()
        selected["reviews_missing_reason"] = None
    response = w["client"].post(
        f"/api/v1/bids/{w['scope'].bid_id}/package-retrospectives/preview",
        json=selected,
        headers=headers(w),
    )
    assert response.status_code == 404, response.text


def test_nonowner_immutability_and_source_set_sql_guard(exact, monkeypatch):
    w = setup(exact)
    published_sources(w)
    base, saved, _, _ = freeze(w)
    with connection() as c:
        assert not c.execute(
            "SELECT has_table_privilege(current_user,'design.package_retrospectives','UPDATE') AS permitted"
        ).fetchone()["permitted"]
        assert not c.execute(
            "SELECT has_table_privilege('tender_worker','design.package_retrospectives','INSERT') AS permitted"
        ).fetchone()["permitted"]
    original = observations.observe

    def forged(c, bid, body):
        value = original(c, bid, body)
        value["manifest"]["source_ids"] = value["manifest"]["source_ids"][1:]
        value["manifest"]["source_snapshot"] = [
            row
            for row in value["manifest"]["source_snapshot"]
            if row["source_id"] in value["manifest"]["source_ids"]
        ]
        value["digest"] = sha(value["manifest"])
        return value

    monkeypatch.setattr(observations, "observe", forged)
    base, preview, body = prepare(w)
    rejected = w["client"].post(base, json=body, headers=headers(w, etag=preview.headers["etag"]))
    assert (
        rejected.status_code == 409
        and rejected.json()["code"] == "PACKAGE_RETROSPECTIVE_STORAGE_REJECTED"
    )


def test_withdrawn_source_blocks_handoff_and_original_candidate_replay_remains_recoverable(exact):
    w = setup(exact)
    published_sources(w)
    base, saved, _, _ = freeze(w)
    path, result, body, h = handoff(w, base, saved)
    w["database"]["owner"].execute(
        "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
        (original_source_id(UUID(w["source"])),),
    )
    replay = w["client"].post(path, json=body, headers=h)
    assert replay.status_code == 201 and replay.json() == result.json()
    detail = w["client"].get(base + "/" + saved.json()["retrospective"]["manifest"]["id"])
    assert detail.json()["current"]["unchanged"] is False
    assert detail.json()["knowledge_link"] == result.json()["link"]


def complete_knowledge_body(w):
    """Deliberately only prebid refs: inherited retrospective policy must survive."""
    with connection() as c:
        row = c.execute(
            "SELECT e.*,p.document_version_id FROM design.evidence_blocks e JOIN design.parse_runs p ON p.id=e.parse_id WHERE e.bid_id=%s AND p.document_version_id=%s ORDER BY e.physical_page,e.ordinal LIMIT 1",
            (w["scope"].bid_id, w["member"].document_version_id),
        ).fetchone()
        source = parse_source_id(row["parse_id"])
        revision = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()["revision"]
    return {
        "title": "合成复盘经成员补充适用条件",
        "content": "仅供合成项目历史参考，仍是事后复盘，不形成事前事实或风险解决结论。",
        "categories": ["chapter_reference"],
        "scope": "仅合成项目历史参考",
        "applicability": {
            "bidder_ids": [w["submission"]["identity"]["bidder_id"]],
            "bid_ids": [w["scope"].bid_id],
            "regions": ["合成地区"],
            "engineering_types": ["合成工程"],
            "conditions": [],
            "purposes": ["history"],
            "validity_kind": "bounded",
            "valid_from": (now() - timedelta(days=1)).isoformat(),
            "valid_until": (now() + timedelta(days=30)).isoformat(),
            "validity_basis": "合成验收窗口；非真实工程适用性证明",
            "specificity_note": "原项目观察不可自动转为本项目事实",
        },
        "source_refs": [
            {
                "source_id": str(source),
                "source_revision": revision,
                "document_version_id": str(row["document_version_id"]),
                "parse_id": str(row["parse_id"]),
                "physical_page": row["physical_page"],
                "evidence_id": str(row["id"]),
                "excerpt": row["text_content"][:100],
            }
        ],
    }


@pytest.mark.parametrize("withdraw", [False, True])
def test_later_prebid_only_version_keeps_mixed_lineage_and_requires_explicit_publish(
    exact, withdraw, monkeypatch
):
    from packages.retrospectives import knowledge as origin_hook

    w = setup(exact)
    published_sources(w)
    base, saved, _, _ = freeze(w)
    _, candidate, _, _ = handoff(w, base, saved)
    linked = candidate.json()["link"]
    path = "/api/v1/knowledge/" + linked["knowledge_id"]
    before = w["client"].get(path)
    body = complete_knowledge_body(w)
    version = w["client"].post(
        path + "/versions", json=body, headers=headers(w, etag=before.headers["etag"])
    )
    assert version.status_code == 201, version.text
    assert version.json()["published_version_id"] is None
    assert "retrospective" in version.json()["categories"]
    with connection() as c:
        native = c.execute(
            "SELECT v.applicability,n.policy_class FROM retrieval.knowledge_versions v JOIN retrieval.source_nodes n ON n.id=v.source_id WHERE v.id=%s",
            (version.json()["version_id"],),
        ).fetchone()
        assert native["policy_class"] == "derived_mixed"
        assert (
            native["applicability"]["retrospective_origin"]["retrospective_digest"]
            == saved.json()["retrospective"]["digest"]
        )
    # Bypass the application inheritance port: API-role SQL must still reject
    # a new version relabelled as prebid content even with a valid marker edge.
    with monkeypatch.context() as patch:
        patch.setattr(
            origin_hook,
            "inherit",
            lambda c, item, categories, metadata, parents, policy: (
                categories,
                metadata,
                parents,
                policy,
            ),
        )
        with (
            pytest.raises(
                psycopg.errors.CheckViolation, match="retrospective_knowledge_lineage_required"
            ),
            connection() as c,
        ):
            knowledge.insert_version(
                c,
                UUID(linked["knowledge_id"]),
                3,
                UUID(w["actor"]),
                "Synthetic downgrade rejected",
                ["retrospective"],
                native["applicability"],
                [UUID(linked["source_id"])],
                "prebid_content",
                now(),
            )
    pending = w["client"].post(
        path + "/submit",
        json={"decision": "submit", "reason": "合成成员明确送确认", "evidence_ids": []},
        headers=headers(w, etag=version.headers["etag"]),
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["workflow"] == "pending_confirmation"
    if withdraw:
        w["database"]["owner"].execute(
            "UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1 WHERE source_id=%s",
            (original_source_id(UUID(w["source"])),),
        )
        current = w["client"].get(path)
        assert current.json()["workflow"] == "source_invalid"
        refused = w["client"].post(
            path + "/versions", json=body, headers=headers(w, etag=current.headers["etag"])
        )
        assert (
            refused.status_code == 409
            and refused.json()["code"] == "KNOWLEDGE_RETROSPECTIVE_SOURCE_CHANGED"
        ), refused.text
        result = w["client"].post(
            path + "/publish",
            json={"decision": "publish", "reason": "合成尝试发布已失效候选", "evidence_ids": []},
            headers=headers(w, etag=current.headers["etag"]),
        )
        assert result.status_code == 409, result.text
        with pytest.raises(psycopg.errors.CheckViolation), connection() as c:
            c.execute(
                "UPDATE retrieval.knowledge_items SET published_version_id=%s WHERE id=%s",
                (version.json()["version_id"], linked["knowledge_id"]),
            )
        with monkeypatch.context() as patch:
            patch.setattr(
                origin_hook,
                "inherit",
                lambda c, item, categories, metadata, parents, policy: (
                    categories,
                    metadata,
                    parents,
                    policy,
                ),
            )
            with (
                pytest.raises(
                    psycopg.errors.CheckViolation, match="retrospective_knowledge_lineage_required"
                ),
                connection() as c,
            ):
                knowledge.insert_version(
                    c,
                    UUID(linked["knowledge_id"]),
                    3,
                    UUID(w["actor"]),
                    "Synthetic stale native version rejected",
                    ["retrospective"],
                    native["applicability"],
                    [UUID(linked["source_id"])],
                    "derived_mixed",
                    now(),
                )
    else:
        result = w["client"].post(
            path + "/publish",
            json={"decision": "publish", "reason": "合成成员明确确认历史用途", "evidence_ids": []},
            headers=headers(w, etag=pending.headers["etag"]),
        )
        assert result.status_code == 200 and result.json()["workflow"] == "published", result.text
        assert result.json()["published_version_id"] == version.json()["version_id"]
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.samples WHERE bid_id=%s", (w["scope"].bid_id,)
            ).fetchone()["n"]
            == 0
        )


def test_unparsed_receipt_keeps_pending_history_and_requires_source_before_candidate(exact):
    w = setup(exact)
    base, saved, _, _ = freeze(w)
    assert "source_closure_missing" in {
        g["code"] for g in saved.json()["retrospective"]["manifest"]["preview"]["manifest"]["gaps"]
    }
    rejected = w["client"].post(
        base + "/" + saved.json()["retrospective"]["manifest"]["id"] + "/knowledge-candidate",
        json={
            "retrospective_digest": saved.json()["retrospective"]["digest"],
            "reason": "合成资料来源尚待解析",
        },
        headers=headers(w, etag=saved.headers["etag"]),
    )
    assert (
        rejected.status_code == 409
        and rejected.json()["code"] == "PACKAGE_RETROSPECTIVE_SOURCE_CHANGED"
    )
    published_sources(w)
    old = w["client"].get(base + "/" + saved.json()["retrospective"]["manifest"]["id"])
    assert (
        old.json()["retrospective"] == saved.json()["retrospective"]
        and old.json()["current"]["unchanged"] is False
    )
    base, fresh, _, _ = freeze(w)
    handoff(w, base, fresh)


def test_selected_business_stage_is_independent_and_current_verification_is_native(
    exact, monkeypatch
):
    import test_package_outcomes_pg as fixture_sources

    monkeypatch.setattr(
        fixture_sources,
        "QUOTE",
        "Synthetic official technical total: 0 points out of 60. Separate official award notice: this bidder was not awarded the contract.",
    )
    w = setup(exact)
    published_sources(w)
    verify(w)
    path = f"/api/v1/bids/{w['scope'].bid_id}/submissions/{w['submission']['id']}/business-results"
    initial = w["client"].get(path)
    registered = w["client"].post(
        path,
        json={
            "submission_id": w["submission"]["id"],
            "stage": "not_awarded",
            "source_type": "official",
            "source_version_id": w["source"],
            "evidence_refs": w["verification"]["evidence_refs"],
            "announced_at": w["result_request"]["known_at"],
            "known_at": now().isoformat(),
            "reason": "合成独立官方未中标通知，不从技术总分推断",
        },
        headers=headers(w, etag=initial.headers["etag"]),
    )
    assert registered.status_code == 201, registered.text
    selected = chosen(w) | {
        "business_result_id": registered.json()["id"],
        "business_result_missing_reason": None,
    }
    base, pending, _, _ = freeze(w, selected)
    assert (
        pending.json()["retrospective"]["manifest"]["preview"]["manifest"]["business_result"][
            "verification"
        ]
        == "pending"
    )
    verified = w["client"].post(
        "/api/v1/business-results/" + registered.json()["id"] + "/verification-decisions",
        json={
            "state": "verified",
            "reason": "合成成员核验独立通知原页",
            "identity_confirmed": True,
            "evidence_refs": w["verification"]["evidence_refs"],
        },
        headers=headers(w, etag=registered.headers["etag"]),
    )
    assert verified.status_code == 200, verified.text
    assert (
        w["client"]
        .get(base + "/" + pending.json()["retrospective"]["manifest"]["id"])
        .json()["current"]["unchanged"]
        is False
    )
    base, saved, _, _ = freeze(w, selected)
    snapshot = saved.json()["retrospective"]["manifest"]["preview"]["manifest"]
    assert snapshot["business_result"]["stage"] == "not_awarded"
    assert snapshot["business_result"]["verification"] == "verified"
    assert snapshot["outcome"]["value"] == "0"
    assert "usable" not in snapshot["business_result"]
    handoff(w, base, saved)
    original = observations.observe

    def forged(c, bid, body):
        value = original(c, bid, body)
        value["manifest"]["business_result"]["verification_details"]["identity_confirmed"] = False
        value["digest"] = sha(value["manifest"])
        return value

    monkeypatch.setattr(observations, "observe", forged)
    base, preview, body = prepare(w, selected)
    refused = w["client"].post(base, json=body, headers=headers(w, etag=preview.headers["etag"]))
    assert (
        refused.status_code == 409
        and refused.json()["code"] == "PACKAGE_RETROSPECTIVE_STORAGE_REJECTED"
    ), refused.text


@pytest.mark.parametrize("world", [b"synthetic-original-v1"], indirect=True)
class TestRetrospectiveTwoRuns:
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
    equivalent_case = _RunCases.equivalent_case

    @pytest.fixture
    def completed_pair(self, launch_case, monkeypatch):
        from apps.worker import engine

        first = launch_case
        second = self.equivalent_case(
            first, rerun={"nonce": uid(), "reason": "合成成员明确要求第二次核查"}
        )
        calls = self.provider(first, monkeypatch)
        runs = []
        for case in (first, second):
            response = self.launch(case)
            assert response.status_code == 202, response.text
            engine.handle_lane("review", self.message(case, response.json()))
            result = case["w"]["client"].get(case["path"] + "/" + response.json()["id"])
            assert (
                result.status_code == 200 and result.json()["operation"]["state"] == "succeeded"
            ), result.text
            runs.append(result.json())
        assert len(calls) == 2
        inv = (
            first["w"]["client"]
            .get(first["w"]["requirement_base"] + "/" + first["scope"][3])
            .json()
        )
        w = first["w"] | {
            "submission_scope": first["scope"][:3],
            "selection": {
                "package_id": first["scope"][1],
                "revision_id": first["scope"][2],
                "package_digest": first["w"]["own"]["digest"],
                "inventory": {"id": inv["manifest"]["id"], "digest": inv["digest"]},
                "coverage": None,
                "review_run": {
                    "id": runs[1]["id"],
                    "input_digest": runs[1]["input_digest"],
                    "result_digest": runs[1]["result"]["digest"],
                },
            },
            "attachment": {
                "document_version_id": first["w"]["member"].document_version_id,
                "digest": first["w"]["member"].file_digest,
                "byte_size": len(b"synthetic-original-v1"),
            },
        }
        from packages.domain import bid_package_repository

        # Establish canonical original ancestry before the actual submission
        # binding is frozen. Late publication cannot repair an old association.
        with connection() as c:
            for revision_id in (first["scope"][2], inv["manifest"]["authority_revision_id"]):
                selected = bid_package_repository.load_revision(c, w["scope"].bid_id, revision_id)
                for member in selected.members:
                    ensure_parse_sources(
                        c,
                        UUID(w["scope"].bid_id),
                        UUID(member.parse.parse_run_id),
                        publish_readable=True,
                    )
        w = setup(w, with_authority=False)
        published_sources(w)
        verify(w)
        return w, runs, second

    def test_full_comparison_has_native_equivalent_and_separate_explicit_handoff(
        self, completed_pair
    ):
        w, runs, _ = completed_pair
        base, preview, body = prepare(w, chosen(w, runs=runs))
        comparison = preview.json()["manifest"]["comparison"]["manifest"]
        with connection() as c:
            native = c.execute(
                "SELECT design.package_retrospective_comparison(%s,%s,%s) AS value",
                (w["scope"].bid_id, runs[0]["id"], runs[1]["id"]),
            ).fetchone()["value"]
        assert native == comparison
        h = headers(w, etag=preview.headers["etag"])
        saved = w["client"].post(base, json=body, headers=h)
        assert saved.status_code == 201, saved.text
        path, candidate, candidate_body, candidate_headers = handoff(w, base, saved)
        target = Path("/tmp/tender-review-retrospective/browser-fixtures")
        target.mkdir(parents=True, exist_ok=True)
        fixture = {
            "notice": "Explicit synthetic originals and synthetic model HTTP only; not real scoring evidence.",
            "bid_id": w["scope"].bid_id,
            "member_id": str(w["actor"]),
            "selection": body["selection"],
            "preview": preview.json(),
            "preview_etag": preview.headers["etag"],
            "request": body,
            "saved": saved.json(),
            "saved_etag": saved.headers["etag"],
            "save_key": h["Idempotency-Key"],
            "candidate": candidate.json(),
            "candidate_request": candidate_body,
            "candidate_key": candidate_headers["Idempotency-Key"],
            "detail": w["client"]
            .get(base + "/" + saved.json()["retrospective"]["manifest"]["id"])
            .json(),
            "choices": {
                kind: w["client"]
                .get(
                    base + "/choices",
                    params={
                        "kind": kind,
                        **(
                            {"submission_id": w["submission"]["id"]}
                            if kind != "submissions"
                            else {}
                        ),
                    },
                )
                .json()
                for kind in ("submissions", "outcomes", "business_results", "runs")
            },
        }
        (target / "package-retrospective-http.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
        )

    @pytest.mark.parametrize(
        "field",
        ["counts", "transition", "method_changed", "missing_side", "summary", "closed_keys"],
    )
    def test_sql_rejects_rehashed_comparison_forgery(self, completed_pair, monkeypatch, field):
        w, runs, _ = completed_pair
        original = observations.observe

        def forged(c, bid, body):
            value = original(c, bid, body)
            comp = value["manifest"]["comparison"]
            m = comp["manifest"]
            if field == "counts":
                m["counts"]["verdict_changed"] += 1
            elif field == "transition":
                m["items"][0]["verdict_transition"] = {
                    "from": "violated",
                    "to": "satisfied",
                    "changed": True,
                }
            elif field == "method_changed":
                m["input_changes"]["method"] = not m["input_changes"]["method"]
            elif field == "missing_side":
                m["items"][0]["left"] = None
                m["items"][0]["definition_change"] = "added"
                m["items"][0]["machine_row_changed"] = None
                m["items"][0]["verdict_transition"] = None
            elif field == "summary":
                m["left"]["method_digest"] = "d" * 64
            else:
                m["hidden_interpretation"] = "Synthetic forged conclusion"
            comp["digest"] = sha(m)
            value["digest"] = sha(value["manifest"])
            return value

        monkeypatch.setattr(observations, "observe", forged)
        monkeypatch.setattr(
            policy,
            "packet",
            lambda manifest, name: {"manifest": deepcopy(manifest), "digest": sha(manifest)},
        )
        selected = chosen(w, runs=runs)
        # The adversary bypasses application schema validation; native DB must refuse.
        base = f"/api/v1/bids/{w['scope'].bid_id}/package-retrospectives"
        with connection() as c:
            preview = forged(c, w["scope"].bid_id, selected)
        body = {
            "selection": selected,
            "preview_digest": preview["digest"],
            "title": "合成篡改不应冻结",
            "notes": {
                "observations": "合成观察",
                "hypotheses": "",
                "next_actions": "继续核对",
                "additional_missing_materials": "",
            },
        }
        response = w["client"].post(
            base,
            json=body,
            headers=headers(w, etag=repository.preview_tag(w["scope"].bid_id, preview["digest"])),
        )
        assert (
            response.status_code == 409
            and response.json()["code"] == "PACKAGE_RETROSPECTIVE_STORAGE_REJECTED"
        ), response.text

    def test_human_head_change_invalidates_preview_without_claiming_risk_resolution(
        self, completed_pair
    ):
        w, runs, second = completed_pair
        base, preview, body = prepare(w, chosen(w, runs=runs))
        row = runs[1]["result"]["manifest"]["matrix"][0]
        path = (
            second["path"]
            + "/"
            + runs[1]["id"]
            + "/requirements/"
            + row["requirement_id"]
            + "/human-decisions"
        )
        response = w["client"].post(
            path,
            json={
                "result_digest": runs[1]["result"]["digest"],
                "row_digest": sha(row),
                "expected_head": None,
                "state": "rejected",
                "reason": "合成人工拒绝原判断；尚未复检",
                "selected_quotes": row["target_quotes"] + row["authority_quotes"],
            },
            headers=headers(w),
        )
        assert response.status_code == 201, response.text
        refused = w["client"].post(
            base, json=body, headers=headers(w, etag=preview.headers["etag"])
        )
        assert refused.status_code == 412, refused.text
        _, saved, _, _ = freeze(w, chosen(w, runs=runs))
        m = saved.json()["retrospective"]["manifest"]["preview"]["manifest"]
        assert m["risk_resolution_assessed"] is False
        assert m["comparison"]["manifest"]["items"][0]["right_human"]["state"] == "rejected"
