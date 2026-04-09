"""
Twilio handoff: send the summary directly as a WhatsApp message via
the Twilio Messaging API.

This is a simpler alternative to the webhook strategy when there is no
external workflow engine (e.g. n8n) in front of the API. The tradeoff is
that the API process becomes responsible for the Twilio call, so any
retries, templating or rate-limiting must live here.
"""
import logging

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


# Standard message template for a qualified-lead handoff.
# Kept in this module on purpose: it's tightly coupled to the channel.
_MESSAGE_TEMPLATE = """\
🔥 New qualified lead!
📱 User id: {user_id}

🤖 Conversation summary:
{summary}

✅ Please reach out as soon as possible to continue the conversation.
"""


class TwilioHandoff:
    """Dispatches qualified leads directly via Twilio WhatsApp."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_number: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._to_number = to_number
        self._timeout = timeout_seconds

    def is_enabled(self) -> bool:
        return all(
            [
                self._account_sid,
                self._auth_token,
                self._from_number,
                self._to_number,
            ]
        )

    def dispatch(self, user_id: str, summary: str) -> None:
        if not self.is_enabled():
            logger.info("Twilio handoff not fully configured; skipping")
            return

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        body = _MESSAGE_TEMPLATE.format(user_id=user_id, summary=summary.strip())

        try:
            response = requests.post(
                url,
                data={
                    "To": self._to_number,
                    "From": self._from_number,
                    "Body": body,
                },
                auth=HTTPBasicAuth(self._account_sid, self._auth_token),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self._timeout,
            )
            logger.info(
                "Twilio handoff dispatched: status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
        except requests.RequestException as exc:
            logger.error("Failed to dispatch Twilio handoff: %s", exc)
