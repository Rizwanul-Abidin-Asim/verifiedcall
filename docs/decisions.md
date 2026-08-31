# Decisions (ADR-lite)

Short records of *why*, written as we go rather than reconstructed at the end.

## ADR-000 — Repository shape

**Date:** 2026-08-12
**Status:** accepted

`camara/` holds one thin, typed module per API so a sandbox limitation breaks exactly one
file. The agent layer never issues HTTP itself — it reaches the network only through
`agent/tools.py`. Audit is a service (`services/audit.py`), not a side effect, because the
audit trail is a scored deliverable rather than a debugging convenience.

---

Still to write (PROMPT 10): why Pydantic AI over LangGraph (type safety in a payments
context), why Groq (checkout latency budget), why voice intervention over a silent decline.

## ADR-001 — The model orchestrates; a deterministic function scores

**Date:** 2026-08-12 · **Status:** accepted

The hackathon rewards agentic orchestration and explicitly does not reward rules engines,
so the agent genuinely chooses which network signals to pull. But this is a payments
system: if a bank asks "why 43?", "the model produced that number" is not an answer a
regulator accepts, and the same transaction must always score the same.

So the split is: **the LLM decides what to check and writes the explanation; `scoring.py`
turns observed facts into the number and the outcome.** Weights live in one reviewable
dict. Most entries will let the model emit a score; being able to say why we did not is
a stronger position than doing it.

## ADR-002 — We do not decline when the customer appears present

**Date:** 2026-08-12 · **Status:** accepted

Decline is reserved for evidence that the person transacting is *not* the customer —
in practice, the network not placing the device where the payment originates.

Refusing a payment the genuine customer is making does not protect them. It leaves them
with a failed transfer and no explanation, and it does nothing about the person on the
phone pressuring them. A thirty-second call resolves coercion; a decline does not. So
when the model recommends declining a payment where the customer is demonstrably present,
the policy engine overrides it to `intervene` and records the disagreement.

This is the product thesis expressed as code, and it is what separates scenario 2
(device elsewhere → theft → decline) from scenario 3 (device present → coercion → call).

## ADR-003 — Selectivity has a floor: mandatory evidence before declining

**Date:** 2026-08-12 · **Status:** accepted

Observed live: the agent skipped the location check on a high-risk transaction, which
meant we could never establish absence and therefore could never justify a decline.

Rather than decline on thinner grounds, the policy engine pulls the missing location
check itself whenever a transaction scores in the decline band without it. One extra
~300ms call, only on already-suspicious payments. **We never decline without the evidence
that justifies declining.**

## ADR-004 — Model choice, and why it is a setting

**Date:** 2026-08-12 · **Status:** accepted

GSMA's Theme 4 sample names Groq with Llama 3.3 70B. **That model has been retired from
Groq** — it 404s and is no longer in the model list. Teams copying the sample will find
this out late. We use `openai/gpt-oss-120b` on Groq, with `reasoning_effort=low`:
measured 1238ms per turn at the default versus 684ms on low, selecting the same check.

`LLM_PROVIDER` is a setting (`groq` | `gemini`) so a rate limit mid-pitch is a one-line
change. Gemini is configured but **not** viable as primary: its free tier allows only
**5 requests per minute**, which four demo scenarios exhaust immediately. Gemini's
`gemini-2.5-flash` is also already closed to new users — `gemini-3.6-flash` replaces it.

**Measured end to end, live:** approve path (agent pulls nothing) ~1.2s; flagged paths
~5.3–6.7s. Latency matters on the approve path, which is the overwhelming majority of
real traffic; a flagged payment is being held for a phone call anyway. Reducing the
flagged-path time is a known tuning target, not a solved problem.

## ADR-005 — Prompt size, and the free-tier ceiling we actually hit

**Date:** 2026-08-29 · **Status:** accepted

Live runs kept dropping into the deterministic fallback on the third and fourth
scenario. Measured cause, from Groq's own rate-limit headers: the constraint is
**tokens per minute, not requests**. The limit is **8,000 TPM per model** (requests were
never close: 965 of 1,000 remaining while the token budget drained).

One evaluation costs roughly 4,400 tokens across its two turns, because a tool-calling
exchange resends the system prompt and the tool schemas on the second turn. That allows
about **1.8 evaluations per minute**, which is why two succeed and the next two throttle.

We trimmed the system prompt and the tool docstrings by 31% (2,512 to 1,738 tokens per
request). Verified the agent still behaves: it pulls zero signals on a clean payment and
still reaches decline on the device-elsewhere case. The approve path got faster,
2,487ms to 1,469ms.

That is not enough to fit four back-to-back evaluations, and cutting far enough to fit
would mean removing the instructions that make the agent selective, which is the thing
worth protecting. So:

- **A demo paced by a human stays inside the limit.** Roughly 40 seconds between
  scenarios is sufficient, which is slower than anyone clicks through a pitch anyway.
- **When it does throttle, the deterministic fallback produces the correct outcome**,
  pulls the full signal set, and says on the dashboard that it did so.

Rejected: short-circuiting the LLM for obviously clean payments. It would save the most
tokens on the most common case, but deciding without consulting the agent is exactly the
rules-engine behaviour the project argues against, and we would rather pay the tokens
than quietly become the thing we criticise.

## ADR-006 — We poll for the call result instead of waiting for a webhook

Vapi reports how a call went by POSTing an end-of-call report to a URL we give it. That
works for a deployed service and does not work on a laptop, where the fix is to run a
tunnel and paste a changing public URL into the provider before every demo. One more
moving part, on the machine that has to work on stage.

Vapi also exposes `GET /call/{id}` with a status that reaches `ended`, carrying the same
analysis, transcript and timings the webhook would have delivered. So a held payment now
starts a background task that polls that endpoint until the call finishes, and resolves
the transaction from the result.

The webhook route is still there and still works, because a deployed instance should use
it. Both paths call `resolve_call`, which ignores a report for a call that is already
resolved: whichever arrives first is the record. Without that guard a late webhook could
overwrite an outcome an analyst had already acted on, and in the worst ordering could
turn a blocked payment into a released one.

What this costs: a poll every three seconds for up to three minutes, and a resolution
that lands up to three seconds later than a webhook would have. What it buys: no tunnel,
no public URL, and one less thing to configure in the ten minutes before a pitch.

## ADR-007 — The provider extracts the answers; we measure the timing ourselves

The assistant carries an analysis plan asking Vapi to return, per question, whether the
customer said yes, no, or neither. That is a reasonable job for a language model reading
a transcript, and it means we are not writing yes/no vocabularies for four languages
against real speech.

Hesitation is different. How long someone paused before denying that anyone told them to
pay is the signal that separates scenario 3 from a clean call, and a model asked to
estimate a pause will produce a plausible number rather than a measured one. So the pause
is computed from the message timestamps in the transcript: the gap between the assistant
finishing a question and the customer starting to answer.

That computation can fail. If the message list has fewer gaps than there are questions,
we cannot say which pause belonged to which question, and we record no timing at all
rather than an alignment we are guessing at. Hesitation then simply does not fire. A
missing signal costs us a detection; a wrongly attributed one costs a real customer their
payment, and those are not equally bad.

## ADR-008 — The intervention can happen in the browser, and says so

We could not place a real call to a UAE mobile, and it is not a bug we can fix.
Etisalat and du are required to block VoIP-originated termination, and every AI voice
platform is VoIP-originated. `docs/telephony-findings.md` has the call records: two
attempts, 55 seconds of ringback each, never billed, never delivered, nothing in the
recipient's log.

So `VOICE_CHANNEL=web` carries the same conversation over the page instead. The server
still builds the assistant, so the interrogation script stays in version control rather
than moving into a dashboard or into the browser. The page receives a definition to
play, reports the call id back, and from that point the code is the one already written
for phone calls: the same polling, the same answer extraction, the same hesitation
timing, the same resolution and the same guard against a second report.

That reuse is the reason this was two hours rather than two days. Only the first step
of the intervention was ever telephony-specific.

The channel is a column, not a mode flag, because a web call is not a phone call and
the dashboard should not imply one rang. Every existing row migrated to `phone`, which
is what those calls were.

What this costs: the customer has to be at the checkout to take the call, which a real
deployment would not accept. In a real deployment the bank is the operator's customer
and would reach the handset over the operator's own network, which is the thing this
whole project argues for. The demo constraint and the product argument point the same
way.

## ADR-009 — Vapi stays, on evidence rather than inertia

Once the phone path failed we re-examined the platform choice rather than defending it.

ElevenLabs Agents looked like the natural alternative, since ElevenLabs already supplies
our voice inside Vapi. Two findings settled it. It issues no phone numbers at all, so it
requires the same Twilio import rather than avoiding it. And its transcript timing is
`time_in_call_secs`, an integer, so a 3,500 ms hesitation threshold cannot be expressed
at all. That threshold is the signal separating a coerced customer from a clean one.

Retell has the best timing data of the three, with word-level start and end times, and
on a blank sheet it would be the strongest technical fit. It cannot call the UAE, and
switching would mean rewriting a tested integration for a platform that does not solve
the blocker either.

So Vapi stays: adequate timing, ElevenLabs voice already included, tested, and no worse
than the alternatives on the thing that actually stopped us. Recorded because "we kept
what we had" and "we checked and kept what we had" are different, and only the second
one is a decision.
