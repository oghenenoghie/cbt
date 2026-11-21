"""Class lists from CSV or Excel (ADR 0002, decisions 8 to 10): the preview, what each row does,
all-or-nothing import, generated passwords, files we refuse, access and audit."""

from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.passwords import verify_password
from app.models import (
    AcademicSession,
    AuditLog,
    Candidate,
    ClassArm,
    ClassLevel,
    Enrolment,
    User,
)

S = "/api/v1/school"


@pytest.fixture
def school(admin, db: Session, make_user):
    """2026/2027 (current) with JSS1 A, JSS1 B and JSS2 A; 2025/2026 with JSS1 C. amy is in JSS1 A
    this session, ben in no class, dora's account is disabled; mrs.okafor teaches."""
    tid = admin.school.id
    year = AcademicSession(
        tenant_id=tid, name="2026/2027", starts_on=date(2026, 9, 1), ends_on=date(2027, 7, 31),
        is_current=True,
    )
    last_year = AcademicSession(
        tenant_id=tid, name="2025/2026", starts_on=date(2025, 9, 1), ends_on=date(2026, 7, 31)
    )
    jss1 = ClassLevel(tenant_id=tid, name="JSS1", position=1)
    jss2 = ClassLevel(tenant_id=tid, name="JSS2", position=2)
    db.add_all([year, last_year, jss1, jss2])
    db.flush()
    arms = {
        "JSS1 A": ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="A"),
        "JSS1 B": ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="B"),
        "JSS2 A": ClassArm(tenant_id=tid, session_id=year.id, level_id=jss2.id, name="A"),
        "old JSS1 C": ClassArm(tenant_id=tid, session_id=last_year.id, level_id=jss1.id, name="C"),
    }
    db.add_all(arms.values())
    db.flush()
    people = {
        name: make_user(tenant=admin.school, username=name, role=role)
        for name, role in [("amy", "student"), ("ben", "student"), ("dora", "student"),
                           ("mrs.okafor", "teacher")]
    }
    people["amy"].display_name = "Amy Adeyemi"
    people["dora"].status = "disabled"
    amy = Candidate(tenant_id=tid, user_id=people["amy"].id, display_name="Amy Adeyemi")
    db.add(amy)
    db.flush()
    db.add(Enrolment(tenant_id=tid, session_id=year.id, arm_id=arms["JSS1 A"].id, candidate_id=amy.id))
    db.commit()
    return SimpleNamespace(tid=tid, year=year, last_year=last_year, arms=arms, people=people)


def csv_file(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def xlsx_file(rows, *, hidden_first=False, extra_sheet=False) -> bytes:
    book = Workbook()
    sheet = book.active
    if hidden_first:
        sheet.title = "Answers"
        sheet.append(["username", "class"])
        sheet.append(["secret", "JSS1 A"])
        sheet.sheet_state = "hidden"
        sheet = book.create_sheet("Students")
    for row in rows:
        sheet.append(row)
    if extra_sheet:
        book.create_sheet("Notes").append(["anything"])
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def send(who, session_id, data: bytes, filename="class-list.csv", *, preview=True, passwords=False):
    path = f"{S}/sessions/{session_id}/class-list" + ("/preview" if preview else "")
    return who.client.post(
        path,
        files={"file": (filename, data, "application/octet-stream")},
        data={"generate_passwords": "true" if passwords else "false"},
        headers=who.headers,
    )


def actions(plan: dict) -> list[tuple]:
    return [(r["username"], r["action"], r["class_name"]) for r in plan["rows"]]


MIXED = csv_file(
    "Username,Name,Class",
    "zara,Zara Obi,JSS1 B",
    "amy,Amy A. Adeyemi,jss1-b",
    "ben,Ben Bello,JSS2A",
    "AMY2,Amy Two,JSS1 A",
)


# --- The preview ---------------------------------------------------------------------------------


def test_the_preview_says_what_each_row_would_do(school, admin, db: Session) -> None:
    response = send(admin, school.year.id, MIXED)

    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["session_name"] == "2026/2027"
    assert actions(plan) == [
        ("zara", "create", "JSS1 B"),
        ("amy", "move", "JSS1 B"),
        ("ben", "enrol", "JSS2 A"),
        ("amy2", "create", "JSS1 A"),
    ]
    assert plan["rows"][1]["from_class"] == "JSS1 A"
    assert plan["rows"][1]["name"] == "Amy Adeyemi"
    assert plan["rows"][1]["notes"] == [
        "The file says “Amy A. Adeyemi”. The account's name stays “Amy Adeyemi”."
    ]
    assert [r["row"] for r in plan["rows"]] == [2, 3, 4, 5]
    assert plan["counts"] == {"create": 2, "enrol": 1, "move": 1, "unchanged": 0, "problem": 0}
    assert plan["ready"] is True
    # Nothing was saved.
    assert db.scalar(select(func.count()).select_from(User).where(User.username == "zara")) == 0
    assert db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action.like("enrolment.%"))) == 0


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("mrs.okafor,Mrs Okafor,JSS1 A", "This username belongs to a staff account."),
        ("newkid,,JSS1 A", "The name is missing, and no account has this username."),
        ("has space,Someone,JSS1 A", "Usernames may contain only"),
        (",Someone,JSS1 A", "The username is missing."),
        ("newkid,New Kid,", "The class is missing."),
        ("newkid,New Kid,JSS3 Z", "There's no class “JSS3 Z” in 2026/2027. Its classes: JSS1 A, JSS1 B, JSS2 A."),
        ("newkid,New Kid,JSS1 C", "There's no class “JSS1 C” in 2026/2027"),
    ],
)
def test_problem_rows(school, admin, line, problem) -> None:
    plan = send(admin, school.year.id, csv_file("username,name,class", line)).json()

    row = plan["rows"][0]
    assert row["action"] == "problem"
    assert row["problem"].startswith(problem)
    assert plan["ready"] is False


def test_a_username_twice(school, admin) -> None:
    plan = send(
        admin, school.year.id, csv_file("username,name,class", "zed,Zed,JSS1 A", "ZED,Zed,JSS1 B")
    ).json()

    assert plan["rows"][0]["action"] == "create"
    assert plan["rows"][1]["problem"] == "This username is also on row 2."


def test_already_in_the_class_and_disabled_accounts(school, admin) -> None:
    plan = send(
        admin,
        school.year.id,
        csv_file("username,class", "amy,JSS1 A", "dora,JSS1 B"),
    ).json()

    assert actions(plan) == [("amy", "unchanged", "JSS1 A"), ("dora", "enrol", "JSS1 B")]
    assert plan["rows"][1]["notes"] == [
        "This account is disabled. They're enrolled, but can't sign in."
    ]


def test_the_name_column_is_needed_only_for_new_students(school, admin) -> None:
    plan = send(admin, school.year.id, csv_file("username,class", "ben,JSS1 A")).json()

    assert actions(plan) == [("ben", "enrol", "JSS1 A")]


# --- Importing ---------------------------------------------------------------------------------


def test_importing_creates_enrols_and_moves(school, admin, db: Session) -> None:
    response = send(admin, school.year.id, MIXED, preview=False)

    assert response.status_code == 201, response.text
    body = response.json()
    assert [(s["username"], s["class_name"], s["generated_password"]) for s in body["created"]] == [
        ("zara", "JSS1 B", None),
        ("amy2", "JSS1 A", None),
    ]
    zara = db.scalar(select(User).where(User.username == "zara"))
    assert (zara.role, zara.display_name, zara.password_hash) == ("student", "Zara Obi", None)

    def class_of(username):
        return db.scalar(
            select(ClassArm.id)
            .join(Enrolment, Enrolment.arm_id == ClassArm.id)
            .join(Candidate, Candidate.id == Enrolment.candidate_id)
            .join(User, User.id == Candidate.user_id)
            .where(User.username == username, Enrolment.session_id == school.year.id)
        )

    assert class_of("zara") == school.arms["JSS1 B"].id
    assert class_of("amy") == school.arms["JSS1 B"].id
    assert class_of("ben") == school.arms["JSS2 A"].id
    db.expire_all()
    assert db.get(User, school.people["amy"].id).display_name == "Amy Adeyemi"
    actions_logged = db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)).all()
    assert actions_logged.count("user.created") == 2
    assert actions_logged.count("enrolment.created") == 3
    assert actions_logged.count("enrolment.moved") == 1
    summary = db.scalar(select(AuditLog).where(AuditLog.action == "class_list.imported"))
    assert summary.resource_id == school.year.id
    assert summary.details == {
        "file": "class-list.csv", "create": 2, "enrol": 1, "move": 1, "unchanged": 0, "problem": 0,
    }

    again = send(admin, school.year.id, MIXED).json()
    assert {r["action"] for r in again["rows"]} == {"unchanged"}


def test_one_problem_and_nothing_is_imported(school, admin, db: Session) -> None:
    data = csv_file("username,name,class", "zara,Zara Obi,JSS1 B", "ghost,Ghost,JSS9 Z")

    response = send(admin, school.year.id, data, preview=False)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "Nothing was imported. Fix these rows and try again."
    assert [e["row"] for e in detail["errors"]] == [3]
    assert db.scalar(select(func.count()).select_from(User).where(User.username == "zara")) == 0


def test_generated_passwords_are_shown_once(school, admin, db: Session) -> None:
    data = csv_file("username,name,class", "zara,Zara Obi,JSS1 B", "ben,Ben,JSS1 B")

    body = send(admin, school.year.id, data, preview=False, passwords=True).json()

    assert len(body["created"]) == 1
    password = body["created"][0]["generated_password"]
    assert len(password) >= 8
    zara = db.scalar(select(User).where(User.username == "zara"))
    assert verify_password(password, zara.password_hash)
    # Existing students' passwords are untouched.
    assert db.get(User, school.people["ben"].id).password_hash is None
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.created"))
    assert password not in str(entry.details)


def test_generated_passwords_are_capped(school, admin, monkeypatch) -> None:
    monkeypatch.setattr("app.school.class_lists.MAX_GENERATED", 1)
    data = csv_file("username,name,class", "a1,A One,JSS1 A", "a2,A Two,JSS1 A")

    plan = send(admin, school.year.id, data, passwords=True).json()
    refused = send(admin, school.year.id, data, preview=False, passwords=True)

    assert plan["ready"] is False
    assert "at most 1 new students" in plan["warnings"][-1]
    assert refused.status_code == 422
    assert send(admin, school.year.id, data, preview=False).status_code == 201


# --- Files ------------------------------------------------------------------------------------


def test_excel_workbooks(school, admin) -> None:
    data = xlsx_file(
        [["Student Name", "Username", "Class", "Notes"], ["Zara Obi", 1001, "JSS1 B", "x"],
         [None, None, None, None], ["Amy", "amy", "JSS1 A", ""]],
        hidden_first=True,
        extra_sheet=True,
    )

    plan = send(admin, school.year.id, data, "list.xlsx").json()

    assert actions(plan) == [("1001", "create", "JSS1 B"), ("amy", "unchanged", "JSS1 A")]
    assert [r["row"] for r in plan["rows"]] == [2, 4]
    assert plan["warnings"] == [
        "Only the first sheet, “Students”, was read.",
        "These columns were ignored: “Notes”.",
    ]


def test_csv_files_from_other_spreadsheets(school, admin) -> None:
    windows = "username;name;class\r\nzoe;Zoé Ade;JSS1 A\r\n".encode("cp1252")
    with_bom = "﻿username,name,class\nzoe,Zoé Ade,JSS1 A\n".encode()

    plan = send(admin, school.year.id, windows).json()
    bom = send(admin, school.year.id, with_bom).json()

    assert actions(plan) == [("zoe", "create", "JSS1 A")]
    assert plan["rows"][0]["name"] == "Zoé Ade"
    assert "read as Windows text" in plan["warnings"][0]
    assert bom["rows"][0]["name"] == "Zoé Ade"
    assert bom["warnings"] == []


@pytest.mark.parametrize(
    ("filename", "data", "message"),
    [
        ("list.csv", b"", "The file is empty."),
        ("list.csv", csv_file("name,class", "Zara,JSS1 A"), "should name the columns"),
        ("list.csv", csv_file("username,class,class", "zara,JSS1 A,JSS1 B"), "more than one “class” column"),
        ("list.csv", csv_file("username,name,class"), "no students"),
        ("list.pdf", b"%PDF-1.4 not really", "Upload the class list as a CSV file or an Excel workbook"),
        ("list.txt", b"username,class\nzara,JSS1 A\n", "Upload the class list as a CSV file"),
        ("list.xls", b"\xd0\xcf\x11\xe0" + b"\x00" * 100, "Older Office files"),
    ],
)
def test_files_we_refuse(school, admin, filename, data, message) -> None:
    response = send(admin, school.year.id, data, filename)

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_too_many_rows_and_too_large_files(school, admin, monkeypatch) -> None:
    monkeypatch.setattr("app.school.class_lists.MAX_ROWS", 2)
    many = csv_file("username,name,class", *(f"s{n},S {n},JSS1 A" for n in range(3)))
    assert "at most 2 students" in send(admin, school.year.id, many).json()["detail"]

    monkeypatch.setattr("app.school.class_lists.MAX_FILE_BYTES", 10)
    response = send(admin, school.year.id, csv_file("username,class", "amy,JSS1 A"))
    assert response.status_code == 413


def test_class_names_of_another_session(school, admin) -> None:
    plan = send(admin, school.last_year.id, csv_file("username,name,class", "ben,Ben,JSS1 C")).json()

    assert actions(plan) == [("ben", "enrol", "JSS1 C")]


# --- Access ------------------------------------------------------------------------------------


def test_only_school_admins_with_the_csrf_token(school, admin, sign_in, make_user, db) -> None:
    for username, role in (("mr.eze", "teacher"), ("kid", "student")):
        make_user(tenant=admin.school, username=username, role=role, password="correct horse battery")
        person = sign_in(admin.school, username, "correct horse battery")
        assert send(person, school.year.id, MIXED).status_code == 403
    no_token = admin.client.post(
        f"{S}/sessions/{school.year.id}/class-list/preview",
        files={"file": ("list.csv", MIXED, "text/csv")},
    )
    assert no_token.status_code == 403


def test_another_schools_session_is_not_found(school, client: TestClient, make_tenant, make_user, sign_in) -> None:
    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password="correct horse battery")
    their_admin = sign_in(other, "head", "correct horse battery")

    assert send(their_admin, school.year.id, MIXED).status_code == 404
    assert send(their_admin, school.year.id, MIXED, preview=False).status_code == 404
