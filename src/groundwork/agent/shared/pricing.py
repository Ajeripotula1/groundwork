"""Turns an AgentResult's token usage into an estimated dollar cost, for
AgentRun.cost_usd (BUILD_PLAN.md Slice 3's "token budgets in the schema
from day one" column). Anthropic-on-Bedrock is billed at the same
per-token rate as the first-party Anthropic API for the same model -
these numbers are that published rate, current as of this slice being
written. Treat this as an estimate to spot cost regressions with, not an
invoice: re-check against the AWS bill/Bedrock pricing page if it ever
needs to be exact.

Keyed by substring match against the Bedrock inference-profile id (e.g.
"us.anthropic.claude-sonnet-4-6" contains "sonnet-4-6") rather than exact
match, since the "us."/"global." cross-region prefix and any trailing
version suffix vary by model without changing the price.
"""

from decimal import Decimal

# (input $ / 1M tokens, output $ / 1M tokens)
_PRICE_PER_MTOK_USD: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    """Return the estimated cost in USD for one call's usage, or None if
    `model_id` isn't in the pricing table above (better to store no cost
    than a silently wrong one for a model nobody's priced yet).
    """
    for key, (input_price, output_price) in _PRICE_PER_MTOK_USD.items():
        if key in model_id:
            return (
                Decimal(input_tokens) * input_price + Decimal(output_tokens) * output_price
            ) / Decimal(1_000_000)
    return None
