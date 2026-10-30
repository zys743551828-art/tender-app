"""Read-only actual capability, scope targets and budget limits. No configuration write API."""

from typing import Any
from uuid import UUID

from packages.assistant import budget, intent_identity
from packages.domain.runtime import DomainError, clean, fetch


def capabilities(c, actor, bid=None):
    result: dict[str, Any] = {
        "protocol": budget.PROTOCOL,
        "configured": False,
        "can_send_new_question": False,
        "reasons": [],
        "purposes": intent_identity.PURPOSES,
        "identity_fact_keys": list(intent_identity.IDENTITY_FACTS),
        "limits": [],
        "unresolved": [],
        "estimate_not_provider_spend_cap": True,
        "new_question_is_explicit_send": True,
        "automatic_retry_authorized": False,
        "price": None,
    }
    if bid:
        fetch(c, "SELECT id FROM bids WHERE id=%s", (bid,))
    if not budget.configured(c):
        result["reasons"] = ["ASSISTANT_BUDGET_NOT_CONFIGURED"]
        return result
    result["configured"] = True
    owners = [("global", "assistant"), ("member", str(actor))]
    if bid:
        try:
            identity = intent_identity.project_identity(c, bid)
            owners.append(("project", identity["canonical_project_key"]))
        except DomainError as error:
            result["reasons"].append(error.code)
    for scope, owner in owners:
        row = c.execute(
            "SELECT *,clock_timestamp() AS checked_at,design.assistant_budget_obligation(id) AS obligation FROM assistant_budget_versions WHERE scope=%s AND owner_key=%s ORDER BY revision DESC LIMIT 1",
            (scope, owner),
        ).fetchone()
        if not row or not row["window_from"] <= row["checked_at"] < row["window_until"]:
            result["reasons"].append("ASSISTANT_BUDGET_NOT_CONFIGURED")
        else:
            result["limits"].append(
                clean(
                    {
                        "id": row["id"],
                        "scope": scope,
                        "revision": row["revision"],
                        "currency": row["currency"],
                        "amount_scale": 1_000_000_000,
                        "limit_minor": row["limit_minor"],
                        "obligation_minor": int(row["obligation"]),
                        "available_minor": max(0, row["limit_minor"] - int(row["obligation"])),
                        "window_from": row["window_from"],
                        "window_until": row["window_until"],
                    }
                )
            )
    rows = c.execute(
        "SELECT i.job_id,i.normalized_question,coalesce(j.input_manifest->'request'->>'text',j.input_manifest->'request'->>'instruction') AS original_question,j.scope,i.target,i.created_at,r.state,r.currency,r.reserved_minor,r.price_id FROM assistant_logical_intents i JOIN assistant_budget_reservations r ON r.job_id=i.job_id JOIN assistant_jobs j ON j.id=i.job_id WHERE r.state IN ('held','sent','unknown') AND ((j.scope='global' AND j.actor_id=%s) OR (j.scope='project' AND j.bid_id=%s)) ORDER BY i.created_at,i.id LIMIT 100",
        (actor, bid),
    ).fetchall()
    result["unresolved"] = [
        clean(
            dict(row)
            | {"target": {key: row["target"][key] for key in ("kind", "id", "purpose", "bid_id")}}
        )
        for row in rows
    ]
    if c.execute(
        "SELECT 1 FROM assistant_jobs j LEFT JOIN assistant_budget_reservations r ON r.job_id=j.id WHERE r.job_id IS NULL AND (EXISTS(SELECT FROM assistant_global_calls c WHERE c.run_id=j.id AND c.state IN ('reserved','unknown')) OR EXISTS(SELECT FROM model_calls c WHERE c.operation_id=j.operation_id AND c.state IN ('reserved','unknown'))) LIMIT 1"
    ).fetchone():
        result["reasons"].append("ASSISTANT_UNPRICED_OBLIGATION")
    from packages.assistant.provider import configured

    try:
        price = budget.checked_price(c, configured())
        result["price"] = clean(
            {
                key: price[key]
                for key in (
                    "id",
                    "version",
                    "provider",
                    "model",
                    "currency",
                    "amount_scale",
                    "input_per_million_minor",
                    "output_per_million_minor",
                    "input_hard_ceiling",
                    "output_hard_ceiling",
                    "source_kind",
                    "source_uri",
                    "source_sha256",
                    "verified_at",
                    "valid_from",
                    "valid_until",
                )
            }
        )
    except DomainError as error:
        result["reasons"].append(error.code)
    result["reasons"] = sorted(set(result["reasons"]))
    result["can_send_new_question"] = not result["reasons"] and all(
        row["available_minor"] > 0 for row in result["limits"]
    )
    return result


def targets(c, bid):
    project = fetch(c, "SELECT id,title FROM bids WHERE id=%s", (bid,))
    items = [
        {
            "kind": "project",
            "id": str(project["id"]),
            "title": project["title"],
            "purposes": ["project_reference"],
        }
    ]
    try:
        proof = intent_identity.project_identity(c, bid)
        reasons = []
    except DomainError as error:
        proof, reasons = None, [error.code]
    for row in c.execute(
        "SELECT id,statement FROM findings WHERE bid_id=%s ORDER BY id LIMIT 100", (bid,)
    ).fetchall():
        items.append(
            {
                "kind": "finding",
                "id": str(row["id"]),
                "title": row["statement"],
                "purposes": ["finding_explanation"],
            }
        )
    for row in c.execute(
        "SELECT id,statement FROM rule_items WHERE bid_id=%s ORDER BY id LIMIT 100", (bid,)
    ).fetchall():
        items.append(
            {
                "kind": "rule",
                "id": str(row["id"]),
                "title": row["statement"],
                "purposes": ["rule_explanation"],
            }
        )
    for row in c.execute(
        "SELECT id,head_revision FROM sections WHERE bid_id=%s ORDER BY id LIMIT 100", (bid,)
    ).fetchall():
        items.append(
            {
                "kind": "section",
                "id": str(row["id"]),
                "title": "已登记章节（版本 " + str(row["head_revision"]) + "）",
                "purposes": ["section_reference", "section_draft"],
            }
        )
    return {
        "protocol": budget.PROTOCOL,
        "bid_id": str(UUID(str(bid))),
        "coverage": "bounded_first_100_each_kind",
        "items": [
            item | {"independence_identity_available": proof is not None, "reasons": reasons}
            for item in items
        ],
        "identity_fact_keys": list(intent_identity.IDENTITY_FACTS),
    }
