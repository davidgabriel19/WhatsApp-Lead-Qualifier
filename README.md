# WhatsApp Lead Qualifier

An end-to-end template for a conversational **lead qualification bot**
that talks to users over WhatsApp, recommends items from a catalog you
own, and hands off qualified leads to a human agent.

The project is split into three independent components that can also
be used on their own:

| Component                | What it is                                        |
|--------------------------|---------------------------------------------------|
| [`api/`](api/)           | FastAPI service: LLM orchestration, sessions, handoff |
| [`workflow/`](workflow/) | n8n workflow: WhatsApp ↔ API ↔ human agent wiring |
| [`scraper/`](scraper/)   | Config-driven scraper that builds the API's catalog |

Each directory has its own focused README with installation and usage
details. This top-level README covers **how the pieces fit together**
and how to run the whole stack locally.

## What it does

- A user sends a message to a WhatsApp number.
- The message flows through an **n8n workflow** that forwards it to a
  **FastAPI service**.
- The API keeps per-user conversation state and asks an **LLM** to reply,
  constrained by a system prompt and a **catalog of real items** you
  control (scraped, exported from your CMS, or hand-curated).
- The reply goes back through the workflow and out to WhatsApp.
- When the model decides the lead is **qualified**, the API generates a
  conversation summary and ships it off-band to a human agent — either
  through a **webhook** (e.g. another n8n flow) or **directly via
  Twilio WhatsApp**, depending on configuration.

## Architecture

```
                      ┌─────────────────────┐
                      │   WhatsApp user     │
                      └──────────┬──────────┘
                                 │
                        1. inbound message
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │  WhatsApp provider     │    e.g. Twilio, Evolution API,
                     │  (webhook → n8n)       │         WPPConnect, ...
                     └──────────┬─────────────┘
                                │
                    2. webhook POST to n8n
                                │
                                ▼
                     ┌────────────────────────┐
                     │       n8n workflow     │ ← workflow/
                     │  extracts message,     │
                     │  calls qualifier API   │
                     └──────────┬─────────────┘
                                │
                       3. POST /chat
                                │
                                ▼
  ┌──────────────────────────────────────────────────┐
  │                Qualifier API                     │ ← api/
  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
  │  │ Session    │  │ Catalog    │  │ AI client  │  │
  │  │ store (TTL)│  │ (JSON)     │  │ (OpenAI)   │  │
  │  └────────────┘  └────────────┘  └────────────┘  │
  │         │               │              │        │
  │         └───────┬───────┴──────────────┘         │
  │                 ▼                                │
  │       ┌──────────────────┐                       │
  │       │ Qualifier        │                       │
  │       │ (orchestrator)   │                       │
  │       └────────┬─────────┘                       │
  │                │                                 │
  │         ┌──────┴───────┐                         │
  │         ▼              ▼                         │
  │    reply body    (if qualified)                  │
  │         │         handoff client                 │
  │         │              │                         │
  │         │   ┌──────────┴──────────┐              │
  │         │   │                     │              │
  │         │   ▼                     ▼              │
  │         │  webhook            twilio direct      │
  │         │  strategy           strategy           │
  └─────────┼───┼─────────────────────┼──────────────┘
            │   │                     │
            │   │                     │
  4. reply  │   │ 5a. POST summary    │ 5b. Twilio API
            │   │     to webhook      │     WhatsApp
            │   │                     │
            │   ▼                     ▼
            │  ┌───────────┐   ┌──────────────┐
            │  │ n8n flow  │   │ Human agent  │
            │  │ (handoff) │   │ WhatsApp     │
            │  └─────┬─────┘   └──────────────┘
            │        │
            │        └──────► Human agent
            │
            ▼
   ┌─────────────────────┐
   │   WhatsApp user     │
   └─────────────────────┘
```

The **scraper** is orthogonal to this flow — it runs on your machine or
on a schedule, fetches public listing data from a site you control or
have permission to scrape, and produces the JSON file the API loads as
its catalog.

## Why this structure?

- **The API knows nothing about WhatsApp.** It speaks HTTP + JSON. You
  can drive it from n8n, from a custom backend, from the CLI with
  `curl` — whatever works for you.
- **The workflow knows nothing about LLMs.** It wires two HTTP APIs
  together and handles retries. Non-developers can edit it in the
  visual editor without touching code.
- **The scraper knows nothing about the bot.** Its only contract is
  "produce a JSON array of objects". You can replace it with a CSV
  export from your CRM, a dump from your CMS, or a hand-written file.
- **Handoff is pluggable.** The API ships with three strategies
  (`none`, `webhook`, `twilio`); adding a Slack, email, or CRM
  handoff means implementing one Protocol method.

## Running the full stack locally

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (for the n8n workflow)
- An OpenAI API key
- (Optional) A Twilio sandbox account for end-to-end WhatsApp testing

### 1. API

```bash
cd api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set API_KEY and OPENAI_API_KEY at minimum.

uvicorn app.main:app --reload --port 8000
```

Sanity check:

```bash
curl http://localhost:8000/health
```

### 2. Workflow

```bash
cd ../workflow
cp .env.example .env
# Edit .env: set QUALIFIER_API_KEY to the same value you picked above.

docker compose -f docker/docker-compose.yml up -d
```

Open http://localhost:5678, log in, import
`workflows/whatsapp-lead-qualifier.json`, configure the Twilio
credential, and toggle the workflow to **Active**. See
[`workflow/README.md`](workflow/README.md) for the full walkthrough.

### 3. (Optional) Scraper

```bash
cd ../scraper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp config.example.yaml my-site.yaml
# Edit my-site.yaml with the target site and selectors.

python scraper.py --config my-site.yaml --output output/catalog.json
cp output/catalog.json ../api/data/catalog.json

# In api/.env set:
#   CATALOG_PATH=data/catalog.json
# Restart the API.
```

## Adapting to your domain

The project ships with generic, domain-agnostic defaults so it works
out of the box as a demo. To specialize it:

1. **Catalog**: replace `api/data/catalog.sample.json` with your own
   JSON — either produced by the scraper, exported from a CRM, or
   hand-written.
2. **System prompt**: edit `api/prompts/system_prompt.md` to reflect
   the questions, tone, and rules your business needs.
3. **Summary prompt**: edit `api/prompts/summary_prompt.md` to match
   the fields your human agents care about.
4. **Handoff strategy**: set `HANDOFF_STRATEGY` in `api/.env` to
   `webhook` (preferred if you're already running n8n) or `twilio`.

No code changes are needed for any of the above.

## Tech stack

- **API**: Python 3.11, FastAPI, Pydantic v2, pydantic-settings,
  cachetools, OpenAI SDK
- **Workflow**: n8n, PostgreSQL
- **Scraper**: Playwright, PyYAML
- **Testing**: pytest (offline, with mocked AI client)
- **Deploy targets**: Docker-native; tested patterns for Railway,
  Render, Fly

## Repository layout

```
whatsapp-lead-qualifier/
├── api/                  # FastAPI service
├── workflow/             # n8n workflow + Docker stack
├── scraper/              # Config-driven catalog scraper
├── LICENSE
├── .gitignore
└── README.md             # (this file)
```

## License

[MIT](LICENSE). Use it, fork it, ship it.

## Roadmap ideas

Things that are intentionally out of scope for the current version but
would be straightforward to add:

- Redis-backed session store for multi-worker deployments (the
  in-memory store already hides behind an interface).
- Swap OpenAI for a local model (the `AIClient` class is the only
  thing that would need to change).
- Additional handoff strategies: Slack, email, HubSpot, Salesforce.
- Analytics: message counts, qualification rates, time-to-qualify
  metrics exposed on `/health` or via Prometheus.
- Multi-language support at the prompt level (the code already passes
  through the user's language unchanged).
