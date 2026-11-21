"""Exact native plan-to-candidate with synthetic documents/mocked provider only."""
# ruff: noqa: F401,F811

import json
from copy import deepcopy
from uuid import UUID

import pytest
from authoring_package_input_fixtures import ADMIN_DSN, save, world
from authoring_package_job_fixtures import case, current, finish, input_database, launch, queued
from authoring_package_job_fixtures import database as job_database
from test_authoring_exact_builds_pg import adopted, database
from test_authoring_exact_revisions_pg import confirm, published
from test_authoring_exact_revisions_pg import database as revision_database
from test_stable_lot_identity import api, headers
from test_technical_bid_generation_journey_pg import (
    blank_target,
    build_structured_word,
    counts,
    current_layout,
    requirements,
)
from test_technical_bid_generation_journey_pg import exact as outline_only

from packages.authoring import saved_chapter_plans
from packages.domain.runtime import ROOT, clean, connection
from packages.knowledge.sources import lock_graph
from packages.rag.indexing import parse_source_id

pytestmark = pytest.mark.skipif(not ADMIN_DSN, reason="requires explicitly isolated authoring PG17")
PRIVATE_GOAL = "本章人工排程暂定每三天校验一次｜不发送给模型"
PRIVATE_NOT_FACT = "未核实日期二〇三九年九月十六日｜不发送给模型"
PRIVATE_SIBLING = "质量章内部人工计划｜不发送给模型"


@pytest.fixture(scope="module")
def planned_schema(job_database):
    owner = job_database["owner"]
    owner.execute((ROOT / saved_chapter_plans.DDL).read_text())
    with connection() as c:
        assert saved_chapter_plans.installed(c)
    return job_database


def draft_path(w):
    return f"/api/v1/bids/{w['bid']}/drafts/{w['input_body']['target_section']['draft_id']}"


def save_plan(w, chapter, *, goal, ref, base_plan_revision=0, rule=True):
    client = w["client"]
    path = draft_path(w)
    base = client.get(path)
    assert base.status_code == 200, base.text
    written = client.put(
        f"{path}/sections/{chapter['section_id']}/plan",
        json={
            "base_draft_revision": base.json()["revision"],
            "base_plan_revision": base_plan_revision,
            "state": "drafting",
            "goal": goal,
            "key_points": ["只供内部编写人"],
            "pending_facts": [PRIVATE_NOT_FACT],
            "rule_ids": [w["rule"]] if rule else [],
            "source_refs": [ref],
            "planned_pages": 3,
            "budget_basis": "manual",
            "budget_rule_id": None,
            "budget_note": "人工预算仅供自查",
        },
        headers=headers(w, etag=base.headers["etag"]),
    )
    assert written.status_code == 200, written.text
    return written.json()


def authority_ref(w, evidence):
    with connection() as c:
        row = c.execute(
            """SELECT e.parse_id,p.document_version_id
               FROM design.evidence_blocks e JOIN design.parse_runs p
                 ON p.id=e.parse_id AND p.bid_id=e.bid_id
               WHERE e.bid_id=%s AND e.id=%s""",
            (w["bid"], evidence),
        ).fetchone()
        source = parse_source_id(row["parse_id"])
        head = c.execute(
            "SELECT revision FROM retrieval.source_heads WHERE source_id=%s", (source,)
        ).fetchone()
    return clean(
        {
            "evidence_id": evidence,
            "document_version_id": row["document_version_id"],
            "source_id": source,
            "source_revision": head["revision"],
        }
    )


def reselect(w, saved):
    chapter = w["technical_journey"]["chapter"]
    observed = w["client"].get(
        f"/api/v1/bids/{w['bid']}/work-contexts/draft_snapshot/{saved['snapshot_id']}"
    )
    assert observed.status_code == 200, observed.text
    assert chapter in observed.json()["document"]["sections"]
    return blank_target(
        w,
        dict(saved, snapshot_digest=observed.json()["selection"]["snapshot_digest"]),
        chapter,
    )


@pytest.fixture
def exact(requirements, planned_schema):
    owner = planned_schema["owner"]
    bid = requirements["scope"].bid_id
    # The inventory fixture fixes the package and rule identities; ordinary
    # manual plan citations also require the authority file in the current
    # material snapshot, not just in a package membership.
    with owner.transaction():
        material = owner.execute(
            "SELECT material_id FROM design.rule_sets WHERE bid_id=%s AND id=%s",
            (bid, requirements["inventory_body"]["rule_set_id"]),
        ).fetchone()["material_id"]
        owner.execute(
            """INSERT INTO design.material_assignments(snapshot_id,bid_id,document_version_id,role,ordinal)
               SELECT %s,e.bid_id,p.document_version_id,'tender',0
               FROM design.evidence_blocks e JOIN design.parse_runs p
               ON p.id=e.parse_id AND p.bid_id=e.bid_id WHERE e.bid_id=%s AND e.id=%s""",
            (material, bid, requirements["evidence"]),
        )
        owner.execute(
            "UPDATE design.bid_profiles SET current_material_id=%s WHERE bid_id=%s",
            (material, bid),
        )
    w = outline_only.__wrapped__(requirements)
    native = w["technical_journey"]
    [rule] = [
        row for row in w["inventory"]["manifest"]["requirements"] if row["rule_id"] == w["rule"]
    ]
    ref = authority_ref(w, rule["rule_snapshot"]["evidence_ids"][0])
    first = save_plan(w, native["chapter"], goal=PRIVATE_GOAL, ref=ref)
    second = save_plan(w, native["quality"], goal=PRIVATE_SIBLING, ref=ref)
    assert second["draft_revision"] == first["draft_revision"] + 1
    w["input_body"]["target_section"] = reselect(w, second)
    w["planned"] = {
        "ref": ref,
        "target": first["plan"],
        "sibling": second["plan"],
        "snapshot_id": second["snapshot_id"],
    }
    return w


def test_saved_plans_keep_identity_and_authority_but_not_free_text_in_provider(adopted):
    w = adopted
    assert len(w["calls"]) == 1
    request = w["calls"][0]
    body = json.dumps(request, ensure_ascii=False)
    for private in (PRIVATE_GOAL, PRIVATE_NOT_FACT, PRIVATE_SIBLING, "人工预算仅供自查"):
        assert private not in body
    [user_payload] = [m["content"] for m in request["messages"] if m["role"] == "user"]
    prompt = json.loads(user_payload)["complete_fixed_package_plan"]
    assert "authoring_structure" not in prompt["context"]["target"]["snapshot_manifest"]
    assert "authoring_structure" not in prompt["context"]["target"]["snapshot"]
    assert prompt["saved_chapter_plan_links"] == {
        "requirement_ids": [w["rule"]],
        "authority_evidence_ids": [w["planned"]["ref"]["evidence_id"]],
    }
    assert prompt["execution_policy"]["saved_plan_method"] == saved_chapter_plans.EXECUTION_METHOD
    assert prompt["context"]["method"]["saved_plan_method"] == saved_chapter_plans.INPUT_METHOD
    assert not prompt["formal_scoring_input"]

    structure = w["client"].get(draft_path(w) + "/structure")
    assert structure.status_code == 200, structure.text
    nodes = {item["section_id"]: item for item in structure.json()["nodes"]}
    target = nodes[w["planned"]["target"]["section_id"]]
    sibling = nodes[w["planned"]["sibling"]["section_id"]]
    assert target["plan"] == w["planned"]["target"]
    assert target["plan_content_basis_state"] == "section_changed"
    assert sibling["plan"] == w["planned"]["sibling"]
    assert sibling["plan_content_basis_state"] == "current"
    assert (
        current_layout(w, draft_path(w), sibling["section_id"])["state"]
        == "structured_layout_rechecked"
    )
    observed = current_layout(w, draft_path(w), target["section_id"])
    assert observed["unsupported_reasons"] == ["saved_chapter_plans"]
    assert observed["plan_state"] == "target_stale" and observed["section_plan_revision"] == 1

    _, _, xml = build_structured_word(w, gate_state="structure_not_supported")
    assert w["raw"]["replacement_text"] in xml
    assert PRIVATE_GOAL not in xml and PRIVATE_NOT_FACT not in xml and PRIVATE_SIBLING not in xml


def test_editing_the_plan_requires_fresh_exact_input_and_no_task(case):
    w = case
    written = save_plan(
        w,
        w["technical_journey"]["chapter"],
        goal="合成新计划，不替换原模板",
        ref=w["planned"]["ref"],
        base_plan_revision=1,
    )
    assert written["plan"]["revision"] == 2
    assert written["snapshot_id"] != w["planned"]["snapshot_id"]
    before = counts()
    denied = launch(w)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    assert not w["calls"] and counts() == before


def test_plan_reference_cannot_use_own_bid_body_as_frozen_authority(exact):
    w = exact
    old = deepcopy(w["input_body"])
    ref = authority_ref(w, str(w["body_evidence"]))
    assert ref["document_version_id"] != w["planned"]["ref"]["document_version_id"]
    written = save_plan(
        w,
        w["technical_journey"]["chapter"],
        goal="合成外范围原页仍保留在人工计划",
        ref=ref,
        base_plan_revision=1,
        rule=False,
    )
    old["target_section"] = reselect(w, written)
    before = counts()
    result = save(w, body=old)
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "AUTHORING_SAVED_PLAN_SOURCE_OUTSIDE_SELECTION"
    assert counts() == before


def test_source_withdrawal_before_dispatch_spends_no_model_call(queued):
    w = queued
    with connection() as c:
        lock_graph(c)
        updated = c.execute(
            """UPDATE retrieval.source_heads SET status='withdrawn',revision=revision+1
               WHERE source_id=%s RETURNING revision""",
            (UUID(w["planned"]["ref"]["source_id"]),),
        ).fetchone()
        assert updated["revision"] == w["planned"]["ref"]["source_revision"] + 1
    finish(w)
    result = current(w)
    assert result["state"] in {"failed", "superseded"}, result
    assert not w["calls"]


def test_project_material_assignment_changes_without_source_head_drift(queued):
    from packages.domain.bid_package_service import lock_bid

    w = queued
    with connection() as c:
        lock_bid(c, w["bid"])
        before = c.execute(
            "SELECT revision,status FROM retrieval.source_heads WHERE source_id=%s",
            (w["planned"]["ref"]["source_id"],),
        ).fetchone()
        changed = c.execute(
            "UPDATE design.bid_profiles SET current_material_id=NULL WHERE bid_id=%s RETURNING bid_id",
            (w["bid"],),
        ).fetchone()
        assert str(changed["bid_id"]) == w["bid"]
        assert before == {"revision": w["planned"]["ref"]["source_revision"], "status": "published"}
    finish(w)
    result = current(w)
    assert result["state"] == "failed", result
    assert result["error_code"] == "AUTHORING_PACKAGE_SAVED_PLAN_SOURCE_CHANGED", result
    assert not w["calls"]


def test_plan_edit_after_publication_cannot_adopt_the_old_candidate(published):
    w = published
    saved = save_plan(
        w,
        w["technical_journey"]["chapter"],
        goal="合成新计划，仅人工维护",
        ref=w["planned"]["ref"],
        base_plan_revision=1,
    )
    assert saved["plan"]["revision"] == 2 and len(w["calls"]) == 1
    before = counts()
    denied = confirm(w)
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "AUTHORING_PACKAGE_DRAFT_CHANGED"
    action = w["client"].get(w["action_ref"])
    assert action.status_code == 200, action.text
    assert action.json()["state"] == "pending"
    with connection() as c:
        assert not c.execute(
            "SELECT 1 FROM design.action_consumptions WHERE action_id=%s", (w["action_id"],)
        ).fetchone()
    assert counts() == before and len(w["calls"]) == 1
