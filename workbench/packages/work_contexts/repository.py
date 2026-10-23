"""Exact native joins under a caller-owned snapshot, never latest-head selection."""

from packages.domain import bid_package_dependency_plan_repository as plans
from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_fact_scope_repository as declarations
from packages.domain import bid_package_repository as packages
from packages.domain import bid_package_requirement_repository as inventories
from packages.domain import bid_package_review_decision_repository as decisions
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain import bid_package_review_run_repository as runs
from packages.domain import bid_package_submission_repository as submissions
from packages.domain import package_fact_usage as fact_usage
from packages.domain import package_scope_review as review
from packages.domain import package_scope_review_identity as execution_key
from packages.domain.bid_package_service import view as package_view
from packages.domain.runtime import clean
from packages.work_contexts import policy


def selected_package(c, bid, package_id, revision_id):
    value = packages.load_revision(c, bid, revision_id)
    policy.check(
        value.package_id == package_id
        and value.revision_id == revision_id
        and value.scope.bid_id == bid
    )
    members = c.execute(
        """SELECT member_id,ordinal,document_version_id::text,file_digest,parse_run_id::text,payload
        FROM design.bid_package_members WHERE bid_id=%s AND revision_id=%s ORDER BY ordinal LIMIT 501""",
        (bid, revision_id),
    ).fetchall()
    stored = value.manifest()["members"]
    policy.check(
        len(members) == len(stored)
        and all(
            row["ordinal"] == ordinal
            and row["payload"] == member
            and row["member_id"] == member["member_id"]
            and row["document_version_id"] == member["document_version_id"]
            and row["file_digest"] == member["file_digest"]
            and row["parse_run_id"] == member["parse"]["parse_run_id"]
            for ordinal, (row, member) in enumerate(zip(members, stored, strict=True))
        )
    )
    return package_view(c, value)


def verify_selection(c, bid, selected):
    """Re-read each explicitly named immutable root; mutable heads are unrelated."""
    own = selected["target"]
    target = own["manifest"]
    policy.check(
        target["scope"]["bid_id"] == bid
        and target["kind"] == "bid"
        and own == selected_package(c, bid, target["package_id"], target["revision_id"])
    )
    authority, inventory, coverage = (
        selected[key] for key in ("authority", "inventory", "coverage")
    )
    if authority is not None:
        am = authority["manifest"]
        policy.check(
            am["kind"] == "authority"
            and am["scope"] == target["scope"]
            and authority == selected_package(c, bid, am["package_id"], am["revision_id"])
        )
    if inventory is not None:
        im = inventory["manifest"]
        policy.check(
            inventory
            == inventories.load_inventory(
                c, bid, target["package_id"], target["revision_id"], im["id"]
            )
            and im["bid_id"] == bid
            and im["package_id"] == target["package_id"]
            and im["target_revision_id"] == target["revision_id"]
            and im["package_digest"] == own["digest"]
            and im["identity_digest"] == own["identity"]["digest"]
            and authority is not None
            and im["authority_revision_id"] == authority["manifest"]["revision_id"]
            and im["authority_digest"] == authority["digest"]
        )
    else:
        policy.check(authority is None and coverage is None)
    if coverage is not None:
        cm = coverage["manifest"]
        policy.check(
            inventory is not None
            and coverage
            == inventories.load_attempt(
                c,
                bid,
                target["package_id"],
                target["revision_id"],
                inventory["manifest"]["id"],
                cm["id"],
            )
        )


def exact_run(c, bid, run_id):
    row = c.execute(runs.SELECT + " WHERE r.bid_id=%s AND r.id=%s", (bid, run_id)).fetchone()
    if row is None:
        policy.fail("NOT_FOUND", "该项目下没有明确选择的整包核查", 404)
    run = runs.view(row)
    policy.check(run["id"] == run_id and run["scope"]["bid_id"] == bid)
    scope = tuple(run["scope"][key] for key in runs.SCOPE_KEYS)
    original = frozen_inputs.load_input(c, scope, run["frozen_input_id"])
    prepared = prepared_inputs.load_packet(
        c, scope, run["frozen_input_id"], run["execution_input_id"]
    )
    original_view, prepared_view = original.view(), prepared.view()
    frozen_manifest = original_view["manifest"]
    root = original.evidence()
    selected = {
        key: root["selection"][key] for key in ("target", "authority", "inventory", "coverage")
    }
    verify_selection(c, bid, selected)
    manifest = row["input_manifest"]
    policy.check(
        run["operation"]["kind"] == "package-scope-review"
        and run["operation"]["handler_version"] == review.HANDLER
        and manifest["frozen_input"]
        == {
            "id": run["frozen_input_id"],
            "digest": original.digest,
            "input_digest": frozen_manifest["input_digest"],
            "evidence_digest": frozen_manifest["evidence_digest"],
        }
        and manifest["execution_input"]
        == {
            "id": run["execution_input_id"],
            "digest": prepared.digest,
            "identity": prepared_view["manifest"]["identity"],
        }
    )
    plan = plans.load(
        c, scope, run["frozen_input_id"], run["execution_input_id"], run["dependency_plan_id"]
    )
    policy.check(plan["digest"] == run["dependency_plan_digest"])
    records = [
        declarations.load(
            c, scope, run["frozen_input_id"], run["execution_input_id"], ref["declaration_id"]
        )
        for ref in manifest["fact_admission"]["fact_declarations"]
    ]
    policy.check(execution_key.identify(manifest, records)["digest"] == row["execution_key"])
    usage = fact_usage.select(
        prepared,
        {
            "purpose": manifest["purpose"],
            "fact_ids": [ref["fact_id"] for ref in manifest["fact_admission"]["fact_declarations"]],
        },
    )
    policy.check(
        usage.digest == manifest["usage_digest"]
        and usage.view()["manifest"]["selected_facts_digest"] == manifest["selected_facts_digest"]
    )
    # model_input consumes only the saved selected_items projection. It neither
    # admits a fact for new use nor calls a provider.
    payload = review.model_input(root, plan, usage)
    policy.check(review.model_digest(payload) == manifest["model_input_digest"])
    human = decisions.current(c, run) if run["result"] is not None else None
    summary = policy.review_summary(run, payload, human)
    return {
        "run": run,
        "input": manifest,
        "selected": selected,
        "root": root,
        "prepared": prepared,
        "usage": usage,
        "payload": payload,
        "human": human,
        "summary": summary,
    }


def exact_submission(c, bid, submission_id):
    record = submissions.load(c, bid, submission_id)
    manifest = record["package_binding"]["manifest"]
    selected = manifest["selection"]
    verify_selection(c, bid, selected)
    request = manifest["selection_request"]
    target = selected["target"]
    policy.check(
        request["package_id"] == target["manifest"]["package_id"]
        and request["revision_id"] == target["manifest"]["revision_id"]
        and request["package_digest"] == target["digest"]
        and request["inventory"]
        == (
            {
                "id": selected["inventory"]["manifest"]["id"],
                "digest": selected["inventory"]["digest"],
            }
            if selected["inventory"]
            else None
        )
        and request["coverage"]
        == (
            {"id": selected["coverage"]["manifest"]["id"], "digest": selected["coverage"]["digest"]}
            if selected["coverage"]
            else None
        )
    )
    saved_run, loaded = manifest["review_run"], None
    if saved_run is None:
        policy.check(request["review_run"] is None)
    else:
        policy.check(
            request["review_run"]
            == {
                "id": saved_run["id"],
                "input_digest": saved_run["input_digest"],
                "result_digest": saved_run["result"]["digest"] if saved_run["result"] else None,
            }
        )
        loaded = exact_run(c, bid, saved_run["id"])
        native = loaded["run"]
        policy.check(loaded["selected"] == selected)
        policy.check(
            {key: value for key, value in saved_run.items() if key not in {"operation", "result"}}
            == {key: value for key, value in native.items() if key not in {"operation", "result"}}
            and all(
                saved_run["operation"][key] == native["operation"][key]
                for key in ("id", "kind", "input_digest", "handler_version", "created_at")
            )
        )
        if saved_run["result"] is not None:
            policy.check(
                saved_run["result"] == native["result"]
                and saved_run["operation"] == native["operation"]
            )
        else:
            # A later completed report is not the report bound at registration.
            policy.check(saved_run["operation"]["state"] != "succeeded")
    return {"record": record, "manifest": manifest, "selected": selected, "run": loaded}


def at(c):
    return clean(c.execute("SELECT transaction_timestamp() AS at").fetchone())["at"]
