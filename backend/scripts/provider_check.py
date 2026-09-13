"""Does the agent actually reason, or does it fall back?

The hackathon requires an AI agent layer, and "the model rate-limited so the deterministic
engine decided" is not that. This script runs one real evaluation per provider against a
real transaction and reports which path it took, so we know before the pitch rather than
during it.

Usage:  uv run python scripts/provider_check.py [persona]
"""

import asyncio
import sys
from decimal import Decimal

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.agent.personas import PERSONAS  # noqa: E402
from app.agent.risk_agent import build_model, evaluate  # noqa: E402
from app.agent.schemas import AgentMode, TransactionContext  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.models import Transaction  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402


async def run_one(provider: str, persona_key: str) -> None:
    settings.llm_provider = provider
    persona = PERSONAS[persona_key]
    msisdn = persona.default_msisdn

    async with get_sessionmaker()() as session:
        txn = Transaction(
            amount=Decimal("42000.00"), currency="AED", merchant_name="Safe account",
            beneficiary_id="BEN-CHECK", is_new_beneficiary=True,
            customer_msisdn="+971500000000", signal_msisdn=msisdn, customer_locale="en")
        session.add(txn)
        await session.flush()

        context = TransactionContext(
            amount=Decimal("42000.00"), merchant_name="Safe account",
            is_new_beneficiary=True, signal_msisdn=msisdn, local_hour=2)

        try:
            model = build_model()
        except Exception as exc:  # noqa: BLE001
            print(f"{provider:8} UNAVAILABLE  {exc}")
            return

        decision = await evaluate(session, txn.id, context, model=model, persona=persona)
        await session.rollback()  # a probe must not leave rows in the demo database

    reasoned = decision.agent_mode is AgentMode.LLM
    print(f"{provider:8} {'REASONED' if reasoned else 'FELL BACK':10} "
          f"{decision.outcome.value:9} score={decision.risk_score:3} "
          f"{decision.total_latency_ms:7.0f}ms  "
          f"{len(decision.signals_pulled)} signals: {','.join(decision.signals_pulled)}")
    if reasoned:
        print(f"         summary: {decision.summary[:150]}")


async def main() -> None:
    persona_key = sys.argv[1] if len(sys.argv) > 1 else "voice_compromised"
    print(f"persona: {persona_key}\n")
    for provider in ("groq", "gemini"):
        await run_one(provider, persona_key)


if __name__ == "__main__":
    asyncio.run(main())
