# Architecture

Structured to match the submission template's Architecture Components section.
Diagram: https://claude.ai/code/artifact/75e75507-b818-4bb8-8134-4295be7f6802

## How the components communicate

1. **Merchant checkout → Decision API.** The payment gateway posts a webhook to
   `POST /transactions/evaluate` and holds the transfer pending our answer.
2. **Decision API → Risk agent.** The transaction is persisted, then handed to the
   Pydantic AI agent with its context: amount, whether this payee has ever been paid,
   local hour.
3. **Risk agent → Agent tools → CAMARA client.** The agent selects which signals justify
   their latency and calls them through the tool layer. The agent issues no HTTP itself.
4. **CAMARA client → Nokia Network as Code.** The chosen signals are queried in parallel
   behind a 3-second timeout. Any failure degrades to a cached response that stays
   labelled as cached.
5. **Scoring engine → Outcome.** Observed facts become a 0–100 score, an outcome and a
   numbered reasoning trace, deterministically, with the policy guard rails applied.
6. **Voice layer → Decision log → Console.** A held payment triggers an outbound call in
   the customer's language; the outcome resolves the transaction, and every signal,
   decision and transcript streams to the fraud-ops console over SSE.

## Architecture components

| Component | Responsibility | Built with |
|---|---|---|
| **Input layer** | Payment gateway webhook; the payment is held from here until layer 5 | FastAPI |
| **Agent layer** | Decides which CAMARA signals to pull; writes the analyst narrative | Pydantic AI, Groq |
| **Verification layer** | Typed CAMARA clients with timeout, retry and labelled fallback cache | httpx, Nokia Network as Code |
| **Scoring engine** | Deterministic weighting of observed signals into a score and outcome | Python |
| **Voice interface** | Multilingual outbound call, interrogation script, outcome classification | Vapi, ElevenLabs, Deepgram, Whisper |
| **Decision log** | Immutable record of every API call, decision, rationale and transcript | PostgreSQL |
| **Fraud-ops console** | Live decision feed and reasoning-trace timeline | Next.js on Vercel |

## Where authority sits

A regulator has to be able to reproduce a payment decision, so the model's authority
stops at the score.

| Decision | Owner | Why |
|---|---|---|
| Which signals to pull | LLM agent | The genuinely agentic part. On a routine payment it pulls none, and says why. |
| The written explanation | LLM agent | Prose is what a language model is good at, and the trace is read by people. |
| The risk score | Scoring engine | Reproducible. Weights sit in one reviewable table. |
| The outcome | Scoring engine | Derived from the score plus one rule about whether the customer is present. |
| Overriding a decline | Policy guard rail | A false decline harms a real customer and does nothing to stop the coercion. |
| Insisting on evidence | Policy guard rail | We never decline without the location check that justifies declining. |

## Two invariants, both enforced by tests

1. **Every CAMARA call and every decision goes through `services/audit.py`.** The audit
   trail is a regulatory requirement in this domain, not a debugging convenience.
2. **A cached response is labelled as cached everywhere it appears** — in the database
   (with a CHECK constraint), in the API, in the reasoning trace and on the dashboard.

## Failure behaviour

| What fails | What happens |
|---|---|
| One CAMARA API | Falls back to a cached response, flagged, with the reason recorded |
| All CAMARA APIs | Same, and the decision still completes |
| The reasoning model | Deterministic path pulls every signal and scores it; the mode is shown on the dashboard |
| The voice call | Payment stays held and the call is recorded as failed; silence never releases money |
| The database | The API returns a clear JSON error through the CORS layer, never a stack trace |
| The dashboard | Bounded event queues drop rather than block; a dead console cannot slow a payment |
