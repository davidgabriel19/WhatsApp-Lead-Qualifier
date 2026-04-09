"""
Application settings loaded from environment variables.

Uses pydantic-settings for automatic validation — if a required variable is
missing, the application fails at startup instead of breaking at runtime.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All environment variables consumed by the API.
    See `.env.example` for documentation of each field.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- API authentication --------------------------------------------------
    # Token that clients (e.g. the n8n workflow) must send in the request
    # body to access the /chat endpoint.
    API_KEY: str = Field(..., description="Shared secret for authenticating API calls")

    # --- AI provider ---------------------------------------------------------
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key")
    OPENAI_MODEL: str = Field(default="gpt-4o", description="Model used for chat and summary")
    OPENAI_MAX_TOKENS_CHAT: int = Field(default=1000)
    OPENAI_MAX_TOKENS_SUMMARY: int = Field(default=500)
    OPENAI_TIMEOUT_SECONDS: float = Field(default=30.0)

    # --- Session management --------------------------------------------------
    # Minutes of inactivity after which a conversation is evicted from memory.
    SESSION_TTL_MINUTES: int = Field(default=90)
    SESSION_MAX_SIZE: int = Field(default=10_000)

    # --- Domain data ---------------------------------------------------------
    # Path (relative to the api working directory) to the catalog JSON file.
    # The repo ships with a fictional sample under data/catalog.sample.json.
    CATALOG_PATH: str = Field(default="data/catalog.sample.json")

    # --- Prompts -------------------------------------------------------------
    SYSTEM_PROMPT_PATH: str = Field(default="prompts/system_prompt.md")
    SUMMARY_PROMPT_PATH: str = Field(default="prompts/summary_prompt.md")

    # --- Conversation markers ------------------------------------------------
    # Tag the model emits to signal that the lead is qualified.
    QUALIFIED_LEAD_TAG: str = Field(default="#qualified_lead")
    # Command a user can send to reset their conversation (debug helper).
    RESET_COMMAND: str = Field(default="#reset")

    # --- Handoff strategy ----------------------------------------------------
    # How to deliver the summary of a qualified lead to a human agent:
    #   * "none"    — disabled, the API just returns the reply
    #   * "webhook" — POST the summary to LEAD_HANDOFF_WEBHOOK_URL (e.g. n8n)
    #   * "twilio"  — send the summary directly via Twilio WhatsApp API
    HANDOFF_STRATEGY: Literal["none", "webhook", "twilio"] = Field(default="none")

    # --- Handoff: webhook strategy -------------------------------------------
    LEAD_HANDOFF_WEBHOOK_URL: str = Field(default="")
    LEAD_HANDOFF_WEBHOOK_SECRET: str = Field(default="")
    # Phone number / identifier passed in the webhook payload (recipient).
    AGENT_PHONE_NUMBER: str = Field(default="")

    # --- Handoff: twilio strategy --------------------------------------------
    TWILIO_ACCOUNT_SID: str = Field(default="")
    TWILIO_AUTH_TOKEN: str = Field(default="")
    # E.164 formatted, prefixed with "whatsapp:", e.g. "whatsapp:+14155238886"
    TWILIO_FROM_NUMBER: str = Field(default="")
    TWILIO_TO_NUMBER: str = Field(default="")


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached singleton of the settings.
    lru_cache avoids re-reading the .env file on every call.
    """
    return Settings()
