# VerifiedCall

**Team antifraud · American University of Sharjah**
GSMA MENA Ignite Hackathon · Theme 4, Secure Fintech, Payments and Anti-Fraud Innovation
GSMA pillar: Connectivity for Good

VerifiedCall goes after the kind of fraud where the customer is the one pressing send.

---

## The problem

In authorised push payment (APP) fraud, somebody phones the customer, says they are from
their bank or the police, and talks them into moving money to a "safe account". Nothing
gets hacked. It is the customer's phone, their login, their fingerprint, their payment.

So the bank's fraud engine looks at the transaction, finds nothing wrong, and lets it
through. Every check it runs is asking *"is this really you?"*, and the answer genuinely
is yes.

That gap matters here in particular. A lot of people in the UAE send money abroad
regularly, often in a hurry, and they are targeted in languages their bank does not
operate in.

## What we do about it

We sit between the payment being submitted and the money leaving. The gateway holds the
transfer while we decide.

1. An agent reads the transaction and decides **which** mobile network checks are worth
   running. On a small payment to a regular payee it pulls nothing and says why.
2. The checks it chose run in parallel against CAMARA APIs on Nokia Network as Code.
3. A fixed weighting table turns what came back into a score and an outcome. The model
   picks the checks and writes the explanation; it does not produce the number.
4. If it looks like coercion, we hold the payment and **phone the customer in their own
   language** before the money moves.

### The idea it rests on

Theft and coercion throw off identical signals. What separates them is where the phone is.

| Network says | Reading | Action |
|---|---|---|
| Device is **not** where the payment claims | Somebody else is in the account | **Decline** |
| Device **is** exactly where expected, calls diverted | The customer is doing this with someone in their ear | **Hold and call** |

No single API tells you which of those you are looking at. That is the combined benefit.

---

## The four CAMARA APIs, and why each one

| API | The question | Why it earns its place |
|---|---|---|
| **Call Forwarding Signal** | Are their calls being diverted? | Highest weighted. A diverted line means the scam is happening *now*, and the bank's own callback would never reach them. |
| **Location Verification** | Is the phone where the payment claims? | The tie-breaker. Decides whether a held payment is declined or verified by phone. |
| **Device Roaming Status** | Is the customer abroad and isolated? | Roaming plus a first-time payee is the classic shape. |
| **SIM Swap** | Could OTPs be reaching someone else? | Deliberately weighted *lower* than most fraud systems would, because in APP fraud the genuine customer is the one authorising. |

Four APIs across two categories, all verified working against the Nokia sandbox.

---

## Running it

```bash
git clone https://github.com/Rizwanul-Abidin-Asim/verifiedcall
cd verifiedcall
cp .env.example .env          # fill in the keys listed below

docker compose up -d          # postgres 16 + redis 7

cd backend
uv sync --extra dev           # or: pip install -e ".[dev]"
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000

cd ../frontend                # in a second terminal
npm install
npm run dev                   # http://localhost:3000
```

Open **http://localhost:3000/checkout**, pick scenario 3, and pay. Then watch
**/dashboard**.

No Docker? The whole thing runs on SQLite:

```bash
DATABASE_URL="sqlite+aiosqlite:///./demo.db" uv run alembic upgrade head
DATABASE_URL="sqlite+aiosqlite:///./demo.db" uv run uvicorn app.main:app --port 8000
```

### Credentials

| Variable | Needed for | Free? |
|---|---|---|
| `NOKIA_NAC_API_KEY`, `NOKIA_NAC_BASE_URL` | The four CAMARA APIs | Yes, Simulator plan |
| `GROQ_API_KEY` | The agent | Yes |
| `GEMINI_API_KEY` | Optional fallback provider | Yes |
| `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID` | **Real** phone calls only | Not required |

`VOICE_MOCK=true` is the default, so everything runs end to end with no Vapi account.

### Placing a real call

Set `VOICE_MOCK=false` with both Vapi variables filled in, restart, and then:

```bash
uv run python scripts/live_call_test.py +971501234567     # a phone you control
```

That dials an actual phone and spends Vapi credits, which is why it is a separate script
rather than a flag. It drives demo scenario 3: the network signals still come from the
sandbox number, only the call goes to your phone.

**A UAE mobile cannot be reached by any AI voice platform.** Etisalat and du are
required to block VoIP-originated termination, and every one of these platforms is
VoIP-originated. We established that by testing each layer separately rather than
guessing: `docs/telephony-findings.md` has the call records, including two attempts that
rang for exactly 55 seconds, were never billed, and never appeared in the recipient's
call log.

The phone path is complete and works where carriers permit it. For the UAE, use the
browser channel below.

### The browser channel

```bash
VOICE_CHANNEL=web        # with VOICE_MOCK=false and VAPI_PUBLIC_KEY set
```

The held payment then offers the customer the same conversation through the checkout
page. Same script, same voice, same transcription, same answer extraction, same
hesitation timing, same resolution, no carrier in the path. The assistant is still built
on the server, so the interrogation script stays in version control; the page plays a
definition rather than composing one.

The channel is recorded per call and shown on the dashboard, because a browser call is
not a phone call and we would rather say so.

No public URL or tunnel is needed. Vapi can report a call two ways and we use the one
that works from a laptop, polling `GET /call/{id}` until the call ends rather than
waiting for a webhook to arrive. The webhook route still works for a deployed instance,
and whichever report lands first is the one recorded. ADR-006 has the reasoning.

### Before a demo

```bash
uv run pytest                                  # 171 tests, no API key or network needed
uv run python scripts/smoke_test.py            # end to end against a running server
```

The smoke test checks the four scenarios, a forced network outage, both read endpoints,
the metrics, the voice intervention and the live feed. It fails loudly and says what
broke.

`DEMO_MODE=true` forces cached CAMARA responses, so the pitch has a guaranteed-working
path if the sandbox is down. Everything it serves is still labelled as cached.

---

## Test numbers

Signals are keyed to the number, as Nokia's sandbox does:

| `signal_msisdn` | Profile |
|---|---|
| `+99999991001` | all clean |
| `+99999991000` | all bad, device **not** in the expected area |
| `+99999991004` | all bad, device **is** in the expected area |
| `+99999991003` | all bad, partial location match |
| `+99999990500` | forces HTTP 500 on all four APIs |

Simulated calls follow the same convention on the number being *called*:

| `customer_msisdn` ends | Scripted customer | Outcome |
|---|---|---|
| `0` | confirms every part of the scam story | scam detected, blocked |
| `1` | answers cleanly | legitimate, released |
| `2` | denies it, but hesitates | inconclusive, held for an analyst |
| `9` | does not pick up | no answer, held |

---

## Measured, not estimated

Run `GET /metrics` for live figures. As of the last full run:

- **4 of 4** CAMARA APIs integrated and verified against the live sandbox
- **541 ms** for all four network signals pulled concurrently
- **~1.2–2.5 s** end to end on the approve path
- **136** automated tests, runnable with no API key and no network
- **4** languages in the voice script

---

## What is real, and what is not

We would rather say this ourselves than have it found.

**Real.** The CAMARA calls are real HTTPS requests to Nokia's platform with real auth and
real latency. The agent is a real model making decisions we do not control in advance.
The audit trail, the API and the console are real.

**Simulated, and labelled as such.**

- **The network data.** Nokia has no MENA operator live and the free plan is Simulator
  mode. The API, auth, latency and error handling are real; the underlying network is not.
- **The bank.** The checkout is ours. It sends exactly the webhook a real gateway would.
- **Holding the money.** No money moves. The hold is a state in our database.
- **The phone call.** `VOICE_MOCK=true` scripts the customer's answers and nothing
  dials. Real calls work and are what `scripts/live_call_test.py` places, but the mode
  is recorded per call and the dashboard labels a simulated one rather than letting it
  pass for real.
- **The demo seam.** Sandbox numbers are not real phones and a real phone has no sandbox
  signals, so in a demo the number we look signals up against differs from the number we
  would call. The dashboard says so on every affected transaction rather than implying
  one device.

**Limitations we found and designed around.**

- **Number Verification cannot be called from a server.** It returns 401 and needs a
  consent token only the handset can obtain over mobile data. We replaced it with Call
  Forwarding Signal, which suits this problem better. `scripts/spikes/probe_number_verification.py`
  is kept as evidence.
- **UAE mobiles are unreachable by internet telephony**, so the demo intervention runs
  in the browser rather than over the phone network. This is a regulatory boundary, not
  an integration gap: the assistant validates against the provider's schema, the call
  reaches the live API, and Twilio bills a rate for the destination. The terminating
  carrier is what stops it. Both channels share every line of code after the call
  starts. `docs/telephony-findings.md` records how we established it, including a bug
  in our own test that had reported a blocked call as a success.
- **Location Verification ignores the area we send.** The sandbox returns the same verdict
  for Dubai, Bonn or Tokyo. Our client sends a real `CIRCLE` area and would work against a
  live network, but no geofence is being computed in the demo.
- **The sandbox is effectively binary.** Only one number is clean. A mixed profile such as
  "SIM clean but calls forwarded" cannot be demonstrated on live sandbox data.
- **Groq's free tier allows about 1.8 evaluations per minute** (8,000 tokens per minute
  per model). A human-paced demo stays inside it; firing scenarios back to back does not,
  and then the deterministic fallback answers instead and says it did.

**⚠️ Not yet reviewed.** The Arabic, Hindi and Urdu scripts in `app/voice/scripts.py` were
written during the build and **have not been checked by native speakers**. They must be
before any real customer hears them. The Arabic is Modern Standard on purpose: dialect
synthesis is poor enough that a bad Gulf accent would sound less trustworthy than clear MSA.

---

## Repository

```
docs/camara-findings.md     Ground truth: observed request and response shapes, measured
docs/decisions.md           Why we built it this way, including what we rejected
docs/architecture.md        Component map
backend/app/camara/         One thin typed module per API, plus labelled fallback cache
backend/app/agent/          Tools, prompts, deterministic scoring, the agent itself
backend/app/voice/          Scripts in four languages, classification, the call
backend/app/services/       Audit trail and the live event broker
backend/scripts/spikes/     The Phase 1 probes, kept
frontend/app/checkout/      The demo surface
frontend/app/dashboard/     The fraud-ops console
```

Two rules the code holds to, both enforced by tests: **every CAMARA call and every
decision goes through the audit trail**, and **a cached response is labelled as cached
everywhere it appears**.

Built with Pydantic AI, Groq, Vapi, ElevenLabs, Deepgram, Whisper, FastAPI, PostgreSQL
and Next.js. All from the approved Resource and Tooling Guide.

## Team

Ahmad Abu Alarjah on network and CAMARA architecture, Khader Kheirallah on network
signals and cloud, Fadil Pasha on the backend, decision API and audit trail, Rizwanul
Asim across the full stack covering the agent, API, console and voice, Ryhan Nijam on
voice intervention and testing.
