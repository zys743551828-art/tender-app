"""Explicit human fact change contract; a saved confirmation grants no review authority."""

import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from packages.domain.review_identity import digest
from packages.domain.runtime import DomainError

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/schemas/package-fact-change.schema.json"
    ).read_text("utf-8")
)


def validate(name, value):
    if not Draft202012Validator(
        {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]}, format_checker=FormatChecker()
    ).is_valid(value):
        raise DomainError(
            "PACKAGE_FACT_CHANGE_INVALID", "请核对事实、明确依据、理由及当前事实集", 422
        )
    reason = value["fact"]["reason"] if name == "ConfirmRequest" else value.get("reason")
    if reason is not None and reason != reason.strip():
        raise DomainError("PACKAGE_FACT_CHANGE_INVALID", "核对理由不能包含首尾空白", 422)
    if name == "ConfirmRequest" and any(
        not value["fact"][key].strip() for key in ("subject", "scope", "name")
    ):
        raise DomainError("PACKAGE_FACT_CHANGE_INVALID", "请填写事实主体、范围及名称", 422)


def seal(manifest):
    value = {"manifest": deepcopy(manifest), "digest": digest(manifest)}
    validate("Record", value)
    _bindings(value["manifest"])
    return value


def verify(value):
    try:
        validate("Record", value)
        _bindings(value["manifest"])
        if digest(value["manifest"]) != value["digest"]:
            raise ValueError("fact_change_digest")
    except (DomainError, TypeError, ValueError, KeyError) as error:
        raise DomainError(
            "PACKAGE_FACT_CHANGE_CORRUPT", "已保存事实操作回执完整性校验失败", 500
        ) from error
    return deepcopy(value)


def _bindings(m):
    if m["reason"] != m["reason"].strip():
        raise ValueError("fact_change_reason")
    if (
        (m["previous_head"]["id"] is None) != (m["previous_head"]["revision"] == 0)
        or m["head"]["id"] is None
        or m["head"]["id"] == m["previous_head"]["id"]
        or m["head"]["revision"] != m["previous_head"]["revision"] + 1
    ):
        raise ValueError("fact_change_head_binding")
    proof_fields = ("decision_id", "evidence_selection_digest", "evidence_basis_digest")
    if m["action"] == "confirmed" and any(m[key] is None for key in proof_fields):
        raise ValueError("fact_confirmation_binding")
    if (
        m["action"] == "confirmed"
        and m["replaces_fact_id"] is not None
        and (m["replaces_fact_id"] == m["fact_id"] or m["previous_head"]["id"] is None)
    ):
        raise ValueError("fact_replacement_binding")
    if m["action"] == "withdrawn" and (
        any(m[key] is not None for key in proof_fields) or m["replaces_fact_id"] is not None
    ):
        raise ValueError("fact_withdrawal_binding")
    if m["action"] == "withdrawn" and m["previous_head"]["id"] is None:
        raise ValueError("fact_withdrawal_head")
