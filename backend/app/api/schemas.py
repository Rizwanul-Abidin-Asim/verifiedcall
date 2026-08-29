"""Request and response shapes for the HTTP API.

These are separate from app/agent/schemas.py on purpose: the agent's types describe how
we reason, these describe our contract with a payment gateway and a dashboard. Changing
one should not silently change the other.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from app.agent.schemas import AgentMode, ReasoningStep
from app.db.models import DecisionOutcome, VoiceOutcome, VoiceStatus

MSISDN = Annotated[str, Field(pattern=r"^\+[1-9]\d{6,17}$", examples=["+971500000000"])]


class EvaluateRequest(BaseModel):
    """What a payment gateway posts while it holds the transaction."""

    amount: Decimal = Field(gt=0, le=Decimal("99999999999.99"))
    currency: str = Field(default="AED", min_length=3, max_length=3)
    merchant_name: str = Field(min_length=1, max_length=200)
    beneficiary_id: str = Field(min_length=1, max_length=120)
    is_new_beneficiary: bool = False

    customer_msisdn: MSISDN
    """The number we would ring if this payment needs a verification call."""

    signal_msisdn: MSISDN | None = None
    """The number to look CAMARA signals up against.

    Defaults to customer_msisdn. They differ only in a demo, because Nokia's sandbox
    numbers are not real phones. The difference is recorded and shown, never hidden.
    """

    customer_locale: str = Field(default="en", max_length=8)
    local_hour: int | None = Field(default=None, ge=0, le=23)
    expected_city: str = Field(default="AE-DXB", max_length=16)

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, v: str) -> str:
        return v.upper()


class EvaluateResponse(BaseModel):
    decision_id: uuid.UUID
    transaction_id: uuid.UUID
    outcome: DecisionOutcome
    risk_score: int
    summary: str
    reasoning_trace: list[ReasoningStep]
    signals_pulled: list[str]
    latency_ms: float
    used_fallback: bool
    agent_mode: AgentMode
    disagreement: str | None = None
    demo_seam: bool = Field(
        description="True when signals were looked up against a different number than "
                    "the one we would call. Shown in the UI rather than hidden.")


class TransactionOut(BaseModel):
    id: uuid.UUID
    amount: Decimal
    currency: str
    merchant_name: str
    beneficiary_id: str
    is_new_beneficiary: bool
    customer_msisdn: str
    signal_msisdn: str
    customer_locale: str
    created_at: datetime
    demo_seam: bool


class SignalCallOut(BaseModel):
    id: uuid.UUID
    api_name: str
    source: str
    fallback_reason: str | None
    latency_ms: float
    request_payload: dict
    response_payload: dict | list
    called_at: datetime


class VoiceCallOut(BaseModel):
    id: uuid.UUID
    vapi_call_id: str | None
    language: str
    status: VoiceStatus
    outcome: VoiceOutcome | None
    transcript: str | None
    answers: dict
    duration_s: int | None
    is_mock: bool
    created_at: datetime


class DecisionListItem(BaseModel):
    decision_id: uuid.UUID
    transaction_id: uuid.UUID
    outcome: DecisionOutcome
    risk_score: int
    used_fallback: bool
    total_latency_ms: float
    decided_at: datetime
    amount: Decimal
    currency: str
    merchant_name: str
    is_new_beneficiary: bool
    signals_pulled: int
    voice_outcome: VoiceOutcome | None = None


class DecisionPage(BaseModel):
    items: list[DecisionListItem]
    total: int
    limit: int
    offset: int


class DecisionDetail(BaseModel):
    decision_id: uuid.UUID
    outcome: DecisionOutcome
    risk_score: int
    reasoning_trace: list[ReasoningStep]
    total_latency_ms: float
    used_fallback: bool
    decided_at: datetime
    transaction: TransactionOut
    signal_calls: list[SignalCallOut]
    voice_call: VoiceCallOut | None = None


class ErrorResponse(BaseModel):
    """Every failure the frontend can see. Never a stack trace."""

    error: str
    detail: str
