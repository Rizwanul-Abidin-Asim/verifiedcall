# Demo runsheet

Everything below was verified live on 2026-09-13. Numbers are the constants in the code,
not estimates: weights from `app/agent/scoring.py`, costs from `docs/business-model.md`.

---

## Before you start

```bash
# terminal 1
cd backend && DATABASE_URL="sqlite+aiosqlite:///./web.db" uv run uvicorn app.main:app --port 8000
# terminal 2
cd frontend && npm run dev
```

Two browser tabs, side by side:

| Tab | URL | What it is |
|---|---|---|
| Left | `localhost:3000/checkout` | The customer's phone |
| Right | `localhost:3000/dashboard` | The bank's fraud desk |

**Three things that will ruin a take if you skip them:**

1. **Wear headphones.** No echo cancellation is perfect. Without them the assistant hears
   itself through the laptop speakers and starts answering its own questions.
2. **Close anything else using the microphone** — Teams, Zoom, another browser tab. Two
   processes cannot own one mic; Vapi opens its track and gets silence.
3. **Leave ~40 seconds between payments.** Groq's free tier rate-limits faster than that.
   If you rush it the trace says "deterministic fallback" — the answer is still right, but
   you lose the agentic story, which is the thing being judged.

---

## The flow, end to end

One payment, nine steps. Steps 3, 5 and 8 are the AI; everything else is deterministic.

| # | What happens | Who decides | Cost |
|---|---|---|---|
| 1 | Payment submitted. The gateway **holds** it — nothing has moved | gateway | — |
| 2 | **Free triage** from the payment itself: amount, first-time payee, hour of day, did the phone share location | deterministic | 0 API calls |
| 3 | **Agent picks the checks** — which of 7 network APIs are worth their latency, or none at all | **AI** · Groq gpt-oss-120b | ~$0.0008 |
| 4 | Chosen CAMARA calls run **in parallel** against Nokia Network as Code | — | p per call |
| 5 | Agent writes the analyst narrative in plain English | **AI** · same model | included |
| 6 | **Score**: fixed weights turn observed facts into 0–100 | deterministic | — |
| 7 | **Channel trust**: which routes to her are still hers | deterministic | — |
| 8 | **The intervention** — a conversation, or a silent in-app prompt | **AI** · Gemini 2.5 Flash via Vapi | $0.10–0.25 / ~$0 |
| 9 | Everything persisted: every call, decision, transcript, override | deterministic | — |

**Approve path: ~1.2 seconds and zero network calls.** Held path: 5–7 seconds.

---

## Where the AI is — and where it deliberately is not

This is the question the mentor caught us contradicting ourselves on. The answer is a line
we can point at in the code.

### AI, because judgement is needed

| Job | Model | Why it must be AI |
|---|---|---|
| Which of 7 checks to pull | Groq `gpt-oss-120b` via Pydantic AI | Genuine judgement per payment. Measured: **3 of 7** on a coached payment, **0 of 7** on a routine one |
| Writing the analyst narrative | same | Plain English a fraud analyst reads, not a template |
| The conversation itself | Gemini 2.5 Flash via Vapi | Understanding a frightened person in Arabic, Hindi or Urdu cannot be a rule |
| Reading her answers | Vapi structured extraction | Classification over natural language — "no one has told me" is a NO, not a keypad 1 |

**Resilience:** Groq → Gemini → deterministic floor. A live demo never errors.

### Deterministic, because accountability is needed

| Job | Why it must NOT be AI |
|---|---|
| The risk number (0–100) | A bank must reproduce and defend it. *"The model produced that number"* is not an answer a regulator accepts |
| Outcome bands (< 30 approve, ≥ 70 + device elsewhere → decline) | Same transaction, same signals, same outcome — every time |
| **Channel trust** (which door is safe) | *"We did not call her because the network said her calls were diverted"* is a sentence a bank may have to defend |
| Mandatory-evidence floor | We never decline without the location check that justifies declining |
| Guard rail | The model may escalate to a hold; it may **not** talk us into a false decline |

> **The line:** autonomy where judgement is needed, determinism where accountability is
> needed. The model orchestrates and explains; it does not score.

---

## The seven APIs, and why each one

All on Nokia Network as Code. All verified live with real requests.

| API | The question | Job | Weight |
|---|---|---|---|
| **Call Forwarding Signal** | Are her calls being diverted right now? | score **+ closes the voice door** | unconditional **30**, conditional **12** |
| **SIM Swap** | Would a text land on her SIM? | score **+ closes the text door** | **22** |
| **Device Swap** | Is the app still on the handset we know? | score **+ closes the app door** | **12**, **+18** paired with SIM Swap |
| **Device Reachability** | Can we reach her — SMS, DATA, neither? | **picks the door** | unreachable **+12** |
| **Location Verification** | Is the phone where the payment claims? | **decides decline vs call** | FALSE **+25**, TRUE **0** |
| **Device Roaming Status** | Is she abroad and isolated? | score | **8**, **+7** with new payee |
| **Location Retrieval** | Where is the handset, actually? | **explains a decline** to a human | 0 |

**Number Verification** returns **401** server-side — it needs the handset's own consent
over mobile data. Kept in the repo as evidence. Documented, not faked.

**The point to make out loud:** these are not seven generic risk points. Each one answers a
*different question about a different door*. Forwarding closes voice, SIM Swap closes text,
Device Swap and Reachability decide the app. That is what multi-API orchestration means.

---

## The runsheet — 3 minutes

Pace the payments ~40 s apart. Talk during the waits; the progress panel gives you
something to point at.

| Time | Do | Say |
|---|---|---|
| **0:00** | — | *"Someone phones you, says they're your bank, and talks you into moving your own money. Nothing gets hacked. Every check the bank runs asks 'is this really you' — and the answer is yes."* |
| **0:20** | Demo controls → **All clear** → Fill in headline payment → change amount to **2,500**, payee **Ahmed Karim** → send | *"An ordinary payment to someone she's paid before."* |
| **0:30** | Dashboard: click the new row | *"Approved in about a second — and look: **zero network checks**. The agent decided this payment didn't need the network's opinion, and wrote down why. That's the difference between an agent and a checklist."* |
| **0:50** | Checkout → Demo controls → **Phone is right here, line is clean** → Fill in headline payment → send | *"Now: 42,000 dirhams, to an account she's never paid, at 2am."* |
| **1:05** | Phone rings — **answer it** | *"Her phone is exactly where it should be and her line is clean — so we call. Only a conversation can tell a coached answer from a free one."* |
| **1:20** | Answer question 1 **"yes"** (or press 1) | *"Three questions about the scam's own story — not about the payment. A scammer can coach 'no' to 'did someone ask you to pay'. He can't coach 'no' to 'were you told your money is at risk' without contradicting himself."* |
| **1:40** | Let it finish, or hang up | — |
| **1:50** | Checkout → Demo controls → **Her calls are diverted** → Fill in headline payment → send | ⭐ *"Same payment. But this time the network says her calls are being forwarded."* |
| **2:05** | The **in-app sheet** appears — no call | ⭐ *"We don't ring her. That call would reach the fraudster, and he'd confirm the transfer in the bank's own voice. So we go to the app instead — silent, where he can't hear it — and show her the sentence he's been talking over."* |
| **2:20** | Dashboard → the new case → **Reach** tab | *"Three doors. Call — barred, call forwarding. App — open, we used it. Text — barred, SIM swap. A door nobody checked is grey, never red: unproven is not the same as compromised."* |
| **2:40** | **Your call** tab → type a reason → **Release** | *"And a human can overrule it. Recorded **beside** the agent's verdict, never over it — so the bank can ask how often it overrules the agent, and whether it was right."* |
| **2:55** | — | *"Existing tools ask 'is this really you'. We ask which door the attacker doesn't control yet — before the money leaves."* |

### If you have 5 minutes, add

| Do | Say |
|---|---|
| **Every route is barred** persona | *"Calls diverted, SIM replaced, handset replaced, device unreachable. We contact **no one** and page a human. Somebody arranging for her to be unreachable by her bank at this exact minute is not a coincidence — that's the finding, not a failure."* |
| **Phone is somewhere else** persona | *"Declined. And Location Retrieval says where: the network puts the handset 4,021 km away, in Budapest. 'verificationResult: FALSE' is not something an analyst can act on. 'Budapest' is."* |
| **Network outage** persona | *"Every CAMARA call fails. We still reach a decision — from cache, and every cached answer is **labelled cached** on screen. We never present cached data as live."* |

---

## Costs — what to say if asked

**Per payment:**

| Component | Cost | Basis |
|---|---|---|
| The agent | **~$0.0008** | ~4,200 input + ~350 output tokens at Groq's $0.15 / $0.60 per M |
| CAMARA calls | **p — not published** | Operators price per partner. Modelled across $0.01–$0.10 |
| Voice call (60–90 s) | **$0.10–0.25** | Vapi all-in. Only on the payments we actually call |
| In-app prompt | **~$0** | Preferred when the voice line is barred |
| SMS | ~$0.01 | Last resort, carries no code |

**Why being selective is the business case.** A bank running 10M payments a year, 5% checked,
~3 APIs each:

| | Check everything, all 7 | Our agent |
|---|---|---|
| CAMARA calls / year | 70,000,000 | **1,500,000** |
| At p = $0.03 | $2,100,000 | $45,000 |
| + agent + interventions | — | **~$54,000 total** |

**About 40× cheaper** — entirely because most payments never need the network's opinion.

**Break-even.** At the demo's AED 42,000 (~$11,400) per prevented scam:

> **Stop 5 scams a year and the whole system pays for itself** at p = $0.03.
> At the most pessimistic price we can imagine, p = $0.10, it's 14.
> Out of ten million payments.

**Honest caveat if pressed:** CAMARA per-call pricing is genuinely not public — operators
negotiate it per partner. We treat it as the unknown `p` rather than inventing a number,
which is also the number a bank would be negotiating.

---

## Questions to expect

**"Do you detect the scammer's call?"**
No, and we don't claim to. No operator API exposes who is phoning someone. We detect the
conditions that mean she probably can't speak freely, then ask her directly — on a channel
he doesn't control.

**"Is this real network data?"**
Nokia's simulator. No MENA operator is live on the platform yet. The API, the auth, the
latency and the error handling are all real.

**"Why does the dashboard show a payment held with a different phone number?"**
Simulator seam, and it's on screen. Each Nokia sandbox number has a fixed personality
across every API, and some ordinary real-world combinations — calls diverted but the
handset still hers — don't exist on any single number. So a demo persona sources each
answer from the number that simulates it. Every call is live; the dashboard prints which
number each fact came from.

**"Why not let the model produce the score?"**
Because a bank has to reproduce and defend it. The model chooses the checks and writes the
explanation; a reviewable table produces the number.

**"What if the model is wrong?"**
If it recommends declining a customer who is demonstrably present, policy overrides it to a
call and records the disagreement. A false decline harms a real customer and stops no
coercion.

**"Call Forwarding isn't deployed in MENA."**
Correct, and we say so on the market slide — 17 deployments across 9 markets, none in MENA.
It's why we redesigned around what operators have actually shipped: SIM Swap is live in 45
markets including UAE and Qatar. Missing signals read as *unproven*, never as *safe*.

---

## If something breaks

| Symptom | Do |
|---|---|
| Trace says "deterministic fallback" | Groq rate-limited. Say: *"that's the fallback, and it still reached the right answer."* Wait 40 s before the next one |
| Call fails, "we could not hear you" | Something else has the microphone. Close it, tap Answer again |
| Sandbox down | `DEMO_MODE=true`, restart backend. Everything works from cache and the dashboard says so |
| Frontend can't reach the API | The checkout says plainly that nothing has been charged |
