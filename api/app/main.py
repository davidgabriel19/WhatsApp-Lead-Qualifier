"""
FastAPI entry point.

This module is kept thin: it wires dependencies together and exposes
endpoints. All business logic lives under app/services and app/handoff.
"""
import logging

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status

from app.catalog import Catalog
from app.config import Settings, get_settings
from app.handoff.factory import build_handoff_client
from app.schemas import ChatRequest, ChatResponse, HealthResponse
from app.services.ai_client import AIClient
from app.services.qualifier import QualifierService
from app.session_store import SessionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="WhatsApp Lead Qualifier API",
    description=(
        "FastAPI service that qualifies leads conversationally via an LLM. "
        "Designed to be driven by a workflow engine (e.g. n8n) connected to "
        "WhatsApp, but works standalone as well."
    ),
    version="1.0.0",
)


# --- Dependency wiring ------------------------------------------------------
# The qualifier singleton is built lazily on the first request. Settings are
# cached via lru_cache in app.config, so Depends(get_settings) is free.

_qualifier: QualifierService | None = None


def get_qualifier(settings: Settings = Depends(get_settings)) -> QualifierService:
    global _qualifier
    if _qualifier is None:
        ai_client = AIClient(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            timeout_seconds=settings.OPENAI_TIMEOUT_SECONDS,
        )
        session_store = SessionStore(
            ttl_minutes=settings.SESSION_TTL_MINUTES,
            maxsize=settings.SESSION_MAX_SIZE,
        )
        catalog = Catalog(path=settings.CATALOG_PATH)
        handoff = build_handoff_client(settings)

        _qualifier = QualifierService(
            ai_client=ai_client,
            session_store=session_store,
            catalog=catalog,
            handoff=handoff,
            system_prompt_path=settings.SYSTEM_PROMPT_PATH,
            summary_prompt_path=settings.SUMMARY_PROMPT_PATH,
            qualified_lead_tag=settings.QUALIFIED_LEAD_TAG,
            max_tokens_chat=settings.OPENAI_MAX_TOKENS_CHAT,
            max_tokens_summary=settings.OPENAI_MAX_TOKENS_SUMMARY,
        )
    return _qualifier


# --- Endpoints --------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health(
    settings: Settings = Depends(get_settings),
    qualifier: QualifierService = Depends(get_qualifier),
) -> HealthResponse:
    """Lightweight health check — useful for platform health probes."""
    return HealthResponse(
        status="ok",
        active_sessions=qualifier.sessions.active_count(),
        catalog_items=qualifier.catalog.size(),
        handoff_strategy=settings.HANDOFF_STRATEGY,
    )


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    qualifier: QualifierService = Depends(get_qualifier),
) -> ChatResponse:
    """
    Main endpoint: accept a user message, return the assistant reply, and
    — when the lead is qualified — schedule a handoff in the background.
    """
    # Simple API-key authentication in the request body. For public
    # deployments prefer moving this to an Authorization: Bearer header.
    if request.api_key != settings.API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # Manual reset command (debug helper)
    if request.message.strip().lower() == settings.RESET_COMMAND.lower():
        qualifier.reset_user(request.user_id)
        return ChatResponse(reply="✅ History cleared.")

    try:
        reply, is_qualified = qualifier.process_message(
            user_id=request.user_id,
            message=request.message,
        )
    except Exception as exc:
        logger.exception("Error processing message: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error while processing the message",
        )

    if is_qualified:
        background_tasks.add_task(qualifier.generate_and_dispatch_handoff, request.user_id)

    return ChatResponse(reply=reply)
