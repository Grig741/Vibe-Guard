"""Database models: a Scan has many Findings."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Scan(Base):
    __tablename__ = "scans"

    id = Column(String(32), primary_key=True, default=_uuid)
    project_id = Column(String(255), index=True, nullable=False)
    # What we targeted. We never store the apiKey itself.
    target_label = Column(String(255), nullable=True)
    status = Column(String(20), default="completed", nullable=False)  # completed | error
    score = Column(Integer, default=0, nullable=False)       # 0..100 (higher = safer)
    grade = Column(String(2), default="F", nullable=False)   # A..F
    critical = Column(Integer, default=0, nullable=False)
    high = Column(Integer, default=0, nullable=False)
    medium = Column(Integer, default=0, nullable=False)
    low = Column(Integer, default=0, nullable=False)
    passed = Column(Integer, default=0, nullable=False)
    duration_ms = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    unlocked = Column(Boolean, default=False, server_default="0", nullable=False)  # paid
    license_key = Column(String(64), nullable=True)
    tg_user_id = Column(BigInteger, nullable=True, index=True)  # set when run from the Mini App
    created_at = Column(DateTime(timezone=True), default=_now, index=True, nullable=False)

    findings = relationship(
        "Finding",
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="Finding.id",
    )


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(32), ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    check_id = Column(String(64), nullable=False)      # e.g. firestore_public_read
    title = Column(String(255), nullable=False)
    severity = Column(String(16), nullable=False)      # critical|high|medium|low|info|pass
    status = Column(String(16), nullable=False)        # vulnerable | ok | skipped | error
    description = Column(Text, nullable=True)
    remediation = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)
    weight = Column(Float, default=0.0, nullable=False)

    scan = relationship("Scan", back_populates="findings")


class License(Base):
    """A paid key. Each unlocked scan consumes one use."""
    __tablename__ = "licenses"

    key = Column(String(64), primary_key=True)
    max_scans = Column(Integer, default=10, nullable=False)
    used = Column(Integer, default=0, nullable=False)
    note = Column(String(255), nullable=True)       # e.g. buyer email / order id
    active = Column(Boolean, default=True, nullable=False)
    tg_user_id = Column(BigInteger, nullable=True, index=True)  # owner when bought in Telegram
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Payment(Base):
    """A Telegram Stars payment. charge_id is unique → webhook retries are idempotent."""
    __tablename__ = "payments"

    charge_id = Column(String(128), primary_key=True)   # telegram_payment_charge_id
    tg_user_id = Column(BigInteger, nullable=False, index=True)
    scan_id = Column(String(32), nullable=True)
    stars = Column(Integer, nullable=False)
    license_key = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
