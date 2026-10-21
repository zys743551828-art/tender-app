"""B2 native queue fixtures: real PG/S3, synthetic business records/model HTTP."""
# ruff: noqa: F811

import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from authoring_package_input_fixtures import database as input_database  # noqa: F401
from authoring_package_input_fixtures import saved
from jsonschema import Draft202012Validator, FormatChecker
from test_stable_lot_identity import headers

from apps.api.views import bid_etag
from packages.assistant import jobs
from packages.domain.providers.deepseek import DeepSeekClient
from packages.domain.runtime import ROOT, assert_role, connection, now, sha
from packages.tasks.models import RunView

EXTENSIONS = (
    "packages/assistant/sql/assistant.sql",
    "packages/assistant/sql/live-facts.sql",
    "packages/assistant/sql/intent-budget.sql",
    "packages/contracts/sql/authoring-package-jobs.sql",
)


@pytest.fixture(scope="module")
def database(input_database):
    from packages.authoring.package_job_authority import available

    value = input_database
    with connection() as c:
        assert not available(c)
    for path in EXTENSIONS:
        value["owner"].execute((ROOT / path).read_text())
    value["owner"].execute(
        """INSERT INTO design.assistant_price_versions(id,version,provider,model,currency,
        input_per_million_minor,output_per_million_minor,input_hard_ceiling,output_hard_ceiling,
        source_kind,source_uri,source_sha256,verified_at,valid_from,valid_until)
        VALUES(%s,%s,'deepseek','deepseek-flash','USD',1000000,1000000,2097152,8192,
        'explicit_mock_fixture','https://synthetic.invalid/authoring-package-tariff',%s,now(),now()-interval '1 hour',now()+interval '4 hours')""",
        (
            uuid4(),
            "package-authoring-mock-" + uuid4().hex,
            sha(b"synthetic offline tariff, never production payment authority"),
        ),
    )
    return value


@pytest.fixture
def case(exact, monkeypatch):
    value = exact
    assert_role()
    assert_role(True)
    fixed = saved(value)
    value["fixed"] = fixed
    with connection() as c:
        context = json.loads(
            c.execute(
                "SELECT context_text FROM design.authoring_package_inputs WHERE id=%s",
                (fixed["manifest"]["id"],),
            ).fetchone()["context_text"]
        )
        condition = bid_etag(c, UUID(value["bid"]))
    stamp = now()
    for scope, owner in (
        ("global", "assistant"),
        ("member", value["actor"]),
        ("project", context["facts"]["canonical_project_key"]),
    ):
        value["database"]["owner"].execute(
            "INSERT INTO design.assistant_budget_versions(id,scope,owner_key,currency,revision,limit_minor,window_from,window_until,configured_reason) "
            "VALUES(%s,%s,%s,'USD',%s,1000000000000,%s,%s,'explicit synthetic B2 acceptance only')",
            (
                uuid4(),
                scope,
                owner,
                int(stamp.timestamp() * 1000000),
                stamp - timedelta(hours=1),
                stamp + timedelta(hours=4),
            ),
        )
    response = value["client"].post(
        f"/api/v1/bids/{value['bid']}/task-definitions",
        json={
            "name": "合成固定整包章节建议",
            "task_kind": "chapter_suggestion",
            "instructions": "按完整固定输入提出有明确来源的文字建议，待人工审阅",
            "section_id": value["input_body"]["target_section"]["section_id"],
            "source_selection": {
                "mode": "exact_package_authoring",
                "input": {
                    "authoring_input_id": fixed["manifest"]["id"],
                    "authoring_input_digest": fixed["digest"],
                },
            },
        },
        headers=headers(value, etag=condition),
    )
    assert response.status_code == 201, response.text
    value.update(
        template=response.json(),
        template_response=response,
        calls=[],
        mode="success",
        after_http=None,
    )
    value["raw"] = {
        "node_id": value["input_body"]["target_section"]["node_id"],
        "before_digest": value["input_body"]["target_section"]["before_node_digest"],
        "replacement_text": "来自合成完整整包的可审阅修改建议；尚未采用。",
        "evidence_ids": [context["documents"][0]["blocks"][0]["id"]],
    }

    def transport(request):
        value["calls"].append(json.loads(request.content))
        if value["mode"] == "timeout":
            raise httpx.ReadTimeout("explicit offline unknown fee", request=request)
        if value["after_http"]:
            value["after_http"]()
        data = (
            value["raw"] if value["mode"] == "success" else {"invalid": "synthetic malformed reply"}
        )
        return httpx.Response(
            200,
            json={
                "id": "mock-fixed-package-" + uuid4().hex,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(data, ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
            },
        )

    provider = DeepSeekClient(
        api_key="explicit-offline-fixture-only", transport=httpx.MockTransport(transport)
    )
    monkeypatch.setattr(DeepSeekClient, "from_env", classmethod(lambda cls: provider))

    def forbidden(*args, **kwargs):
        raise AssertionError("B2 fixture attempted actual provider network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    return value


def launch(case, *, key=None, rerun=False):
    return case["client"].post(
        f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}/runs",
        json={"rerun": rerun},
        headers=headers(case, key=key, etag=case["template_response"].headers["etag"]),
    )


@pytest.fixture
def queued(case):
    case["key"] = uuid4().hex
    response = launch(case, key=case["key"])
    assert response.status_code == 202, response.text
    bind_task(case, response.json())
    assert not case["calls"]
    return case


def bind_task(case, task):
    case["task"] = task
    case["job_id"] = UUID(case["task"]["frozen_manifest"]["assistant_job_id"])
    with connection() as c:
        native = jobs.job(c, case["job_id"])
        case["message"] = c.execute(
            "SELECT payload FROM design.outbox WHERE operation_id=%s AND topic='tender.task.assistant.v1'",
            (native["operation_id"],),
        ).fetchone()["payload"]


def finish(case, *, publish=True):
    from apps.worker import engine
    from packages.assistant import coordinator

    engine.handle(case["message"])
    engine.handle(case["message"])
    if publish:
        coordinator.tick([case["job_id"]])
    return current(case)


def change_template(case, **patch):
    from copy import deepcopy

    config = deepcopy(case["template"]["configuration"])
    config.update(patch)
    path = f"/api/v1/bids/{case['bid']}/task-definitions/{case['template']['id']}"
    response = case["client"].put(
        path, json=config, headers=headers(case, etag=case["template_response"].headers["etag"])
    )
    assert response.status_code == 200, response.text
    case.update(template=response.json(), template_response=response)
    return response


def cancel(case):
    path = "/api/v1/operations/" + case["task"]["root_operation_id"]
    view = case["client"].get(path)
    assert view.status_code == 200, view.text
    response = case["client"].post(
        path + "/cancel",
        json={"reason": "合成验收：明确停止原固定整包任务", "cancel_pending_same_input": False},
        headers=headers(case, etag=view.headers["etag"]),
    )
    assert response.status_code == 200, response.text
    return response


def no_action(case):
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.proposed_actions WHERE bid_id=%s", (case["bid"],)
            ).fetchone()["n"]
            == 0
        )


def no_job(case):
    with connection() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM design.assistant_jobs WHERE bid_id=%s", (case["bid"],)
            ).fetchone()["n"]
            == 0
        )


def legacy_queue(case, *, instruction=None):
    """Actual unchanged legacy native producer, under a real explicit command."""
    from packages.domain.runtime import Command

    selected = case["input_body"]["target_section"]
    body = {
        "section_id": selected["section_id"],
        "base_section_revision": selected["base_section_revision"],
        "instruction": instruction or case["template"]["configuration"]["instructions"],
        "source_version_ids": [str(case["member"].document_version_id)],
        "max_tokens": 2048,
    }
    with connection() as c:
        command = Command(
            c, UUID(case["actor"]), "authoring-generation", UUID(case["bid"]), uuid4().hex, body
        )
        value = jobs.queue_generation(
            c, UUID(case["bid"]), UUID(case["actor"]), body, command.id, explicit_send=True
        )
        command.finish(value, 202)
        return value


def current(case):
    response = case["client"].get(f"/api/v1/bids/{case['bid']}/task-runs/{case['task']['id']}")
    assert response.status_code == 200, response.text
    RunView.model_validate(response.json())
    return response.json()


def validate_wire(case):
    """Validate actual native HTTP responses against the mounted app contract."""
    from apps.api.export_openapi import implemented_openapi
    from apps.api.main import app

    actual = implemented_openapi(app)
    task = current(case)
    job = case["client"].get(task["result"]["job_ref"])
    assert job.status_code == 200, job.text
    values = [("RunView", task), ("AssistantJob", job.json())]
    if task["result"]["action_ref"]:
        action = case["client"].get(task["result"]["action_ref"])
        assert action.status_code == 200, action.text
        values.append(("AssistantAction", action.json()))
    for name, value in values:
        Draft202012Validator(
            {"components": actual["components"], "$ref": "#/components/schemas/" + name},
            format_checker=FormatChecker(),
        ).validate(value)


def export(case, label):
    """Only explicit synthetic API responses, never cookies/DSNs/provider secrets."""
    directory = os.environ.get("FUSION_AUTHORING_JOB_FIXTURE_DIR")
    if not directory:
        return
    task = current(case)
    bid = case["bid"]
    definition = task["frozen_manifest"]["definition_id"]
    input_id = task["frozen_manifest"]["context"]["input"]["authoring_input_id"]
    base = f"/api/v1/bids/{bid}"

    def read(path):
        response = case["client"].get(path)
        assert response.status_code == 200, response.text
        return response

    template = read(f"{base}/task-definitions/{definition}")
    operation = read("/api/v1/operations/" + task["root_operation_id"])
    input_path = base + "/authoring/package-inputs/" + input_id
    action_ref = (task.get("result") or {}).get("action_ref")
    value = {
        "fixture_kind": "synthetic business inputs and MockTransport; actual PG17/S3/API responses",
        "member_id": case["actor"],
        "bid": read(base).json(),
        "bid_etag": read(base).headers.get("etag"),
        "input_request": case["input_body"],
        "input": read(input_path).json(),
        "input_page": read(base + "/authoring/package-inputs").json(),
        "context": read(input_path + "/context").json(),
        "kinds": read("/api/v1/task-kinds").json(),
        "template": template.json(),
        "template_etag": template.headers.get("etag"),
        "template_version": read(
            f"{base}/task-definitions/{definition}/versions/{task['definition_version_id']}"
        ).json(),
        "run": task,
        "accepted_run": case["task"],
        "job": read(task["result"]["job_ref"]).json(),
        "operation": operation.json(),
        "operation_etag": operation.headers.get("etag"),
        "proposal": read(action_ref).json() if action_ref else None,
        "proposal_etag": read(action_ref).headers.get("etag") if action_ref else None,
        "notifications": read(base + "/task-notifications").json(),
        "task_draft": read(base + "/task-definition-drafts/" + case["private_draft_id"]).json()
        if case.get("private_draft_id")
        else None,
        "task_draft_flow": case.get("task_draft_flow"),
    }
    target = Path(directory) / (label + ".json")
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
