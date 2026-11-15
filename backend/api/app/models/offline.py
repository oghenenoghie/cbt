"""Offline exams on lab computers (ADR 0007).

- A `LabDevice` is a lab computer a school admin registered, online with a one-time
  `DeviceRegistration` code or by file. It holds the public half of the computer's own key pair;
  a computer registered online also authenticates with a device token, stored only as a hash.
- `OfflineCode`s are the one-time codes students sign in with on a lab computer, stored as salted
  PBKDF2 hashes that packages carry so the computer can check them offline.
- An `OfflinePackage` records each signed exam package issued: to which computer (or exported for
  USB), the paper's fingerprint and the students it lists, for checking results later.
- An `OfflineSubmission` is one signed result uploaded from a lab computer, kept as received with
  what the server decided: accepted (and the attempt it became), a conflict, or rejected.
- `SchoolOfflineKey` is the school's key for the answer keys of instant-score packages, which only
  registered lab computers hold.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.tenant import utc_now

DEVICE_STATUSES = ("active", "revoked")
REGISTRATION_METHODS = ("online", "file")
SUBMISSION_STATUSES = ("accepted", "conflict", "rejected")


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


def _tenant_id() -> Mapped[str]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _user_fk(column: str, table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        [column, "tenant_id"],
        ["users.id", "users.tenant_id"],
        name=f"fk_{table}_{column.removesuffix('_id')}_same_tenant",
    )


def _exam_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["exam_id", "tenant_id"],
        ["exams.id", "exams.tenant_id"],
        ondelete="CASCADE",
        name=f"fk_{table}_exam_same_tenant",
    )


class SchoolOfflineKey(Base):
    """The school's AES-256 key for the answer keys of instant-score packages."""

    __tablename__ = "school_offline_keys"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    # 32 random bytes, base64.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class LabDevice(Base):
    __tablename__ = "lab_devices"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_lab_devices_id_tenant_id"),
        UniqueConstraint("token_hash", name="uq_lab_devices_token_hash"),
        _user_fk("registered_by_id", "lab_devices"),
        _user_fk("revoked_by_id", "lab_devices"),
        CheckConstraint("status IN ('active', 'revoked')", name="ck_lab_devices_status"),
        CheckConstraint("method IN ('online', 'file')", name="ck_lab_devices_method"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    # The computer's Ed25519 public key, raw 32 bytes in base64. It signs results with the
    # private half, which never leaves the computer.
    public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # SHA-256 of the device token, for computers registered online. Null for file registration.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    registered_at: Mapped[datetime] = _created_at()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class DeviceRegistration(Base):
    """A one-time code a school admin creates to register a lab computer online."""

    __tablename__ = "device_registrations"
    __table_args__ = (
        UniqueConstraint("code_hash", name="uq_device_registrations_code_hash"),
        _user_fk("created_by_id", "device_registrations"),
        ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_device_registrations_device_same_tenant",
        ),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    # SHA-256 of the code; the code itself is shown once.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class OfflineCode(Base):
    """A student's code for signing in to an exam on a lab computer. Generating codes again
    replaces a student's code (a higher `batch`)."""

    __tablename__ = "offline_codes"
    __table_args__ = (
        UniqueConstraint("exam_id", "candidate_id", name="uq_offline_codes_exam_id_candidate_id"),
        _exam_fk("offline_codes"),
        ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            ondelete="CASCADE",
            name="fk_offline_codes_candidate_same_tenant",
        ),
        _user_fk("created_by_id", "offline_codes"),
        CheckConstraint("iterations >= 1", name="ck_offline_codes_iterations"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # PBKDF2-SHA256 of the normalized code: salt and hash in hex.
    salt: Mapped[str] = mapped_column(String(32), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, nullable=False)
    batch: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class OfflinePackage(Base):
    """A signed exam package issued to a lab computer, or exported for USB."""

    __tablename__ = "offline_packages"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_offline_packages_id_tenant_id"),
        _exam_fk("offline_packages"),
        ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_offline_packages_device_same_tenant",
        ),
        _user_fk("exported_by_id", "offline_packages"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    exam_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # The computer it was downloaded to, or null when exported for USB.
    device_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    exported_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # SHA-256 over the frozen paper's item and version ids.
    paper_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    codes_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    instant_scores: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class OfflineSubmission(Base):
    """One signed result from a lab computer, as received, and what the server decided."""

    __tablename__ = "offline_submissions"
    __table_args__ = (
        # The lab computer's own id for the result: uploading it again is recognised.
        UniqueConstraint(
            "tenant_id", "submission_id", name="uq_offline_submissions_tenant_submission"
        ),
        _exam_fk("offline_submissions"),
        ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_offline_submissions_candidate_same_tenant",
        ),
        ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_offline_submissions_device_same_tenant",
        ),
        ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["exam_attempts.id", "exam_attempts.tenant_id"],
            name="fk_offline_submissions_attempt_same_tenant",
        ),
        _user_fk("uploaded_by_id", "offline_submissions"),
        CheckConstraint(
            "status IN ('accepted', 'conflict', 'rejected')", name="ck_offline_submissions_status"
        ),
        CheckConstraint("received_via IN ('device', 'file')", name="ck_offline_submissions_via"),
    )

    id: Mapped[str] = _id()
    tenant_id: Mapped[str] = _tenant_id()
    submission_id: Mapped[str] = mapped_column(String(36), nullable=False)
    exam_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    package_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # Why it was a conflict or rejected, in words for staff.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Things staff should know about an accepted result, e.g. a lab computer's clock out of step.
    flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # The signed envelope as received, and SHA-256 of its body.
    envelope: Mapped[dict] = mapped_column(JSON, nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    received_via: Mapped[str] = mapped_column(String(20), nullable=False)
    uploaded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    received_at: Mapped[datetime] = _created_at()
