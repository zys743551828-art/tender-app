"""Native additive context fixture helpers; synthetic contents, real persistence."""

import io
from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from PIL import Image
from test_authoring_rich_integration import register
from work_context_fixtures import context_app
from work_context_fixtures import openapi as base_openapi

from apps.api.work_context_catalog_routes import router
from apps.worker import engine
from packages.authoring import rich_images
from packages.authoring.build_repository import DEFAULT_TEMPLATE_ID, freeze_build
from packages.authoring.content import schema_digest_for
from packages.authoring.repository import latest_sections, save_draft
from packages.contracts import work_context_catalog_api as contract
from packages.domain.runtime import Command, connection, enqueue_plan, etag, sha


def catalog_app():
    app = context_app()
    app.include_router(router)
    return app


def openapi(app):
    result = base_openapi(app)
    contract.extend_openapi(result)
    return result


@contextmanager
def client_for(original):
    with TestClient(catalog_app()) as client:
        client.cookies.update(original.cookies)
        yield client


def path(bid, kind, identity=None):
    result = f"/api/v1/bids/{bid}/work-contexts/{kind}"
    return result + "/" + str(identity) if identity is not None else result


def current(env):
    with connection() as c:
        revision = c.execute(
            "SELECT revision FROM design.drafts WHERE bid_id=%s AND id=%s",
            (env["bid"], env["draft"]),
        ).fetchone()["revision"]
        section = latest_sections(c, env["bid"], env["draft"])[0]
    return revision, section


def save(env, *, text=None, content=None):
    revision, section = current(env)
    content = deepcopy(content or section["content"])
    if text is not None:
        content["content"][0]["content"] = [{"type": "text", "text": text}]
    with connection() as c:
        return save_draft(
            c,
            env["bid"],
            env["draft"],
            env["actor"],
            {
                "base_draft_revision": revision,
                "changes": [
                    {
                        "section_id": str(section["section_id"]),
                        "base_section_revision": section["revision"],
                        "schema_digest": schema_digest_for(content),
                        "content": content,
                    }
                ],
            },
            etag("draft", env["draft"], revision),
        )


def image_asset(env):
    # Distinct pixels prevent fixture-only global blob deduplication collisions.
    stream = io.BytesIO()
    with Image.frombytes("RGB", (4, 4), uuid4().bytes * 3) as image:
        image.save(stream, format="PNG")
    raw = stream.getvalue()
    normalized = rich_images.normalize(raw, "image/png")

    def descriptor(data, name):
        return {
            "digest": sha(data),
            "byte_size": len(data),
            "object_key": f"authoring-images/{env['bid']}/{uuid4()}/{name}",
            "media_type": "image/png",
        }

    value, _, _, _ = register(
        env
        | {
            "original": descriptor(raw, "original"),
            "normalized": descriptor(normalized["bytes"], "normalized"),
            "proof": normalized["proof"],
        }
    )
    return value


def queue_build(env, formats=("docx",)):
    revision, _ = current(env)
    body = {
        "draft_id": str(env["draft"]),
        "draft_revision": revision,
        "template_version_id": str(DEFAULT_TEMPLATE_ID),
        "formats": list(formats),
        "follow_up": "none",
    }
    with connection() as c:
        cmd = Command(c, env["actor"], "synthetic-context-build", env["bid"], uuid4().hex, body)
        input_id, manifest = freeze_build(c, env["bid"], body, env["actor"], None)
        operation = enqueue_plan(
            c,
            env["bid"],
            cmd.id,
            "build",
            {"id": str(input_id), "manifest": manifest},
            stages=[{"key": "build-document", "depends_on": []}],
            handler_version="export/1",
            topic="tender.task.export.v1",
        )
        identity = uuid4()
        c.execute(
            "INSERT INTO builds(id,bid_id,input_id,operation_id) VALUES(%s,%s,%s,%s)",
            (identity, env["bid"], input_id, UUID(operation["id"])),
        )
        message = c.execute(
            "SELECT payload FROM outbox WHERE operation_id=%s AND topic='tender.task.export.v1'",
            (UUID(operation["id"]),),
        ).fetchone()["payload"]
        cmd.finish({"build_id": str(identity)})
    return identity, message


def complete_build(message):
    lease = engine.acquire(message)
    assert lease is not None
    computed = engine.run_compute(message, lease)
    assert engine.finish(message, lease, computed)
    return computed
