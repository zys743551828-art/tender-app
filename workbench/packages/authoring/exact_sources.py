"""Revision-bound exact provenance. A JSON mode never grants source authority."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from packages.authoring.exact_revision_contracts import (
    AuthoringExactRevisionView,
    AuthoringExactSnapshotExtension,
)
from packages.domain.runtime import DomainError, clean, fetch, sha, uid


@dataclass(frozen=True, slots=True)
class ExactAdoption:
    """Server-side identity, revalidated at the shared save boundary.

    Merely constructing this value grants nothing: the actual published action,
    pending card, command and frozen source authority are checked on every use.
    """

    action_id: UUID
    command_id: UUID
    actor_id: UUID
    condition: str
    before_action: dict = field(repr=False)
    section_revision_id: UUID = field(default_factory=uid)
    qualification_id: UUID = field(default_factory=uid)


def check_adoption(c, admission, bid, draft, actor, body):
    from packages.assistant import actions
    from packages.authoring import package_generation, package_proposals
    from packages.authoring.package_job_authority import assert_job

    if not isinstance(admission, ExactAdoption):
        raise DomainError("AUTHORING_EXACT_ADMISSION_INVALID", "采用准入必须来自实际候选", 409)
    require_apply(c)
    actual, job, before = package_proposals._pending(c, admission.action_id, admission.condition)
    assert_job(c, job["id"])
    plan = package_generation.checked(job["input_manifest"], live_policy=True)
    target = plan["target"]
    content = package_generation.materialize(plan, actual["payload"]["candidate"])["after"]
    expected = {
        "base_draft_revision": target["base_draft_revision"],
        "changes": [
            {
                "section_id": target["section_id"],
                "base_section_revision": target["base_section_revision"],
                "schema_digest": target["schema_digest"],
                "content": content,
            }
        ],
    }
    command = fetch(c, "SELECT * FROM design.commands WHERE id=%s", (admission.command_id,))
    if (
        str(actual["bid_id"]) != str(bid)
        or target["draft_id"] != str(draft)
        or str(admission.actor_id) != str(actor)
        or before != admission.before_action
        or admission.condition != actions.tag(before)
        or body != expected
        or command["actor_id"] != admission.actor_id
        or command["command_kind"] != package_proposals.KIND
        or command["target_id"] != admission.action_id
        or command["response"] is not None
        or command["request_digest"]
        != sha({"body": {"decision": "confirm"}, "if_match": admission.condition})
    ):
        raise DomainError(
            "AUTHORING_EXACT_ADMISSION_INVALID", "采用准入与实际命令、目标或内容不符", 409
        )
    return actual, job


def append_adoption(c, admission, bid, draft, section, revision, content, actor, schema_digest):
    """Recheck all authority immediately before the shared section INSERT."""
    if not isinstance(admission, ExactAdoption):
        raise DomainError("AUTHORING_EXACT_ADMISSION_INVALID", "缺少实际采用准入", 409)
    return check_adoption(
        c,
        admission,
        bid,
        draft,
        actor,
        {
            "base_draft_revision": admission.before_action["base_revision"],
            "changes": [
                {
                    "section_id": str(section),
                    "base_section_revision": revision - 1,
                    "schema_digest": schema_digest,
                    "content": content,
                }
            ],
        },
    )


def bind_adoption(c, admission, actual, job, content, schema_digest):
    from packages.authoring.package_proposals import policy

    target = job["input_manifest"]["plan"]["target"]
    method = policy()
    manifest = clean(
        {
            "protocol": "authoring-exact-revision/1",
            "id": admission.qualification_id,
            "bid_id": actual["bid_id"],
            "draft_id": target["draft_id"],
            "draft_revision": target["base_draft_revision"] + 1,
            "section_id": target["section_id"],
            "section_revision_id": admission.section_revision_id,
            "section_revision": target["base_section_revision"] + 1,
            "section_digest": sha(content),
            "schema_digest": schema_digest,
            "parent_section_revision_id": target["section_revision_id"],
            "parent_section_revision": target["base_section_revision"],
            "parent_section_digest": target["section_digest"],
            "input": job["input_manifest"]["plan"]["input"],
            "origin": {
                "kind": "model_candidate_adoption",
                "job_id": job["id"],
                "job_input_digest": job["input_digest"],
                "action_id": actual["id"],
                "action_digest": actual["request_digest"],
                "candidate_digest": actual["candidate_digest"],
                "command_id": admission.command_id,
                "actor_id": admission.actor_id,
                "before_action_digest": sha(admission.before_action),
            },
            "source_scope": "exact_package_context",
            "source_refs_digest": sha(content["attrs"]["source_refs"]),
            "rule_ids_digest": sha(content["attrs"]["rule_ids"]),
            "method": method,
            "method_digest": sha(method),
            "candidate_adopted": True,
            "content_correctness_certified": False,
        }
    )
    value = insert(c, manifest, admission.before_action, admission.condition)
    record_citations(c, actual["bid_id"], admission.section_revision_id, content)
    return value


def available(c):
    """Structural installation only; Worker keeps its narrow snapshot-proof RPC."""
    return bool(
        c.execute(
            "SELECT to_regclass('design.authoring_exact_revisions') IS NOT NULL "
            "AND to_regprocedure('design.authoring_exact_check_revision(uuid)') IS NOT NULL "
            "AND to_regprocedure('design.authoring_exact_assert_revision(uuid)') IS NOT NULL "
            "AND to_regprocedure('design.authoring_exact_snapshot_proof(uuid)') IS NOT NULL AS ready"
        ).fetchone()["ready"]
    )


def apply_available(c):
    """Actual API adoption privileges, separate from historical and Worker reads."""
    if not available(c):
        return False
    tables = (
        ("design.authoring_exact_revisions", "SELECT"),
        ("design.authoring_exact_revisions", "INSERT"),
        ("design.authoring_package_inputs", "SELECT"),
        ("design.authoring_package_fact_scopes", "SELECT"),
        ("design.authoring_package_job_bindings", "SELECT"),
        ("design.authoring_package_action_bindings", "SELECT"),
    )
    functions = (
        "design.authoring_exact_check_revision(uuid)",
        "design.authoring_exact_assert_revision(uuid)",
        "design.authoring_exact_snapshot_proof(uuid)",
        "design.authoring_package_assert_job(uuid)",
    )
    return all(
        c.execute(
            "SELECT coalesce(has_table_privilege(current_user,to_regclass(%s),%s),false) AS ready",
            (name, privilege),
        ).fetchone()["ready"]
        for name, privilege in tables
    ) and all(
        c.execute(
            "SELECT coalesce(has_function_privilege(current_user,to_regprocedure(%s),'EXECUTE'),false) AS ready",
            (name,),
        ).fetchone()["ready"]
        for name in functions
    )


def require_apply(c):
    if not apply_available(c):
        raise DomainError(
            "AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED",
            "固定整包候选采用所需存储或 API 权限尚未完整配置，原草稿已保留",
            503,
        )


def require_schema(c):
    if not available(c):
        raise DomainError(
            "AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED",
            "固定整包候选采用资格尚未配置，原草稿已保留",
            409,
        )


@contextmanager
def errors():
    try:
        yield
    except psycopg.Error as error:
        code = error.diag.message_primary or ""
        if code.startswith(("AUTHORING_EXACT_", "AUTHORING_PACKAGE_", "ASSISTANT_")):
            raise DomainError(
                code, "原候选、修订资格或当前来源已变化，未保存部分正文", 409
            ) from None
        raise


def capabilities(c):
    from packages.authoring import exact_builds

    ready = apply_available(c)
    return {
        "protocol": "authoring-exact-revision-capabilities/1",
        "apply_available": ready,
        "build_available": available(c) and exact_builds.available(c),
        "ordinary_edit_available": False,
        "supported_content": "plain_text_stable_node",
        "blocking_reasons": [] if ready else ["AUTHORING_PACKAGE_APPLY_NOT_CONFIGURED"],
    }


def bound_action(c, action):
    """Dispatch from the protected relationship, never a client mode or payload flag."""
    if (
        c.execute(
            "SELECT to_regclass('design.authoring_package_action_bindings') AS id"
        ).fetchone()["id"]
        is None
    ):
        return False
    return bool(
        c.execute(
            "SELECT 1 FROM design.authoring_package_action_bindings WHERE action_id=%s", (action,)
        ).fetchone()
    )


def assert_ordinary_edit(c, bid, draft):
    if (
        c.execute(
            "SELECT to_regclass('design.authoring_exact_revisions') IS NOT NULL AS present"
        ).fetchone()["present"]
        and c.execute(
            "SELECT 1 FROM design.authoring_exact_revisions WHERE bid_id=%s AND draft_id=%s LIMIT 1",
            (bid, draft),
        ).fetchone()
    ):
        raise DomainError(
            "AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED",
            "本草稿含固定整包修订，当前操作尚未支持继承来源资格；原草稿与内容已保留",
            409,
        )


def load(c, bid, revision):
    require_schema(c)
    row = fetch(
        c,
        "SELECT q.* FROM design.authoring_exact_revisions q "
        "WHERE q.bid_id=%s AND q.section_revision_id=%s",
        (bid, revision),
    )
    value = {"manifest": row["manifest"], "digest": row["digest"]}
    AuthoringExactRevisionView.model_validate(value)
    m = row["manifest"]
    if (
        sha(m) != row["digest"]
        or m["id"] != str(row["id"])
        or m["bid_id"] != str(bid)
        or m["section_revision_id"] != str(revision)
        or m["origin"]["before_action_digest"] != sha(row["before_action"])
    ):
        raise DomainError("AUTHORING_EXACT_QUALIFICATION_CORRUPT", "修订来源资格摘要不一致", 409)
    with errors():
        c.execute("SELECT design.authoring_exact_check_revision(%s)", (revision,))
    return value


def assert_current(c, bid, revision):
    """Current authority requires an actual immutable revision binding, not a proof argument."""
    value = load(c, bid, revision)
    with errors(), c.transaction():
        c.execute("SELECT design.authoring_exact_assert_revision(%s)", (revision,))
    return value


def section_binding(row):
    m = row["manifest"]
    return {
        "section_id": m["section_id"],
        "section_revision_id": m["section_revision_id"],
        "section_revision": m["section_revision"],
        "section_digest": m["section_digest"],
        "qualification_id": m["id"],
        "qualification_digest": row["digest"],
        "authoring_input_id": m["input"]["id"],
        "authoring_input_digest": m["input"]["digest"],
        "source_scope": "exact_package_context",
    }


def prepare_snapshot(c, bid, draft, sections):
    if not available(c):
        assert_ordinary_edit(c, bid, draft)
        return None
    rows = c.execute(
        "SELECT * FROM design.authoring_exact_revisions WHERE bid_id=%s AND draft_id=%s "
        "AND section_revision_id=ANY(%s::uuid[])",
        (bid, draft, [s["id"] for s in sections]),
    ).fetchall()
    by_id = {r["section_revision_id"]: r for r in rows}
    if not rows:
        if c.execute(
            "SELECT 1 FROM design.authoring_exact_revisions WHERE bid_id=%s AND draft_id=%s LIMIT 1",
            (bid, draft),
        ).fetchone():
            raise DomainError(
                "AUTHORING_EXACT_QUALIFICATION_MISSING", "草稿不能剥离已有修订资格", 409
            )
        return None
    value = {
        "protocol": "authoring-exact-snapshot/1",
        "sections": [section_binding(by_id[s["id"]]) for s in sections if s["id"] in by_id],
    }
    result = value | {"digest": sha(value)}
    AuthoringExactSnapshotExtension.model_validate(result)
    return result


def snapshot(c, row, sections):
    """Historical read verifies actual selected revisions; it does not claim current use."""
    extension = row["manifest"].get("authoring_exact_sections")
    if not available(c):
        if extension is not None:
            require_schema(c)
        return None
    with errors():
        actual = c.execute(
            "SELECT design.authoring_exact_snapshot_proof(%s) AS value", (row["id"],)
        ).fetchone()["value"]
    if extension != actual:
        raise DomainError("AUTHORING_EXACT_SNAPSHOT_CORRUPT", "快照的实际修订来源资格不一致", 409)
    if extension is not None:
        AuthoringExactSnapshotExtension.model_validate(extension)
        if sha({k: v for k, v in extension.items() if k != "digest"}) != extension["digest"]:
            raise DomainError("AUTHORING_EXACT_SNAPSHOT_CORRUPT", "来源资格快照摘要不一致", 409)
        identities = {str(s["id"]): s for s in sections}
        for bound in extension["sections"]:
            section = identities.get(bound["section_revision_id"])
            if (
                section is None
                or str(section["section_id"]) != bound["section_id"]
                or section["revision"] != bound["section_revision"]
                or section["digest"] != bound["section_digest"]
            ):
                raise DomainError("AUTHORING_EXACT_SNAPSHOT_CORRUPT", "资格与快照所选章节不符", 409)
    return extension


def draft_status(c, bid, draft):
    from packages.authoring import exact_builds

    require_schema(c)
    row = fetch(
        c,
        "SELECT s.* FROM design.drafts d JOIN design.draft_snapshots s "
        "ON s.draft_id=d.id AND s.bid_id=d.bid_id AND s.revision=d.revision "
        "WHERE d.bid_id=%s AND d.id=%s",
        (bid, draft),
    )
    sections = c.execute(
        "SELECT r.* FROM design.draft_snapshot_sections ss JOIN design.section_revisions r "
        "ON r.id=ss.section_revision_id AND r.bid_id=ss.bid_id WHERE ss.snapshot_id=%s ORDER BY ss.ordinal",
        (row["id"],),
    ).fetchall()
    extension = snapshot(c, row, sections)
    build_ready = extension is None or exact_builds.available(c)
    return clean(
        {
            "protocol": "authoring-exact-draft-status/1",
            "bid_id": bid,
            "draft_id": draft,
            "draft_revision": row["revision"],
            "snapshot_id": row["id"],
            "snapshot_digest": row["digest"],
            "exact_sections": extension["sections"] if extension else [],
            "ordinary_edit_available": extension is None,
            "build_available": build_ready,
            "blocking_reasons": ["AUTHORING_EXACT_REVISION_OPERATION_UNSUPPORTED"]
            + ([] if build_ready else ["AUTHORING_EXACT_BUILD_NOT_CONFIGURED"])
            if extension
            else [],
        }
    )


def record_citations(c, bid, revision, content):
    for ref in content["attrs"]["source_refs"]:
        c.execute(
            "INSERT INTO retrieval.citations(id,bid_id,source_id,source_revision,purpose,evidence_id,target_object_id) "
            "VALUES(%s,%s,%s,%s,'authoring',%s,%s)",
            (
                uid(),
                bid,
                UUID(ref["source_id"]),
                ref["source_revision"],
                UUID(ref["evidence_id"]),
                revision,
            ),
        )


def insert(c, manifest, before_action, condition):
    value = {"manifest": clean(manifest), "digest": sha(manifest)}
    AuthoringExactRevisionView.model_validate(value)
    m = value["manifest"]
    c.execute(
        "INSERT INTO design.authoring_exact_revisions "
        "(id,bid_id,draft_id,section_id,section_revision_id,parent_revision_id,input_id,job_id,action_id,command_id,actor_id,draft_revision,manifest,digest,before_action,request_condition) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            m["id"],
            m["bid_id"],
            m["draft_id"],
            m["section_id"],
            m["section_revision_id"],
            m["parent_section_revision_id"],
            m["input"]["id"],
            m["origin"]["job_id"],
            m["origin"]["action_id"],
            m["origin"]["command_id"],
            m["origin"]["actor_id"],
            m["draft_revision"],
            Jsonb(m),
            value["digest"],
            Jsonb(before_action),
            condition,
        ),
    )
    return value
