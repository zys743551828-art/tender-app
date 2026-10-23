"""Exact selected-run read port; one nonowner snapshot, no provider or original-byte IO."""

from pathlib import Path

from packages.contracts import package_next_actions as contract
from packages.domain import package_next_actions as policy
from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError, clean, sha
from packages.work_contexts import observations, repository, service
from packages.work_contexts import policy as context_policy

RULES = """SELECT r.*,d.id::text AS observed_direct_id,d.object_kind AS observed_direct_kind,
d.object_id::text AS observed_direct_object,h.decision_id::text AS observed_head_id,
h.revision AS observed_head_revision,coalesce(d.decision,cd.decision,'pending') AS observed_confirmation,
co.from_rule_id::text AS observed_carry_rule,co.from_decision_id::text AS observed_carry_id,
co.equivalence_digest AS observed_carry_digest,cd.id::text AS observed_carry_decision,
cd.object_kind AS observed_carry_kind,cd.object_id::text AS observed_carry_object
FROM design.rule_items r
LEFT JOIN design.decision_heads h ON h.bid_id=r.bid_id AND h.object_kind='rule' AND h.object_id=r.id
LEFT JOIN design.decisions d ON d.id=h.decision_id AND d.bid_id=h.bid_id
LEFT JOIN design.rule_carryovers co ON co.bid_id=r.bid_id AND co.new_rule_id=r.id
LEFT JOIN design.decisions cd ON cd.id=co.from_decision_id AND cd.bid_id=co.bid_id
WHERE r.bid_id=%s AND r.id=ANY(%s::uuid[]) ORDER BY r.id"""


def _source_digest(module):
    path = module.__file__
    if not isinstance(path, str):
        raise DomainError("PACKAGE_NEXT_ACTION_METHOD_UNAVAILABLE", "下一步方法来源不可核验", 503)
    return sha(Path(path).read_bytes())


def method_digest():
    return digest(
        {
            name: _source_digest(module)
            for name, module in (
                ("selector", policy),
                ("contract", contract),
                ("native_reader", repository),
                ("observation", observations),
                ("native_policy", context_policy),
            )
        }
        | {"confirmation_reader": sha(Path(__file__).read_bytes())}
    )


def confirmations(c, bid, payload, current):
    for table in ("rule_items", "rule_carryovers"):
        row = c.execute(
            "SELECT has_table_privilege(current_user,%s,'SELECT') AS allowed", ("design." + table,)
        ).fetchone()
        if not row or not row["allowed"]:
            raise DomainError(
                "PACKAGE_NEXT_ACTION_UNAVAILABLE", "关键规则当前观察的只读权限不可用", 503
            )
    selected = {
        row["requirement_id"]: row
        for row in payload["requirements"]
        if row["rule"]["kind"] in policy.CRITICAL
    }
    found = {
        str(row["id"]): clean(row) for row in c.execute(RULES, (bid, list(selected))).fetchall()
    }
    states, proof, old_rules, new_rules = {}, [], [], []
    changed = False
    for identity, original in sorted(selected.items()):
        row = found.get(identity)
        if row is None:
            states[identity] = "unknown"
            proof.append({"rule_id": identity, "current_native_rule": None})
            continue
        if (
            row["observed_head_id"] is not None
            and (
                row["observed_head_id"] != row["observed_direct_id"]
                or row["observed_direct_kind"] != "rule"
                or row["observed_direct_object"] != identity
            )
        ) or (
            row["observed_direct_id"] is None
            and row["observed_carry_id"] is not None
            and (
                row["observed_carry_id"] != row["observed_carry_decision"]
                or row["observed_carry_kind"] != "rule"
                or row["observed_carry_object"] != row["observed_carry_rule"]
            )
        ):
            raise DomainError(
                "PACKAGE_NEXT_ACTION_RULE_HEAD_INVALID", "关键规则确认头与原记录不能一致核验", 500
            )
        observed_rule = {key: row.get(key) for key in original["rule"]}
        changed |= digest(observed_rule) != original["rule_digest"]
        old_rules.append(original["rule"])
        new_rules.append(observed_rule)
        states[identity] = row["observed_confirmation"]
        proof.append(
            {
                "rule_id": identity,
                "rule_digest": digest(observed_rule),
                **{key: value for key, value in row.items() if key.startswith("observed_")},
            }
        )
    if changed:
        current["rule_set_head"] = context_policy.dimension(
            "changed", "SELECTED_RULE_CONTENT_CHANGED", digest(old_rules), digest(new_rules)
        )
    return states, digest(proof)


def read(bid, run_id, expected_input_digest):
    service.request_ids(bid, run_id)
    with service.snapshot("run") as c:
        loaded = repository.exact_run(c, bid, run_id)
        run = loaded["run"]
        if run["input_digest"] != expected_input_digest:
            raise DomainError(
                "PACKAGE_NEXT_ACTION_SELECTION_CHANGED",
                "所选核查输入摘要不同，请保留原选择后重新核对",
                412,
            )
        at = repository.at(c)
        current = observations.observe(
            c,
            bid,
            loaded["selected"],
            loaded["prepared"].snapshot()["context"]["manifest"]["sources"],
            at,
            loaded=loaded,
        )
        profile = c.execute(
            "SELECT p.phase,p.archived_at,b.settings FROM design.bid_profiles p JOIN design.bids b ON b.id=p.bid_id WHERE p.bid_id=%s",
            (bid,),
        ).fetchone()
        states, proof = confirmations(c, bid, loaded["payload"], current)
        return policy.make(
            run,
            loaded["payload"],
            loaded["human"],
            current,
            phase=profile["phase"],
            archived_at=clean(profile["archived_at"]),
            accept_rules_as_written=profile["settings"].get("accept_rules_as_written", False),
            confirmations=states,
            confirmation_digest=proof,
            method_digest=method_digest(),
            observed_at=at,
        )
