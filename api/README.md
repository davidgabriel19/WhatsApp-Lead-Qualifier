# API — WhatsApp Lead Qualifier

FastAPI service that qualifies leads conversationally using an LLM and
hands off qualified leads to a human agent through a pluggable channel.

This directory is one of three components of the broader
[`whatsapp-lead-qualifier`](../README.md) project; see the top-level
README for the architecture overview.

## Features

- **Stateful conversations** per user, with automatic expiration of
  idle sessions.
- **Domain-agnostic prompts** and catalog — swap the JSON file and the
  prompt to adapt to a new vertical without touching code.
- **Pluggable handoff strategy**: `none`, `webhook` (e.g. n8n), or
  `twilio` (direct WhatsApp via Twilio) — selected by env var.
- **Background handoff**: the qualified-lead summary is generated and
  dispatched in a FastAPI `BackgroundTask` so the end-user reply is
  never delayed.
- **Typed everywhere**: Pydantic models for requests, responses, and
  settings — invalid input fails fast, Swagger docs are free.
- **Layered architecture**: config, schemas, session store, catalog,
  AI client, handoff clients, and orchestrator are all independent and
  independently testable.

## Project layout

```
api/
├── app/
│   ├── main.py              # FastAPI entry point (thin wiring layer)
│   ├── config.py            # pydantic-settings, loaded from .env
│   ├── schemas.py           # Pydantic request/response models
│   ├── session_store.py     # In-memory TTL-based conversation store
│   ├── catalog.py           # JSON catalog loader + prompt formatter
│   ├── services/
│   │   ├── ai_client.py     # OpenAI wrapper (thin, swappable)
│   │   └── qualifier.py     # Orchestrator — the core service
│   └── handoff/
│       ├── base.py          # HandoffClient Protocol
│       ├── none.py          # no-op
│       ├── webhook.py       # POST summary to an HTTP webhook
│       ├── twilio.py        # Send summary via Twilio WhatsApp API
│       └── factory.py       # Picks a strategy from settings
├── prompts/
│   ├── system_prompt.md     # Domain-agnostic system prompt
│   └── summary_prompt.md    # Prompt used to summarize on handoff
├── data/
│   └── catalog.sample.json  # Fictional sample catalog
├── tests/                   # Pytest unit tests (no network needed)
├── .env.example             # Documented environment variables
├── Dockerfile
├── pyproject.toml           # ruff + pytest config
├── requirements.txt
└── requirements-dev.txt
```

## Quick start

### 1. Install

```bash
cd api
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For development (adds pytest, httpx, ruff):

```bash
pip install -r requirements-dev.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set at minimum:
#   API_KEY           — any long random string
#   OPENAI_API_KEY    — your OpenAI key
```

All other variables have sensible defaults. The handoff strategy
defaults to `none`, meaning the API will reply to messages but will
not try to contact any human agent — ideal for early testing.

### 3. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for an interactive Swagger UI.

### 4. Talk to it

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "the-key-you-set-in-env",
    "user_id": "test-user-1",
    "message": "Hi, I am looking for a premium item under $1500"
  }'
```

## Endpoints

### `POST /chat`

Main endpoint. Accepts a user message and returns the assistant reply.
If the model emits the qualification tag, the API schedules a handoff
in the background before returning.

Request body:

```json
{
  "api_key": "string",
  "user_id": "string",
  "message": "string"
}
```

Response body:

```json
{
  "reply": "string"
}
```

Returns `401 Unauthorized` if `api_key` doesn't match the server's
`API_KEY` environment variable.

### `GET /health`

Lightweight health probe. Returns the number of active sessions,
catalog size, and the configured handoff strategy. Does not require
authentication — keep that in mind when exposing it publicly.

## Configuration reference

See [`.env.example`](.env.example) for the full, commented list.
The most important settings:

| Variable              | Purpose                                                     |
|-----------------------|-------------------------------------------------------------|
| `API_KEY`             | Shared secret for `/chat` (required)                        |
| `OPENAI_API_KEY`      | OpenAI credentials (required)                               |
| `OPENAI_MODEL`        | Model name — defaults to `gpt-4o`                           |
| `CATALOG_PATH`        | Path to the catalog JSON to load at startup                 |
| `SYSTEM_PROMPT_PATH`  | Path to the system prompt (markdown)                        |
| `SUMMARY_PROMPT_PATH` | Path to the summary prompt used during handoff              |
| `SESSION_TTL_MINUTES` | Idle timeout before a conversation is dropped (default 90)  |
| `QUALIFIED_LEAD_TAG`  | Tag the model emits to trigger handoff                      |
| `HANDOFF_STRATEGY`    | `none`, `webhook`, or `twilio`                              |

## Handoff strategies

The qualifier depends on a `HandoffClient` protocol; three concrete
implementations ship with the repo.

### `none`

Handoff is disabled. The API replies to messages but takes no action
when the lead is qualified. Useful for development and for deployments
where another system already owns the handoff step.

### `webhook`

When a lead is qualified, the API generates a summary and `POST`s it
to `LEAD_HANDOFF_WEBHOOK_URL` with the payload:

```json
{
  "to": "<AGENT_PHONE_NUMBER>",
  "body": "<summary>",
  "lead_user_id": "<user_id>"
}
```

If `LEAD_HANDOFF_WEBHOOK_SECRET` is set, it's forwarded as an
`x-api-key` header. This is the strategy used by the companion
[`workflow/`](../workflow/) n8n flow.

### `twilio`

When a lead is qualified, the API sends the summary directly as a
WhatsApp message through the Twilio Messaging API. Use this when you
don't want an intermediate workflow engine. Requires all four
`TWILIO_*` environment variables to be set.

## Adapting to a new domain

The system prompt and catalog are deliberately generic. To specialize
the assistant:

1. Replace `data/catalog.sample.json` with your real catalog
   (or point `CATALOG_PATH` to a different file). Any JSON array of
   objects works — the catalog formatter accepts both `title`/`price`
   and the legacy Portuguese `titulo`/`preco` keys.
2. Edit `prompts/system_prompt.md` to reflect your domain — the
   questions to ask during qualification, the tone, any compliance
   requirements, and the exact format in which items should be
   presented.
3. Optionally edit `prompts/summary_prompt.md` to match the fields
   your human agents care about.

No code changes are needed for any of this.

## Testing

```bash
cd api
pip install -r requirements-dev.txt
pytest
```

The tests mock the AI client and the handoff client, so they run
offline and do not consume OpenAI credits.

## Linting

```bash
ruff check .
ruff format .
```

## Deployment notes

- The included `Dockerfile` is production-ready, runs as a non-root
  user, and respects a `$PORT` env var injected by platforms like
  Railway, Render, and Fly.
- The session store is **in-memory and single-process**. If you scale
  beyond one worker/instance, replace `SessionStore` with a Redis-
  backed implementation. The rest of the app does not need to change —
  it only depends on the `SessionStore` interface.
- `/health` does not require authentication; fine for internal
  platform probes, but consider adding auth if you expose the API
  publicly.
