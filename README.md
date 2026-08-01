# VerifiedCall

> Judge-facing README is written last (PROMPT 10). This is a stub so the repo isn't bare.

Detecting **authorised push payment (APP) fraud** — the scam where the victim, under
social-engineering pressure from someone impersonating their bank, sends the money
themselves. The transaction is correctly authenticated, so conventional SIM-swap fraud
tooling sees nothing wrong.

VerifiedCall scores the transaction with CAMARA network signals, and when risk is high an
AI voice agent calls the customer in their own language and runs a scam-interrogation
script before the payment settles.

Built for the **GSMA MENA Ignite Hackathon**, Theme 4 — Secure Fintech, Payments &
Anti-Fraud.

See [CLAUDE.md](CLAUDE.md) for the stack, layout, and working rules.

## Quickstart

```bash
cp .env.example .env      # fill in credentials
docker compose up -d      # postgres 16 + redis 7
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```
