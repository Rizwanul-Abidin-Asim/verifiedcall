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
