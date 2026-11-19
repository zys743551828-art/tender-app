"""Read the current tariff and project its exact authoring reservation upper bound."""

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from packages.assistant import budget
from packages.assistant.generation_batch_contracts import SCALE
from packages.assistant.generation_batches import price_view, reservation_estimate
from packages.assistant.provider import configured
from packages.authoring import package_job_authority
from packages.domain.runtime import DomainError, etag

PROTOCOL = "exact-authoring-fee-quote/1"
MAX_OUTPUT_TOKENS = 2048
_FEE_LIMIT: ContextVar[tuple[UUID | None, int | None] | None] = ContextVar(
    "exact_package_fee_limit", default=None
)


@contextmanager
def fee_limit(price_version_id: UUID | None, max_reserved_minor: int | None):
    """Bind new-admission consent to the current HTTP request, never to a worker manifest."""
    token = _FEE_LIMIT.set((price_version_id, max_reserved_minor))
    try:
        yield
    finally:
        _FEE_LIMIT.reset(token)


def require_admitted_price(c, price_version_id):
    approval = _FEE_LIMIT.get()
    if approval is None:
        # Existing native callers/stored command receipts remain compatible.
        return
    expected, approved_upper = approval
    if expected is not None and str(expected) != str(price_version_id):
        raise DomainError("AUTHORING_PACKAGE_PRICE_CHANGED", "价格已更新，请重新确认费用", 409)
    price = c.execute(
        "SELECT * FROM design.assistant_price_versions WHERE id=%s "
        "AND valid_from<=clock_timestamp() AND valid_until>clock_timestamp()",
        (price_version_id,),
    ).fetchone()
    if price is None:
        raise DomainError("AUTHORING_PACKAGE_PRICE_CHANGED", "价格已失效，请重新确认费用", 409)
    if expected is None or approved_upper is None:
        if price["source_kind"] == "explicit_mock_fixture":
            # budget.checked_price has already required an actual MockTransport.
            return
        raise DomainError(
            "AUTHORING_PACKAGE_FEE_CONFIRMATION_REQUIRED",
            "请先读取并确认本次费用预留上限，未创建任务",
            409,
        )
    if _estimate(price) > approved_upper:
        raise DomainError("AUTHORING_PACKAGE_FEE_LIMIT", "预留上限超过已确认费用，未创建任务", 409)


def _estimate(price):
    projected = price_view(price)
    if projected["amount_scale"] != SCALE:
        raise DomainError("ASSISTANT_PRICE_UNAVAILABLE", "报价单位无法核对，未授权费用", 409)
    return reservation_estimate(projected, MAX_OUTPUT_TOKENS)


def quote(c, row):
    config = row["config"]["definition"]
    if config["source_selection"]["mode"] != "exact_package_authoring":
        raise DomainError(
            "AUTHORING_PACKAGE_QUOTE_UNSUPPORTED", "仅固定整包章节任务支持此报价", 422
        )
    if row["paused"]:
        raise DomainError("TASK_TEMPLATE_PAUSED", "模板已暂停", 409)
    package_job_authority.require_schema(c)
    price = budget.checked_price(c, configured())
    return {
        "protocol": PROTOCOL,
        "bid_id": row["bid_id"],
        "definition_id": row["id"],
        "definition_version_id": row["version_id"],
        "template_etag": etag("task-template", row["id"], row["revision"]),
        "price_version_id": price["id"],
        "currency": price["currency"],
        "amount_scale": SCALE,
        "reserved_minor": _estimate(price),
        "valid_until": price["valid_until"],
        "estimate_not_provider_spend_cap": True,
    }
