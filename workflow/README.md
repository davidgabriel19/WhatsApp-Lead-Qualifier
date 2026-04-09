# Workflow — WhatsApp Lead Qualifier

n8n workflow that sits between a WhatsApp provider (Twilio, WPPConnect,
Evolution API, ...) and the [`api/`](../api/) service, wiring the
conversation together and forwarding qualified-lead handoffs to a
human agent.

This directory is one of three components of the broader
[`whatsapp-lead-qualifier`](../README.md) project.

## Why an n8n workflow?

The API is deliberately WhatsApp-agnostic — it only knows how to talk
to an LLM and produce a reply. Everything WhatsApp-specific (receiving
inbound messages, sending outbound messages, authenticating with the
provider, handling retries and rate limits) lives in the workflow.
Keeping that separation has three benefits:

1. **Swap providers without touching the API.** Moving from Twilio to
   Evolution API, or adding a Telegram channel alongside WhatsApp,
   only requires editing the workflow.
2. **Business logic in a visual tool.** Non-developers on the team can
   tweak the routing, add notifications, or plug in a CRM node
   without deploying code.
3. **Retries and observability for free.** n8n gives you built-in
   execution history and retry controls for HTTP nodes.

## Project layout

```
workflow/
├── workflows/
│   └── whatsapp-lead-qualifier.json   # Importable n8n workflow
├── docker/
│   ├── Dockerfile                     # For platform deploy (Railway, etc.)
│   └── docker-compose.yml             # Local dev stack: postgres + n8n
├── .env.example
└── README.md
```

## Workflow overview

```
  WhatsApp provider
        │
        │ inbound webhook
        ▼
  ┌───────────────────────┐
  │ Incoming Message      │
  │ Webhook               │
  └─────────┬─────────────┘
            │
            ▼
  ┌───────────────────────┐
  │ Extract Message       │  pulls out user_id and message text
  └─────────┬─────────────┘
            │
            ├──────────────────┐
            │                  │
            ▼                  ▼
  ┌───────────────────┐   ┌──────────────────┐
  │ Call Qualifier API│   │ (passes raw ctx  │
  │ POST /chat        │   │  through Merge)  │
  └─────────┬─────────┘   └────────┬─────────┘
            │                      │
            └───────────┬──────────┘
                        ▼
              ┌──────────────────┐
              │ Merge Context    │
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ Prepare Reply    │  builds the outbound payload
              └────────┬─────────┘
                       ▼
              ┌──────────────────┐
              │ Send WhatsApp    │  Twilio Messages API
              │ Reply            │
              └──────────────────┘


  Independent branch — qualified lead handoff:

  ┌───────────────────┐     ┌──────────┐     ┌─────────────────┐     ┌──────────────────┐
  │ Handoff Webhook   │──▶ │ Wait 8s   │──▶ │ Prepare Handoff │──▶ │ Send WhatsApp    │
  │ (called by API)   │     └──────────┘     └─────────────────┘     │ Reply (reused)   │
  └───────────────────┘                                                └──────────────────┘
```

The **Handoff Webhook** is what the API calls when `HANDOFF_STRATEGY=webhook`
and the qualified-lead tag is emitted. The short wait gives the user
time to receive the final assistant reply before the human agent is
pinged.

## Quick start — local development

### 1. Start the stack

```bash
cd workflow
cp .env.example .env
# Edit .env and fill in QUALIFIER_API_URL, QUALIFIER_API_KEY,
# TWILIO_ACCOUNT_SID, WHATSAPP_FROM_NUMBER (and the Postgres/Basic
# Auth secrets if you care — defaults work for local).

docker compose -f docker/docker-compose.yml up -d
```

Open http://localhost:5678 and log in with the Basic Auth credentials
you set in `.env`.

### 2. Import the workflow

In the n8n UI:

1. Click **Workflows → Import from File**.
2. Pick `workflows/whatsapp-lead-qualifier.json`.
3. Click **Save**.

### 3. Configure credentials

The "Send WhatsApp Reply" node uses HTTP Basic Auth to call the Twilio
Messages API. Create a new credential in n8n:

1. **Credentials → Create → HTTP Basic Auth**
2. **User**: your Twilio Account SID
3. **Password**: your Twilio Auth Token
4. Save and attach it to the "Send WhatsApp Reply" node.

### 4. Point your WhatsApp provider at the webhook

Each node that starts with "Webhook" has a test and production URL
you can copy from the n8n UI (look for the "Webhook URLs" panel on the
node). Point your WhatsApp provider (e.g. Twilio Sandbox → "When a
message comes in") at the **Incoming Message Webhook** production URL.

### 5. Expose the API

In a separate terminal, start the companion API (see [`../api/`](../api/)):

```bash
cd ../api
uvicorn app.main:app --port 8000
```

If you're running the API on your host machine and n8n in Docker, the
URL inside the n8n container is `http://host.docker.internal:8000`
(this is the default in `.env.example`).

### 6. Enable the workflow

Toggle the "Active" switch in the top-right corner of the n8n editor.
The workflow is now live and handling inbound WhatsApp messages.

## Deploying to Railway / Render / Fly

The `docker/Dockerfile` is a minimal wrapper around `n8nio/n8n:latest`
that the platform can build directly from this directory. You'll need
to:

1. Provision a managed Postgres instance and set `DB_POSTGRESDB_*` env
   vars on the n8n service to point at it.
2. Set all the n8n and workflow variables listed in `.env.example`
   directly in the platform's environment settings (not as a committed
   `.env` file).
3. Set `WEBHOOK_URL` to your public https URL so webhook URLs are
   generated correctly.
4. After the first deploy, import `workflows/whatsapp-lead-qualifier.json`
   through the UI — n8n stores workflows in the database, not in the
   image.

## Environment variables

The workflow reads four variables at runtime through `$env.*`
expressions in the nodes:

| Variable                | Used by                                      |
|-------------------------|----------------------------------------------|
| `QUALIFIER_API_URL`     | Call Qualifier API node                      |
| `QUALIFIER_API_KEY`     | Call Qualifier API node                      |
| `TWILIO_ACCOUNT_SID`    | Send WhatsApp Reply node (URL path)          |
| `WHATSAPP_FROM_NUMBER`  | Prepare Reply node (sender identifier)       |

These must be set in the n8n environment (either via `docker-compose.yml`
or the platform's environment settings). The Twilio Auth Token lives in
an n8n credential, never in an env var.

## Adapting to a different WhatsApp provider

The workflow is written against Twilio because that was the simplest
provider to reach from n8n, but it's easy to swap:

1. Replace the **Incoming Message Webhook**'s **Extract Message** node
   to pull `message` and `user_id` out of your provider's payload
   instead of Twilio's `Body` / `From`.
2. Replace the **Send WhatsApp Reply** HTTP Request node with either
   your provider's equivalent REST call, or a dedicated n8n node if
   your provider has one.

No changes are needed on the API side.
