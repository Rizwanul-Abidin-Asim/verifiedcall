# VerifiedCall — Idea Capture Template

**Idea Name:** VerifiedCall
**Submission Date:** 12 August 2026
**Team Name:** antifraud
**Submitter:** Ahmad Abu Alarjah (Team Leader) — ahmad.abualarjah21@gmail.com
**Institution:** American University of Sharjah, United Arab Emirates

**Theme:** Theme 4 — Secure Fintech, Payments & Anti-Fraud Innovation
**Project Type:** AI agent-orchestrated, real-time interception layer for authorised push payment fraud, combining CAMARA network intelligence with multilingual voice verification.
**GSMA Pillar Alignment:** Connectivity for Good

---

## Team Details

| Member | Role | Expertise |
|---|---|---|
| Ahmad Abu Alarjah (Leader) | Network & CAMARA integration architect | Network architecture, data architecture, IoT, machine learning, blockchain |
| Khader Kheirallah | Network signals & cloud infrastructure | Network architecture, machine learning, IoT, cloud computing |
| Fadil Pasha | Backend engineer — decision API & audit trail | Back-end, full-stack development |
| Rizwanul Asim | Full-stack engineer — fraud-ops dashboard & UX | Full-stack, back-end, front-end, machine learning, UI/UX |
| Ryhan Nijam | [role to confirm] | — |

All five members are based in Sharjah, UAE. We are building for the market we live in.

---

## Integration Context

Authorised push payment (APP) fraud is the fastest-growing category of payment fraud, and it is structurally invisible to the tools banks already own. A criminal telephones the victim, impersonates their bank, the police or a government department, and frightens or persuades them into transferring their own money to a "safe account". There is no stolen card, no compromised password, no malware.

Every control a bank relies on returns green. The correct customer, on the correct device, with the correct credentials and the correct biometric, authorises a genuine payment. Fraud engines ask *"is this really you?"* — and in APP fraud the honest answer is yes. So the payment is approved.

The MENA region is unusually exposed. Digital payment adoption is accelerating, and the Gulf hosts a very large migrant workforce who transfer money frequently, often internationally, often under time pressure, and who are routinely targeted in languages their bank does not serve them in. A fraud control that only operates in English and only asks about identity cannot protect them.

**VerifiedCall** uses CAMARA APIs on the Nokia Network as Code platform as a live behavioural signal rather than an identity check. An AI agent decides, per transaction, which network signals are worth pulling; combines them with transaction context; and where the pattern indicates a customer acting under pressure, holds the payment and places an automated voice call in the customer's own language before the money settles.

---

## Solution Overview

VerifiedCall is an API-first decision layer that sits between a payment being submitted and the money actually leaving. It operates in three stages.

**1. Detect.** A payment gateway webhook delivers the transaction. An AI agent reads the context — amount, whether the beneficiary has ever been paid before, the local time — and autonomously decides which mobile-network signals justify their latency. It pulls them in parallel, produces a 0–100 risk score, and writes a step-by-step reasoning trace in plain English.

**2. Intervene.** Where the evidence indicates coercion rather than theft, the payment is held and an AI voice agent telephones the customer in their own language — English, Arabic, Hindi or Urdu — and asks whether anyone is on another call with them, whether someone instructed them to make this payment, and whether they were told not to discuss it with their bank.

**3. Resolve.** Based on the answers, the payment is released, blocked, or escalated to a human analyst. Every network call, decision, rationale and call transcript is written to an immutable audit log.

### How it helps solve the problem

It closes the specific gap that identity-based fraud controls cannot reach. Instead of re-asking a question the scammer has already defeated, VerifiedCall asks whether the customer is free to say no — and it asks in a language they actually speak, in the seconds before the money is irrecoverable.

It also reduces the opposite harm. Because the system distinguishes a customer being coerced from an account being operated by somebody else, it can hold and verify rather than decline outright, avoiding false declines on legitimate payments.

---

## Key Features & Benefits

- **Autonomous signal selection.** The agent decides which CAMARA APIs to call for each transaction rather than running a fixed checklist. On a routine payment to a known payee it pulls no network signals at all, and explains why.
- **Coercion detection, not identity verification.** The voice agent's purpose is to establish whether the customer is under social-engineering pressure — a question no authentication factor can answer.
- **Multilingual by design.** English, Arabic, Hindi and Urdu, reflecting the actual population of the Gulf rather than an afterthought translation.
- **Explainable by construction.** Every decision carries a numbered reasoning trace showing which signal was pulled, what it returned, and how it moved the score — readable by a fraud analyst or a regulator.
- **Deterministic, reproducible scoring.** The risk number comes from a transparent weighting table, not from a language model, so the same transaction always scores the same.
- **Graceful degradation.** If a network API fails or rate-limits, the system falls back to cached responses that are *visibly labelled as cached*. Cached data is never presented as live.
- **API-first adoption.** Integrates with an existing payment gateway through a single webhook. No core banking replacement required.

---

## APIs & Technology

### APIs used and why each is essential

| CAMARA API | Fraud question it answers | Why it is essential |
|---|---|---|
| **Call Forwarding Signal** | Are the customer's calls being intercepted right now? | Our highest-weighted signal. An active unconditional divert means a scam is in progress, not that something went wrong in the past — and it means the bank's own verification call would never reach the customer. |
| **Device Roaming Status** | Is the customer abroad and isolated? | Roaming combined with a first-time beneficiary is the classic APP fraud shape: travelling, harder to reach, easier to pressure. |
| **Location Verification** | Is the device where the payment claims to originate? | The signal that separates theft from coercion, and therefore the signal that decides whether we decline or call. |
| **SIM Swap** | Could one-time passcodes be reaching someone else? | Deliberately weighted lower here than in conventional fraud models, because in APP fraud the genuine customer is the one authorising. A clean SIM does not make a payment safe. |

Four APIs spanning two categories — identity/anti-fraud and device/network — all accessed through Nokia Network as Code.

### Tech stack and frameworks

| Layer | Choice |
|---|---|
| Agent orchestration | **Pydantic AI** — type-safe, production-oriented agent framework |
| Reasoning model | **Groq** — lowest available inference latency, which matters inside a checkout |
| Voice | **Vapi** (telephony), **ElevenLabs** (speech synthesis), **Deepgram** and **Whisper** (speech recognition, routed by language) |
| Backend | Python, FastAPI, SQLAlchemy, PostgreSQL |
| Frontend | Next.js on Vercel |
| Network data | CAMARA APIs via **Nokia Network as Code** |

Every component is drawn from the approved Resource & Tooling Guide, and every one has a free or freemium tier, so the full prototype is buildable without any paid commitment.

### How the tech stack helps

Pydantic AI's typed outputs matter in a payments context: a malformed decision is not an acceptable failure mode, so the agent's output is schema-validated rather than parsed from free text. Groq's inference speed is what makes an in-checkout agent viable at all — the approve path completes in roughly 1.2 seconds end to end. Postgres gives us an immutable, queryable decision log, which is a regulatory requirement in this domain rather than a convenience. And routing speech recognition by language, rather than using one engine for all four, is what makes the Arabic and Urdu paths usable.

---

## Innovation Highlights

- **A different question.** Existing anti-fraud asks "is this really you?". VerifiedCall asks "is someone standing over you while you do this?" — the only question that catches authorised fraud.
- **Theft and coercion separated by network evidence.** Identical signal profiles produce opposite responses depending on whether the device is where the payment claims. A device elsewhere reads as account takeover and is declined; a device exactly where expected means the genuine customer is present and possibly being coached, so we call them instead. No single API can make that distinction.
- **Call Forwarding Signal used as a scam-in-progress indicator.** To our knowledge this API is not currently used this way. It is a far stronger APP fraud signal than SIM Swap, because it describes what is happening now rather than what happened previously.
- **The model orchestrates; it does not score.** The agent chooses which APIs to call and writes the explanation, while a deterministic engine produces the number. A regulator can reproduce every decision.
- **A policy guard rail against false declines.** If the model recommends declining a payment while the customer is demonstrably present, the system overrides it to a verification call and records the disagreement. Refusing a payment the genuine customer is making does not protect them.
- **Language-independent coercion signals.** Because a coached victim hesitates before denying that they were told to keep the call secret, response timing and hesitation are treated as evidence — and timing works identically in every language, independent of speech-recognition quality.

---

## Impact Metrics

| Metric | Status |
|---|---|
| CAMARA APIs integrated and verified live | **4 of 4**, across 2 categories |
| All four network signals pulled concurrently | **541 ms** measured |
| End-to-end added latency, approve path | **~1.2 s** measured |
| Languages supported by the voice agent | **4** — English, Arabic, Hindi, Urdu |
| Automated tests passing | **53** |
| Signals pulled on a routine low-risk payment | **0** — the agent declines to spend the latency, and says so |

Metrics we will report from the prototype phase: reduction in confirmed fraud losses on flagged transactions; reduction in false declines on legitimate transactions; median added latency per transaction; and percentage of decisions served from live network data versus cache.

---

## Methodology & Architecture

### How the components communicate

1. **Merchant checkout → Decision API.** The payment gateway posts a webhook for a submitted transaction, and the payment is held pending a decision.
2. **Decision API → Risk Agent.** The transaction is persisted, then handed to the Pydantic AI agent with its context.
3. **Risk Agent → CAMARA APIs (via Nokia Network as Code).** The agent autonomously selects which network signals are worth pulling and calls them in parallel through the agent tool layer.
4. **Risk Agent → Scoring Engine.** Observed signals are converted into a deterministic risk score, an outcome, and a numbered reasoning trace.
5. **Scoring Engine → Voice Layer.** Where the outcome is *intervene*, an outbound call is placed in the customer's language and the scam-interrogation script is run.
6. **Voice Layer → Decision Log → Dashboard.** The call outcome resolves the transaction, and every signal, decision and transcript is streamed live to the fraud-operations console.

### Architecture components

| Component | Responsibility |
|---|---|
| **Input Layer** | Payment gateway webhook carrying transaction context |
| **Agent Layer** | Pydantic AI agent that decides which CAMARA signals to pull and writes the analyst narrative |
| **Verification Layer** | Typed CAMARA client layer with timeouts, retries and labelled fallback caching |
| **Scoring Engine** | Deterministic, reviewable weighting of observed signals into a risk score and outcome |
| **Voice Interface** | Multilingual outbound call, scam-interrogation script, outcome classification |
| **Decision Log** | Immutable record of every API call, decision, rationale and transcript |
| **Fraud-Ops Console** | Live feed and reasoning-trace timeline for analysts |

**Architecture diagram:** [INSERT LUCIDCHART / FIGMA / MIRO / EXCALIDRAW LINK]

---

## Appendix — Implementation progress to date

VerifiedCall is not a concept document. The following is built, tested and running as of 12 August 2026.

- **All four CAMARA APIs integrated and verified live** against the Nokia Network as Code sandbox, with recorded request and response shapes and measured latency.
- **Typed client layer** with a 3-second timeout, retries on server errors only, and fallback caching where every cached response is explicitly labelled.
- **Immutable audit trail** in PostgreSQL — every network call and every decision persisted, with database-level constraints preventing an unlabelled signal from being stored.
- **Autonomous risk agent** producing a numbered reasoning trace, verified live across four reproducible demo scenarios.
- **53 automated tests** passing, runnable with no API key and no network access.

Three findings from that work, which shaped the design:

- **Number Verification cannot be called server-side.** It returns HTTP 401 because it requires a three-legged consent token that only the handset can obtain, over mobile data. We replaced it with Call Forwarding Signal, which is a materially better APP fraud signal.
- **Sandbox behaviour differs from its documentation.** We mapped every available test number across all four APIs before designing our demo scenarios, rather than trusting the published mapping.
- **Degradation is tested with real failures.** The sandbox provides numbers that force HTTP 500 responses, so the fallback path is exercised against genuine errors rather than mocks.

### Prototype phase plan (26 August – 9 September 2026)

Decision API and live dashboard → multilingual voice intervention with keypad fallback → fraud-operations console with full reasoning trace → demo hardening and end-to-end smoke tests.
