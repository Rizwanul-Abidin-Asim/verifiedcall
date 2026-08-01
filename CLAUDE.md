# VerifiedCall

**GSMA MENA Ignite Hackathon · Theme 4 — Secure Fintech, Payments & Anti-Fraud**

## What it is

An AI agent that detects **authorised push payment (APP) fraud** — where a victim is on a
call with a scammer impersonating their bank and sends the money themselves. Existing
SIM-swap fraud tools miss this entirely because the transaction is correctly
authenticated: the real customer, on the real device, with the real credentials.

Our system scores the transaction using CAMARA network signals, and when risk is high, an
AI voice agent calls the customer in their own language and runs a scam-interrogation
script **before the payment settles**.

## Stack (fixed — do not substitute)

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Postgres |
| Agent | Pydantic AI, Groq (`llama-3.3-70b-versatile`) |
| Voice | Vapi (telephony), ElevenLabs (TTS), Deepgram (STT) |
| Network APIs | CAMARA via Nokia Network-as-Code |
| Frontend | Next.js 14 App Router on Vercel |
| Local infra | docker-compose: postgres 16 + redis 7 |

## Standing rules

1. **Never invent CAMARA API request or response shapes.** Always read
   `docs/camara-findings.md` first. If a shape isn't documented there, **stop and tell
   me** — do not guess an endpoint path, a field name, or a payload structure.
2. **Every CAMARA call and every agent decision must be persisted** via
   `app/services/audit.py`. No exceptions, no direct writes bypassing it. The audit trail
   is a scored part of the submission, not a debug convenience.
3. **The agent layer makes no direct HTTP calls.** `app/agent/` reaches the network only
   through `app/agent/tools.py`, which calls `app/camara/`.
4. **Fallback responses must be flagged.** Anything served from `app/camara/fallback.py`
   carries `source="fallback"` all the way to the dashboard. We show it honestly.
5. **Secrets live in `.env`.** Never hardcode a key, never paste one into a commit, never
   echo one in a log line or the `/health` payload.
6. **One prompt = one commit.** Keep the history readable — judges read it.

## Directory layout

```
verified-call/
├── CLAUDE.md                        # this file
├── README.md                        # judge-facing (written last)
├── .env.example
├── docker-compose.yml               # postgres + redis for local dev
│
├── docs/
│   ├── camara-findings.md           # PHASE 1 OUTPUT — ground truth for all API code
│   ├── architecture.md              # component map, feeds the Excalidraw diagram
│   ├── decisions.md                 # ADR-lite: why Pydantic AI, why Groq, etc.
│   └── demo-script.md               # the 3-minute pitch runsheet
│
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py                  # FastAPI entrypoint
│   │   ├── config.py                # pydantic-settings, env loading
│   │   │
│   │   ├── camara/                  # ONE module per API, thin + typed
│   │   │   ├── base.py              # shared auth, retry, timeout, fallback wrapper
│   │   │   ├── sim_swap.py
│   │   │   ├── number_verification.py
│   │   │   ├── location_verification.py
│   │   │   ├── device_status.py
│   │   │   └── fallback.py          # cached responses for demo resilience
│   │   │
│   │   ├── agent/
│   │   │   ├── risk_agent.py        # Pydantic AI agent definition
│   │   │   ├── tools.py             # CAMARA calls exposed as agent tools
│   │   │   ├── prompts.py           # system prompt + scam-pattern heuristics
│   │   │   └── schemas.py           # RiskDecision, SignalResult, ReasoningStep
│   │   │
│   │   ├── voice/
│   │   │   ├── vapi_client.py       # place call, poll status
│   │   │   ├── scripts.py           # scam-interrogation scripts per language
│   │   │   └── webhooks.py          # call outcome → transaction resolution
│   │   │
│   │   ├── api/routes/
│   │   │   ├── transactions.py      # POST /transactions/evaluate (gateway webhook)
│   │   │   ├── decisions.py         # GET  /decisions, /decisions/{id}
│   │   │   ├── voice.py             # POST /voice/webhook
│   │   │   └── stream.py            # SSE feed for the live dashboard
│   │   │
│   │   ├── db/
│   │   │   ├── models.py            # Transaction, SignalCall, Decision, VoiceCall
│   │   │   ├── session.py
│   │   │   └── migrations/
│   │   └── services/
│   │       └── audit.py             # every API call + decision persisted
│   │
│   ├── scripts/
│   │   ├── spikes/                  # PHASE 1 throwaway probes (keep them — judges like them)
│   │   └── seed_demo.py             # loads the 4 demo scenarios
│   └── tests/
│
└── frontend/                        # Next.js on Vercel
    ├── app/
    │   ├── checkout/                # fake merchant checkout that fires the webhook
    │   └── dashboard/               # fraud analyst view: signals, reasoning, transcript
    └── components/
```

**Why this shape:** `camara/` is isolated so a sandbox limitation only breaks one file.
`agent/` never talks HTTP directly — only through tools. `audit.py` is a service, not a
side effect, because the audit trail is scored.

## Demo scenarios (the four we pitch)

1. Clean transaction, all signals green → **approve**
2. Recent SIM swap + new beneficiary → **decline**
3. Roaming device + large amount + new beneficiary → **intervene** ← headline APP fraud case
4. Location mismatch, moderate amount → **intervene**

## Running locally

```bash
docker compose up -d                       # postgres + redis
cd backend
uv sync --extra dev                        # or: pip install -e ".[dev]"
uv run uvicorn app.main:app --reload       # http://127.0.0.1:8000/health
```

## Current status

Phase 0 complete: skeleton, config, health endpoint.
Next: **Phase 1 — probe the Nokia NaC sandbox** and fill in `docs/camara-findings.md`.
Nothing in `app/camara/` should be written until that file has real recorded shapes in it.
