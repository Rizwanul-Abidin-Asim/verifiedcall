"""The risk agent.

Division of labour, and the reason for it:

  LLM               chooses which signals to pull, and writes the explanation
  scoring.py        turns the observed facts into the number and the outcome
  this module       runs both, reconciles them, and guarantees an answer

If the model and the scorer disagree on the outcome we take the MORE CAUTIOUS of the two
and record that we did. If the model is unavailable entirely we fall back to a
deterministic pass — pull everything, score it — and mark the decision so the dashboard
shows how it was reached. A live demo must never return an error page.
"""

import asyncio
import logging
import time

from pydantic_ai import Agent
from pydantic_ai.models import Model

from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agent.schemas import (
    AgentMode,
    AgentOpinion,
    ReasoningStep,
    RiskDecision,
    TransactionContext,
)
from app.agent.scoring import (
    APPROVE_BELOW,
    build_trace,
    choose_outcome,
    customer_appears_absent,
)
from app.agent.tools import ALL_TOOLS, AgentDeps
from app.camara.call_forwarding import check_call_forwarding
from app.camara.device_status import check_device_status
from app.camara.location_verification import CITY_CENTRES, verify_location
from app.camara.sim_swap import check_sim_swap
from app.config import settings
from app.db.models import DecisionOutcome

log = logging.getLogger("agent")

# Ordered least to most cautious. Used to reconcile a disagreement.
CAUTION_ORDER = [DecisionOutcome.APPROVE, DecisionOutcome.INTERVENE, DecisionOutcome.DECLINE]


def build_model() -> Model:
    """Resolve the configured provider. Swappable so a rate limit mid-pitch is a
    one-line .env change, and so we can compare how selective each model is."""
    provider = settings.llm_provider.lower()

    if provider == "groq":
        from pydantic_ai.models.groq import GroqModel
        from pydantic_ai.providers.groq import GroqProvider

        if not settings.groq_api_key:
            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is empty")
        return GroqModel(settings.groq_model,
                         provider=GroqProvider(api_key=settings.groq_api_key))

    if provider == "gemini":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        if not settings.gemini_api_key:
            raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is empty")
        return GoogleModel(settings.gemini_model,
                           provider=GoogleProvider(api_key=settings.gemini_api_key))

    raise RuntimeError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}; use groq|gemini")


def model_settings() -> dict:
    """Per-provider tuning.

    reasoning_effort=low on Groq is not a quality compromise here, it is the difference
    between fitting the checkout latency budget and not: measured 1238ms per turn at the
    default versus 684ms on low, with the model still selecting the same (correct) check.
    Two turns at the default would blow the 2s budget on its own, before any network
    signal is pulled.
    """
    base = {"temperature": 0.0, "parallel_tool_calls": True}
    if settings.llm_provider.lower() == "groq":
        base["groq_reasoning_effort"] = "low"
    return base


def build_agent(model: Model | None = None) -> Agent[AgentDeps, AgentOpinion]:
    """Assemble the agent. Pass a model to inject a test double."""
    return Agent(
        model or build_model(),
        deps_type=AgentDeps,
        output_type=AgentOpinion,
        system_prompt=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        retries=1,
        model_settings=model_settings(),
    )


def more_cautious(a: DecisionOutcome, b: DecisionOutcome) -> DecisionOutcome:
    return max(a, b, key=CAUTION_ORDER.index)


async def _pull_missing_signals(deps: AgentDeps) -> None:
    """Deterministic path: make sure every signal is present, concurrently.

    Tops up rather than starts fresh. A model that timed out halfway has usually already
    collected one or two signals, and an earlier version skipped this entirely whenever
    anything had been collected, which left the fallback deciding on partial evidence.
    """
    msisdn = deps.context.signal_msisdn
    latitude, longitude = CITY_CENTRES.get(deps.expected_city, CITY_CENTRES["AE-DXB"])
    already = {s.api_name for s in deps.collected}

    wanted = [
        ("call_forwarding", check_call_forwarding(msisdn), {"phoneNumber": msisdn}),
        ("sim_swap", check_sim_swap(msisdn), {"phoneNumber": msisdn, "maxAge": 240}),
        ("device_status", check_device_status(msisdn), {"device": {"phoneNumber": msisdn}}),
        ("location_verification", verify_location(msisdn, latitude, longitude),
         {"device": {"phoneNumber": msisdn},
          "area": {"areaType": "CIRCLE",
                   "center": {"latitude": latitude, "longitude": longitude},
                   "radius": 50_000}}),
    ]
    pending = [(name, coro, payload) for name, coro, payload in wanted if name not in already]
    for _, coro, _ in [w for w in wanted if w[0] in already]:
        coro.close()                      # never leave an un-awaited coroutine behind

    if not pending:
        return
    results = await asyncio.gather(*(coro for _, coro, _ in pending))
    for signal, (_, _, payload) in zip(results, pending, strict=True):
        await deps.capture(signal, payload)


async def _ensure_location_before_acting(deps: AgentDeps) -> bool:
    """On any flagged payment, make sure we have the check that decides what to do.

    Location is what separates the two actions: a device that is not where the payment
    claims means decline, a device that is present means call the customer. Without it we
    can only ever intervene, which quietly makes decline unreachable.

    An earlier version of this gated on the decline threshold, which was circular: the
    score cannot reach that threshold without the location check in the first place. A
    live run caught it. So the floor is the flag threshold, not the decline threshold.

    Clean payments are untouched, because they never reach it. Costs one extra ~300ms
    call on payments we were going to hold anyway. Returns True if a signal was added.
    """
    score, _ = build_trace(deps.context, deps.collected)
    if score < APPROVE_BELOW:
        return False
    if any(s.api_name == "location_verification" for s in deps.collected):
        return False

    latitude, longitude = CITY_CENTRES.get(deps.expected_city, CITY_CENTRES["AE-DXB"])
    log.info("agent.mandatory_evidence pulling location check; score=%d", score)
    signal = await verify_location(deps.context.signal_msisdn, latitude, longitude)
    await deps.capture(signal, {
        "device": {"phoneNumber": deps.context.signal_msisdn},
        "area": {"areaType": "CIRCLE",
                 "center": {"latitude": latitude, "longitude": longitude},
                 "radius": 50_000}})
    return True


def _assemble(deps: AgentDeps, opinion: AgentOpinion | None, started: float,
              mode: AgentMode, extra_steps: list[ReasoningStep]) -> RiskDecision:
    """Shared tail: score what was collected and produce the final decision."""
    score, trace = build_trace(deps.context, deps.collected)
    scored_outcome, scored_rationale = choose_outcome(score, deps.collected)

    outcome = scored_outcome
    disagreement = None
    if opinion is not None and opinion.recommended_outcome is not scored_outcome:
        proposed = more_cautious(opinion.recommended_outcome, scored_outcome)
        model_said = opinion.recommended_outcome.value

        # Guard rail. "More cautious" is the right instinct for approve versus hold, but
        # it is wrong for decline: refusing a payment the genuine customer is making does
        # not protect them, it just leaves them with a failed transfer and no
        # explanation, and it does nothing to stop the coercion. Decline is reserved for
        # the case where the evidence says the customer is not the one transacting. So
        # the model may escalate to a hold, but it may not talk us into a false decline.
        if proposed is DecisionOutcome.DECLINE and not customer_appears_absent(
                deps.collected):
            outcome = DecisionOutcome.INTERVENE
            disagreement = (
                f"The analyst model recommended '{model_said}' while the scoring engine "
                f"reached '{scored_outcome.value}'. Policy does not allow declining a "
                f"payment when the customer appears present and reachable — a false "
                f"decline harms a real customer and does nothing to stop coercion — so "
                f"the payment is held for a verification call instead.")
        else:
            outcome = proposed
            disagreement = (
                f"The analyst model recommended '{model_said}' while the scoring engine "
                f"reached '{scored_outcome.value}'. We took the more cautious of the "
                f"two: '{outcome.value}'.")
        log.info("agent.disagreement model=%s scored=%s taken=%s",
                 opinion.recommended_outcome, scored_outcome, outcome)

    trace = extra_steps + trace
    trace.append(ReasoningStep(
        step=len(trace) + 1, kind="assessment",
        observed=f"Final score {score} of 100 -> {outcome.value}",
        rationale=scored_rationale + (f" {disagreement}" if disagreement else ""),
        running_score=score))
    for position, step in enumerate(trace, start=1):
        step.step = position

    summary = opinion.summary if opinion else scored_rationale

    return RiskDecision(
        outcome=outcome,
        risk_score=score,
        summary=summary,
        reasoning_trace=trace,
        signals_pulled=[s.api_name for s in deps.collected],
        total_latency_ms=round((time.perf_counter() - started) * 1000, 1),
        used_fallback=any(s.is_fallback for s in deps.collected),
        agent_mode=mode,
        disagreement=disagreement,
    )


async def evaluate(
    session,
    transaction_id,
    context: TransactionContext,
    model: Model | None = None,
    expected_city: str = "AE-DXB",
    device_latitude: float | None = None,
    device_longitude: float | None = None,
) -> RiskDecision:
    """Assess one transaction. Always returns a decision — never raises."""
    started = time.perf_counter()
    deps = AgentDeps(session=session, transaction_id=transaction_id, context=context,
                     expected_city=expected_city, device_latitude=device_latitude,
                     device_longitude=device_longitude)

    try:
        agent = build_agent(model)
        result = await asyncio.wait_for(
            agent.run(build_user_prompt(context.describe()), deps=deps),
            timeout=settings.agent_timeout_s,
        )
        opinion: AgentOpinion = result.output
        completed = await _ensure_location_before_acting(deps)
        note = ReasoningStep(
            step=0, kind="context",
            observed=f"Agent chose to pull {len(deps.collected)} of 4 available signals",
            rationale=opinion.why_these_signals + (
                " The policy engine then added the location check, because this payment "
                "was going to be held either way and location is what decides whether a "
                "held payment is declined or verified by phone." if completed else ""))
        return _assemble(deps, opinion, started, AgentMode.LLM, [note])

    except Exception as exc:  # noqa: BLE001 — a live demo must not surface a stack trace
        log.warning("agent.llm_unavailable falling back to deterministic path: %r", exc)

    # The model is unavailable, slow, or returned something unusable. Pull everything
    # and score it. Slower and less selective, but it always produces an answer.
    try:
        await _pull_missing_signals(deps)
    except Exception as exc:  # noqa: BLE001
        log.error("agent.signals_unavailable %r", exc)

    note = ReasoningStep(
        step=0, kind="context",
        observed="Reasoning model unavailable, deterministic fallback used",
        rationale="The analyst model could not be reached, so every available signal was "
                  "pulled and scored by the deterministic engine. The decision is sound "
                  "but less selective than usual, and no written analyst summary is "
                  "available for this transaction.")
    return _assemble(deps, None, started, AgentMode.DETERMINISTIC_FALLBACK, [note])
