"""Three owned exact-package judgments with the existing real call/budget ledger.

The initial usable lane is isolated mechanism acceptance. Formal execution has
separate unfulfilled qualifications and is refused before reservation or send.
"""

import json
from copy import deepcopy

from packages.domain.runtime import DomainError, clean, sha
from packages.model_governance import package_scoring_profile as profile
from packages.research.model_port import usage_estimate


class PackageScorePort:
    def __init__(self, authority, lease, snapshot, transport):
        self.authority = authority
        self.lease = lease
        self.snapshot = snapshot
        self.transport = transport
        self.reserve_fee = profile.conservative_fee(snapshot["price_config"])
        self.allowed = {entry["package"]["digest"]: entry["id"] for entry in snapshot["chapters"]}
        if len(self.allowed) != len(snapshot["chapters"]):
            raise DomainError("PACKAGE_SCORE_DUPLICATE_RULE", "整包独立判断单元不能重复", 409)
        if snapshot["execution_mode"] != "mechanism_test" or not getattr(
            transport, "isolated_mechanism_transport", False
        ):
            raise DomainError(
                "PACKAGE_SCORE_PRODUCTION_UNQUALIFIED",
                "真实图文与必要范围资格未成立，合成任务只能使用隔离机制端口",
                409,
            )

    def judge(self, packet, replicate):
        if (
            type(replicate) is not int
            or replicate not in {1, 2, 3}
            or packet["digest"] not in self.allowed
            or getattr(self.transport, "model", None) != profile.descriptor()["model_alias"]
            or getattr(self.transport, "provider", None) != profile.descriptor()["provider"]
        ):
            raise DomainError(
                "PACKAGE_SCORE_CALL_INVALID", "调用的方法、模型或独立判断身份不符", 409
            )
        request = profile.request_for(packet)
        reservation = self.authority.reserve(
            self.lease,
            chapter_id=self.allowed[packet["digest"]],
            replicate=replicate,
            request_digest=sha(request),
            profile_digest=profile.digest(),
            reserved_fee=str(self.reserve_fee),
        )
        identity = str(reservation["call_id"])
        if not reservation["new_reservation"]:
            recorded = self.authority.success(self.lease, identity)
            if (
                recorded["request_digest"] != sha(request)
                or recorded["profile_digest"] != profile.digest()
                or recorded["model"] != profile.descriptor()["model_alias"]
                or recorded["execution_purpose"] != "score"
            ):
                raise DomainError("PACKAGE_SCORE_RECEIPT_INVALID", "既有调用不属于此冻结输入", 409)
            data = recorded["data"]
        else:
            # reserve has committed, and no database connection remains open during
            # transport. Only a new logical receipt permits exactly one send.
            try:
                generated = self.transport.generate(**request)
            except Exception as error:
                details = error.details if isinstance(error, DomainError) else {}
                state = "not_sent" if details.get("billing_state") == "not_sent" else "unknown"
                self.authority.settle(
                    identity,
                    self.lease,
                    state=state,
                    response=None,
                    estimated_fee="0" if state == "not_sent" else None,
                )
                raise DomainError(
                    "PACKAGE_SCORE_CALL_UNRESOLVED",
                    "调用未完成，未补发；未知计费保留预留并待对账",
                    409,
                ) from None
            try:
                if generated.model != profile.descriptor()["model_alias"]:
                    raise ValueError("provider model changed")
                fee = usage_estimate(generated.usage, self.snapshot["price_config"])
                response = clean(
                    {
                        "schema": "controlled-score-response/1",
                        "execution_purpose": "score",
                        "data": generated.data,
                        "content": generated.content,
                        "usage": generated.usage,
                        "model": generated.model,
                        "request_id": generated.request_id,
                        "response_id": generated.response_id,
                        "finish_reason": generated.finish_reason,
                        "request_digest": sha(request),
                        "profile_digest": profile.digest(),
                        "formal_scoring_eligible": False,
                        "fee_basis": "usage_price_estimate",
                    }
                )
                raw = json.dumps(
                    response,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                if len(raw.encode()) > 2097152:
                    raise ValueError("unbounded response")
            except Exception:
                self.authority.settle(
                    identity,
                    self.lease,
                    state="unknown",
                    response=None,
                    estimated_fee=None,
                )
                raise DomainError(
                    "PACKAGE_SCORE_RESPONSE_UNVERIFIED", "响应计费无法核验，保留预留且未补发", 409
                ) from None
            # Usage is truthful even if the judgment is invalid. Validation is never
            # allowed to turn a charged invalid response into a zero-fee retry.
            self.authority.settle(
                identity,
                self.lease,
                state="succeeded",
                response=raw,
                estimated_fee=str(fee),
            )
            data = generated.data
            recorded = response
        try:
            if (
                recorded["finish_reason"] != "stop"
                or json.loads(recorded["content"]) != data
                or not recorded["response_id"]
            ):
                raise ValueError("raw response mismatch")
        except (ValueError, TypeError, KeyError):
            raise DomainError(
                "PACKAGE_SCORE_RAW_RESPONSE_INVALID", "原始响应未准确绑定完整结构化判断", 409
            ) from None
        profile.validate_judgment(packet, data)
        return {"replicate": replicate, "call_id": identity, "payload": deepcopy(data)}


def execute(authority, lease, *, transport):
    snapshot = authority.input(lease)
    if (
        snapshot["schema"] != "owned-package-technical-score/1"
        or snapshot["execution_purpose"] != "package_technical_judgment"
        or snapshot["execution_mode"] != "mechanism_test"
        or snapshot["method_digest"] != profile.digest()
        or snapshot["formal_scoring_eligible"] is not False
        or not snapshot["chapters"]
    ):
        raise DomainError("PACKAGE_SCORE_OWNED_SCOPE_INVALID", "专用任务缺少正确完整整包输入", 409)
    packets = [row["package"] for row in snapshot["chapters"]]
    rule_ids = [packet["rule"]["id"] for packet in packets]
    if len(set(rule_ids)) != len(rule_ids) or sorted(rule_ids) != sorted(
        snapshot["necessary_rule_ids"]
    ):
        raise DomainError("PACKAGE_SCORE_RULE_SET_INVALID", "必须逐项覆盖全部明确适用条款", 409)
    # Validate every complete request before spending even one reservation.
    for packet in packets:
        profile.request_for(packet)
    port = PackageScorePort(authority, lease, snapshot, transport)
    items, seen = [], set()
    for packet in packets:
        judgments = []
        for replicate in (1, 2, 3):
            judgment = port.judge(deepcopy(packet), replicate)
            if judgment["call_id"] in seen:
                raise DomainError(
                    "PACKAGE_SCORE_REPLICATE_REUSED", "重试或同一响应不能充作独立判断", 409
                )
            seen.add(judgment["call_id"])
            judgments.append(judgment)
        items.append(
            {
                "rule_id": packet["rule"]["id"],
                "package_digest": packet["digest"],
                "valid_replicates": 3,
                "judgments": judgments,
            }
        )
    result = {
        "schema": "package-technical-judgments/1",
        "execution_purpose": "package_technical_judgment",
        "execution_mode": "mechanism_test",
        "scope_id": snapshot["scope_id"],
        "scope_digest": snapshot["scope_digest"],
        "input_digest": snapshot["input_digest"],
        "method_digest": profile.digest(),
        "provider": profile.descriptor()["provider"],
        "model_alias": profile.descriptor()["model_alias"],
        "items": items,
        "numeric_prediction": None,
        "formal_scoring_eligible": False,
        "training_eligible": False,
        "metrics_eligible": False,
        "eligibility_reasons": ["isolated_synthetic_mechanism_only"],
    }
    authority.publish(lease, result)
    return result
