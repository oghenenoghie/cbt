"""Class lists: put a whole school's students in their classes from one CSV or Excel file.

Decided by the user on 2026-11-21 (ADR 0002, decisions 8 to 10):
- A school admin uploads a class list for one session: a header row, then a student per row with
  their username, name and class. The server reads the file, checks every row and shows a
  **preview** (what each row would do) before anything is saved.
- A username nobody has becomes a new **student account** (no password unless the admin asks for
  generated ones). An existing student is matched by username and **keeps their name**; the
  preview notes a different name in the file.
- A student already in another class of the session is **moved**, and the preview says from where.
- Importing is all or nothing: one row with a problem and nothing is saved.

Files are read in memory and never stored. Only the first visible sheet of a workbook is read, and
Office files with macros, or that unpack into something huge, are refused as for learning
materials (`app/documents/extract.identify`).
"""

import csv
import re
from dataclasses import dataclass, field
from io import BytesIO, StringIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.core.passwords import generate_password, hash_password
from app.db.session import get_db
from app.documents.extract import UnreadableFile, decode_text, identify, row_cells
from app.models import AcademicSession, Candidate, ClassArm, ClassLevel, Enrolment, Tenant, User
from app.models.identity import USERNAME_RULE, normalize_username, valid_username
from app.school.common import audit, flush_or_conflict, get_owned, write_access
from app.school.schemas import ClassListImported, ClassListPlan, ClassListRow, NewStudent

router = APIRouter(prefix="/school", tags=["school enrolments"])

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
# Hashing a password is deliberately slow, so generated ones are capped per upload.
MAX_GENERATED = 200

COLUMNS = {
    "username": "username",
    "user name": "username",
    "user_name": "username",
    "login": "username",
    "name": "name",
    "full name": "name",
    "full_name": "name",
    "display name": "name",
    "display_name": "name",
    "student name": "name",
    "student": "name",
    "class": "class",
    "class name": "class",
    "class arm": "class",
    "arm": "class",
    "form": "class",
}


class ClassListError(Exception):
    """The file as a whole can't be used, with a message for the admin."""


@dataclass
class Table:
    # (row number in the file, cells)
    rows: list[tuple[int, list[str]]]
    warnings: list[str] = field(default_factory=list)


def _key(text: str) -> str:
    """How a class name is compared: case, spaces, hyphens and underscores don't matter."""
    return re.sub(r"[\s_-]+", "", text).casefold()


def _same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def read_table(filename: str, data: bytes) -> Table:
    """The non-empty rows of a CSV file or of a workbook's first visible sheet."""
    if len(data) > MAX_FILE_BYTES:
        raise ClassListError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    try:
        kind = identify(filename, data)
    except UnreadableFile as error:
        raise ClassListError(str(error)) from error
    if kind == "csv":
        return _read_csv(data)
    if kind == "xlsx":
        return _read_xlsx(data)
    raise ClassListError("Upload the class list as a CSV file or an Excel workbook (.xlsx).")


def _read_csv(data: bytes) -> Table:
    text, fallback = decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    try:
        for number, values in enumerate(csv.reader(StringIO(text), dialect), start=1):
            cells = [cell.strip() for cell in row_cells(values)]
            if any(cells):
                rows.append((number, cells))
    except csv.Error as error:
        raise ClassListError("This CSV file couldn't be read: check it opens in a spreadsheet.") from error
    warnings = []
    if fallback:
        warnings.append(
            "This file isn't UTF-8, so it was read as Windows text. Check accented letters in "
            "names came out right."
        )
    return Table(rows=rows, warnings=warnings)


def _read_xlsx(data: bytes) -> Table:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as error:
        raise ClassListError("This Excel file looks damaged and couldn't be opened.") from error
    try:
        visible = [s for s in workbook.worksheets if s.sheet_state == "visible"]
        if not visible:
            raise ClassListError("This workbook has no visible sheet.")
        sheet = visible[0]
        rows = []
        for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = [cell.strip() for cell in row_cells(values)]
            if any(cells):
                rows.append((number, cells))
                if len(rows) > MAX_ROWS + 1:
                    break
        warnings = []
        if len(visible) > 1:
            warnings.append(f"Only the first sheet, “{sheet.title}”, was read.")
        return Table(rows=rows, warnings=warnings)
    finally:
        workbook.close()


@dataclass
class Line:
    number: int
    username: str
    name: str
    class_text: str


def _lines(table: Table) -> tuple[list[Line], list[str]]:
    """The student rows under the header, and warnings about the header."""
    if not table.rows:
        raise ClassListError("The file is empty.")
    header_number, header = table.rows[0]
    columns = [COLUMNS.get(" ".join(cell.split()).casefold()) for cell in header]
    missing = [c for c in ("username", "class") if c not in columns]
    if missing:
        raise ClassListError(
            f"Row {header_number} should name the columns, with at least “username” and “class” "
            "(and “name” for new students)."
        )
    for column in ("username", "name", "class"):
        if columns.count(column) > 1:
            raise ClassListError(f"Row {header_number} has more than one “{column}” column.")
    warnings = []
    ignored = [cell for cell, column in zip(header, columns, strict=False) if column is None and cell]
    if ignored:
        names = ", ".join(f"“{cell}”" for cell in ignored)
        warnings.append(f"These columns were ignored: {names}.")

    def get(cells: list[str], column: str) -> str:
        if column not in columns:
            return ""
        index = columns.index(column)
        return cells[index] if index < len(cells) else ""

    lines = [
        Line(number, get(cells, "username"), get(cells, "name"), get(cells, "class"))
        for number, cells in table.rows[1:]
    ]
    if not lines:
        raise ClassListError("The file has a header row but no students.")
    if len(lines) > MAX_ROWS:
        raise ClassListError(f"A class list can have at most {MAX_ROWS} students. Split the file.")
    return lines, warnings


@dataclass
class Planned:
    row: ClassListRow
    user: User | None = None
    candidate: Candidate | None = None
    enrolment: Enrolment | None = None
    arm: ClassArm | None = None


def plan(
    db: Session,
    tenant_id: str,
    session: AcademicSession,
    table: Table,
    generate_passwords: bool,
) -> tuple[ClassListPlan, list[Planned]]:
    """What each row would do. Writes nothing."""
    lines, warnings = _lines(table)
    arm_rows = db.execute(
        select(ClassArm, ClassLevel.name)
        .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
        .where(ClassArm.tenant_id == tenant_id, ClassArm.session_id == session.id)
    ).all()
    names = {arm.id: f"{level} {arm.name}" for arm, level in arm_rows}
    by_key: dict[str, list[ClassArm]] = {}
    for arm, _level in arm_rows:
        by_key.setdefault(_key(names[arm.id]), []).append(arm)

    usernames = {normalize_username(line.username) for line in lines}
    users = {
        u.username: u
        for u in db.scalars(
            select(User).where(User.tenant_id == tenant_id, User.username.in_(usernames))
        )
    }
    candidates = {
        c.user_id: c
        for c in db.scalars(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.user_id.in_([u.id for u in users.values()]),
            )
        )
    }
    enrolments = {
        e.candidate_id: e
        for e in db.scalars(
            select(Enrolment).where(
                Enrolment.session_id == session.id,
                Enrolment.candidate_id.in_([c.id for c in candidates.values()]),
            )
        )
    }

    planned: list[Planned] = []
    first_row: dict[str, int] = {}
    for line in lines:
        username = normalize_username(line.username)
        row = ClassListRow(
            row=line.number,
            username=username,
            name=line.name,
            class_name=None,
            action="problem",
            from_class=None,
            notes=[],
            problem=None,
        )
        item = Planned(row=row)
        planned.append(item)

        def problem(message: str, row=row) -> None:
            row.problem = message

        if not username:
            problem("The username is missing.")
            continue
        if not valid_username(username):
            problem(USERNAME_RULE)
            continue
        if username in first_row:
            problem(f"This username is also on row {first_row[username]}.")
            continue
        first_row[username] = line.number
        if not line.class_text:
            problem("The class is missing.")
            continue
        matches = by_key.get(_key(line.class_text), [])
        if not matches:
            known = ", ".join(sorted(names.values())[:8]) or "none yet"
            problem(f"There's no class “{line.class_text}” in {session.name}. Its classes: {known}.")
            continue
        if len(matches) > 1:
            problem(f"“{line.class_text}” matches more than one class in {session.name}.")
            continue
        arm = matches[0]
        item.arm = arm
        row.class_name = names[arm.id]

        user = users.get(username)
        if user is None:
            if not line.name:
                problem("The name is missing, and no account has this username.")
                continue
            if len(line.name) > 200:
                problem("The name is longer than 200 characters.")
                continue
            row.action = "create"
            continue
        if user.role != "student":
            problem("This username belongs to a staff account.")
            continue
        item.user = user
        row.name = user.display_name
        if line.name and not _same_name(line.name, user.display_name):
            row.notes.append(
                f"The file says “{line.name}”. The account's name stays “{user.display_name}”."
            )
        if user.status != "active":
            row.notes.append("This account is disabled. They're enrolled, but can't sign in.")
        candidate = candidates.get(user.id)
        item.candidate = candidate
        enrolment = enrolments.get(candidate.id) if candidate else None
        item.enrolment = enrolment
        if enrolment is None:
            row.action = "enrol"
        elif enrolment.arm_id == arm.id:
            row.action = "unchanged"
        else:
            row.action = "move"
            row.from_class = names.get(enrolment.arm_id)

    counts = {action: 0 for action in ("create", "enrol", "move", "unchanged", "problem")}
    for item in planned:
        counts[item.row.action] += 1
    if generate_passwords and counts["create"] > MAX_GENERATED:
        warnings.append(
            f"Passwords can be generated for at most {MAX_GENERATED} new students at a time. "
            "Split the file, or import without generated passwords."
        )
    return (
        ClassListPlan(
            session_id=session.id,
            session_name=session.name,
            rows=[p.row for p in planned],
            counts=counts,
            warnings=table.warnings + warnings,
            ready=counts["problem"] == 0
            and not (generate_passwords and counts["create"] > MAX_GENERATED),
        ),
        planned,
    )


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.",
        )
    return file.filename or "", data


def _planned(db, principal, session_id, filename, data, generate_passwords):
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    try:
        table = read_table(filename, data)
        return plan(db, principal.tenant_id, session, table, generate_passwords)
    except ClassListError as error:
        raise HTTPException(422, detail=str(error)) from error


@router.post("/sessions/{session_id}/class-list/preview", response_model=ClassListPlan)
async def preview_class_list(
    session_id: str,
    file: UploadFile = File(...),
    generate_passwords: bool = Form(default=False),
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> ClassListPlan:
    """What importing this class list into the session would do, row by row. Saves nothing."""
    filename, data = await _read_upload(file)
    result, _ = _planned(db, principal, session_id, filename, data, generate_passwords)
    return result


@router.post(
    "/sessions/{session_id}/class-list",
    response_model=ClassListImported,
    status_code=status.HTTP_201_CREATED,
)
async def import_class_list(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    generate_passwords: bool = Form(default=False),
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> ClassListImported:
    """Import the class list: new students, enrolments and moves, or nothing if any row has a
    problem. Generated passwords are in this response only."""
    filename, data = await _read_upload(file)
    result, planned = _planned(db, principal, session_id, filename, data, generate_passwords)
    if not result.ready:
        errors = [{"row": p.row.row, "message": p.row.problem} for p in planned if p.row.problem]
        message = (
            "Nothing was imported. Fix these rows and try again."
            if errors
            else "Nothing was imported. " + result.warnings[-1]
        )
        raise HTTPException(422, detail={"message": message, "errors": errors})

    tid = principal.tenant_id
    school_code = db.get(Tenant, tid).slug
    created: list[NewStudent] = []
    changes = []
    for item in planned:
        row = item.row
        if row.action == "create":
            password = None
            if generate_passwords:
                password = generate_password(staff=False, context=(row.username, school_code))
            user = User(
                tenant_id=tid,
                username=row.username,
                display_name=row.name,
                role="student",
                password_hash=hash_password(password) if password else None,
            )
            db.add(user)
            db.flush()
            item.user = user
            created.append(
                NewStudent(
                    id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                    class_name=row.class_name,
                    generated_password=password,
                )
            )
        if row.action in ("create", "enrol"):
            if item.candidate is None:
                item.candidate = Candidate(
                    tenant_id=tid, user_id=item.user.id, display_name=item.user.display_name
                )
                db.add(item.candidate)
                db.flush()
            item.enrolment = Enrolment(
                tenant_id=tid,
                session_id=result.session_id,
                arm_id=item.arm.id,
                candidate_id=item.candidate.id,
            )
            db.add(item.enrolment)
            changes.append(item)
        elif row.action == "move":
            item.enrolment.arm_id = item.arm.id
            changes.append(item)
    flush_or_conflict(db, "Some of these students were changed at the same time. Try again.")

    for item in planned:
        row = item.row
        if row.action == "create":
            audit(
                db, principal, request, "user.created", "user", item.user.id,
                {
                    "role": "student",
                    "password_set": item.user.password_hash is not None,
                    "password_generated": item.user.password_hash is not None,
                    "via": "class_list",
                },
            )
    for item in changes:
        if item.row.action == "move":
            audit(
                db, principal, request, "enrolment.moved", "enrolment", item.enrolment.id,
                {"from": item.row.from_class, "to": item.row.class_name, "via": "class_list"},
            )
        else:
            audit(
                db, principal, request, "enrolment.created", "enrolment", item.enrolment.id,
                {"arm": item.row.class_name, "user_id": item.user.id, "via": "class_list"},
            )
    audit(
        db, principal, request, "class_list.imported", "academic_session", result.session_id,
        {"file": filename[:200], **result.counts},
    )
    db.commit()
    return ClassListImported(**result.model_dump(), created=created)
