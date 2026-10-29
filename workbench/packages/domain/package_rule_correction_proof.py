"""Replay the exact, bounded human derivation chain against archived native rows.

The repository loads these immutable records by the descriptor's explicit IDs and
validates command/audit ownership. This pure consumer validates their mutual content
bindings; it does not infer a current head, fetch a replacement parse or grant use.
"""

from jsonschema import FormatChecker

from packages.contracts import package_rule_corrections_api as contract
from packages.domain import package_rule_corrections as core
from packages.domain.review_identity import digest


def check(condition):
    core.require(
        condition, "DERIVATION_CORRUPT", "人工更正链与原抽取、真实条款、决定或证据无法一致核验", 500
    )


def _rules(inventory):
    return sorted(
        (row["rule_snapshot"] for row in inventory["manifest"]["requirements"]),
        key=lambda r: (r["kind"], r["id"]),
    )


def _decisions(step, expected, record):
    bindings = record["decision_bindings"]
    by_rule = {row["rule_id"]: row for row in bindings}
    check(len(by_rule) == len(bindings))
    new = {row["rule_id"]: row for row in expected["decisions"]}
    carried = {row["new_rule_id"]: row for row in expected["carryovers"]}
    check(set(by_rule) == set(new) | set(carried))
    actual = {row["id"]: row for row in step["decisions"]}
    check(
        len(actual) == len(step["decisions"])
        and set(actual) == {r["decision_id"] for r in bindings}
    )
    columns = {
        "id",
        "bid_id",
        "object_kind",
        "object_id",
        "object_revision",
        "decision",
        "reason",
        "evidence_ids",
        "actor_id",
        "created_at",
    }
    before = {r["rule_id"]: r for r in step["base_inventory"]["manifest"]["requirements"]}
    for rid, binding in by_rule.items():
        decision = actual[binding["decision_id"]]
        check(
            set(decision) == columns
            and decision["bid_id"] == record["scope"]["bid_id"]
            and decision["object_kind"] == "rule"
            and digest(decision) == binding["decision_digest"]
        )
        check(FormatChecker().conforms(decision["created_at"], "date-time"))
        if rid in new:
            want = new[rid]
            check(
                binding["mode"] == want["decision"]
                and decision["object_id"] == rid
                and type(decision["object_revision"]) is int
                and decision["object_revision"] == 1
                and decision["actor_id"] == record["actor_id"]
                and all(decision[k] == want[k] for k in ("decision", "reason", "evidence_ids"))
            )
        else:
            want = carried[rid]
            check(
                binding["mode"] == "carried"
                and decision["id"] == want["from_decision_id"]
                and decision == before[want["from_rule_id"]]["decision_snapshot"]
            )
    actual_carries = step["carryovers"]
    check(
        len(actual_carries) == len(carried)
        and len({r["new_rule_id"] for r in actual_carries}) == len(actual_carries)
    )
    for row in actual_carries:
        want = carried.get(row["new_rule_id"])
        check(
            want is not None
            and set(row) in (set(want), set(want) | {"adopted_at"})
            and all(row[k] == v for k, v in want.items())
        )
    check(bindings == sorted(bindings, key=lambda row: row["rule_id"]))


def _step(step, authority, evidence):
    check(
        type(step) is dict
        and set(step)
        == {"manifest", "digest", "base_inventory", "result_rules", "decisions", "carryovers"}
    )
    record = step["manifest"]
    check(
        contract.valid("PackageRuleCorrectionView", {"manifest": record, "digest": step["digest"]})
        and digest(record) == step["digest"]
    )
    preview = core._prepare(
        step["base_inventory"], authority, evidence, record["request"], record["policy_digest"]
    )
    check(
        all(record[key] == preview["manifest"][key] for key in contract.COMMON)
        and record["preview_digest"] == preview["digest"]
    )
    check(record["result"]["inventory_id"] != record["scope"]["inventory_id"])
    existing = {r["from_rule_id"]: r["to_rule_id"] for r in record["mappings"]}
    added = {str(r["change_index"]): r["to_rule_id"] for r in record["additions"]}
    check(len(existing) == len(record["mappings"]) and len(added) == len(record["additions"]))
    expected = core.materialize(
        step["base_inventory"],
        preview,
        rule_set_id=record["result"]["rule_set_id"],
        rule_ids={"existing": existing, "added": added},
    )
    check(
        record["mappings"] == expected["mappings"] and record["additions"] == expected["additions"]
    )
    check(
        record["result"]["rule_set_digest"] == expected["rule_set_digest"]
        and record["result"]["rules_digest"] == expected["rules_digest"]
        and record["result"]["rule_count"] == len(expected["rules"])
    )
    check(step["result_rules"] == expected["rules"])
    _decisions(step, expected, record)
    return expected["rules"]


def verify(inventory, derivation, authority, evidence):
    core.bounded(derivation, contract.LIMITS["derivation_bytes"], "完整人工派生证明")
    core.verify_inventory_header(inventory)
    selected = inventory["manifest"]
    check(selected["version"] == core.V3)
    check(type(derivation) is dict and set(derivation) == {"root_inventory", "steps"})
    root, steps = derivation["root_inventory"], derivation["steps"]
    core.verify_inventory_header(root)
    check(root["manifest"]["version"] == core.V2)
    core._authority(root, authority)
    core._authority(inventory, authority)
    basis = core.extraction_basis(root)
    head = selected["human_derivation"]
    check(
        selected["extraction_basis"] == basis
        and type(steps) is list
        and len(steps) == head["length"]
        and 1 <= len(steps) <= contract.MAX_CHAIN
    )
    previous = None
    previous_rules = _rules(root)
    previous_set = (root["manifest"]["rule_set_id"], root["manifest"]["rule_set_digest"])
    record_ids, command_ids = set(), set()
    rule_ids = {r["id"] for r in previous_rules}
    rule_set_ids = {previous_set[0]}
    result_inventory_ids = {root["manifest"]["id"]}
    human_withdrawn = set()
    for index, step in enumerate(steps, 1):
        check(type(step) is dict and "manifest" in step and "base_inventory" in step)
        record = step["manifest"]
        before = step["base_inventory"]
        core.verify_inventory_header(before)
        bm = before["manifest"]
        check(
            (bm["rule_set_id"], bm["rule_set_digest"]) == previous_set
            and _rules(before) == previous_rules
        )
        if previous is None:
            check(before == root)
        else:
            check(
                bm["version"] == core.V3
                and bm["extraction_basis"] == basis
                and bm["human_derivation"]
                == {
                    "version": "package-rule-derivation/1",
                    "head_id": previous["id"],
                    "head_digest": previous["digest"],
                    "length": index - 1,
                }
            )
        check(
            record["previous"] == previous
            and record["sequence_no"] == index
            and record["extraction_basis"] == basis
        )
        check(
            record["id"] not in record_ids
            and record["command_id"] not in command_ids
            and record["result"]["rule_set_id"] not in rule_set_ids
            and record["result"]["inventory_id"] not in result_inventory_ids
        )
        result = _step(step, authority, evidence)
        human_withdrawn = {
            row["to_rule_id"]
            for row in record["mappings"]
            if row["op"] == "withdraw"
            or row["op"] == "carry"
            and row["from_rule_id"] in human_withdrawn
        }
        new_ids = {r["id"] for r in result}
        check(not new_ids & rule_ids)
        rule_ids.update(new_ids)
        rule_set_ids.add(record["result"]["rule_set_id"])
        result_inventory_ids.add(record["result"]["inventory_id"])
        record_ids.add(record["id"])
        command_ids.add(record["command_id"])
        previous = {"id": record["id"], "digest": step["digest"]}
        previous_rules = result
        previous_set = (record["result"]["rule_set_id"], record["result"]["rule_set_digest"])
    check(previous == {"id": head["head_id"], "digest": head["head_digest"]})
    # A later inventory may re-annotate or project the same set onto a new target.
    # Its mappings and decision heads are checked by the normal inventory guards.
    check(
        (selected["rule_set_id"], selected["rule_set_digest"]) == previous_set
        and _rules(inventory) == previous_rules
    )
    counts = core.rule_counts(previous_rules)
    counts.update(
        human_withdrawn=len(human_withdrawn),
        inherited_superseded=counts["inactive"] - len(human_withdrawn),
    )
    return {
        "state": "verified",
        "root_inventory_id": basis["inventory_id"],
        "root_rule_set_id": basis["rule_set_id"],
        "head_id": head["head_id"],
        "head_digest": head["head_digest"],
        "length": head["length"],
        "counts": counts,
    }
