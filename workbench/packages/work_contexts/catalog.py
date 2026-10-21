"""Bounded native record directory; a sorted first item is never a selection."""

from packages.contracts import work_context_catalog_api as contract
from packages.domain.review_identity import digest
from packages.domain.runtime import clean
from packages.work_contexts import authoring_repository, cursors, policy, repository

MAX_RECORDS = 1000


def validated(name, value):
    policy.check(contract.valid(name, value), "只读工作上下文目录不能通过封闭协议核验")
    return value


def filters(c, bid, kind, *, draft_id=None, package_id=None, revision_id=None):
    selected = {"draft_id": draft_id, "package_id": package_id, "revision_id": revision_id}
    authoring = kind in {"draft_snapshot", "build"}
    if (authoring and (package_id or revision_id)) or (not authoring and draft_id):
        policy.fail("REQUEST_INVALID", "目录筛选不属于明确选择的阶段", 422)
    if not c.execute("SELECT id FROM design.bids WHERE id=%s", (bid,)).fetchone():
        policy.fail("NOT_FOUND", "该项目不存在", 404)
    if (
        draft_id
        and not c.execute(
            "SELECT id FROM design.drafts WHERE bid_id=%s AND id=%s", (bid, draft_id)
        ).fetchone()
    ):
        policy.fail("NOT_FOUND", "所选草稿不属于当前项目", 404)
    if (
        package_id
        and not c.execute(
            "SELECT id FROM design.bid_packages WHERE bid_id=%s AND id=%s AND kind='bid'",
            (bid, package_id),
        ).fetchone()
    ):
        policy.fail("NOT_FOUND", "所选投标包不属于当前项目", 404)
    if (
        revision_id
        and not c.execute(
            """SELECT r.id FROM design.bid_package_revisions r JOIN design.bid_packages p ON p.id=r.package_id
        WHERE p.bid_id=%s AND p.kind='bid' AND r.id=%s AND (%s::uuid IS NULL OR p.id=%s)""",
            (bid, revision_id, package_id, package_id),
        ).fetchone()
    ):
        policy.fail("NOT_FOUND", "所选包修订不属于当前项目或所选包", 404)
    return selected


def _rows(c, bid, kind, f):
    args: tuple = ()
    if kind == "draft_snapshot":
        statement = """SELECT s.id::text,s.created_at,s.draft_id::text,s.revision,s.digest,
        s.manifest->>'title' AS title FROM design.draft_snapshots s
        WHERE s.bid_id=%s AND (%s::uuid IS NULL OR s.draft_id=%s)
        ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
        args = (bid, f["draft_id"], f["draft_id"], MAX_RECORDS + 1)
    elif kind == "build":
        statement = """SELECT b.id::text,o.created_at,o.state,b.input_id::text,o.input_digest,
        s.id::text AS snapshot_id,s.draft_id::text,s.revision,s.digest AS snapshot_digest,
        s.manifest->>'title' AS title,
        (SELECT coalesce(jsonb_agg(jsonb_build_object('format',x.format,'state',x.state,
          'document_version_id',x.document_version_id,'gaps',x.gaps) ORDER BY x.format),'[]'::jsonb)
          FROM design.build_outputs x WHERE x.bid_id=b.bid_id AND x.build_id=b.id) AS outputs
        FROM design.builds b LEFT JOIN design.build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
        LEFT JOIN design.draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
        LEFT JOIN design.operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
        WHERE b.bid_id=%s AND (%s::uuid IS NULL OR s.draft_id=%s)
        ORDER BY o.created_at DESC,b.id DESC LIMIT %s"""
        args = (bid, f["draft_id"], f["draft_id"], MAX_RECORDS + 1)
    elif kind == "package_review_run":
        statement = """SELECT r.id::text,r.created_at,r.input_digest,r.execution_input_id::text,
        r.input_manifest#>>'{scope,package_id}' AS package_id,
        r.input_manifest#>>'{scope,revision_id}' AS revision_id,
        r.input_manifest#>>'{scope,inventory_id}' AS inventory_id,
        o.state,o.input_digest AS operation_input_digest,x.digest AS result_digest,
        p.revision,p.digest AS package_digest
        FROM design.bid_package_review_runs r
        LEFT JOIN design.operations o ON o.id=r.operation_id AND o.bid_id=r.bid_id
        LEFT JOIN design.bid_package_review_results x ON x.run_id=r.id AND x.bid_id=r.bid_id AND x.operation_id=r.operation_id
        LEFT JOIN design.bid_packages k ON k.id::text=r.input_manifest#>>'{scope,package_id}' AND k.bid_id=r.bid_id AND k.kind='bid'
        LEFT JOIN design.bid_package_revisions p ON p.id::text=r.input_manifest#>>'{scope,revision_id}' AND p.package_id=k.id
        WHERE r.bid_id=%s AND (%s::text IS NULL OR r.input_manifest#>>'{scope,package_id}'=%s)
        AND (%s::text IS NULL OR r.input_manifest#>>'{scope,revision_id}'=%s)
        ORDER BY r.created_at DESC,r.id DESC LIMIT %s"""
        args = (
            bid,
            f["package_id"],
            f["package_id"],
            f["revision_id"],
            f["revision_id"],
            MAX_RECORDS + 1,
        )
    else:
        statement = """SELECT s.id::text,s.created_at,s.kind AS state,s.submitted_at,s.supersedes_id::text,
        b.package_id::text,b.revision_id::text,b.digest AS binding_digest,p.revision,p.digest AS package_digest
        FROM design.submission_records s
        LEFT JOIN design.bid_package_submission_bindings b ON b.bid_id=s.bid_id AND b.submission_id=s.id
        LEFT JOIN design.bid_packages k ON k.id=b.package_id AND k.bid_id=s.bid_id AND k.kind='bid'
        LEFT JOIN design.bid_package_revisions p ON p.package_id=k.id AND p.id=b.revision_id
        WHERE s.bid_id=%s AND s.subject_kind='bid_package'
        AND (%s::uuid IS NULL OR b.package_id=%s) AND (%s::uuid IS NULL OR b.revision_id=%s)
        ORDER BY s.created_at DESC,s.id DESC LIMIT %s"""
        args = (
            bid,
            f["package_id"],
            f["package_id"],
            f["revision_id"],
            f["revision_id"],
            MAX_RECORDS + 1,
        )
    rows = clean(c.execute(statement, args).fetchall())
    if len(rows) > MAX_RECORDS:
        policy.fail(
            "CAPACITY_EXCEEDED", "完整阶段目录超过本次只读预算，请明确草稿或包范围后再读取", 413
        )
    policy.check(len({row["id"] for row in rows}) == len(rows))
    policy.check(all(row["created_at"] is not None and row["revision"] is not None for row in rows))
    return rows


def _choice(c, bid, kind, row):
    if kind == "draft_snapshot":
        loaded = authoring_repository.snapshot(c, bid, row["id"])
        selection = loaded["selection"]
        policy.check(selection["snapshot_digest"] == row["digest"])
        label, status = (
            f"{loaded['metadata']['title']} · 已保存修订 {selection['draft_revision']}",
            "saved",
        )
    elif kind == "build":
        loaded = authoring_repository.build(c, bid, row["id"])
        selection = loaded["selection"]
        policy.check(
            selection["input_digest"] == row["input_digest"]
            and loaded["details"]["operation_state"] == row["state"]
        )
        label, status = (
            f"{loaded['snapshot']['metadata']['title']} · 构建 · 草稿修订 {selection['draft_revision']}",
            row["state"],
        )
    elif kind == "package_review_run":
        loaded = repository.exact_run(c, bid, row["id"])
        selection = policy.run_selection(loaded["run"], loaded["selected"])
        policy.check(
            selection["input_digest"] == row["input_digest"]
            and selection["result_digest"] == row["result_digest"]
        )
        label, status = f"整包核查 · 包修订 {row['revision']}", row["state"]
    else:
        loaded = repository.exact_submission(c, bid, row["id"])
        record, manifest, selected = loaded["record"], loaded["manifest"], loaded["selected"]
        selection = {
            **policy.package_target(selected["target"]),
            "kind": "package_submission",
            "submission_id": row["id"],
            "package_binding_digest": record["package_binding"]["digest"],
            "inventory": manifest["selection_request"]["inventory"],
            "review_run": policy.run_selection(manifest["review_run"], selected)
            if manifest["review_run"]
            else None,
        }
        policy.check(selection["package_binding_digest"] == row["binding_digest"])
        label, status = f"实交登记 · 包修订 {row['revision']}", row["state"]
    return validated(
        "WorkContextChoice",
        {
            "kind": kind,
            "id": row["id"],
            "label": label,
            "created_at": row["created_at"],
            "status": status,
            "selection": selection,
            "selection_digest": digest(selection),
        },
    )


def page(c, bid, kind, *, limit=20, cursor=None, draft_id=None, package_id=None, revision_id=None):
    f = filters(c, bid, kind, draft_id=draft_id, package_id=package_id, revision_id=revision_id)
    rows = _rows(c, bid, kind, f)
    scope = digest({"version": "work-context-choice/1", "bid_id": bid, "kind": kind, "filters": f})
    observation = digest({"scope": scope, "records": rows})
    after = cursors.decode(cursor, scope, observation)
    identities = [digest({"kind": kind, "id": row["id"]}) for row in rows]
    if after is not None and after not in identities:
        policy.fail("CURSOR_INVALID", "目录游标不属于本次完整阶段观察", 422)
    offset = 0 if after is None else identities.index(after) + 1
    selected, more = rows[offset : offset + limit], offset + limit < len(rows)
    items = [_choice(c, bid, kind, row) for row in selected]
    return validated(
        "WorkContextChoicePage",
        {
            "version": "work-context-choice-page/1",
            "bid_id": bid,
            "kind": kind,
            "filters": f,
            "observed_at": repository.at(c),
            "observation_digest": observation,
            "items": items,
            "total": len(rows),
            "has_more": more,
            "next_cursor": cursors.encode(
                scope, observation, identities[offset + len(selected) - 1]
            )
            if more
            else None,
            "complete_observation": True,
            "directory_basis": "native_record_identity_and_state",
            "selection_requires_resolution": True,
            "qualification_assessed": False,
        },
    )
