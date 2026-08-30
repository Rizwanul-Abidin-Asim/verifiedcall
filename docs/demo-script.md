# Demo script

Three minutes. The point is the contrast between scenario 2 and scenario 3.

## Before going on stage

```bash
docker compose up -d                            # or use the SQLite path
cd backend && uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000         # terminal 1
cd frontend && npm run dev                      # terminal 2
uv run python scripts/smoke_test.py             # must print "safe to demo"
```

Have `/checkout` open in one tab and `/dashboard` in another.

Pace the scenarios at least 30 seconds apart. Groq's free tier allows about 1.8
evaluations per minute, and back-to-back submissions drop into the deterministic
fallback. That still gives the right answer, but the agentic story is better told when
the agent is doing the choosing.

If the sandbox is down, set `DEMO_MODE=true` and restart the backend. Everything works
from cache and the dashboard says so.

## Runsheet

| Time | Beat | What to do |
|---|---|---|
| 0:00 | **The problem.** "Someone phones you, says they are your bank, and talks you into moving your money. Nothing gets hacked. Every check the bank runs asks *is this really you*, and the answer is yes." | Slides |
| 0:30 | **A normal payment.** Scenario 1. Approved in about a second. | Checkout |
| 0:45 | **Show why that was fast.** The agent pulled zero network checks and wrote down why. "That is the difference between an agent and a checklist." | Dashboard, click the row |
| 1:10 | **Theft.** Scenario 2. Declined. | Checkout |
| 1:25 | **Why declined.** The network cannot place the phone where the payment came from, so calling the registered number would not reach the person spending the money. | Dashboard, reasoning trace |
| 1:50 | **Coercion.** Scenario 3. Identical signals, one difference: the phone is exactly where it should be. Held, and the customer is called. | Checkout, let the call resolve on screen |
| 2:20 | **The call.** Three questions. The customer admits they were told to pay and told not to tell their bank. Payment blocked. | Checkout shows the answers |
| 2:40 | **Honesty.** Point at the demo-seam banner and the cached labels. "Sandbox numbers are not real phones. We show the seam rather than hide it." | Dashboard detail |
| 2:50 | **Close.** "Existing tools ask is this really you. We ask whether someone is standing over you while you do it, in the customer's own language, before the money leaves." | |

## If something breaks

- **Sandbox down** → `DEMO_MODE=true`, restart. Decisions come from cache, labelled.
- **Agent slow** → it falls back automatically and the dashboard shows the mode. Say so:
  "that is the fallback, and it still reached the right answer."
- **Frontend cannot reach the API** → the checkout says plainly that nothing was charged.
- **Live voice mode** → keep `VOICE_MOCK=true` for the pitch. A free Vapi number cannot
  dial internationally, so on this account a live call fails, correctly, with the payment
  left held. That is worth showing as a failure story if asked, but not as the demo.

## Questions to expect

**"Do you detect the scammer's call?"** No, and we do not claim to. No operator API
exposes who is calling someone. We detect the conditions that mean the customer probably
cannot speak freely, then we ask them directly.

**"Is this real network data?"** It is Nokia's simulator. No MENA operator is live on the
platform yet. The API, the auth, the latency and the error handling are real.

**"Why not let the model produce the score?"** Because a bank has to reproduce and defend
the number. The model chooses the checks and writes the explanation; a reviewable table
produces the score.
