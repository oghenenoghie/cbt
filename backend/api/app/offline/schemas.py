"""Request and response models for offline exams (ADR 0007)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

PACKAGE_FORMAT = "cbt-offline-package/1"
SUBMISSION_FORMAT = "cbt-offline-submission/1"
REQUEST_FORMAT = "cbt-device-request/1"
SETUP_FORMAT = "cbt-device-setup/1"

DeviceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
PublicKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=40, max_length=64)]
# A signed body is at most this long: a long paper with passages, or every answer of an attempt.
MAX_BODY_CHARS = 5_000_000


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(_Input):
    """Signed JSON: `body` is the JSON as text, `signature` Ed25519 over its UTF-8 bytes."""

    format: str = Field(max_length=60)
    body: str = Field(max_length=MAX_BODY_CHARS)
    signature: str = Field(max_length=200)


# --- Lab computers -------------------------------------------------------------------------------


class RegistrationCodeOut(BaseModel):
    """A one-time code for registering a lab computer online. Shown once."""

    code: str
    expires_at: datetime


class DeviceOut(BaseModel):
    id: str
    name: str
    # "active" or "revoked".
    status: str
    # "online" (registered with a code) or "file" (by USB).
    method: str
    registered_at: datetime
    registered_by_name: str | None
    last_seen_at: datetime | None
    revoked_at: datetime | None


class DeviceUpdate(_Input):
    name: DeviceName


class DeviceRegister(_Input):
    """What the desktop app sends to register a computer online."""

    school_code: str = Field(min_length=1, max_length=40)
    registration_code: str = Field(min_length=1, max_length=40)
    name: DeviceName
    # The computer's Ed25519 public key, raw 32 bytes in base64.
    public_key: PublicKey


class SchoolOut(BaseModel):
    id: str
    code: str
    name: str


class DeviceRegistered(BaseModel):
    """What a computer registered online keeps. The token is shown once."""

    device_id: str
    device_token: str
    school: SchoolOut
    # The server's key for checking exam packages (Ed25519, base64).
    signing_public_key: str
    # The school's AES-256 key for answer keys in instant-score packages (base64).
    school_key: str


class FileRegistration(_Input):
    """A registration request file from the desktop app: an envelope signed by the computer's
    own key, whose body holds `name`, `public_key` (Ed25519) and `exchange_key` (X25519)."""

    request: Envelope


class FileRegistered(BaseModel):
    device: DeviceOut
    # The setup file to carry back to the computer, signed by the server.
    setup: Envelope


class DeviceInfo(BaseModel):
    device_id: str
    name: str
    school: SchoolOut
    signing_public_key: str


class DeviceExam(BaseModel):
    """An exam this lab computer can download."""

    id: str
    title: str
    subject_name: str
    opens_at: datetime
    closes_at: datetime
    duration_minutes: int
    instant_scores: bool
    # Whether students' codes exist yet; the package needs them.
    codes_ready: bool
    # The code batch in the newest package; download again when it changes.
    codes_batch: int


class DeviceExamList(BaseModel):
    exams: list[DeviceExam]


# --- Exam codes ------------------------------------------------------------------------------------


class CodesRequest(_Input):
    """Codes for every student the exam is set for, or only these (e.g. a lost slip)."""

    candidate_ids: list[str] | None = Field(default=None, max_length=2000)


class StudentCode(BaseModel):
    candidate_id: str
    name: str
    username: str | None
    class_name: str | None
    # "K7QM-3XRP". Shown once: only a hash is kept.
    code: str


class CodesOut(BaseModel):
    exam_id: str
    batch: int
    codes: list[StudentCode]


# --- Results ---------------------------------------------------------------------------------------


class SubmittedEvent(_Input):
    sequence: int = Field(ge=1)
    item_id: str = Field(max_length=36)
    selected_option_ids: list[str] = Field(default_factory=list, max_length=10)
    text: str | None = Field(default=None, max_length=20000)
    # The lab computer's clock when it was saved.
    at: AwareDatetime


class SubmissionBody(_Input):
    """A finished attempt from a lab computer, as signed by it."""

    submission_id: str = Field(min_length=1, max_length=36)
    package_id: str = Field(max_length=36)
    exam_id: str = Field(max_length=36)
    candidate_id: str = Field(max_length=36)
    device_id: str = Field(max_length=36)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    submitted_reason: Literal["student", "time_up"]
    question_order: list[str] = Field(max_length=1000)
    option_orders: dict[str, list[str]]
    events: list[SubmittedEvent] = Field(max_length=20000)


class SubmissionResult(BaseModel):
    submission_id: str
    # "accepted", "conflict" (kept but not counted) or "rejected".
    status: str
    reason: str | None
    flags: list[str]
    attempt_id: str | None


class ResultsFile(_Input):
    """Results brought back from a lab computer by USB."""

    submissions: list[Envelope] = Field(min_length=1, max_length=2000)


class ResultsFileOut(BaseModel):
    results: list[SubmissionResult]


# --- An exam's offline status ----------------------------------------------------------------------


class PackageOut(BaseModel):
    id: str
    device_id: str | None
    device_name: str | None
    exported_by_name: str | None
    codes_batch: int
    instant_scores: bool
    created_at: datetime


class OfflineSubmissionOut(BaseModel):
    submission_id: str
    candidate_id: str
    candidate_name: str
    device_id: str
    device_name: str
    status: str
    reason: str | None
    flags: list[str]
    attempt_id: str | None
    received_via: str
    received_at: datetime


class OfflineStudent(BaseModel):
    """A student the exam is set for, and the batch of their current code (never the code)."""

    candidate_id: str
    name: str
    username: str | None
    class_name: str | None
    code_batch: int | None


class OfflineStatus(BaseModel):
    exam_id: str
    offline_allowed: bool
    instant_scores: bool
    students: int
    codes_issued: int
    codes_batch: int
    roster: list[OfflineStudent]
    packages: list[PackageOut]
    submissions: list[OfflineSubmissionOut]
