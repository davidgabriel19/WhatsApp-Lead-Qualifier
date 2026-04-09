"""
Thin wrapper over the OpenAI SDK.

Isolating the provider in a single class makes it easy to:
    * swap providers (Anthropic, Google, local model) without touching
      the rest of the codebase;
    * add retries, timeouts, and observability in one place;
    * mock it out cleanly in tests.
"""
import logging
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


class AIClient:
    """Chat completion client with centralized configuration."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        """
        Send a list of messages to the model and return the reply content.
        Exceptions propagate — error handling lives in the caller.
        """
        logger.debug("Calling model %s with %d messages", self._model, len(messages))
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""
