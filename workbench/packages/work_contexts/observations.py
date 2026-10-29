"""Compare exact historical identities with this read snapshot, without admission."""

from packages.domain import bid_package_fact_admission as fact_admission
from packages.domain import package_scope_review as review
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean
from packages.work_contexts import policy


def package_head(c, selected):
    if selected is None:
        return policy.dimension("not_applicable", "NO_SELECTED_AUTHORITY")
    m = selected["manifest"]
    row = c.execute(
        """SELECT h.revision_id::text,h.digest FROM design.bid_package_heads h
        JOIN design.bid_packages p ON p.id=h.package_id
        WHERE p.bid_id=%s AND h.package_id=%s""",
        (m["scope"]["bid_id"], m["package_id"]),
    ).fetchone()
    return policy.compare({"revision_id": m["revision_id"], "digest": selected["digest"]}, row)


def source_basis(c, selected, baseline, at):
    own, authority = selected["target"]["manifest"], selected["authority"]
    current = c.execute(
        "SELECT design.bid_requirement_source_snapshot(%s,%s) AS value",
        (own["revision_id"], authority["manifest"]["revision_id"] if authority else None),
    ).fetchone()["value"]
    if not current or not baseline:
        return policy.dimension(
            "unknown", "SOURCE_GRAPH_NOT_ESTABLISHED", digest(baseline), digest(current)
        )
    compared = policy.compare(baseline, current)
    if not policy.effective_sources(current, at):
        compared.update(status="changed", reason="SOURCE_NOT_CURRENTLY_EFFECTIVE")
    return compared


def selected_facts(c, loaded):
    if loaded is None:
        return policy.dimension("not_applicable", "NO_BOUND_REVIEW_FACT_SELECTION")
    original = loaded["input"]["fact_admission"]
    if not original["fact_declarations"]:
        return policy.dimension("not_applicable", "NO_FACTS_SELECTED")
    try:
        current = fact_admission._observe(c, loaded["prepared"], loaded["usage"]).view()["manifest"]
    except DomainError as error:
        if error.status >= 500:
            raise
        return policy.dimension("changed", error.code, original["content_digest"])
    return policy.compare(original["content_digest"], current["content_digest"])


def executor_method(loaded):
    if loaded is None:
        return policy.dimension("not_applicable", "NO_BOUND_REVIEW_METHOD")
    selected = loaded["run"]["method_digest"]
    try:
        current = digest(review.method_profile())
    except (DomainError, OSError):
        return policy.dimension("unknown", "CURRENT_METHOD_UNAVAILABLE", selected)
    return policy.dimension(
        "matched" if selected == current else "changed",
        "EXACT_METHOD_MATCH" if selected == current else "EXECUTOR_METHOD_CHANGED",
        selected,
        current,
    )


def observe(c, bid, selected, baseline_sources, at, *, loaded=None, submission=None):
    own = selected["target"]
    profile = c.execute(
        "SELECT design.identity_snapshot_v2(%s) AS identity,p.current_rule_set_id::text FROM design.bid_profiles p WHERE p.bid_id=%s",
        (bid, bid),
    ).fetchone()
    policy.check(profile is not None)
    inventory = selected["inventory"]
    current_inventory = c.execute(
        "SELECT inventory_id::text AS id,digest FROM design.bid_package_requirement_heads WHERE target_revision_id=%s",
        (own["manifest"]["revision_id"],),
    ).fetchone()
    observations = {
        "identity": policy.compare(own["identity"], clean(profile["identity"])),
        "package_head": package_head(c, own),
        "authority_head": package_head(c, selected["authority"]),
        "inventory_head": policy.compare(
            {"id": inventory["manifest"]["id"], "digest": inventory["digest"]}, current_inventory
        )
        if inventory
        else policy.dimension("not_applicable", "NO_INVENTORY_SELECTED"),
        "rule_set_head": policy.compare(
            inventory["manifest"]["rule_set_id"], profile["current_rule_set_id"]
        )
        if inventory
        else policy.dimension("not_applicable", "NO_INVENTORY_SELECTED"),
        "sources": source_basis(c, selected, baseline_sources, at),
        "selected_facts": selected_facts(c, loaded),
        "executor_method": executor_method(loaded),
        "submission_head": policy.dimension("not_applicable", "NOT_A_SUBMISSION_SELECTION"),
        "review_run_head": policy.dimension(
            "not_applicable", "NO_NATIVE_CURRENT_PACKAGE_REVIEW_HEAD"
        ),
        "bound_run_state": policy.dimension("not_applicable", "NOT_A_BOUND_RUN_SNAPSHOT"),
    }
    if submission is not None:
        manifest = submission["manifest"]
        head = c.execute(
            "SELECT submission_id::text AS id,revision FROM design.submission_heads WHERE bid_id=%s",
            (bid,),
        ).fetchone()
        observations["submission_head"] = policy.compare(
            {"id": manifest["submission_id"], "revision": manifest["head_revision"]}, head
        )
        if loaded is not None:

            def run_state(run):
                return {
                    "operation_state": run["operation"]["state"],
                    "result_digest": run["result"]["digest"] if run["result"] else None,
                }

            observations["bound_run_state"] = policy.compare(
                run_state(manifest["review_run"]), run_state(loaded["run"])
            )
    return observations
