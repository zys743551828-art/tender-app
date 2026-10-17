"""Integer-only ceiling estimates; never confuses a reservation with an invoice cap."""

from packages.domain.runtime import DomainError

SCALE = 1_000_000_000


def ceiling_charge(input_tokens, output_tokens, input_per_million_minor, output_per_million_minor):
    values = (input_tokens, output_tokens, input_per_million_minor, output_per_million_minor)
    if any(type(value) is not int or value < 0 for value in values):
        raise DomainError(
            "ASSISTANT_PRICE_INVALID", "计价数量及金额须为非负整数，不能使用浮点或布尔值", 422
        )
    numerator = input_tokens * input_per_million_minor + output_tokens * output_per_million_minor
    return (numerator + 999_999) // 1_000_000


def worst_case(price, max_output):
    if type(max_output) is not int or not 1 <= max_output <= price["output_hard_ceiling"]:
        raise DomainError("ASSISTANT_PRICE_UNAVAILABLE", "输出上限不在冻结的可信计价范围内", 409)
    return ceiling_charge(
        price["input_hard_ceiling"],
        max_output,
        price["input_per_million_minor"],
        price["output_per_million_minor"],
    )
