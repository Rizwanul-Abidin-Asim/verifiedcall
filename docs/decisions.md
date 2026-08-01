# Decisions (ADR-lite)

Short records of *why*, written as we go rather than reconstructed at the end.

## ADR-000 — Repository shape

**Date:** 2026-08-01
**Status:** accepted

`camara/` holds one thin, typed module per API so a sandbox limitation breaks exactly one
file. The agent layer never issues HTTP itself — it reaches the network only through
`agent/tools.py`. Audit is a service (`services/audit.py`), not a side effect, because the
audit trail is a scored deliverable rather than a debugging convenience.

---

Still to write (PROMPT 10): why Pydantic AI over LangGraph (type safety in a payments
context), why Groq (checkout latency budget), why voice intervention over a silent decline.
