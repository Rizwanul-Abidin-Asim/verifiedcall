"""CAMARA signals exposed as agent tools.

Every docstring here is a prompt: it is what the model reads when deciding whether a
check is worth its latency. They state what fraud signal the check gives, what it costs,
and when it is NOT worth calling — that last part is what makes the agent selective
rather than a checklist.

The agent layer never touches HTTP. These functions call app/camara/ and nothing else,
and every one of them writes to the audit trail.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from pydantic_ai import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import TransactionContext
from app.camara.call_forwarding import check_call_forwarding
from app.camara.device_status import check_device_status
from app.camara.location_verification import CITY_CENTRES, verify_location
from app.camara.models import SignalResult
from app.camara.sim_swap import check_sim_swap
from app.services.audit import record_signal_call

log = logging.getLogger("agent.tools")


@dataclass
class AgentDeps:
    """Everything the tools need. Passed through Pydantic AI's RunContext."""

    session: AsyncSession
    transaction_id: object
    context: TransactionContext
    collected: list[SignalResult] = field(default_factory=list)
    expected_city: str = "AE-DXB"
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def capture(self, signal: SignalResult, request_payload: dict) -> None:
        """Record a signal once, to both the audit trail and the run's collection.

        Single place so a tool cannot accidentally skip the audit — the standing rule is
        that every CAMARA call is persisted, with no exceptions.

        The lock matters. The model issues several tool calls in one turn and they run
        concurrently, which is exactly what keeps us inside the latency budget — but an
        AsyncSession cannot be used from two coroutines at once, and overlapping flushes
        raise "Session is already flushing". Only the database write is serialised; the
        CAMARA requests themselves, where the time actually goes, still overlap.
        """
        async with self._write_lock:
            await record_signal_call(
                self.session, self.transaction_id, signal,
                request_payload=request_payload)
            self.collected.append(signal)


def _already_pulled(deps: AgentDeps, api_name: str) -> SignalResult | None:
    return next((s for s in deps.collected if s.api_name == api_name), None)


def _provenance(signal: SignalResult) -> str:
    if not signal.is_fallback:
        return ""
    return (" [NOTE: this came from cache, not the live network, because "
            f"{signal.fallback_reason}. Treat it as weaker evidence.]")


async def check_call_forwarding_tool(ctx: RunContext[AgentDeps]) -> str:
    """Check whether the customer's incoming calls are being diverted.

    The strongest indicator of a scam in progress: if unconditional forwarding is active,
    calls are being intercepted now and the bank could not reach the customer. Worth
    calling on any payment that looks unusual. About 300ms.
    """
    deps = ctx.deps
    if (existing := _already_pulled(deps, "call_forwarding")) is not None:
        return f"Already checked: forwarding active = {existing.active}."

    payload = {"phoneNumber": deps.context.signal_msisdn}
    signal = await check_call_forwarding(deps.context.signal_msisdn)
    await deps.capture(signal, payload)

    if not signal.active:
        return "No call forwarding is active. Calls reach the customer normally." \
            + _provenance(signal)
    types = ", ".join(t for t in signal.forwarding_types if t != "inactive")
    return (f"UNCONDITIONAL CALL FORWARDING IS ACTIVE"
            f"{f' (types: {types})' if types else ''}. The customer's calls are being "
            f"diverted." + _provenance(signal))


async def check_sim_swap_tool(ctx: RunContext[AgentDeps]) -> str:
    """Check whether the SIM behind this number was recently replaced.

    Means one-time passcodes may reach someone else. Weaker evidence for APP fraud than
    for account takeover, because here the genuine customer is the one authorising, so a
    clean SIM does not make the payment safe. About 300ms.
    """
    deps = ctx.deps
    if (existing := _already_pulled(deps, "sim_swap")) is not None:
        return f"Already checked: SIM swapped = {existing.swapped}."

    payload = {"phoneNumber": deps.context.signal_msisdn, "maxAge": 240}
    signal = await check_sim_swap(deps.context.signal_msisdn)
    await deps.capture(signal, payload)

    if not signal.swapped:
        return "No SIM swap in the last 10 days." + _provenance(signal)
    return "The SIM was swapped within the last 10 days." + _provenance(signal)


async def check_device_roaming_tool(ctx: RunContext[AgentDeps]) -> str:
    """Check whether the device is on a foreign network, and which country.

    A customer abroad is harder to reach and easier to pressure; roaming plus a
    first-time payee is the classic shape. Not worth calling on a routine payment to a
    known payee. About 250ms.
    """
    deps = ctx.deps
    if (existing := _already_pulled(deps, "device_status")) is not None:
        return f"Already checked: roaming = {existing.roaming}."

    payload = {"device": {"phoneNumber": deps.context.signal_msisdn}}
    signal = await check_device_status(deps.context.signal_msisdn)
    await deps.capture(signal, payload)

    if not signal.roaming:
        return "The device is on its home network." + _provenance(signal)
    where = ", ".join(signal.country_names) or str(signal.country_code or "unknown")
    return f"The device is ROAMING in {where}." + _provenance(signal)


async def verify_device_location_tool(ctx: RunContext[AgentDeps]) -> str:
    """Check whether the device is in the area this payment claims to come from.

    Separates two opposite situations: device not there means somebody else is probably
    operating the account, device there means the genuine customer is present and
    possibly being coached. Worth its latency whenever the other signals look bad.
    About 280ms.
    """
    deps = ctx.deps
    if (existing := _already_pulled(deps, "location_verification")) is not None:
        return f"Already checked: {existing.verification_result.value}."

    latitude, longitude = CITY_CENTRES.get(deps.expected_city, CITY_CENTRES["AE-DXB"])
    payload = {
        "device": {"phoneNumber": deps.context.signal_msisdn},
        "area": {"areaType": "CIRCLE",
                 "center": {"latitude": latitude, "longitude": longitude},
                 "radius": 50_000},
    }
    signal = await verify_location(deps.context.signal_msisdn, latitude, longitude)
    await deps.capture(signal, payload)

    described = {
        "TRUE": "The device IS within 50km of the expected location.",
        "FALSE": "The device is NOT within 50km of the expected location.",
        "PARTIAL": "The device is only partially within the expected area.",
        "UNKNOWN": "The network could not locate the device.",
    }[signal.verification_result.value]
    rate = f" Match rate {signal.match_rate}%." if signal.match_rate is not None else ""
    return described + rate + _provenance(signal)


ALL_TOOLS = [
    check_call_forwarding_tool,
    check_sim_swap_tool,
    check_device_roaming_tool,
    verify_device_location_tool,
]
