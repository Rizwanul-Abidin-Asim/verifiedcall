"""Types for the risk agent.

The split that matters: the LLM decides WHICH signals to pull and writes the narrative;
`scoring.py` turns observed facts into the number. See docs/decisions.md — an LLM must
not invent a risk score in a payments system, because a bank has to reproduce and defend
it to a regulator.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import DecisionOutcome


class AgentMode(StrEnum):
    LLM = "llm"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class TransactionContext(BaseModel):
    """What the agent knows before pulling any network signal."""

    amount: Decimal
    currency: str = "AED"
    merchant_name: str
    is_new_beneficiary: bool
    customer_locale: str = "en"
    local_hour: int = Field(ge=0, le=23, default=12)
    signal_msisdn: str

    def describe(self) -> str:
        """Rendered into the prompt. Keep it short — it is read on every turn."""
        payee = "FIRST-TIME payee" if self.is_new_beneficiary else "known payee"
        return (
            f"Amount {self.amount} {self.currency} to {self.merchant_name} ({payee}). "
            f"Local time {self.local_hour:02d}:00. Customer language: {self.customer_locale}."
        )
    device_location_denied: bool = False
    """The customer refused to share the handset's position.

    Not proof of anything on its own. A bank still has to decide without it, and the
    honest reading is that we lost a check rather than that the customer is guilty."""



class ReasoningStep(BaseModel):
    """One line of the audit narrative shown to judges and fraud analysts.

    This is a deliverable, not a debug log — every field exists to be rendered.
    """

    step: int
    kind: Literal["context", "signal", "assessment"]
    observed: str
    rationale: str
    score_delta: int = 0
    running_score: int = 0
    signal: str | None = None
    source: str | None = None
    latency_ms: float | None = None


class AgentOpinion(BaseModel):
    """The LLM's structured output.

    Note what is absent: a risk score. The model gives a judgement and an explanation;
    the number comes from scoring.py.
    """

    recommended_outcome: DecisionOutcome
    summary: str = Field(
        description="Two or three sentences a fraud analyst would read. Plain English, "
                    "no jargon, explaining what you checked and what you concluded."
    )
    why_these_signals: str = Field(
        description="Why you chose to pull the signals you pulled, and why you skipped "
                    "any others. Be specific about the trade-off you made."
    )


class RiskDecision(BaseModel):
    """The complete result. Persisted, returned by the API, rendered on the dashboard."""

    outcome: DecisionOutcome
    risk_score: int = Field(ge=0, le=100)
    summary: str
    reasoning_trace: list[ReasoningStep]
    signals_pulled: list[str]
    total_latency_ms: float
    used_fallback: bool = False
    agent_mode: AgentMode = AgentMode.LLM
    disagreement: str | None = None
    """Set when the model's recommendation differed from the scored outcome.

    We take the more cautious of the two and record that we did, rather than silently
    preferring one. A judge asking "what if the model is wrong?" gets a real answer."""
