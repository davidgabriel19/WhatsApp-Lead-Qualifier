"""
Webhook handoff: POST the summary to an HTTP endpoint.

Typical use case: an n8n workflow listens on the URL, receives the
summary, and relays it to a human agent via whatever channel the team
already uses (WhatsApp, Slack, email, CRM, ...).
"""
import logging

import requests

logger = logging.getLogger(__name__)


class WebhookHandoff:
    """Dispatches qualified leads to an external HTTP webhook."""

    def __init__(
        self,
        webhook_url: str,
        webhook_secret: str,
        agent_phone: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._webhook_secret = webhook_secret
        self._agent_phone = agent_phone
        self._timeout = timeout_seconds

    def is_enabled(self) -> bool:
        return bool(self._webhook_url and self._agent_phone)

    def dispatch(self, user_id: str, summary: str) -> None:
        if not self.is_enabled():
            logger.info("Webhook handoff not configured; skipping")
            return

        payload = {
            "to": self._agent_phone,
            "body": summary,
            "lead_user_id": user_id,
        }
        headers = {}
        if self._webhook_secret:
            headers["x-api-key"] = self._webhook_secret

        try:
            response = requests.post(
                self._webhook_url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            logger.info(
                "Webhook handoff dispatched: status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
        except requests.RequestException as exc:
            logger.error("Failed to dispatch webhook handoff: %s", exc)
