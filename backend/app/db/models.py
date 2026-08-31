"""Persistence model for the decision log.

This is the audit trail, and the audit trail is a scored deliverable — a bank cannot
adopt a fraud system that can't explain itself to a regulator. Everything the agent saw
and everything it concluded is recorded here.

JSON columns use JSONB on Postgres and plain JSON elsewhere, so tests can run on SQLite
without Docker.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONColumn = JSON().with_variant(JSONB, "postgresql")


def enum_column(enum_cls, length: int) -> Enum:
    """Store the enum's VALUE ("live"), not its NAME ("LIVE").

    SQLAlchemy defaults to names. The dashboard, /metrics and any ad-hoc SQL read these
    columns directly, and they expect the same lowercase strings the API returns.

    create_constraint=True because it defaults to False since SQLAlchemy 1.4 — without
    it the column is a bare VARCHAR and the database would happily store source='banana'.
    "Was this signal live or cached?" is the honesty claim of this project; it should not
    be enforceable only by application code.
    """
    return Enum(enum_cls, native_enum=False, length=length, create_constraint=True,
                values_callable=lambda e: [m.value for m in e])


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DecisionOutcome(StrEnum):
    APPROVE = "approve"
    INTERVENE = "intervene"
    DECLINE = "decline"


class SignalSourceKind(StrEnum):
    LIVE = "live"
    FALLBACK = "fallback"


class VoiceStatus(StrEnum):
    PENDING = "pending"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class VoiceChannel(StrEnum):
    """How the customer was reached.

    A UAE mobile cannot be reached by any AI voice platform: Etisalat and du are
    required to block VoIP-originated termination, which we verified with call records
    rather than assumed. WEB carries the same conversation over the browser instead,
    with no carrier in the path. The distinction is recorded because a web call is not
    a phone call and the dashboard should not imply it was.
    """

    PHONE = "phone"
    WEB = "web"


class VoiceOutcome(StrEnum):
    CONFIRMED_LEGITIMATE = "confirmed_legitimate"
    SCAM_DETECTED = "scam_detected"
    NO_ANSWER = "no_answer"
    INCONCLUSIVE = "inconclusive"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AED")
    merchant_name: Mapped[str] = mapped_column(String(200))
    beneficiary_id: Mapped[str] = mapped_column(String(120))
    is_new_beneficiary: Mapped[bool] = mapped_column(Boolean, default=False)

    customer_msisdn: Mapped[str] = mapped_column(String(24))
    """The number we would CALL. In a demo this is a judge's real phone."""

    signal_msisdn: Mapped[str] = mapped_column(String(24))
    """The number we look CAMARA signals up against.

    In production these are the same. In a demo they differ, because Nokia's sandbox
    numbers are not real phones and a real phone has no sandbox signals. This split is
    deliberate and must be shown on the dashboard — hiding the seam would be the one
    thing that could genuinely discredit the project.
    """

    customer_locale: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    signal_calls: Mapped[list["SignalCall"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin")
    decision: Mapped["Decision | None"] = relationship(
        back_populates="transaction", cascade="all, delete-orphan",
        uselist=False, lazy="selectin")
    voice_call: Mapped["VoiceCall | None"] = relationship(
        back_populates="transaction", cascade="all, delete-orphan",
        uselist=False, lazy="selectin")

    @property
    def is_demo_seam(self) -> bool:
        """True when signals and the call target are different numbers."""
        return self.customer_msisdn != self.signal_msisdn


class SignalCall(Base):
    """One CAMARA request/response pair. Written for every call without exception."""

    __tablename__ = "signal_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True)
    api_name: Mapped[str] = mapped_column(String(64))
    request_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    response_payload: Mapped[dict | list] = mapped_column(JSONColumn, default=dict)
    source: Mapped[SignalSourceKind] = mapped_column(
        enum_column(SignalSourceKind, 16))
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transaction: Mapped[Transaction] = relationship(back_populates="signal_calls")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True, index=True)
    outcome: Mapped[DecisionOutcome] = mapped_column(
        enum_column(DecisionOutcome, 16))
    risk_score: Mapped[int] = mapped_column(Integer)
    reasoning_trace: Mapped[list] = mapped_column(JSONColumn, default=list)
    """Ordered steps: which signal was pulled, what it returned, how it moved the score.

    A deliverable shown to judges, not a debug log."""

    total_latency_ms: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transaction: Mapped[Transaction] = relationship(back_populates="decision")


class VoiceCall(Base):
    __tablename__ = "voice_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), unique=True, index=True)
    vapi_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[VoiceStatus] = mapped_column(
        enum_column(VoiceStatus, 16), default=VoiceStatus.PENDING)
    outcome: Mapped[VoiceOutcome | None] = mapped_column(
        enum_column(VoiceOutcome, 24), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    answers: Mapped[dict] = mapped_column(JSONColumn, default=dict)
    """Per-question result, including how long the customer took to answer.

    Hesitation before the 'were you told not to tell your bank' question is signal in
    itself, and response timing works identically in every language."""

    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    channel: Mapped[VoiceChannel] = mapped_column(
        enum_column(VoiceChannel, 8), default=VoiceChannel.PHONE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    transaction: Mapped[Transaction] = relationship(back_populates="voice_call")
