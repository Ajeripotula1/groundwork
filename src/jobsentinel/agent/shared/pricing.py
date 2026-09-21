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

# Anthropic prompt caching (see jobsentinel.agent.score_fit.agent's
# CacheConfig usage) prices cache writes/reads as multipliers of the same
# model's base input price, not flat rates of their own - a write (first
# call that populates the cache point) costs *more* than a normal input
# token because it also has to run inference over that prefix once fully,
# while a read (a later call that hits the same prefix) costs far less
# because it skips reprocessing it. These multipliers are Anthropic's
# published 5-minute-TTL cache rates (our cache_config leaves TTL at the
# 5m default) and are model-independent - same multiplier at every tier.
_CACHE_WRITE_MULTIPLIER = Decimal("1.25")
_CACHE_READ_MULTIPLIER = Decimal("0.10")


def estimate_cost_usd(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal | None:
    """Return the estimated cost in USD for one call's usage, or None if
    `model_id` isn't in the pricing table above (better to store no cost
    than a silently wrong one for a model nobody's priced yet).

    `cache_read_tokens`/`cache_write_tokens` default to 0 (not None) so
    callers that never touch caching - or a model that doesn't support it -
    can omit them and get exactly the pre-caching cost back.
    """
    for key, (input_price, output_price) in _PRICE_PER_MTOK_USD.items():
        if key in model_id:
            cost = (
                Decimal(input_tokens) * input_price
                + Decimal(output_tokens) * output_price
                + Decimal(cache_write_tokens) * input_price * _CACHE_WRITE_MULTIPLIER
                + Decimal(cache_read_tokens) * input_price * _CACHE_READ_MULTIPLIER
            )
            return cost / Decimal(1_000_000)
    return None
