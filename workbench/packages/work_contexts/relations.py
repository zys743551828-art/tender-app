"""Native generated-file relations. Receipt adoption and membership stay distinct."""

from packages.authoring import build_views, package_adoption_contracts, package_outputs
from packages.authoring.repository import source_authority_manifest
from packages.domain.review_identity import digest, utc
from packages.domain.runtime import DomainError, clean, etag, sha
from packages.work_contexts import cursors, observations, policy, repository

MAX_RECORDS = 1000
KIND = "adopt-authoring-output"


def _bounded(rows):
    if len(rows) > MAX_RECORDS:
        policy.fail(
            "CAPACITY_EXCEEDED", "完整关联目录超过本次只读预算，未返回被截断的空目录或摘要", 413
        )
    return rows


def build(c, bid, build_id):
    row = c.execute(
        """SELECT b.*,i.draft_snapshot_id,i.manifest,s.draft_id,
        s.revision AS draft_revision,s.digest AS snapshot_digest,
        o.input_digest,o.kind AS operation_kind,o.state AS operation_state,
        o.handler_version AS operation_handler
        FROM design.builds b JOIN design.build_inputs i ON i.id=b.input_id AND i.bid_id=b.bid_id
        JOIN design.draft_snapshots s ON s.id=i.draft_snapshot_id AND s.bid_id=b.bid_id
        JOIN design.operations o ON o.id=b.operation_id AND o.bid_id=b.bid_id
        WHERE b.bid_id=%s AND b.id=%s""",
        (bid, build_id),
    ).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目下没有明确选择的构建", 404)
    identity = build_views.identity(row)
    policy.check(
        identity["bid_id"] == bid
        and row["input_digest"] == sha({"id": str(row["input_id"]), "manifest": row["manifest"]})
    )
    seed = {key: value for key, value in identity.items() if key not in {"protocol", "request"}}
    seed["build_id"] = build_id
    policy.validated("WorkContextBuildIdentity", seed)
    raw_outputs = c.execute(
        "SELECT format,state,document_version_id FROM design.build_outputs WHERE bid_id=%s AND build_id=%s ORDER BY format",
        (bid, build_id),
    ).fetchall()
    policy.check(len({row["format"] for row in raw_outputs}) == len(raw_outputs))
    policy.check(
        len({str(row["document_version_id"]) for row in raw_outputs if row["document_version_id"]})
        == sum(row["document_version_id"] is not None for row in raw_outputs)
    )
    proofs = {}
    for output in raw_outputs:
        if output["state"] != "succeeded":
            policy.check(output["document_version_id"] is None)
            continue
        document = str(output["document_version_id"])
        # capture is SELECT-only. Source authority may differ from an adoption's
        # historical digest; this is a current observation, not lost history.
        packet = package_outputs.capture(c, bid, build_id, document)
        proofs[document] = packet["proof"]
    return seed, proofs, {"state": row["operation_state"], "outputs": clean(raw_outputs)}


def _source_observation(c, proof, at, baseline=None):
    sources = source_authority_manifest(
        c, [{"source_id": identity} for identity in proof["direct_source_ids"]]
    )
    current_digest = digest(sources)
    if not proof["direct_source_ids"]:
        return policy.dimension(
            "not_applicable", "NO_SOURCE_REFERENCES_DECLARED", baseline, current_digest
        )
    if baseline is None:
        return policy.dimension("unknown", "NO_ADOPTION_SOURCE_BASELINE", None, current_digest)
    effective = policy.effective_sources(sources, at)
    return policy.dimension(
        "matched" if baseline == current_digest and effective else "changed",
        "EXACT_SOURCE_BASIS_MATCH"
        if baseline == current_digest and effective
        else "SOURCE_BASIS_CHANGED_OR_INEFFECTIVE",
        baseline,
        current_digest,
    )


def _item(kind, output, package, proof, current, source, *, command=None, at=None):
    target = policy.package_target(package)
    exposed_output = {key: output[key] for key in ("document_version_id", "format", "sha256")}
    identity = {
        "kind": kind,
        "output": exposed_output,
        "package_revision": target,
        "adoption_command_id": command,
    }
    return {
        "id": digest(identity),
        **identity,
        "package_revision_number": package["manifest"]["revision"],
        "proof_digest": digest(proof),
        "adopted_at": at,
        "current_package_head": current,
        "current_source_basis": source,
        "qualification_assessed": False,
    }


def _adoption(c, bid, build_id, row, proofs, at):
    row = clean(row)
    saved = row["response"]
    policy.check(
        isinstance(saved, dict)
        and set(saved) == {"body", "status", "headers"}
        and saved["status"] == 201
    )
    value = saved["body"]
    try:
        package_adoption_contracts.validate("AuthoringOutputAdopted", value)
    except DomainError as error:
        raise DomainError("WORK_CONTEXT_CORRUPT", "生成采用回执不符合原生封闭协议", 500) from error
    output, target = value["output"], value["package"]["manifest"]
    policy.check(
        row["command_kind"] == KIND
        and row["target_id"] == build_id
        and value["bid_id"] == output["bid_id"] == bid
        and value["build_id"] == output["build_id"] == build_id
        and value["actor_id"] == row["actor_id"]
        and value["command_id"] == row["id"]
        and value["request_digest"] == row["request_digest"]
        and saved["headers"] == {"ETag": value["package_etag"]}
        and value["package_etag"]
        == etag("bid-package-head", target["package_id"], value["package"]["digest"])
    )
    current_output = proofs.get(output["document_version_id"])
    policy.check(current_output is not None)
    policy.check(
        {key: item for key, item in output.items() if key != "source_authority_digest"}
        == {key: item for key, item in current_output.items() if key != "source_authority_digest"},
        "采用回执与本次构建、输出、快照或发布凭据不一致",
    )
    package = repository.selected_package(c, bid, target["package_id"], target["revision_id"])
    policy.check(package == value["package"] and target["kind"] == "bid")
    audits = c.execute(
        """SELECT actor_id,bid_id,event_type,payload,created_at FROM design.audit_entries
        WHERE command_id=%s AND event_type IN ('authoring.output_adopted','authoring.output_qualified')
        ORDER BY event_type,id LIMIT 3""",
        (row["id"],),
    ).fetchall()
    policy.check(len(audits) == 2)
    by_event = {item["event_type"]: clean(item) for item in audits}
    policy.check(set(by_event) == {"authoring.output_adopted", "authoring.output_qualified"})
    adopted, qualified = (
        by_event[key] for key in ("authoring.output_adopted", "authoring.output_qualified")
    )
    policy.check(
        all(
            item["actor_id"] == row["actor_id"] and item["bid_id"] == bid
            for item in by_event.values()
        )
    )
    policy.check(qualified["payload"] == {"proof": output, "proof_digest": sha(output)})
    audit = adopted["payload"]
    policy.check(
        set(audit)
        == {
            "build_id",
            "document_version_id",
            "package_id",
            "package_revision_id",
            "package_digest",
            "reason",
        }
        and audit["build_id"] == build_id
        and audit["document_version_id"] == output["document_version_id"]
        and audit["package_id"] == target["package_id"]
        and audit["package_revision_id"] == target["revision_id"]
        and audit["package_digest"] == package["digest"]
    )
    member = target["members"][-1]
    policy.check(
        member["document_version_id"] == output["document_version_id"]
        and member["file_digest"] == output["sha256"]
    )
    original_member = {
        key: member[key] for key in ("member_id", "document_version_id", "purposes", "parts")
    }
    if member["parse"]["status"] == "frozen":
        original_member["parse_run_id"] = member["parse"]["parse_run_id"]
    # Reconstruct the exact adopted request from the native appended member and
    # audit reason. A copied response with a foreign command digest is rejected.
    request = {
        "bid_id": bid,
        "snapshot_id": output["build_identity"]["snapshot_id"],
        "snapshot_digest": output["build_identity"]["snapshot_digest"],
        "package_id": target["package_id"] if target["predecessor_digest"] else None,
        "member": original_member,
        "reason": audit["reason"],
    }
    condition = (
        etag("bid-package-head", target["package_id"], target["predecessor_digest"])
        if target["predecessor_digest"]
        else None
    )
    policy.check(sha({"body": request, "if_match": condition}) == row["request_digest"])
    if target["predecessor_digest"]:
        previous = c.execute(
            "SELECT id::text FROM design.bid_package_revisions WHERE package_id=%s AND digest=%s",
            (target["package_id"], target["predecessor_digest"]),
        ).fetchone()
        policy.check(previous is not None)
        prior = repository.selected_package(c, bid, target["package_id"], previous["id"])[
            "manifest"
        ]
        fields = ("member_id", "document_version_id", "file_digest", "purposes", "parts", "parse")
        policy.check(
            [{key: item[key] for key in fields} for item in prior["members"]]
            == [{key: item[key] for key in fields} for item in target["members"][:-1]]
        )
    else:
        policy.check(len(target["members"]) == 1)
    return _item(
        "adopted_into",
        output,
        package,
        {"receipt": saved, "adoption": audit, "qualification": qualified["payload"]},
        observations.package_head(c, package),
        _source_observation(c, current_output, at, output["source_authority_digest"]),
        command=row["id"],
        at=utc(adopted["created_at"]),
    )


def _memberships(c, bid, proofs, at):
    rows = _bounded(
        c.execute(
            """SELECT m.revision_id::text,m.member_id,m.document_version_id::text,m.file_digest,m.payload,
        r.package_id::text FROM design.bid_package_members m
        JOIN design.bid_package_revisions r ON r.id=m.revision_id
        JOIN design.bid_packages p ON p.id=r.package_id AND p.bid_id=m.bid_id
        WHERE m.bid_id=%s AND p.kind='bid' AND m.document_version_id=ANY(%s::uuid[])
        ORDER BY m.revision_id,m.document_version_id LIMIT %s""",
            (bid, list(proofs), MAX_RECORDS + 1),
        ).fetchall()
    )
    result, seen = [], set()
    for row in rows:
        key = (row["revision_id"], row["document_version_id"])
        policy.check(key not in seen)
        seen.add(key)
        package = repository.selected_package(c, bid, row["package_id"], row["revision_id"])
        members = [
            item
            for item in package["manifest"]["members"]
            if item["document_version_id"] == row["document_version_id"]
        ]
        output = proofs[row["document_version_id"]]
        policy.check(
            len(members) == 1
            and members[0] == row["payload"]
            and members[0]["member_id"] == row["member_id"]
            and members[0]["file_digest"] == row["file_digest"] == output["sha256"]
        )
        result.append(
            _item(
                "contains_output",
                output,
                package,
                {
                    "package_digest": package["digest"],
                    "member": members[0],
                    "build_output": {
                        key: value
                        for key, value in output.items()
                        if key != "source_authority_digest"
                    },
                },
                observations.package_head(c, package),
                _source_observation(c, output, at),
            )
        )
    return result


def page(c, bid, build_id, *, limit=20, cursor=None):
    seed, proofs, state = build(c, bid, build_id)
    at = repository.at(c)
    commands = _bounded(
        c.execute(
            """SELECT id,actor_id,command_kind,target_id,request_digest,response,created_at
        FROM design.commands WHERE command_kind=%s AND target_id=%s ORDER BY id LIMIT %s""",
            (KIND, build_id, MAX_RECORDS + 1),
        ).fetchall()
    )
    items = [_adoption(c, bid, build_id, row, proofs, at) for row in commands]
    items.extend(_memberships(c, bid, proofs, at))
    policy.check(len({item["id"] for item in items}) == len(items))
    items.sort(key=lambda item: item["id"])
    observation = digest({"seed": seed, "state": state, "proofs": proofs, "items": items})
    scope = digest(
        {
            "version": "work-context-build-relations/1",
            "bid_id": bid,
            "build_id": build_id,
            "target": "package_revision",
        }
    )
    after = cursors.decode(cursor, scope, observation)
    if after is not None and after not in {item["id"] for item in items}:
        policy.fail("CURSOR_INVALID", "游标不属于本次完整关联观察", 422)
    remaining = [item for item in items if after is None or item["id"] > after]
    selected, more = remaining[:limit], len(remaining) > limit
    return policy.validated(
        "WorkContextRelationPage",
        {
            "version": "package-work-context-relations/1",
            "seed": seed,
            "target": "package_revision",
            "observed_at": at,
            "observation_digest": observation,
            "items": selected,
            "total": len(items),
            "has_more": more,
            "next_cursor": cursors.encode(scope, observation, selected[-1]["id"]) if more else None,
            "complete_observation": True,
            "original_bytes_reverified": False,
            "qualification_assessed": False,
        },
    )
