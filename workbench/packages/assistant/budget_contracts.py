"""Actual intent/budget schemas. No changes to the target contract snapshots."""

from packages.assistant.protocol import HASH, ID, array, obj

NID = {"type": ["string", "null"], "format": "uuid"}
TIME = {"type": "string", "format": "date-time"}
NTIME = {"type": ["string", "null"], "format": "date-time"}
MONEY = {"type": "integer", "minimum": 0}
TEXT = {"type": "string"}
BOOL = {"type": "boolean"}
PURPOSE = {
    "enum": [
        "general_reference",
        "project_reference",
        "finding_explanation",
        "rule_explanation",
        "section_reference",
        "section_draft",
    ]
}
KIND = {"enum": ["general", "project", "finding", "rule", "section"]}
CURRENCY = {"enum": ["CNY", "USD"]}
HOLD_STATE = {"enum": ["held", "sent", "unknown", "settled", "released"]}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def schemas():
    target = obj({"kind": KIND, "id": NID, "purpose": PURPOSE, "bid_id": NID})
    intent_target = obj(
        target["properties"]
        | {"canonical_project_key": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"}}
    )
    intent = obj(
        {
            "id": ID,
            "request_mode": {"const": "new_question"},
            "normalized_question": TEXT | {"maxLength": 400000},
            "coarse_key": HASH,
            "anti_resend_key": HASH,
            "price_version_id": ID,
            "origin_action_id": NID,
            "target": intent_target,
        }
    )
    hold = obj(
        {
            "job_id": ID,
            "intent_id": ID,
            "actor_id": ID,
            "coarse_key": HASH,
            "price_id": ID,
            "member_budget_id": ID,
            "project_budget_id": NID,
            "global_budget_id": ID,
            "currency": CURRENCY,
            "reserved_minor": MONEY,
            "input_upper": MONEY,
            "output_upper": MONEY,
            "state": HOLD_STATE,
            "requires_manual_reconciliation": BOOL,
            "charged_minor": {"type": ["integer", "null"], "minimum": 0},
            "project_call_id": NID,
            "global_call_id": NID,
            "dispatched_at": NTIME,
            "settled_at": NTIME,
            "created_at": TIME,
            "price_version": TEXT,
            "amount_scale": {"const": 1000000000},
            "source_kind": {"enum": ["official_tariff_and_context_limit", "explicit_mock_fixture"]},
            "input_per_million_minor": MONEY,
            "output_per_million_minor": MONEY,
            "estimate_not_provider_spend_cap": {"const": True},
            "unknown_hold_released_automatically": {"const": False},
        }
    )
    limit = obj(
        {
            "id": ID,
            "scope": {"enum": ["member", "project", "global"]},
            "revision": {"type": "integer", "minimum": 1},
            "currency": CURRENCY,
            "amount_scale": {"const": 1000000000},
            "limit_minor": MONEY,
            "obligation_minor": MONEY,
            "available_minor": MONEY,
            "window_from": TIME,
            "window_until": TIME,
        }
    )
    price = obj(
        {
            "id": ID,
            "version": TEXT,
            "provider": {"const": "deepseek"},
            "model": {"enum": ["deepseek-flash", "deepseek-v4-pro"]},
            "currency": CURRENCY,
            "amount_scale": {"const": 1000000000},
            "input_per_million_minor": MONEY,
            "output_per_million_minor": MONEY,
            "input_hard_ceiling": MONEY,
            "output_hard_ceiling": MONEY,
            "source_kind": {"enum": ["official_tariff_and_context_limit", "explicit_mock_fixture"]},
            "source_uri": {"type": "string", "format": "uri"},
            "source_sha256": HASH,
            "verified_at": TIME,
            "valid_from": TIME,
            "valid_until": TIME,
        }
    )
    pending = obj(
        {
            "job_id": ID,
            "normalized_question": TEXT,
            "original_question": TEXT,
            "scope": {"enum": ["global", "project"]},
            "target": target,
            "created_at": TIME,
            "state": HOLD_STATE,
            "currency": CURRENCY,
            "reserved_minor": MONEY,
            "price_id": ID,
        }
    )
    capabilities = obj(
        {
            "protocol": {"const": "assistant-intent-budget/1"},
            "configured": BOOL,
            "can_send_new_question": BOOL,
            "reasons": array(TEXT, 30),
            "purposes": obj(
                {
                    key: array(PURPOSE, 6)
                    for key in ("general", "project", "finding", "rule", "section")
                }
            ),
            "identity_fact_keys": array(TEXT, 5),
            "limits": array(limit, 3),
            "unresolved": array(pending, 100),
            "estimate_not_provider_spend_cap": {"const": True},
            "new_question_is_explicit_send": {"const": True},
            "automatic_retry_authorized": {"const": False},
            "price": {"oneOf": [price, {"type": "null"}]},
        }
    )
    target_choice = obj(
        {
            "kind": KIND,
            "id": ID,
            "title": TEXT,
            "purposes": array(PURPOSE, 6),
            "independence_identity_available": BOOL,
            "reasons": array(TEXT, 20),
        }
    )
    choices = obj(
        {
            "protocol": {"const": "assistant-intent-budget/1"},
            "bid_id": ID,
            "coverage": {"const": "bounded_first_100_each_kind"},
            "items": array(target_choice, 301),
            "identity_fact_keys": array(TEXT, 5),
        }
    )
    return {
        "AssistantLogicalIntent": intent,
        "AssistantBudgetReservation": hold,
        "AssistantIntentCapabilities": capabilities,
        "AssistantIntentTargetPage": choices,
    }


def extend(actual):
    actual["components"]["schemas"].update(schemas())
    for suffix, name in (
        ("intent-capabilities", "AssistantIntentCapabilities"),
        ("intent-targets", "AssistantIntentTargetPage"),
    ):
        route = actual["paths"].get("/api/v1/assistant/" + suffix, {}).get("get")
        if route is not None:
            route["responses"]["200"] = {
                "description": "实际受控意图与聚合预算能力；不授真实费用授权",
                "content": {"application/json": {"schema": ref(name)}},
            }
    job = actual["components"]["schemas"]["AssistantJob"]
    job["properties"].update(
        logical_intent={"oneOf": [ref("AssistantLogicalIntent"), {"type": "null"}]},
        budget={"oneOf": [ref("AssistantBudgetReservation"), {"type": "null"}]},
    )
    for name in ("logical_intent", "budget"):
        if name not in job["required"]:
            job["required"].append(name)
    return actual
