from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def _name(max_length: int) -> type[str]:
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
    ]


Name50 = _name(50)
Name100 = _name(100)
Name200 = _name(200)
SubjectCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)
]
Position = Annotated[int, Field(ge=0, le=10_000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_range(starts_on: date | None, ends_on: date | None, what: str) -> None:
    if starts_on is not None and ends_on is not None and ends_on <= starts_on:
        raise ValueError(f"{what} must end after it starts.")


# --- Calendar ------------------------------------------------------------------------------------


class TermIn(_Input):
    name: Name100
    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _dates(self) -> "TermIn":
        _check_range(self.starts_on, self.ends_on, "A term")
        return self


class SessionCreate(_Input):
    name: Name100
    starts_on: date
    ends_on: date
    # Omit for the default three terms (First, Second and Third Term, dates to be set later).
    terms: list[TermIn] | None = Field(default=None, min_length=1, max_length=6)

    @model_validator(mode="after")
    def _valid(self) -> "SessionCreate":
        _check_range(self.starts_on, self.ends_on, "A session")
        names = [t.name.casefold() for t in self.terms or []]
        if len(names) != len(set(names)):
            raise ValueError("Term names must be different from each other.")
        return self


class SessionUpdate(_Input):
    name: Name100 | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class TermUpdate(_Input):
    """Omitted fields stay as they are; a date set to null is cleared."""

    name: Name100 | None = None
    starts_on: date | None = None
    ends_on: date | None = None


class TermOut(BaseModel):
    id: str
    name: str
    position: int
    starts_on: date | None
    ends_on: date | None


class SessionOut(BaseModel):
    id: str
    name: str
    starts_on: date
    ends_on: date
    is_current: bool
    terms: list[TermOut]


# --- Classes -------------------------------------------------------------------------------------


class LevelCreate(_Input):
    name: Name50
    position: Position = 0


class LevelUpdate(_Input):
    name: Name50 | None = None
    position: Position | None = None


class LevelOut(BaseModel):
    id: str
    name: str
    position: int


class ArmCreate(_Input):
    level_id: str = Field(min_length=1, max_length=36)
    name: Name50


class ArmUpdate(_Input):
    name: Name50


class ArmOut(BaseModel):
    id: str
    session_id: str
    level_id: str
    level_name: str
    name: str
    # e.g. "JSS1 A"
    display_name: str


# --- Subjects and topics -------------------------------------------------------------------------


class SubjectCreate(_Input):
    name: Name100
    code: SubjectCode | None = None
    level_ids: list[str] = Field(default_factory=list, max_length=100)


class SubjectUpdate(_Input):
    """Omitted fields stay as they are; `code` set to null is cleared."""

    name: Name100 | None = None
    code: SubjectCode | None = None


class SubjectLevels(_Input):
    level_ids: list[str] = Field(max_length=100)


class TopicCreate(_Input):
    name: Name200


class TopicUpdate(_Input):
    name: Name200 | None = None
    position: Position | None = None


class TopicOut(BaseModel):
    id: str
    name: str
    position: int


class SubjectOut(BaseModel):
    id: str
    name: str
    code: str | None
    level_ids: list[str]
    topics: list[TopicOut]


# --- People in classes ---------------------------------------------------------------------------

MAX_ENROL_ROWS = 200


class EnrolRequest(_Input):
    """Student accounts to enrol in the arm, all or none."""

    user_ids: list[str] = Field(min_length=1, max_length=MAX_ENROL_ROWS)


class EnrolmentMove(_Input):
    arm_id: str = Field(min_length=1, max_length=36)


class EnrolmentOut(BaseModel):
    id: str
    session_id: str
    arm_id: str
    candidate_id: str
    user_id: str | None
    username: str | None
    display_name: str


class AssignmentCreate(_Input):
    teacher_id: str = Field(min_length=1, max_length=36)
    arm_id: str = Field(min_length=1, max_length=36)
    subject_id: str = Field(min_length=1, max_length=36)


class AssignmentOut(BaseModel):
    id: str
    teacher_id: str
    teacher_name: str
    session_id: str
    arm_id: str
    arm_name: str
    subject_id: str
    subject_name: str


class SessionRef(BaseModel):
    id: str
    name: str
    is_current: bool


class SubjectRef(BaseModel):
    id: str
    name: str
    code: str | None


class MyEnrolment(BaseModel):
    session: SessionRef
    arm_id: str
    arm_name: str
    subjects: list[SubjectRef]


class MyTeaching(BaseModel):
    session: SessionRef
    arm_id: str
    arm_name: str
    subject: SubjectRef


class MyClasses(BaseModel):
    """The signed-in person's own classes: as a student, as a teacher, or both empty."""

    enrolments: list[MyEnrolment]
    teaching: list[MyTeaching]
