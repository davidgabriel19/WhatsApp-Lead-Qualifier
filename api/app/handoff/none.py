"""Null handoff: does nothing. Used when HANDOFF_STRATEGY=none."""
import logging

logger = logging.getLogger(__name__)


class NoHandoff:
    """No-op handoff implementation."""

    def is_enabled(self) -> bool:
        return False

    def dispatch(self, user_id: str, summary: str) -> None:
        logger.info("Handoff disabled; would have dispatched for user=%s", user_id)
