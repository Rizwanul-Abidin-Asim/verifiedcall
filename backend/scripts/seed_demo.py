"""Load the four demo scenarios.

Run:  uv run python scripts/seed_demo.py [--call-number +9715XXXXXXX]

The --call-number option sets the phone that the voice agent would actually ring, while
signal lookups still use Nokia's sandbox numbers. That split is the demo seam described
in db/models.py: it is recorded per transaction and shown on the dashboard rather than
hidden.
"""

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import Transaction  # noqa: E402
from app.db.session import create_all, dispose_engine, get_sessionmaker  # noqa: E402

SANDBOX_HIGH_RISK = "+99999991000"  # swapped SIM, forwarding on, roaming, wrong location
SANDBOX_CLEAN = "+99999991001"  # everything green
SANDBOX_OUTAGE = "+99999990500"  # forces HTTP 500 on all four APIs

SCENARIOS = [
    {
        "name": "1. Clean transaction — expect APPROVE",
        "amount": Decimal("240.00"),
        "merchant_name": "Carrefour Mall of the Emirates",
        "beneficiary_id": "BEN-KNOWN-0041",
        "is_new_beneficiary": False,
        "signal_msisdn": SANDBOX_CLEAN,
        "customer_locale": "en",
    },
    {
        "name": "2. Recent SIM swap + new beneficiary — expect DECLINE",
        "amount": Decimal("18500.00"),
        "merchant_name": "Direct transfer",
        "beneficiary_id": "BEN-NEW-9912",
        "is_new_beneficiary": True,
        "signal_msisdn": SANDBOX_HIGH_RISK,
        "customer_locale": "ar",
    },
    {
        "name": "3. Roaming + large amount + new beneficiary — expect INTERVENE "
                "(headline APP fraud case)",
        "amount": Decimal("42000.00"),
        "merchant_name": "Direct transfer — 'safe account'",
        "beneficiary_id": "BEN-NEW-7731",
        "is_new_beneficiary": True,
        "signal_msisdn": SANDBOX_HIGH_RISK,
        "customer_locale": "ur",
    },
    {
        "name": "4. Location mismatch, moderate amount — expect INTERVENE",
        "amount": Decimal("6300.00"),
        "merchant_name": "Al Ansari Exchange",
        "beneficiary_id": "BEN-NEW-2280",
        "is_new_beneficiary": True,
        "signal_msisdn": SANDBOX_HIGH_RISK,
        "customer_locale": "hi",
    },
]


async def seed(call_number: str) -> None:
    await create_all()
    async with get_sessionmaker()() as session:
        for scenario in SCENARIOS:
            fields = {k: v for k, v in scenario.items() if k != "name"}
            txn = Transaction(customer_msisdn=call_number, currency="AED", **fields)
            session.add(txn)
            await session.flush()
            seam = "  [demo seam: signals != call target]" if txn.is_demo_seam else ""
            print(f"  {txn.id}  {scenario['name']}{seam}")
        await session.commit()
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--call-number", default=SANDBOX_CLEAN,
        help="Real phone the voice agent would ring during the demo.")
    args = parser.parse_args()
    print("Seeding demo scenarios...")
    asyncio.run(seed(args.call_number))
    print("Done.")
