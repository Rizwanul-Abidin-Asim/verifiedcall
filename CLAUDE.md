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
| Agent | Pydantic AI, Groq (`openai/gpt-oss-120b`; Llama 3.3 was retired mid-build) |
| Voice | Vapi (telephony), ElevenLabs (TTS), Deepgram (STT) |
| Network APIs | CAMARA via Nokia Network-as-Code |
| Frontend | Next.js 15 App Router on Vercel |
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
│   │   │   ├── call_forwarding.py   # replaced Number Verification; see ADR in decisions.md
│   │   │   ├── location_verification.py
│   │   │   ├── device_status.py
│   │   │   ├── models.py            # typed signal results
│   │   │   └── fallback.py          # cached responses, always flagged
│   │   │
│   │   ├── agent/
│   │   │   ├── risk_agent.py        # Pydantic AI agent definition
│   │   │   ├── tools.py             # CAMARA calls exposed as agent tools
│   │   │   ├── prompts.py           # system prompt + scam-pattern heuristics
│   │   │   ├── scoring.py           # deterministic weights; the model does NOT score
│   │   │   └── schemas.py           # RiskDecision, SignalResult, ReasoningStep
│   │   │
│   │   ├── voice/
│   │   │   ├── vapi_client.py       # place call, poll the result, mock-mode simulator
│   │   │   ├── scripts.py           # interrogation script in EN, AR, HI, UR
│   │   │   ├── classify.py          # answers + hesitation timing -> outcome
│   │   │   ├── service.py           # orchestrates an intervention
│   │   │   └── webhooks.py          # call outcome -> transaction resolution
│   │   │
│   │   ├── api/routes/
│   │   │   ├── transactions.py      # POST /transactions/evaluate (gateway webhook)
│   │   │   ├── decisions.py         # GET  /decisions, /decisions/{id}
│   │   │   ├── metrics.py           # GET /metrics, computed from the decision log
│   │   │   └── stream.py            # SSE feed for the live dashboard
│   │   │
│   │   ├── db/
│   │   │   ├── models.py            # Transaction, SignalCall, Decision, VoiceCall
│   │   │   ├── session.py
│   │   │   └── migrations/
│   │   └── services/
│   │       ├── audit.py             # every API call + decision persisted
│   │       └── events.py            # in-process fan-out for the live feed
│   │
│   ├── scripts/
│   │   ├── spikes/                  # PHASE 1 probes, kept as evidence
│   │   ├── smoke_test.py            # run this before pitching
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

Signal profiles come from the measured sandbox matrix in `docs/camara-findings.md`.

1. `+99999991001` clean, known payee, small amount -> **approve** (agent pulls nothing)
2. `+99999991000` all signals bad, device NOT where the payment claims -> **decline**
3. `+99999991004` all signals bad, device IS where expected -> **intervene** <- headline
4. `+99999991003` all signals bad, partial location match -> **intervene**

Scenarios 2 and 3 carry the pitch: same signals, opposite responses, because location is
what separates theft from coercion.

## Running locally

```bash
docker compose up -d                       # postgres + redis
cd backend
uv sync --extra dev                        # or: pip install -e ".[dev]"
uv run uvicorn app.main:app --reload       # http://127.0.0.1:8000/health
```

## Deadlines — two gates

| Gate | Date | Deliverable |
|---|---|---|
| **Idea Phase** | **23 Aug 2026** | Filled-in GSMA template + architecture diagram link. Document, not code. |
| **Prototype Phase** | **26 Aug – 9 Sep 2026** | Working codebase, public repo link mandatory. |

Full detail in `docs/hackathon-requirements.md` — read it before any scoping decision.

## Current status

Backend and frontend both complete and verified end to end.

| Step | State |
|---|---|
| CAMARA client layer, audit trail, risk agent | done |
| Decision API, read endpoints, SSE feed | done |
| Voice intervention (mock mode) | done |
| Fraud-ops console and demo checkout | done |
| Metrics, DEMO_MODE, smoke test | done |
| README, architecture, demo script | done |

171 tests pass with no API key and no network. `scripts/smoke_test.py` checks everything
end to end against a running server, and `scripts/live_call_test.py` places one real call
to a phone you control.

Real calls are wired: credentials verified, the assistant validated against the
provider's schema, and the result read by polling rather than by webhook, so no tunnel
is needed. See ADR-006 and ADR-007.

A UAE mobile cannot be reached by any AI voice platform, because Etisalat and du block
VoIP-originated termination. Verified from call records, not assumed; see
`docs/telephony-findings.md`. `VOICE_CHANNEL=web` carries the same conversation over the
browser, sharing every line of code after the call starts. See ADR-008 and ADR-009.

Outstanding, needs a human: the Arabic, Hindi and Urdu voice scripts have not been
reviewed by native speakers.
