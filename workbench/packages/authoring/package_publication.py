"""Exact package candidate publication and historical read-only proposal views."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from packages.authoring import package_generation
from packages.authoring.package_job_authority import assert_job
from packages.domain.runtime import DomainError, clean, fetch, sha, uid


def create(c, job, output):
    from packages.assistant import jobs

    assert_job(c, job["id"])
    package_generation.checked(job["input_manifest"], live_policy=True)
    if jobs.view(c, job["id"])["requires_billing_reconciliation"]:
        raise DomainError("MODEL_CALL_REQUIRES_RECONCILIATION", "原调用尚需核清，未发布建议", 409)
    candidate = package_generation.validate(
        job["input_manifest"], output["payload"], canonical=True
    )
    plan = job["input_manifest"]["plan"]
    identity = uid()
    payload = clean(
        {
            "kind": "package_authoring_patch",
            "job_id": job["id"],
            "input": plan["input"],
            "target": plan["target"],
            "candidate": candidate,
            "apply_available": False,
            "build_available": False,
        }
    )
    clock = fetch(c, "SELECT clock_timestamp() AS at")["at"]
    c.execute(
        "INSERT INTO design.proposed_actions(id,bid_id,base_revision,request_digest,expires_at,payload) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            identity,
            job["bid_id"],
            plan["target"]["base_draft_revision"],
            sha(payload),
            clock + timedelta(minutes=30),
            Jsonb(payload),
        ),
    )
    c.execute(
        "INSERT INTO design.authoring_package_action_bindings(action_id,job_id,bid_id,input_id,input_digest,candidate_digest,action_digest) VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (
            identity,
            job["id"],
            job["bid_id"],
            plan["input"]["id"],
            plan["input"]["digest"],
            output["digest"],
            sha(payload),
        ),
    )
    return {"action_id": str(identity), "apply_available": False, "build_available": False}


def inspect(c, action_id):
    row = fetch(
        c,
        "SELECT a.*,b.job_id,b.input_id,b.input_digest,b.candidate_digest,b.action_digest "
        "FROM design.proposed_actions a JOIN design.authoring_package_action_bindings b ON b.action_id=a.id AND b.bid_id=a.bid_id WHERE a.id=%s",
        (action_id,),
    )
    job = fetch(
        c,
        "SELECT * FROM design.assistant_jobs WHERE id=%s AND bid_id=%s",
        (row["job_id"], row["bid_id"]),
    )
    binding = fetch(
        c,
        "SELECT * FROM design.authoring_package_job_bindings WHERE job_id=%s AND input_id=%s AND bid_id=%s",
        (job["id"], row["input_id"], row["bid_id"]),
    )
    output = fetch(c, "SELECT * FROM design.assistant_outputs WHERE job_id=%s", (job["id"],))
    payload, plan = row["payload"], job["input_manifest"]["plan"]
    expected = clean(
        {
            "kind": "package_authoring_patch",
            "job_id": job["id"],
            "input": plan["input"],
            "target": plan["target"],
            "candidate": output["payload"],
            "apply_available": False,
            "build_available": False,
        }
    )
    if (
        job["input_digest"] != sha(job["input_manifest"])
        or job["input_digest"] != binding["job_input_digest"]
        or payload != expected
        or sha(payload) != row["request_digest"]
        or row["action_digest"] != row["request_digest"]
        or row["input_digest"] != binding["input_digest"]
        or row["input_digest"] != plan["input"]["digest"]
        or row["candidate_digest"] != output["digest"]
        or output["digest"] != sha(output["payload"])
        or row["base_revision"] != plan["target"]["base_draft_revision"]
        or not c.execute(
            "SELECT 1 FROM design.assistant_publications p JOIN design.assistant_action_links l ON l.action_id=p.action_id AND l.job_id=p.job_id WHERE p.job_id=%s AND p.state='published' AND p.action_id=%s AND l.tool='authoring.apply_patch'",
            (job["id"], action_id),
        ).fetchone()
    ):
        raise DomainError(
            "AUTHORING_PACKAGE_ACTION_BINDING_INVALID", "整包候选的实际发布绑定不一致", 409
        )
    package_generation.validate(job["input_manifest"], output["payload"], canonical=True)
    return row, job


def preview(c, action_id):
    row, job = inspect(c, action_id)
    payload = row["payload"]
    return package_generation.materialize(job["input_manifest"]["plan"], payload["candidate"]) | {
        "kind": "package_authoring_patch",
        "section_id": payload["target"]["section_id"],
        "base_section_revision": payload["target"]["base_section_revision"],
        "authoring_input_id": payload["input"]["id"],
        "authoring_input_digest": payload["input"]["digest"],
        "source_scope": "exact_package_context",
        "apply_available": False,
        "build_available": False,
        "effect": "固定整包候选已发布；采用资格与后续构建尚未接通，草稿保持原修订",
    }
