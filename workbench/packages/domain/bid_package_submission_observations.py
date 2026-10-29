"""Exact package selections and bounded whole-bid observations, without external IO."""

from copy import deepcopy
from typing import NoReturn

from psycopg import sql

from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_requirement_repository as inventories
from packages.domain import bid_package_review_decision_repository as opinions
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import finding_lifecycle, package_submission_gate
from packages.domain.bid_package_service import historical
from packages.domain.bid_package_service import view as package_view
from packages.domain.review_identity import canonical, utc
from packages.domain.rule_sets import current_decision
from packages.domain.runtime import DomainError, clean, fetch, sha
from packages.lifecycle.service import profile

MAX_HISTORY_BYTES = 24 * 1024 * 1024
MAX_LEGACY_FINDINGS = 5000
MAX_ORIGINALS = 2000


def failure(code, message, status=409) -> NoReturn:
    raise DomainError("PACKAGE_SUBMISSION_" + code, message, status)


def selected(c, scope, request):
    bid, package, revision = scope
    if (request["package_id"], request["revision_id"]) != (package, revision):
        failure("SCOPE_MISMATCH", "请求与明确选择的投标包修订不一致", 422)
    target = package_view(c, historical(c, *scope))
    if target["manifest"]["kind"] != "bid" or target["digest"] != request["package_digest"]:
        failure("SELECTION_CHANGED", "所选投标包身份或摘要不一致，请重新核对")
    if not target["manifest"]["members"]:
        failure("EMPTY_PACKAGE", "实际提交的投标包必须至少包含一份确切原件", 422)
    inventory = authority = coverage = None
    if request["inventory"] is not None:
        pointer = request["inventory"]
        inventory = inventories.load_inventory(c, bid, package, revision, pointer["id"])
        if inventory["digest"] != pointer["digest"]:
            failure("SELECTION_CHANGED", "所选要求清单摘要不一致")
        authority = package_view(
            c, packages.load_revision(c, bid, inventory["manifest"]["authority_revision_id"])
        )
    if request["coverage"] is not None:
        if inventory is None:
            failure("SELECTION_INVALID", "范围声明必须对应本次明确选择的要求清单", 422)
        pointer = request["coverage"]
        coverage = inventories.load_attempt(
            c, bid, package, revision, inventory["manifest"]["id"], pointer["id"]
        )
        if coverage["digest"] != pointer["digest"]:
            failure("SELECTION_CHANGED", "所选范围声明摘要不一致")
    run = None
    if request["review_run"] is not None:
        if inventory is None:
            failure("SELECTION_INVALID", "核查运行必须对应本次明确选择的要求清单", 422)
        pointer = request["review_run"]
        row = c.execute(
            runs.SELECT + " WHERE r.bid_id=%s AND r.id=%s", (bid, pointer["id"])
        ).fetchone()
        if row is None:
            failure("RUN_NOT_FOUND", "所选整包核查运行不存在", 404)
        run = runs.view(row)
        if (
            tuple(run["scope"][key] for key in runs.SCOPE_KEYS)
            != (*scope, inventory["manifest"]["id"])
            or run["input_digest"] != pointer["input_digest"]
            or (run["result"]["digest"] if run["result"] else None) != pointer["result_digest"]
        ):
            failure("SELECTION_CHANGED", "核查运行、结果或精确清单与本次选择不一致")
    return {
        "target": target,
        "authority": authority,
        "inventory": inventory,
        "coverage": coverage,
    }, run


def current(c, bid, selection):
    from packages.authoring.package_outputs import observe_admission

    chosen = [selection[role] for role in ("target", "authority") if selection[role] is not None]
    heads = c.execute(
        "SELECT package_id::text,revision_id::text FROM design.bid_package_heads WHERE package_id=ANY(%s::uuid[]) ORDER BY package_id",
        ([value["manifest"]["package_id"] for value in chosen],),
    ).fetchall()
    target = selection["target"]["manifest"]
    authority = selection["authority"]
    generated = []
    for role in ("target", "authority"):
        value = selection[role]
        if value is None:
            continue
        for member in value["manifest"]["members"]:
            admission = observe_admission(c, bid, member["document_version_id"])
            if admission is not None:
                generated.append(
                    {
                        "package_role": role,
                        "member_id": member["member_id"],
                        "document_version_id": member["document_version_id"],
                        "admission": admission,
                    }
                )
    return clean(
        {
            "current": fetch(
                c,
                "SELECT design.identity_snapshot_v2(%s) AS identity,p.current_rule_set_id,p.phase,p.archived_at FROM design.bid_profiles p WHERE p.bid_id=%s",
                (bid, bid),
            ),
            "lifecycle": profile(c, bid),
            "package_heads": {row["package_id"]: row["revision_id"] for row in heads},
            "inventory_head": inventories.head(c, target["revision_id"]),
            "sources": c.execute(
                "SELECT design.bid_requirement_source_snapshot(%s,%s) AS value",
                (
                    target["revision_id"],
                    authority["manifest"]["revision_id"] if authority else None,
                ),
            ).fetchone()["value"],
            "generated_outputs": generated,
        }
    )


def decisions(c, bid, inventory):
    if inventory is None:
        return []
    result = []
    for row in inventory["manifest"]["requirements"]:
        chosen = current_decision(c, bid, "rule", row["rule_id"])
        value = (
            c.execute(
                "SELECT to_jsonb(d) AS value FROM design.decisions d WHERE d.bid_id=%s AND d.id=%s",
                (bid, chosen["id"]),
            ).fetchone()["value"]
            if chosen
            else None
        )
        result.append(
            {"rule_id": row["rule_id"], "rule_digest": row["rule_digest"], "decision": value}
        )
    return result


def inventory_proof(c, selection, run):
    if run is None:
        return None
    from packages.domain import bid_package_execution_input_repository as prepared
    from packages.domain import bid_package_review_input_repository as frozen
    from packages.domain.bid_package_inventory_proof import _receipt
    from packages.domain.package_inventory_proof import assess

    scope = tuple(run["scope"][key] for key in runs.SCOPE_KEYS)
    original = frozen.load_input(c, scope, run["frozen_input_id"])
    packet = prepared.load_packet(c, scope, run["frozen_input_id"], run["execution_input_id"])
    original_selection = original.evidence()["selection"]
    if any(original_selection[key] != selection[key] for key in selection):
        failure("SELECTION_CHANGED", "核查冻结的包、清单或范围声明与实际选择不一致")
    try:
        return assess(
            original, packet, _receipt(c, scope, selection["inventory"]["manifest"])
        ).view()
    except (ValueError, KeyError, TypeError) as error:
        raise DomainError(
            "PACKAGE_SUBMISSION_PROOF_CORRUPT", "原始清单抽取凭据无法核验", 500
        ) from error


def _legacy(c, bid):
    # Manual dismissal remains a known risk. Only a verified recheck may remove it.
    rows = c.execute(
        """SELECT f.*,q.kind AS rule_kind FROM design.findings f
        LEFT JOIN design.rule_items q ON q.bid_id=f.bid_id AND q.id=f.rule_id
        JOIN design.review_runs r ON r.bid_id=f.bid_id AND r.id=f.review_id
        WHERE f.bid_id=%s AND (f.severity='critical' OR q.kind IN ('mandatory','disqualification'))
        ORDER BY r.created_at,(jsonb_array_length(f.searched_ranges)>0),f.id LIMIT %s""",
        (bid, MAX_LEGACY_FINDINGS + 1),
    ).fetchall()
    if len(rows) > MAX_LEGACY_FINDINGS:
        failure(
            "HISTORY_CAPACITY_EXCEEDED", "历史关键问题超过本次可完整核验的容量，未省略旧风险", 422
        )
    latest = {}
    for row in rows:
        root = finding_lifecycle.origin(c, row)
        latest[str(root["id"])] = row
    result = []
    for origin_id, row in sorted(latest.items()):
        state = finding_lifecycle.lifecycle(c, row)
        if state == "resolved_by_recheck":
            continue
        result.append(
            clean(
                {
                    **{
                        key: row[key]
                        for key in (
                            "id",
                            "bid_id",
                            "review_id",
                            "rule_id",
                            "rule_kind",
                            "severity",
                            "category",
                            "verdict",
                            "statement",
                        )
                    },
                    "origin_id": origin_id,
                    "lifecycle": state,
                }
            )
        )
    return result


def risk_history(c, bid, selected_run):
    limits = package_submission_gate.LIMITS
    # This first query is a small metadata projection. Known core risks sort first,
    # including risks belonging to a superseded package or inventory.
    metadata = c.execute(
        """SELECT r.id::text,
        (EXISTS(SELECT FROM jsonb_array_elements(coalesce(x.manifest->'matrix','[]')) q
          WHERE q->>'rule_kind' IN ('mandatory','disqualification')
            AND q->>'verdict' IN ('violated','not_found','unable_to_judge'))) AS has_risk,
        octet_length(r.input_manifest::text)+coalesce(octet_length(x.manifest::text),0)+4096 AS bytes,
        count(*) OVER() AS total_count
        FROM design.bid_package_review_runs r
        LEFT JOIN design.bid_package_review_results x ON x.run_id=r.id AND x.bid_id=r.bid_id
        WHERE r.bid_id=%s
        ORDER BY has_risk DESC,(r.id=%s::uuid) DESC,r.created_at DESC,r.id DESC LIMIT %s""",
        (bid, selected_run["id"] if selected_run else None, limits["history_runs"] + 1),
    ).fetchall()
    chosen, used, complete = [], 0, True
    for index, row in enumerate(metadata):
        if index >= limits["history_runs"] or used + row["bytes"] > MAX_HISTORY_BYTES:
            complete = False
            if row["has_risk"]:
                failure(
                    "HISTORY_CAPACITY_EXCEEDED",
                    "历史关键核查超过可完整冻结的容量，未隐藏旧风险",
                    422,
                )
            continue
        chosen.append(row["id"])
        used += row["bytes"]
    complete = complete and (not metadata or len(chosen) == metadata[0]["total_count"])
    records = (
        c.execute(
            runs.SELECT + " WHERE r.bid_id=%s AND r.id=ANY(%s::uuid[]) ORDER BY r.created_at,r.id",
            (bid, chosen),
        ).fetchall()
        if chosen
        else []
    )
    values = [runs.view(row) for row in records]
    by_id = {row["id"]: row for row in values}
    # Include the exact chosen run even when noncritical history was bounded.
    if selected_run is not None and selected_run["id"] not in by_id:
        if len(values) >= limits["history_runs"]:
            removable = next(
                (
                    row
                    for row in reversed(values)
                    if not any(
                        item["rule_kind"] in {"mandatory", "disqualification"}
                        and item["verdict"] in {"violated", "not_found", "unable_to_judge"}
                        for item in (row["result"]["manifest"]["matrix"] if row["result"] else [])
                    )
                ),
                None,
            )
            if removable is None:
                failure("HISTORY_CAPACITY_EXCEEDED", "当前运行与完整历史关键风险超过容量", 422)
            values.remove(removable)
        values.append(selected_run)
        by_id = {row["id"]: row for row in values}
        complete = False
    human_rows = (
        c.execute(
            opinions.HEAD_SELECT
            + " WHERE h.bid_id=%s AND h.run_id=ANY(%s::uuid[]) ORDER BY h.run_id,h.requirement_id LIMIT %s",
            (bid, list(by_id), limits["history_rows"] + 1),
        ).fetchall()
        if by_id
        else []
    )
    if len(human_rows) > limits["history_rows"]:
        failure("HISTORY_CAPACITY_EXCEEDED", "历史人工意见超过完整读取容量", 422)
    result = {
        "complete": complete,
        "package_runs": sorted(values, key=lambda row: row["id"]),
        "human_decisions": [
            opinions.head_view(row, by_id[str(row["run_id"])]) for row in human_rows
        ],
        "legacy_findings": _legacy(c, bid),
    }
    if len(canonical(result)) > MAX_HISTORY_BYTES:
        failure("HISTORY_CAPACITY_EXCEEDED", "完整历史风险及意见超过存储容量，未截断风险", 422)
    return result


def source_rows(c, versions):
    return c.execute(
        """SELECT coalesce(jsonb_agg(jsonb_build_object(
        'source_id',s.source_id,'ancestor_id',n.id,'document_version_id',n.document_version_id,
        'policy_class',n.policy_class,'known_at',n.known_at,'revision',h.revision,
        'status',h.status,'valid_from',h.valid_from,'valid_until',h.valid_until)
        ORDER BY s.source_id,n.id),'[]'::jsonb) AS value
        FROM retrieval.source_ancestors s JOIN retrieval.source_nodes n ON n.id=s.ancestor_id
        LEFT JOIN retrieval.source_heads h ON h.source_id=n.id
        WHERE s.source_id IN(SELECT id FROM retrieval.source_nodes WHERE document_version_id=ANY(%s::uuid[]))""",
        (list(versions),),
    ).fetchone()["value"]


def originals(c, bid, selection, evidence=None):
    roles: dict[str, set[str]] = {}
    expected: dict[str, str] = {}
    for role in ("target", "authority"):
        value = selection[role]
        if value is None:
            continue
        for member in value["manifest"]["members"]:
            identity = member["document_version_id"]
            roles.setdefault(identity, set()).add(role)
            if identity in expected and expected[identity] != member["file_digest"]:
                failure("ORIGINAL_CHANGED", "包成员对同一原件声明了不同摘要")
            expected[identity] = member["file_digest"]
    if evidence is not None:
        identity = evidence["document_version_id"]
        roles.setdefault(identity, set()).add("submission_attachment")
        if identity in expected and expected[identity] != evidence["digest"]:
            failure("EVIDENCE_CHANGED", "实际提交附件与所选包成员的原件摘要不一致")
        expected[identity] = evidence["digest"]
    sources = source_rows(c, roles)
    for row in sources:
        if row["document_version_id"] is not None:
            roles.setdefault(row["document_version_id"], set()).add("source_ancestor")
    if len(roles) > MAX_ORIGINALS:
        failure("ORIGINAL_CAPACITY_EXCEEDED", "包原件与祖先超过完整核验容量", 422)
    rows = clean(
        c.execute(
            """SELECT v.id::text AS document_version_id,v.artifact_kind,v.original_name,
        b.id::text AS blob_id,b.digest,b.byte_size,b.media_type,b.object_key
        FROM design.document_versions v JOIN design.blobs b ON b.id=v.blob_id
        WHERE v.bid_id=%s AND v.id=ANY(%s::uuid[]) ORDER BY v.id""",
            (bid, sorted(roles)),
        ).fetchall()
    )
    if {row["document_version_id"] for row in rows} != set(roles):
        failure("ORIGINAL_NOT_FOUND", "包原件、附件或其原件祖先不属于该项目", 404)
    for row in rows:
        identity = row["document_version_id"]
        if identity in expected and row["digest"] != expected[identity]:
            failure("ORIGINAL_CHANGED", "包或附件的确切原件摘要不一致")
        if (
            evidence is not None
            and identity == evidence["document_version_id"]
            and row["byte_size"] != evidence["byte_size"]
        ):
            failure("EVIDENCE_CHANGED", "实际提交附件的确切大小不一致")
        row["roles"] = sorted(roles[identity])
    return rows, sources


def public_original(row):
    return {
        key: deepcopy(value) for key, value in row.items() if key not in {"object_key", "blob_id"}
    }


def submission_head(c, bid, *, lock=False):
    row = c.execute(
        sql.SQL(
            "SELECT s.id::text,h.revision,s.subject_kind FROM design.submission_heads h JOIN design.submission_records s ON s.bid_id=h.bid_id AND s.id=h.submission_id WHERE h.bid_id=%s"
        )
        + sql.SQL(" FOR UPDATE OF h" if lock else ""),
        (bid,),
    ).fetchone()
    return clean(row) if row else None


def observe(c, scope, request):
    selection, run = selected(c, scope, request)
    observation = current(c, scope[0], selection)
    chosen_decisions = decisions(c, scope[0], selection["inventory"])
    proof = inventory_proof(c, selection, run)
    history = risk_history(c, scope[0], run)
    raw_originals, sources = originals(c, scope[0], selection)
    context = {
        "method_digest": package_submission_gate.policy_identity()["digest"],
        "current": observation,
        "rule_decisions": chosen_decisions,
        "risk_history": history,
        "current_submission_head": submission_head(c, scope[0]),
        "originals": [public_original(row) for row in raw_originals],
        "original_sources": sources,
    }
    identity = {
        "selection": selection,
        "selection_request": request,
        "context": context,
        "review_run": run,
        "inventory_proof": proof,
    }
    if len(canonical(identity)) > package_submission_gate.LIMITS["input_bytes"]:
        failure("CAPACITY_EXCEEDED", "完整包、清单与风险观察超过本次冻结容量", 422)
    observed_at = utc(c.execute("SELECT clock_timestamp() AS at").fetchone()["at"].isoformat())
    gate = package_submission_gate.assess(
        selection,
        observed_at=observed_at,
        current=observation,
        run=run,
        inventory_proof=proof,
        rule_decisions=chosen_decisions,
        risk_history=history,
    )
    return {
        **identity,
        "input_digest": sha(identity),
        "gate": gate,
        "originals": raw_originals,
        "observed_at": observed_at,
    }
