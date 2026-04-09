"""
Factory that picks a concrete HandoffClient based on settings.
"""
import logging

from app.config import Settings
from app.handoff.base import HandoffClient
from app.handoff.none import NoHandoff
from app.handoff.twilio import TwilioHandoff
from app.handoff.webhook import WebhookHandoff

logger = logging.getLogger(__name__)


def build_handoff_client(settings: Settings) -> HandoffClient:
    """Return a handoff client matching the configured strategy."""
    strategy = settings.HANDOFF_STRATEGY
    logger.info("Building handoff client with strategy=%s", strategy)

    if strategy == "webhook":
        return WebhookHandoff(
            webhook_url=settings.LEAD_HANDOFF_WEBHOOK_URL,
            webhook_secret=settings.LEAD_HANDOFF_WEBHOOK_SECRET,
            agent_phone=settings.AGENT_PHONE_NUMBER,
        )

    if strategy == "twilio":
        return TwilioHandoff(
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_FROM_NUMBER,
            to_number=settings.TWILIO_TO_NUMBER,
        )

    return NoHandoff()
