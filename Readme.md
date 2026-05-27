# Voyager — A2A Multi-Agent Travel Planner

Voyager is a distributed multi-agent travel planning system built on the [A2A protocol](https://github.com/a2aproject/A2A). Send a natural language travel request and five specialized AI agents — weather, domestic flights, international flights, hotels, and budget — collaborate in real time to build your trip plan.

```
"Fly from Kathmandu to Bangkok on July 15 for 3 nights"

→ Planner routes the task (OpenRouter LLM)
→ Weather Agent      (Open-Meteo)
→ Intl Flight Agent  (eSewa Travels)
→ Hotel Agent        (Serper / Google)
→ Budget Agent       (calculation)
→ Live streamed results via SSE
```

---

## Features

- Multi-agent orchestration via A2A protocol
- Real-time SSE streaming — results appear as each agent completes
- Parallel agent execution — weather, flights, and hotels run simultaneously
- Redis + PostgreSQL state management
- MemoryStore fallback for development (no Redis needed)
- FastAPI gateway with typed exception handling
- OpenRouter-powered planner (swap any LLM)

---

## Tech Stack

| Component | Technology |
|---|---|
| Gateway | FastAPI |
| Agent Protocol | A2A SDK |
| LLM Router | OpenRouter (OpenAI-compatible) |
| State (dev) | In-process MemoryStore |
| State (prod) | Redis |
| Persistence | PostgreSQL + SQLAlchemy Async |
| Streaming | Server-Sent Events (SSE) |
| Package manager | uv |

---

## Agents

| Agent | Port | External API |
|---|---|---|
| Weather | 8001 | Open-Meteo (free, no key needed) |
| Domestic Flight | 8002 | TripTurbo (Nepal routes) |
| International Flight | 8003 | eSewa Travels (KTM departures) |
| Hotel | 8004 | Serper.dev (Google Search) |
| Budget | 8005 | None (pure calculation) |

---

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Start Redis + PostgreSQL

```bash
docker compose up -d
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in your API keys in `.env`. Minimum required:

```
LLM_API_KEY      — OpenRouter API key (https://openrouter.ai/keys)
SERPER_API_KEY   — Serper.dev API key (https://serper.dev)
DATABASE_URL     — PostgreSQL connection string
```

All other fields have working defaults for local development.  
Leave `REDIS_URL` empty to use the in-memory store (no Redis needed for development).

### 4. Run

```bash
uv run python main.py
```

---

## Usage

Open the UI:

```
http://localhost:8000/ui
```

Or call the API directly:

```bash
# Create task and stream results in one request
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Fly from Kathmandu to Bangkok on July 15"}'

# Fire and forget — returns task_id immediately
curl -X POST http://localhost:8000/tasks/send \
  -H "Content-Type: application/json" \
  -d '{"input": "Fly from Kathmandu to Bangkok on July 15"}'

# Stream results for an existing task
curl -N http://localhost:8000/tasks/{task_id}/stream
```

---

## API

| Endpoint | Method | Description |
|---|---|---|
| `/chat` | POST | Create task and stream results in one request |
| `/tasks/send` | POST | Create task, returns `task_id` |
| `/tasks/{task_id}` | GET | Get task status and results |
| `/tasks/{task_id}/stream` | GET | Stream task events via SSE |
| `/agents` | GET | List all resolved agents and their skills |
| `/health` | GET | Gateway health check |
| `/ui` | GET | Browser UI |

---

## Architecture

```
User Request (natural language)
        │
        ▼
   Gateway :8000 (FastAPI)
        │
   ┌────┴──────────────────────┐
   │                           │
   ▼                           ▼
Store                     Orchestrator
(MemoryStore /            ├── Registry  (discovers agents via AgentCard)
 RedisStore /             ├── Planner   (LLM routes request → agent plan)
 PostgresStore)           └── Client    (speaks A2A protocol to each agent)
                                │
              ┌─────────────────┼───────────────────┐
              ▼                 ▼                   ▼
       Weather :8001    Flights :8002/:8003    Hotel :8004
              └─────────────────┴───────────────────┘
                                │
                         Budget :8005
                     (runs last, uses other agents' data)
                                │
                                ▼
                    SSE stream → client
                    PostgreSQL ← persistence
```

---

## Project Structure

```
agents/
├── base/executor.py              Base class: logger, cancel handling
├── weather_agent/forecast.py     Open-Meteo weather
├── domestic_flight_agent/        TripTurbo Nepal flights
├── intl_flight_agent/            eSewa international fares
├── hotel_agent/                  Serper hotel search
└── budget_agent/                 Cost estimation

orchestrator/
├── registry.py                   Agent discovery via AgentCard
├── client.py                     A2A protocol client
└── planner.py                    LLM routing + clarification handling

gateway/
├── app.py                        FastAPI lifespan, middleware, error handlers
├── router.py                     HTTP endpoints
├── task_manager.py               Task lifecycle management
└── stream.py                     SSE event pipe

state/
├── base.py                       Store protocol
├── transitions.py                State machine rules
├── memory_store.py               Development store
├── redis_store.py                Production store
└── postgres_store.py             Persistence layer

config/
├── agents.yaml                   Agent registry (single source of truth)
└── events.yaml                   SSE terminal event definitions

prompts/planner/
├── system.yaml                   LLM system prompt
└── routing.yaml                  Routing template + few-shot examples
```

---

## License

MIT