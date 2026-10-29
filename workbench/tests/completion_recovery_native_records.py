"""Actual nonowner F11/F08 records for the disposable current-schema recovery drill.

All originals are explicit synthetic fixtures. No worker or model is started.
The helper uses production services/HTTP, without inventing durable task fields.
"""

from uuid import UUID, uuid4

from test_stable_lot_identity import headers
from test_task_package_triggers_pg import automatic, material_event

from packages.domain import bid_package_dependency_plans as plans
from packages.domain import bid_package_input_dependencies as dependencies
from packages.domain.bid_package_original_verification import read_input
from packages.domain.bid_package_review_eligibility import inspect
from packages.domain.runtime import connection
from packages.retrospectives import repository as retrospectives
from packages.tasks import package_triggers, templates


def response_body(response, status):
    assert response.status_code == status, response.text
    return response.json()


def persist(w, inventory, submission):
    """Freeze real records before the exported snapshot; do not run any pending work."""
    bid = w["scope"].bid_id
    scope = (
        bid,
        w["own"]["manifest"]["package_id"],
        w["own"]["manifest"]["revision_id"],
        inventory["manifest"]["id"],
    )
    base = w["requirement_base"] + "/" + scope[3]
    selection = {
        "package_digest": inventory["manifest"]["package_digest"],
        "inventory_digest": inventory["digest"],
        "coverage_attempt_id": None,
        "coverage_digest": None,
    }
    preview = response_body(
        w["client"].post(base + "/review-input-preview", json=selection, headers=headers(w)), 200
    )
    selection["input_digest"] = preview["digest"]
    captured = read_input(*scope, selection)
    frozen = response_body(
        w["client"].post(
            base + "/frozen-review-inputs",
            json=selection | {"context_digest": captured.execution_context["semantic_digest"]},
            headers=headers(w),
        ),
        201,
    )
    eligibility = inspect(scope, frozen["manifest"]["id"], frozen["digest"])
    prepared = response_body(
        w["client"].post(
            base + "/frozen-review-inputs/" + frozen["manifest"]["id"] + "/execution-inputs",
            json={
                "frozen_digest": frozen["digest"],
                "context_digest": eligibility["current_context"]["semantic_digest"],
                "rerun": None,
            },
            headers=headers(w),
        ),
        201,
    )
    dependency = {
        "execution_input_digest": prepared["digest"],
        "purpose": "prebid_compliance",
        "fact_ids": [],
        "dependencies": [
            {
                "requirement_id": row["rule_id"],
                "requirement_digest": row["requirement_digest"],
                "state": "not_needed",
                "fact_ids": [],
                "evidence_ids": row["rule_snapshot"]["evidence_ids"],
                "reason": "Synthetic recovery input only checks its quoted text, without external facts.",
            }
            for row in inventory["manifest"]["requirements"]
        ],
    }
    args = (scope, frozen["manifest"]["id"], prepared["manifest"]["id"])
    assessed = dependencies.check(*args, dependency)
    saved_plan, replay = plans.save(
        str(w["actor"]),
        *args,
        str(uuid4()),
        dependency
        | {"assessment_digest": assessed["digest"], "reason": "Explicit synthetic recovery plan"},
    )
    assert not replay and saved_plan["status"] == 201
    case = {
        "w": w,
        "scope": scope,
        "frozen": frozen,
        "prepared": prepared,
        "plan": saved_plan["body"],
    }
    template = response_body(automatic(case), 201)

    # The material producer helper persists a named synthetic event under the API
    # login; the coordinator, cancel API and SQL guards make the durable records.
    _, accepted = material_event(case)
    assert len(accepted) == 1 and accepted[0]["state"] == "pending"
    intent_base = f"/api/v1/bids/{bid}/task-package-trigger-intents/"
    initial = w["client"].get(intent_base + accepted[0]["intent_id"])
    assert response_body(initial, 200)["state"] == "pending"
    cancelled = response_body(
        w["client"].post(
            intent_base + accepted[0]["intent_id"] + "/cancel",
            json={"reason": "Cancel this exact synthetic trigger before the recovery snapshot"},
            headers=headers(w, etag=initial.headers["etag"]),
        ),
        200,
    )
    assert cancelled["state"] == "cancelled" and cancelled["run_id"] is None
    _, accepted = material_event(case)
    assert len(accepted) == 1 and accepted[0]["state"] == "pending"
    pending = response_body(w["client"].get(intent_base + accepted[0]["intent_id"]), 200)
    assert pending["state"] == "pending" and pending["run_id"] is None

    retro_base = f"/api/v1/bids/{bid}/package-retrospectives"
    selected = {
        "submission_id": submission["id"],
        "outcome_id": None,
        "outcome_missing_reason": "Synthetic recovery has no official outcome original",
        "business_result_id": None,
        "business_result_missing_reason": "Synthetic recovery has no award notice",
        "baseline_run_id": None,
        "submitted_run_id": None,
        "reviews_missing_reason": "No completed comparison run was performed in this recovery drill",
    }
    preview = w["client"].post(retro_base + "/preview", json=selected, headers=headers(w))
    preview_body = response_body(preview, 200)
    saved = response_body(
        w["client"].post(
            retro_base,
            json={
                "selection": selected,
                "preview_digest": preview_body["digest"],
                "title": "Synthetic native recovery retrospective",
                "notes": {
                    "observations": "Only the original declared package submission is available.",
                    "hypotheses": "No conclusion is asserted from missing official evidence.",
                    "next_actions": "Obtain actual evidence and review explicitly.",
                    "additional_missing_materials": "Official result and completed paired reviews.",
                },
            },
            headers=headers(w, etag=preview.headers["etag"]),
        ),
        201,
    )["retrospective"]
    assert saved["manifest"]["state"] == "pending_review"
    assert saved["manifest"]["preview"]["manifest"]["outcome"] is None
    with connection() as c:
        assert (
            c.execute("SELECT current_user AS name").fetchone()["name"]
            == "fusion_package_requirements_service"
        )
        assert c.execute("SELECT count(*) AS n FROM design.model_calls").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM design.task_runs").fetchone()["n"] == 0
    return {
        "bid_id": bid,
        "template": template,
        "intents": [cancelled, pending],
        "retrospective": saved,
    }


def assert_restored(c, expected):
    """Read restored historical records through the same domain validators."""
    c.execute("SET LOCAL search_path=design,public")
    bid = expected["bid_id"]
    assert templates.view(c, UUID(bid), UUID(expected["template"]["id"])) == expected["template"]
    for intent in expected["intents"]:
        row = package_triggers.load(c, UUID(bid), UUID(intent["id"]))
        assert package_triggers.view(row) == intent
    saved = expected["retrospective"]
    assert retrospectives.load(c, bid, saved["manifest"]["id"]) == saved
    assert retrospectives.link(c, saved["manifest"]["id"]) is None
    return {
        "exact_template_response_identical": True,
        "exact_trigger_pending_and_cancelled_views_identical": True,
        "retrospective_immutable_view_identical": True,
        "retrospective_state": saved["manifest"]["state"],
        "knowledge_link_created": False,
        "task_runs_created": 0,
        "model_calls": 0,
    }
