from typing import Any

import litellm


class LLMError(RuntimeError):
    """Raised when the provider call fails (network, auth, rate limit, etc.)."""


class LLMClient:
    """Single chokepoint for LLM traffic: completion + token accounting.

    Every LLM call in DocPulse goes through here so retries, accounting, and
    mocking live in one place (boundary rule from the master plan).
    """

    def __init__(self, model: str | None) -> None:
        if not model:
            raise ValueError(
                "no model configured; set `model:` in docpulse.yml or pass --model"
            )
        self.model = model
        self.tokens_used = 0

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> Any:
        """Call the model once and return the assistant message.

        Accumulates token usage. Wraps any provider exception in LLMError.
        """
        try:
            response = litellm.completion(model=self.model, messages=messages, tools=tools)
        except Exception as exc:  # noqa: BLE001 — normalize every provider failure
            raise LLMError(str(exc)) from exc
        usage = getattr(response, "usage", None)
        self.tokens_used += getattr(usage, "total_tokens", 0) or 0
        return response.choices[0].message
