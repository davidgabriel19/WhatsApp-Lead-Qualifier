"""
Core lead-qualification service.

Orchestrates session_store + catalog + ai_client + handoff to implement
the full flow: receive message → reply → (if qualified) summarize → dispatch.
"""
import logging
from pathlib import Path

from app.catalog import Catalog
from app.handoff.base import HandoffClient
from app.services.ai_client import AIClient
from app.session_store import SessionStore

logger = logging.getLogger(__name__)


class QualifierService:
    """High-level service encapsulating the qualification flow."""

    def __init__(
        self,
        ai_client: AIClient,
        session_store: SessionStore,
        catalog: Catalog,
        handoff: HandoffClient,
        system_prompt_path: str,
        summary_prompt_path: str,
        qualified_lead_tag: str,
        max_tokens_chat: int,
        max_tokens_summary: int,
    ) -> None:
        self._ai = ai_client
        self._sessions = session_store
        self._catalog = catalog
        self._handoff = handoff
        self._qualified_tag = qualified_lead_tag
        self._max_tokens_chat = max_tokens_chat
        self._max_tokens_summary = max_tokens_summary

        # Prompts are loaded once at startup. For hot-reload, move these
        # reads into the methods that use them.
        self._system_prompt = Path(system_prompt_path).read_text(encoding="utf-8")
        self._summary_prompt = Path(summary_prompt_path).read_text(encoding="utf-8")

    # --- Read-only accessors used by /health --------------------------------

    @property
    def sessions(self) -> SessionStore:
        return self._sessions

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    # --- Public API ---------------------------------------------------------

    def reset_user(self, user_id: str) -> None:
        """Drop a user's conversation history."""
        self._sessions.reset(user_id)
        logger.info("History reset for user=%s", user_id)

    def process_message(self, user_id: str, message: str) -> tuple[str, bool]:
        """
        Process a user message and return (reply, should_dispatch_handoff).

        If `should_dispatch_handoff` is True, the caller is expected to
        invoke `generate_and_dispatch_handoff(user_id)` — typically in a
        background task so the end-user reply is not delayed.
        """
        # 1. Append the user message to history
        self._sessions.append(user_id, {"role": "user", "content": message})
        history = self._sessions.get_history(user_id)

        # 2. Build the prompt: system + catalog + history
        system_content = (
            f"{self._system_prompt}\n\n"
            f"Available catalog:\n{self._catalog.format_for_prompt()}"
        )
        messages = [{"role": "system", "content": system_content}, *history]

        # 3. Call the model
        try:
            reply = self._ai.chat(messages, max_tokens=self._max_tokens_chat)
        except Exception as exc:
            logger.exception("Model call failed for user=%s: %s", user_id, exc)
            raise

        # 4. Detect the qualification tag (whitespace-tolerant comparison)
        normalized = reply.lower().replace(" ", "")
        is_qualified = self._qualified_tag.lower().replace(" ", "") in normalized
        if is_qualified:
            reply = reply.replace(self._qualified_tag, "").strip()

        # 5. Persist the assistant reply (tag stripped) in the history
        self._sessions.append(user_id, {"role": "assistant", "content": reply})

        return reply, is_qualified

    def generate_and_dispatch_handoff(self, user_id: str) -> None:
        """
        Generate a summary of the conversation and dispatch it via the
        configured handoff client. Designed to run in a background task.
        """
        if not self._handoff.is_enabled():
            return

        history = self._sessions.get_history(user_id)
        if not history:
            logger.warning("Handoff requested but history is empty for user=%s", user_id)
            return

        summary_messages = [
            {"role": "system", "content": self._summary_prompt},
            *history,
        ]
        try:
            summary = self._ai.chat(summary_messages, max_tokens=self._max_tokens_summary)
            self._handoff.dispatch(user_id, summary)
        except Exception as exc:
            logger.exception("Failed to generate/dispatch handoff for user=%s: %s", user_id, exc)
