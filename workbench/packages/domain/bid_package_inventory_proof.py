"""Read exact archived extraction identity in one RR snapshot; never infer legacy bindings."""

from packages.domain import bid_package_execution_input_repository as prepared_inputs
from packages.domain import bid_package_review_input_repository as frozen_inputs
from packages.domain.package_inventory_proof import assess
from packages.domain.runtime import DomainError, clean, connection


def _receipt(c, scope, inventory):
    if inventory["version"] == "bid-package-requirements/1":
        return None
    run = c.execute(
        """SELECT id,bid_id,authority_revision_id,authority_digest,input_blob_id,input_digest,
        input_manifest,operation_id,operation_input_digest,rule_set_id,result_digest,result
        FROM design.bid_package_requirement_extraction_runs
        WHERE bid_id=%s AND id=%s""",
        (scope[0], inventory["extraction_result_id"]),
    ).fetchone()
    if run is None:
        return None
    operation = c.execute(
        "SELECT id,bid_id,input_digest,handler_version,state FROM design.operations WHERE id=%s",
        (run["operation_id"],),
    ).fetchone()
    effect = c.execute(
        "SELECT result FROM design.effect_receipts WHERE operation_id=%s AND effect_key='extract-rules'",
        (run["operation_id"],),
    ).fetchone()
    return clean(
        {"run": run, "operation": operation, "effect": effect["result"] if effect else None}
    )


def observe(scope, frozen_id, input_id, prepared_digest):
    with connection() as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        packet = prepared_inputs.load_packet(c, scope, frozen_id, input_id)
        if packet.digest != prepared_digest:
            raise DomainError(
                "PACKAGE_EXECUTION_INPUT_CHANGED", "准备输入摘要与明确选择不一致", 409
            )
        original = frozen_inputs.load_input(c, scope, frozen_id)
        inventory = original.evidence()["selection"]["inventory"]["manifest"]
        try:
            return assess(original, packet, _receipt(c, scope, inventory))
        except (ValueError, KeyError, TypeError) as error:
            raise DomainError(
                "PACKAGE_INVENTORY_PROOF_CORRUPT", "清单与原抽取回执的冻结身份无法一致核验", 500
            ) from error
