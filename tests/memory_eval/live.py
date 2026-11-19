"""Budgeted access to the fixed provider for the TC-347 synthetic trial."""

from math import ceil

import anthropic

# Reserve at the published long-context rates and KRW 2,000/USD.
INPUT_RESERVE = 16_000
INPUT_ESTIMATE_LIMIT = 8_000
OUTPUT_LIMIT = 6_000
BUDGET_KRW = 10_000


def reserve_krw(max_tokens):
    return ceil((INPUT_RESERVE + 5 * max_tokens) / 1000)


class TrialError(RuntimeError):
    """A stop reason safe to print without the provider's response body."""


class LiveTrial:
    def __init__(self, client, model):
        self.client = client
        self.model = model
        self.requests = 0
        self.reserved_krw = 0
        self.input_tokens = 0
        self.output_tokens = 0

    async def create_once(self, body, timeout):
        if (body["model"] != self.model or body.get("tools")
                or not 1 <= body["max_tokens"] <= OUTPUT_LIMIT):
            raise TrialError("request_outside_trial_limits")

        # Send no cache controls, tools, or caller-specific transport options.
        system = body["system"]
        if isinstance(system, list):
            system = [{k: v for k, v in block.items() if k != "cache_control"} for block in system]
        request = {**body, "system": system}
        reserve = reserve_krw(body["max_tokens"])
        if self.reserved_krw + reserve > BUDGET_KRW:
            raise TrialError("trial_budget_exhausted")

        try:
            count = {key: request[key] for key in ("model", "system", "messages", "output_config") if key in request}
            estimate = await self.client.messages.count_tokens(
                **count, timeout=20,
            )
            if estimate.input_tokens > INPUT_ESTIMATE_LIMIT:
                raise TrialError("input_estimate_exceeds_limit")
            self.requests += 1
            self.reserved_krw += reserve
            response = await self.client.messages.create(**request, timeout=timeout)
        except anthropic.APIError as error:
            status = getattr(error, "status_code", None)
            suffix = f":{status}" if isinstance(status, int) else ""
            raise TrialError(f"{type(error).__name__}{suffix}") from None

        usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        if (usage.input_tokens > INPUT_RESERVE or usage.output_tokens > body["max_tokens"]
                or usage.cache_creation_input_tokens or usage.cache_read_input_tokens):
            raise TrialError("provider_usage_outside_reservation")
        return response

    def totals(self):
        return {
            "provider_calls": self.requests, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "cost_reservation_krw": self.reserved_krw,
        }
