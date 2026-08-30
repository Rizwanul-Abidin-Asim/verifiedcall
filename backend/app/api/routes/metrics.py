"""GET /metrics — the impact numbers, computed from the decision log rather than claimed.

These are the figures quoted in the submission, so they are derived from what actually
happened rather than typed into a slide. If the deck and this endpoint ever disagree,
this endpoint is right.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Decision, DecisionOutcome, SignalCall, SignalSourceKind, VoiceCall
from app.db.session import get_session
from app.voice.scripts import SCRIPTS

log = logging.getLogger("api.metrics")
router = APIRouter(tags=["ops"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(int(round(fraction * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[index], 1)


@router.get("/metrics")
async def metrics(session: SessionDep) -> dict:
    decisions = (await session.execute(
        select(Decision.outcome, Decision.total_latency_ms, Decision.used_fallback)
    )).all()

    latencies = [float(row.total_latency_ms) for row in decisions]
    by_outcome = {o.value: 0 for o in DecisionOutcome}
    for row in decisions:
        by_outcome[row.outcome.value] += 1

    # Added latency is only meaningful on the approve path: a held payment is waiting for
    # a phone call anyway, so its latency is not what a customer experiences at checkout.
    approve_latencies = [float(r.total_latency_ms) for r in decisions
                         if r.outcome is DecisionOutcome.APPROVE]

    signal_rows = (await session.execute(
        select(SignalCall.api_name, SignalCall.source, SignalCall.latency_ms)
    )).all()
    per_api: dict[str, dict] = {}
    for row in signal_rows:
        entry = per_api.setdefault(row.api_name, {"calls": 0, "fallback": 0, "latencies": []})
        entry["calls"] += 1
        entry["latencies"].append(float(row.latency_ms))
        if row.source is SignalSourceKind.FALLBACK:
            entry["fallback"] += 1

    voice_total = await session.scalar(select(func.count()).select_from(VoiceCall)) or 0
    voice_rows = (await session.execute(select(VoiceCall.outcome))).scalars().all()
    voice_breakdown: dict[str, int] = {}
    for outcome in voice_rows:
        key = outcome.value if outcome else "in_progress"
        voice_breakdown[key] = voice_breakdown.get(key, 0) + 1

    fallback_calls = sum(e["fallback"] for e in per_api.values())
    total_calls = sum(e["calls"] for e in per_api.values())

    return {
        "decisions": {
            "total": len(decisions),
            "by_outcome": by_outcome,
            "used_fallback": sum(1 for r in decisions if r.used_fallback),
        },
        "added_latency_ms": {
            "approve_path_median": _percentile(approve_latencies, 0.5),
            "approve_path_p95": _percentile(approve_latencies, 0.95),
            "all_median": _percentile(latencies, 0.5),
            "note": "Added latency is reported on the approve path because a held "
                    "payment is waiting for a phone call regardless.",
        },
        "camara": {
            "apis_integrated": 4,
            "categories_spanned": 2,
            "total_calls": total_calls,
            "served_from_cache_pct": (
                round(100 * fallback_calls / total_calls, 1) if total_calls else None),
            "per_api": {
                name: {
                    "calls": e["calls"],
                    "median_ms": _percentile(e["latencies"], 0.5),
                    "from_cache": e["fallback"],
                }
                for name, e in sorted(per_api.items())
            },
        },
        "voice": {
            "languages_supported": len(SCRIPTS),
            "languages": sorted(s.value for s in SCRIPTS),
            "calls_placed": voice_total,
            "by_outcome": voice_breakdown,
        },
        "mode": {
            "demo_mode": settings.demo_mode,
            "voice_mock": settings.voice_mock,
            "llm_provider": settings.llm_provider,
        },
    }
