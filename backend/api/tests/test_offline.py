"""Offline exams on lab computers (ADR 0007): registering lab computers, exam codes, signed
packages, and checked, idempotent results.

A lab computer is simulated with its own Ed25519 key pair; no desktop app is involved.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from test_attempts import ME, E, build_school, item_for, published, questions, start

from app.core.config import get_settings
from app.models import (
    AuditLog,
    DeviceRegistration,
    Exam,
    ExamAttempt,
    LabDevice,
    LoginThrottle,
    OfflineCode,
    OfflinePackage,
    OfflineSubmission,
)
from app.offline import crypto
from app.offline.schemas import PACKAGE_FORMAT, REQUEST_FORMAT, SETUP_FORMAT, SUBMISSION_FORMAT

D = "/api/v1/devices"
SD = "/api/v1/school/devices"


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch):
    """A signing key for this test, and cheap code hashing so tests stay quick."""
    settings = get_settings()
    monkeypatch.setattr(settings, "offline_signing_key", crypto.new_signing_seed())
    monkeypatch.setattr(settings, "offline_code_iterations", 1000)
    crypto._signing_key.cache_clear()
    yield settings
    crypto._signing_key.cache_clear()


def test_production_signing_key_can_be_loaded_from_private_file(tmp_path, monkeypatch) -> None:
    settings = get_settings()
    seed = crypto.new_signing_seed()
    key_file = tmp_path / "offline-signing.key"
    key_file.write_text(seed, encoding="ascii")
    if os.name != "nt":
        key_file.chmod(0o600)
    monkeypatch.setattr(settings, "offline_signing_key", None)
    monkeypatch.setattr(settings, "offline_signing_key_file", str(key_file))
    monkeypatch.setattr(settings, "environment", "production")
    crypto._signing_key.cache_clear()
    try:
        expected = crypto._key_from_seed(seed)
        expected_fingerprint = crypto.sha256_hex(crypto.unb64(crypto.public_key_b64(expected)))
        assert crypto.signing_key_fingerprint(settings) == expected_fingerprint
    finally:
        crypto._signing_key.cache_clear()


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX file permission bits are not available on Windows"
)
def test_production_signing_key_file_rejects_group_or_world_permissions(
    tmp_path, monkeypatch
) -> None:
    settings = get_settings()
    key_file = tmp_path / "offline-signing.key"
    key_file.write_text(crypto.new_signing_seed(), encoding="ascii")
    key_file.chmod(0o644)
    monkeypatch.setattr(settings, "offline_signing_key", None)
    monkeypatch.setattr(settings, "offline_signing_key_file", str(key_file))
    monkeypatch.setattr(settings, "environment", "production")
    crypto._signing_key.cache_clear()
    try:
        with pytest.raises(crypto.SigningNotConfigured, match="group or others"):
            crypto.signing_key(settings)
    finally:
        crypto._signing_key.cache_clear()


def test_signing_key_configuration_rejects_two_secret_sources(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "offline_signing_key", crypto.new_signing_seed())
    monkeypatch.setattr(settings, "offline_signing_key_file", "/unused/secret")
    monkeypatch.setattr(settings, "environment", "production")
    crypto._signing_key.cache_clear()
    try:
        with pytest.raises(crypto.SigningNotConfigured, match="only one"):
            crypto.signing_key(settings)
    finally:
        crypto._signing_key.cache_clear()


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """The school from tests/test_attempts.py: amy and ben in JSS1 A, cara in JSS1 B,
    mrs.okafor teaching Basic Science, mr.eze a coordinator who doesn't teach it."""
    return build_school(admin, db, make_user, sign_in)


def count(db: Session, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


class Lab:
    """A simulated lab computer: its key pair, and its token once registered online."""

    def __init__(self, client, name="Lab A, PC 1"):
        self.client = client
        self.name = name
        self.key = Ed25519PrivateKey.generate()
        self.exchange = X25519PrivateKey.generate()
        self.public_key = crypto.public_key_b64(self.key)
        self.token = None
        self.device_id = None
        self.signing_public_key = None
        self.school_key = None

    @property
    def headers(self):
        return {"Authorization": f"Device {self.token}"}

    def register(self, school_code, code):
        response = self.client.post(
            f"{D}/register",
            json={
                "school_code": school_code,
                "registration_code": code,
                "name": self.name,
                "public_key": self.public_key,
            },
        )
        if response.status_code == 201:
            data = response.json()
            self.token = data["device_token"]
            self.device_id = data["device_id"]
            self.signing_public_key = data["signing_public_key"]
            self.school_key = data["school_key"]
        return response

    def get(self, path):
        return self.client.get(f"{D}{path}", headers=self.headers)

    def package(self, exam_id) -> dict:
        response = self.get(f"/me/exams/{exam_id}/package")
        assert response.status_code == 200, response.text
        envelope = response.json()
        assert crypto.verify(envelope, self.signing_public_key)
        return json.loads(envelope["body"])

    def result(self, body: dict) -> dict:
        """A signed result, as the desktop app would seal it."""
        return crypto.seal(SUBMISSION_FORMAT, body, self.key)

    def upload(self, envelope):
        return self.client.post(f"{D}/me/submissions", json=envelope, headers=self.headers)


def registration_code(school) -> str:
    response = school.head.client.post(f"{SD}/registrations", headers=school.head.headers)
    assert response.status_code == 201, response.text
    return response.json()["code"]


def registered(school, client, name="Lab A, PC 1") -> Lab:
    lab = Lab(client, name)
    response = lab.register(school.head.school.slug, registration_code(school))
    assert response.status_code == 201, response.text
    return lab


def codes_for(school, exam_id, who=None, **body) -> dict:
    who = who or school.teacher
    response = who.client.post(f"{E}/{exam_id}/offline/codes", json=body, headers=who.headers)
    assert response.status_code == 200, response.text
    return response.json()


def offline_exam(school, **settings) -> str:
    """Published, with codes for amy and ben."""
    exam_id = published(school, **settings)
    codes_for(school, exam_id)
    return exam_id


def sat(package: dict, candidate_id: str, answers: dict, **overrides) -> dict:
    """A finished attempt on the lab computer: `answers` maps paper item id to options or text."""
    now = datetime.now(UTC)
    paper = package["paper"]
    events = []
    for sequence, (item_id, answer) in enumerate(answers.items(), start=1):
        event = {"sequence": sequence, "item_id": item_id, "at": now.isoformat()}
        if isinstance(answer, str):
            event["text"] = answer
        else:
            event["selected_option_ids"] = answer
        events.append(event)
    body = {
        "submission_id": str(uuid.uuid4()),
        "package_id": package["package_id"],
        "exam_id": package["exam"]["id"],
        "candidate_id": candidate_id,
        "device_id": package["device_id"],
        # The exam opened 5 minutes ago (test_attempts.published).
        "started_at": (now - timedelta(minutes=4)).isoformat(),
        "ended_at": now.isoformat(),
        "submitted_reason": "student",
        "question_order": [q["item_id"] for q in paper],
        "option_orders": {q["item_id"]: [o["id"] for o in q["options"]] for q in paper},
        "events": events,
    }
    body.update(overrides)
    return body


def item_ids(db: Session, exam_id, school) -> SimpleNamespace:
    return SimpleNamespace(
        q1=item_for(db, exam_id, school.q1),
        q2=item_for(db, exam_id, school.q2),
        pq1=item_for(db, exam_id, school.pq1),
        pq2=item_for(db, exam_id, school.pq2),
    )


def full_marks(db: Session, exam_id, school) -> dict:
    ids = item_ids(db, exam_id, school)
    return {ids.q1: ["b"], ids.pq1: ["a"], ids.pq2: ["false"], ids.q2: ["true"]}


# --- Registering lab computers ----------------------------------------------------------------


def test_an_admin_registers_a_lab_computer_online(school, client, db: Session) -> None:
    code = registration_code(school)
    assert len(code) == 9 and code[4] == "-"
    assert db.scalar(select(DeviceRegistration.code_hash)) != code

    lab = Lab(client)
    response = lab.register(school.head.school.slug.lower(), code.lower())

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["device_token"].startswith("cbt_device_")
    assert data["school"]["code"] == school.head.school.slug
    assert data["signing_public_key"] == crypto.signing_public_key()
    assert len(crypto.unb64(data["school_key"])) == 32
    stored = db.scalar(select(LabDevice))
    assert (stored.name, stored.method, stored.status) == ("Lab A, PC 1", "online", "active")
    assert stored.token_hash == crypto.sha256_hex(data["device_token"])
    me = lab.get("/me")
    assert me.status_code == 200
    assert me.json()["name"] == "Lab A, PC 1"

    # A code works once.
    again = Lab(client, "Lab A, PC 2").register(school.head.school.slug, code)
    assert again.status_code == 401
    listed = school.head.client.get(SD).json()
    assert [(d["name"], d["method"]) for d in listed] == [("Lab A, PC 1", "online")]
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"device.registration_created", "device.registered", "device.registration_failed"} <= (
        actions
    )


def test_registration_codes_expire_and_belong_to_one_school(
    school, client, db: Session, make_tenant
) -> None:
    code = registration_code(school)
    other = make_tenant()
    assert Lab(client).register(other.slug, code).status_code == 401
    db.execute(
        update(DeviceRegistration).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()
    assert Lab(client).register(school.head.school.slug, code).status_code == 401
    # Too many wrong codes for a school, and registration waits.
    for _ in range(get_settings().login_max_failures):
        Lab(client).register(school.head.school.slug, "WRONG-CODE")
    blocked = Lab(client).register(school.head.school.slug, registration_code(school))
    assert blocked.status_code == 429
    db.execute(delete(LoginThrottle))
    db.commit()
    bad_key = Lab(client)
    bad_key.public_key = "not a key at all, not a key at all, nope!"
    assert bad_key.register(school.head.school.slug, registration_code(school)).status_code == 422


def test_only_school_admins_manage_lab_computers(school) -> None:
    for who in (school.teacher, school.coordinator, school.amy):
        assert who.client.get(SD).status_code == 403
        assert who.client.post(f"{SD}/registrations", headers=who.headers).status_code == 403
    no_csrf = school.head.client.post(f"{SD}/registrations")
    assert no_csrf.status_code == 403


def test_a_lab_computer_registers_by_file(school, client, db: Session) -> None:
    lab = Lab(client, "Old lab, PC 9")
    request_file = crypto.seal(
        REQUEST_FORMAT,
        {
            "name": lab.name,
            "public_key": lab.public_key,
            "exchange_key": crypto.exchange_public_b64(lab.exchange),
        },
        lab.key,
    )

    response = school.head.client.post(
        f"{SD}/file-registration", json={"request": request_file}, headers=school.head.headers
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert (data["device"]["method"], data["device"]["name"]) == ("file", "Old lab, PC 9")
    setup = data["setup"]
    assert setup["format"] == SETUP_FORMAT
    assert crypto.verify(setup, crypto.signing_public_key())
    body = json.loads(setup["body"])
    assert body["device_id"] == data["device"]["id"]
    school_key = crypto.open_sealed(body["school_key"], lab.exchange, body["device_id"])["key"]
    assert len(crypto.unb64(school_key)) == 32
    assert school_key not in setup["body"]  # sealed for the computer, not in plain text
    assert db.scalar(select(LabDevice.token_hash)) is None

    # A request changed after the computer signed it is refused.
    tampered = {**request_file, "body": request_file["body"].replace("PC 9", "PC 8")}
    refused = school.head.client.post(
        f"{SD}/file-registration", json={"request": tampered}, headers=school.head.headers
    )
    assert refused.status_code == 422


def test_revoked_lab_computers_are_refused(school, client) -> None:
    lab = registered(school, client)
    response = school.head.client.post(f"{SD}/{lab.device_id}/revoke", headers=school.head.headers)
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert lab.get("/me").status_code == 401
    assert lab.get("/me/exams").status_code == 401
    assert (
        client.get(f"{D}/me", headers={"Authorization": "Device cbt_device_nope"}).status_code
        == 401
    )
    assert client.get(f"{D}/me").status_code == 401


# --- Exam codes ----------------------------------------------------------------------------------


def test_teachers_print_codes_for_the_students_an_exam_is_set_for(school, db: Session) -> None:
    exam_id = published(school)

    printed = codes_for(school, exam_id)

    assert printed["batch"] == 1
    by_name = {c["username"]: c for c in printed["codes"]}
    assert set(by_name) == {"amy", "ben"}
    assert by_name["amy"]["class_name"] == "JSS1 A"
    code = by_name["amy"]["code"]
    assert len(code) == 9 and all(ch in crypto.CODE_ALPHABET + "-" for ch in code)
    stored = db.scalar(
        select(OfflineCode).where(OfflineCode.candidate_id == by_name["amy"]["candidate_id"])
    )
    assert code.replace("-", "") not in (stored.code_hash, stored.salt)
    assert crypto.code_matches(code, stored.salt, stored.code_hash, stored.iterations)

    # A lost slip: a new code for amy only. Ben's stays.
    again = codes_for(school, exam_id, candidate_ids=[by_name["amy"]["candidate_id"]])
    assert again["batch"] == 2
    assert [c["username"] for c in again["codes"]] == ["amy"]
    db.expire_all()
    batches = dict(db.execute(select(OfflineCode.candidate_id, OfflineCode.batch)).all())
    assert batches == {by_name["amy"]["candidate_id"]: 2, by_name["ben"]["candidate_id"]: 1}

    # The exam's status lists who has a code, and from which batch, but never the codes.
    status_ = school.teacher.client.get(f"{E}/{exam_id}/offline").json()
    assert [(s["username"], s["class_name"], s["code_batch"]) for s in status_["roster"]] == [
        ("amy", "JSS1 A", 2),
        ("ben", "JSS1 A", 1),
    ]
    assert "code" not in status_["roster"][0]


def test_who_can_print_codes_and_when(school, db: Session) -> None:
    exam_id = published(school)
    url = f"{E}/{exam_id}/offline/codes"
    # The exam tells each person whether they can manage it on lab computers.
    for who, expected in ((school.teacher, True), (school.head, True), (school.coordinator, False)):
        exam = who.client.get(f"{E}/{exam_id}").json()
        assert ("manage_offline" in exam["allowed_actions"]) is expected
    for who in (school.coordinator, school.other_teacher):
        assert who.client.post(url, json={}, headers=who.headers).status_code == 403
    assert school.amy.client.post(url, json={}, headers=school.amy.headers).status_code == 403
    assert codes_for(school, exam_id, who=school.head)["batch"] == 1

    draft = published(school, publish=False)
    response = school.teacher.client.post(
        f"{E}/{draft}/offline/codes", json={}, headers=school.teacher.headers
    )
    assert response.status_code == 409
    not_offline = published(school, offline_allowed=False)
    response = school.teacher.client.post(
        f"{E}/{not_offline}/offline/codes", json={}, headers=school.teacher.headers
    )
    assert response.status_code == 409
    assert "turned off" in response.json()["detail"]
    exam = school.teacher.client.get(f"{E}/{not_offline}").json()
    assert "manage_offline" not in exam["allowed_actions"]
    cara = db.scalar(select(LabDevice.id))  # nobody: just a stranger's id
    response = school.teacher.client.post(
        url, json={"candidate_ids": [cara or "someone-else"]}, headers=school.teacher.headers
    )
    assert response.status_code == 422


# --- Packages ------------------------------------------------------------------------------------


def test_a_lab_computer_downloads_a_signed_package_without_answer_keys(
    school, client, db: Session
) -> None:
    exam_id = published(school)
    lab = registered(school, client)
    listed = lab.get("/me/exams").json()["exams"]
    assert [(e["id"], e["codes_ready"]) for e in listed] == [(exam_id, False)]
    refused = lab.get(f"/me/exams/{exam_id}/package")
    assert refused.status_code == 409
    assert "codes first" in refused.json()["detail"]
    printed = {c["username"]: c["code"] for c in codes_for(school, exam_id)["codes"]}

    response = lab.get(f"/me/exams/{exam_id}/package")

    envelope = response.json()
    assert envelope["format"] == PACKAGE_FORMAT
    assert crypto.verify(envelope, lab.signing_public_key)
    assert not crypto.verify({**envelope, "body": envelope["body"] + " "}, lab.signing_public_key)
    body = json.loads(envelope["body"])
    assert body["device_id"] == lab.device_id
    assert body["exam"]["title"] == "Synthetic Science Test"
    assert body["exam"]["total_marks"] == 7
    assert body["answer_key"] is None
    assert len(body["paper"]) == 4
    raw = envelope["body"]
    for secret in ("correct_option_ids", "explanation", "guide", "accepted_answers"):
        assert secret not in raw
    assert body["passages"] and all(q["stem"] for q in body["paper"])
    students = {s["username"]: s for s in body["students"]}
    assert set(students) == {"amy", "ben"}
    amy = students["amy"]["code"]
    assert crypto.code_matches(printed["amy"], amy["salt"], amy["hash"], amy["iterations"])
    assert not crypto.code_matches(printed["ben"], amy["salt"], amy["hash"], amy["iterations"])
    issued = db.scalar(select(OfflinePackage))
    assert (issued.id, issued.device_id, issued.codes_batch) == (
        body["package_id"],
        lab.device_id,
        1,
    )


def test_which_exams_a_lab_computer_can_download(school, client, db: Session) -> None:
    lab = registered(school, client)
    offline = offline_exam(school)
    not_offline = published(school, offline_allowed=False)
    far_off = published(school, opens_in=30 * 24 * 60, closes_in=30 * 24 * 60 + 60)
    closed = offline_exam(school)
    db.execute(
        update(Exam)
        .where(Exam.id == closed)
        .values(closes_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db.commit()

    listed = [e["id"] for e in lab.get("/me/exams").json()["exams"]]

    assert listed == [offline]
    for exam_id in (not_offline, far_off, closed):
        assert lab.get(f"/me/exams/{exam_id}/package").status_code == 409
    # Another school's lab computer can't see the exam at all.
    assert lab.get(f"/me/exams/{uuid.uuid4()}/package").status_code == 404


def test_instant_scores_put_the_encrypted_key_in_the_package(school, client) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school, results_release="immediate", offline_instant_scores=True)

    body = lab.package(exam_id)

    blob = body["answer_key"]
    assert blob["alg"] == "A256GCM"
    assert "correct_option_ids" not in json.dumps(blob)
    keys = crypto.decrypt(blob, lab.school_key, body["package_id"])
    assert sorted(k["correct_option_ids"][0] for k in keys.values()) == ["a", "b", "false", "true"]
    with pytest.raises(Exception):  # noqa: B017 - any failure: the wrong key can't read it
        crypto.decrypt(blob, crypto.new_school_key(), body["package_id"])


def test_instant_scores_need_results_shown_at_once(school) -> None:
    exam_id = published(school, publish=False, offline_instant_scores=True)
    t = school.teacher
    response = t.client.post(f"{E}/{exam_id}/submit", headers=t.headers)
    assert response.status_code == 422
    assert "As soon as each student submits" in response.json()["detail"]


def test_staff_export_a_package_for_usb(school, db: Session) -> None:
    exam_id = offline_exam(school)
    response = school.teacher.client.get(f"{E}/{exam_id}/offline/package")
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert crypto.verify(envelope, crypto.signing_public_key())
    assert json.loads(envelope["body"])["device_id"] is None
    issued = db.scalar(select(OfflinePackage))
    assert (issued.device_id, issued.exported_by_id) == (None, school.people["mrs.okafor"].id)
    assert school.coordinator.client.get(f"{E}/{exam_id}/offline/package").status_code == 403


# --- Results -------------------------------------------------------------------------------------


def test_an_offline_result_becomes_a_marked_attempt(school, client, db: Session) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school)
    package = lab.package(exam_id)
    amy = school.people["amy"]
    candidate_id = next(s["candidate_id"] for s in package["students"] if s["username"] == "amy")
    envelope = lab.result(sat(package, candidate_id, full_marks(db, exam_id, school)))

    response = lab.upload(envelope)

    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["status"], result["reason"], result["flags"]) == ("accepted", None, [])
    attempt = db.get(ExamAttempt, result["attempt_id"])
    assert (attempt.source, attempt.status, attempt.score, attempt.max_score) == (
        "offline",
        "submitted",
        7,
        7,
    )
    assert attempt.candidate_id == candidate_id
    assert amy.id  # amy's account is the one the candidate record belongs to
    listed = school.teacher.client.get(f"{E}/{exam_id}/attempts").json()["attempts"]
    assert [(a["candidate_id"], a["score"], a["source"]) for a in listed] == [
        (candidate_id, 7, "offline")
    ]

    # The same result again changes nothing; the same id with different answers is refused.
    again = lab.upload(envelope)
    assert again.status_code == 200
    assert again.json() == result
    assert count(db, ExamAttempt) == 1
    changed = lab.result({**json.loads(envelope["body"]), "submitted_reason": "time_up"})
    assert lab.upload(changed).status_code == 409
    assert count(db, OfflineSubmission) == 1

    status_ = school.teacher.client.get(f"{E}/{exam_id}/offline").json()
    assert (status_["students"], status_["codes_issued"], status_["codes_batch"]) == (2, 2, 1)
    assert [p["device_name"] for p in status_["packages"]] == ["Lab A, PC 1"]
    assert [(s["status"], s["device_name"]) for s in status_["submissions"]] == [
        ("accepted", "Lab A, PC 1")
    ]


def test_results_are_checked_before_they_count(school, client, db: Session) -> None:
    lab = registered(school, client)
    other_lab = registered(school, client, "Lab B, PC 1")
    exam_id = offline_exam(school)
    package = lab.package(exam_id)
    students = {s["username"]: s["candidate_id"] for s in package["students"]}
    answers = full_marks(db, exam_id, school)
    ids = item_ids(db, exam_id, school)

    # Refused outright: tampering, another computer's signature, or a damaged file.
    envelope = lab.result(sat(package, students["amy"], answers))
    tampered = {**envelope, "body": envelope["body"].replace('"student"', '"time_up"')}
    assert lab.upload(tampered).status_code == 422
    assert other_lab.upload(envelope).status_code == 422
    forged = other_lab.result(json.loads(envelope["body"]))
    assert lab.upload(forged).status_code == 422
    assert lab.upload({**envelope, "format": "something/1"}).status_code == 422
    assert lab.upload({**envelope, "body": "not json"}).status_code == 422
    assert count(db, OfflineSubmission) == 0

    def outcome(body) -> dict:
        response = lab.upload(lab.result(body))
        assert response.status_code == 200, response.text
        return response.json()

    # Kept, but rejected: not from this exam's package, or not its paper.
    wrong_package = outcome(sat(package, students["amy"], answers, package_id=str(uuid.uuid4())))
    assert wrong_package["status"] == "rejected"
    order = sat(package, students["amy"], answers)
    order["question_order"] = order["question_order"][:-1]
    assert outcome(order)["reason"] == "Its questions don't match the exam's paper."
    two_options = sat(package, students["amy"], {**answers, ids.q1: ["a", "b"]})
    assert outcome(two_options)["reason"].startswith("An answer doesn't fit its question")
    assert count(db, ExamAttempt) == 0

    # Accepted with a flag: the lab computer's clock was a day out.
    skewed = sat(
        package,
        students["amy"],
        answers,
        started_at=(datetime.now(UTC) - timedelta(days=1, minutes=20)).isoformat(),
        ended_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
    )
    accepted = outcome(skewed)
    assert accepted["status"] == "accepted"
    assert "outside the exam's window" in accepted["flags"][0]

    # A conflict: amy had one attempt, and has used it.
    conflict = outcome(sat(package, students["amy"], answers))
    assert conflict["status"] == "conflict"
    assert "all their attempts" in conflict["reason"]
    assert count(db, ExamAttempt) == 1


def test_a_student_sitting_online_at_the_same_time_is_a_conflict(
    school, client, db: Session
) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school, max_attempts=2)
    package = lab.package(exam_id)
    ben = next(s["candidate_id"] for s in package["students"] if s["username"] == "ben")
    online = start(school.ben, exam_id).json()
    assert online["status"] == "in_progress"

    result = lab.upload(lab.result(sat(package, ben, full_marks(db, exam_id, school)))).json()

    assert result["status"] == "conflict"
    assert "online at the same time" in result["reason"]
    assert questions(online)


def test_late_results_for_a_withdrawn_or_released_exam_dont_count(
    school, client, db: Session
) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school)
    package = lab.package(exam_id)
    students = {s["username"]: s["candidate_id"] for s in package["students"]}
    answers = full_marks(db, exam_id, school)

    def outcome(candidate_id) -> dict:
        response = lab.upload(lab.result(sat(package, candidate_id, answers)))
        assert response.status_code == 200, response.text
        return response.json()

    # The lab computer didn't know the results were released before amy's result arrived.
    db.execute(update(Exam).where(Exam.id == exam_id).values(results_released_at=datetime.now(UTC)))
    db.commit()
    released = outcome(students["amy"])
    assert (released["status"], released["reason"]) == (
        "conflict",
        "The exam's results were already released when it arrived.",
    )

    # Or that the exam was withdrawn.
    db.execute(update(Exam).where(Exam.id == exam_id).values(status="withdrawn"))
    db.commit()
    withdrawn = outcome(students["ben"])
    assert (withdrawn["status"], withdrawn["reason"]) == (
        "rejected",
        "The exam was withdrawn, so results for it don't count.",
    )
    assert count(db, ExamAttempt) == 0
    assert count(db, OfflineSubmission) == 2


def test_a_revoked_lab_computers_results_brought_by_usb_are_rejected(
    school, client, db: Session
) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school)
    package = lab.package(exam_id)
    amy = next(s["candidate_id"] for s in package["students"] if s["username"] == "amy")
    envelope = lab.result(sat(package, amy, full_marks(db, exam_id, school)))
    school.head.client.post(f"{SD}/{lab.device_id}/revoke", headers=school.head.headers)

    response = school.teacher.client.post(
        f"{E}/{exam_id}/offline/results",
        json={"submissions": [envelope]},
        headers=school.teacher.headers,
    )

    assert response.status_code == 200, response.text
    [result] = response.json()["results"]
    assert (result["status"], result["reason"]) == (
        "rejected",
        "This lab computer was removed from the school.",
    )
    assert count(db, ExamAttempt) == 0


def test_results_come_back_by_usb(school, client, db: Session) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school)
    package_envelope = school.teacher.client.get(f"{E}/{exam_id}/offline/package").json()
    package = json.loads(package_envelope["body"])
    package["device_id"] = lab.device_id  # sat on this computer from the USB package
    students = {s["username"]: s["candidate_id"] for s in package["students"]}
    answers = full_marks(db, exam_id, school)
    good = lab.result(sat(package, students["amy"], answers))
    ben_answers = {**answers, item_ids(db, exam_id, school).q1: ["a"]}
    second = lab.result(sat(package, students["ben"], ben_answers))
    broken = {**second, "body": second["body"][:-5]}
    other_exam = offline_exam(school)
    elsewhere = lab.result(sat(package, students["amy"], answers, exam_id=other_exam))
    url = f"{E}/{exam_id}/offline/results"

    response = school.teacher.client.post(
        url, json={"submissions": [good, broken, second, elsewhere]}, headers=school.teacher.headers
    )

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["accepted", "rejected", "accepted", "rejected"]
    assert results[1]["reason"] == "This result couldn't be read: it may be damaged."
    assert results[3]["reason"] == "This result is for another exam."
    scores = dict(db.execute(select(ExamAttempt.candidate_id, ExamAttempt.score)).all())
    assert scores == {students["amy"]: 7, students["ben"]: 5}
    received = db.scalars(select(OfflineSubmission.received_via)).all()
    assert set(received) == {"file"}

    # Uploading the same file again adds nothing.
    again = school.teacher.client.post(
        url, json={"submissions": [good, second]}, headers=school.teacher.headers
    ).json()["results"]
    assert [r["status"] for r in again] == ["accepted", "accepted"]
    assert count(db, ExamAttempt) == 2
    assert (
        school.coordinator.client.post(
            url, json={"submissions": [good]}, headers=school.coordinator.headers
        ).status_code
        == 403
    )


def test_offline_attempts_count_in_results(school, client, db: Session) -> None:
    lab = registered(school, client)
    exam_id = offline_exam(school, results_release="immediate")
    package = lab.package(exam_id)
    amy = next(s["candidate_id"] for s in package["students"] if s["username"] == "amy")
    lab.upload(lab.result(sat(package, amy, full_marks(db, exam_id, school))))

    mine = school.amy.client.get(f"{ME}/results").json()["results"]

    assert [(r["exam_id"], r["score"], r["max_score"]) for r in mine] == [(exam_id, 7, 7)]


def test_students_and_unregistered_callers_cant_reach_offline_endpoints(school, client) -> None:
    exam_id = offline_exam(school)
    amy = school.amy
    assert amy.client.get(f"{E}/{exam_id}/offline").status_code == 403
    assert amy.client.get(f"{E}/{exam_id}/offline/package").status_code == 403
    assert client.get(f"{D}/me/exams").status_code == 401
    assert client.post(f"{D}/me/submissions", json={}).status_code in (401, 422)
    key = client.get("/api/v1/offline/signing-key").json()
    assert key == {"alg": "Ed25519", "public_key": crypto.signing_public_key()}
