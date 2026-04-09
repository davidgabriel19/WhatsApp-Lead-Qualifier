"""
Handoff protocol.

A handoff is the act of transferring a qualified lead from the AI
assistant to a human agent. Different deployments use different channels
(n8n webhook, direct Twilio message, Slack, email, ...), so the qualifier
depends only on this protocol and picks a concrete implementation at
startup based on the HANDOFF_STRATEGY setting.
"""
from typing import Protocol


class HandoffClient(Protocol):
    """Contract every handoff implementation must satisfy."""

    def is_enabled(self) -> bool:
        """Return True when the client is configured and ready to dispatch."""
        ...

    def dispatch(self, user_id: str, summary: str) -> None:
        """
        Deliver a conversation summary to a human agent.

        Implementations SHOULD swallow network/API errors (logging them)
        so that a handoff failure never breaks the end-user reply — the
        bot has already done its job, the handoff is best-effort.
        """
        ...
