"""Learning materials (ADR 0004): uploading, checking files, extracting text with where it came
from, review and approval, versions, the processing queue, and who can do what.

All material here is synthetic, built in memory by tests/samples.py.
"""

import io
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from samples import make_docx, make_pdf
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.documents.processing import (
    MAX_ATTEMPTS,
    claim,
    now,
    process_queued,
    recover_stuck,
)
from app.documents.router import _filename
from app.models import (
    AcademicSession,
    AuditLog,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Document,
    DocumentSegment,
    DocumentVersion,
    Subject,
    Topic,
    User,
)

D = "/api/v1/documents"
S = "/api/v1/school"
TEST_PASSWORD = "correct horse battery staple"

NOTES_PDF = make_pdf(
    [
        "Living things\nAll living things grow, feed and reproduce.",
        None,
        "Matter\nMatter has mass and takes up space.",
    ],
    outline=[("Living things", 0), ("Matter", 2)],
)
CLEAN_PDF = make_pdf(
    ["Energy can change from one form to another.", "Heat flows from hot to cold."]
)


@pytest.fixture
def school(admin, db: Session, make_user, sign_in):
    """Two subjects with topics, a teacher of the first, a teacher of neither, and a student."""
    tid = admin.school.id
    year = AcademicSession(
        tenant_id=tid,
        name="2026/2027",
        starts_on=date(2026, 9, 1),
        ends_on=date(2027, 7, 31),
        is_current=True,
    )
    jss1 = ClassLevel(tenant_id=tid, name="JSS1", position=1)
    science = Subject(tenant_id=tid, name="Basic Science", code="BSC")
    physics = Subject(tenant_id=tid, name="Physics")
    db.add_all([year, jss1, science, physics])
    db.flush()
    jss1a = ClassArm(tenant_id=tid, session_id=year.id, level_id=jss1.id, name="A")
    cells = Topic(tenant_id=tid, subject_id=science.id, name="Cells", position=1)
    motion = Topic(tenant_id=tid, subject_id=physics.id, name="Motion", position=1)
    db.add_all(
        [
            jss1a,
            cells,
            motion,
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=science.id),
            ClassLevelSubject(tenant_id=tid, level_id=jss1.id, subject_id=physics.id),
        ]
    )
    db.commit()
    for username, role in [("mrs.okafor", "teacher"), ("mr.bello", "teacher"), ("amy", "student")]:
        make_user(
            tenant=admin.school,
            username=username,
            role=role,
            password=TEST_PASSWORD,
            display_name=f"Synthetic {username}",
        )
    okafor = db.scalar(select(User.id).where(User.username == "mrs.okafor"))
    response = admin.client.post(
        f"{S}/assignments",
        json={"teacher_id": okafor, "arm_id": jss1a.id, "subject_id": science.id},
        headers=admin.headers,
    )
    assert response.status_code == 201, response.text
    return SimpleNamespace(
        admin=admin,
        science=science,
        physics=physics,
        cells=cells,
        motion=motion,
        teacher=sign_in(admin.school, "mrs.okafor"),
        other_teacher=sign_in(admin.school, "mr.bello"),
        student=sign_in(admin.school, "amy"),
    )


def upload(who, subject, data=CLEAN_PDF, filename="notes.pdf", title="Synthetic notes", **form):
    fields = {"subject_id": subject.id, "title": title, **form}
    return who.client.post(
        D,
        data=fields,
        files={"file": (filename, data, "application/octet-stream")},
        headers=who.headers,
    )


def uploaded(who, subject, **kwargs) -> dict:
    response = upload(who, subject, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def get(who, document_id) -> dict:
    response = who.client.get(f"{D}/{document_id}")
    assert response.status_code == 200, response.text
    return response.json()


def segments(who, document_id, version=1, **params) -> dict:
    response = who.client.get(f"{D}/{document_id}/versions/{version}/segments", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def act(who, document_id, path, body=None):
    return who.client.post(f"{D}/{document_id}/{path}", json=body, headers=who.headers)


# --- Uploading and extracting -------------------------------------------------------------------


def test_a_teacher_uploads_a_pdf_and_its_pages_are_extracted(school, storage, db: Session) -> None:
    created = uploaded(school.teacher, school.science, data=NOTES_PDF, topic_ids=[school.cells.id])

    # The response comes back before processing; inline processing runs right after it.
    assert created["latest"]["status"] == "queued"
    assert created["topic_ids"] == [school.cells.id]
    assert created["created_by_name"] == "Synthetic mrs.okafor"
    document = get(school.teacher, created["id"])
    latest = document["latest"]
    assert latest["status"] == "extracted"
    assert (latest["kind"], latest["filename"], latest["size_bytes"]) == (
        "pdf",
        "notes.pdf",
        len(NOTES_PDF),
    )
    assert latest["segment_count"] == 3
    # (A server without OCR adds a second warning saying scanned pages can't be read.)
    assert latest["warnings"][0] == (
        "Page 2 has no readable text (it may be a scanned picture or a diagram). "
        "Anything on it won't be used."
    )
    pages = segments(school.teacher, created["id"])["segments"]
    assert [(p["kind"], p["number"], p["label"], p["flags"]) for p in pages] == [
        ("page", 1, "Living things", []),
        ("page", 2, "Living things", ["no_text"]),
        ("page", 3, "Matter", []),
    ]
    assert pages[0]["text"] == "Living things\nAll living things grow, feed and reproduce."
    assert pages[1]["text"] == ""
    # The original is stored exactly, under a key the server made.
    version = db.scalar(select(DocumentVersion))
    assert storage.get(version.storage_key) == NOTES_PDF
    assert version.storage_key == f"{school.admin.school.id}/documents/{created['id']}/{version.id}"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.uploaded"))
    assert entry.details == {
        "subject": "Basic Science",
        "kind": "pdf",
        "size_bytes": len(NOTES_PDF),
    }


def test_word_files_are_split_into_sections_at_headings(school) -> None:
    data = make_docx(
        [
            ("paragraph", "A short introduction."),
            ("heading", "Cells"),
            ("paragraph", "A cell is the smallest unit of a living thing."),
            ("table", [["Part", "Job"], ["Nucleus", "Controls the cell"]]),
            ("heading", "Tissues"),
            ("paragraph", "Similar cells form tissues."),
        ]
    )
    created = uploaded(school.teacher, school.science, data=data, filename="cells.docx")

    parts = segments(school.teacher, created["id"])["segments"]
    assert [(p["kind"], p["number"], p["label"]) for p in parts] == [
        ("section", 1, None),
        ("section", 2, "Cells"),
        ("section", 3, "Tissues"),
    ]
    assert "Nucleus | Controls the cell" in parts[1]["text"]
    assert get(school.teacher, created["id"])["latest"]["warnings"] == []


def test_text_files_are_read_and_odd_encodings_are_flagged(school) -> None:
    data = "Photosynthesis\n\nPlants make food from light.\n".encode("cp1252") + b"caf\xe9"
    created = uploaded(school.teacher, school.science, data=data, filename="notes.txt")

    latest = get(school.teacher, created["id"])["latest"]
    assert latest["kind"] == "txt"
    assert "isn't UTF-8" in latest["warnings"][0]
    [part] = segments(school.teacher, created["id"])["segments"]
    assert (part["kind"], part["number"]) == ("lines", 1)
    assert part["text"].endswith("café")


@pytest.mark.parametrize(
    ("filename", "data", "message"),
    [
        ("animation.gif", b"GIF89a synthetic", "isn't supported"),
        ("program.exe", b"MZ\x90\x00 synthetic", "isn't supported"),
        ("empty.pdf", b"", "empty"),
        ("old.doc", b"\xd0\xcf\x11\xe0 synthetic", "Older Office files"),
        ("old.xls", b"\xd0\xcf\x11\xe0 synthetic", ".xlsx"),
    ],
)
def test_files_we_cant_read_are_refused_up_front(school, db: Session, filename, data, message):
    response = upload(school.teacher, school.science, data=data, filename=filename)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def _office(content_type: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<Types><Override PartName="/x.xml" ContentType="{content_type}"/></Types>',
        )
        archive.writestr("x.xml", "<x/>")
    return out.getvalue()


@pytest.mark.parametrize(
    ("content_type", "message"),
    [
        ("application/vnd.ms-word.document.macroEnabled.main+xml", "macros"),
        ("application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml", "macros"),
        ("application/vnd.openxmlformats-officedocument.presentationml.template.main+xml", "Templates"),
        ("application/vnd.openxmlformats-officedocument.presentationml.slide+xml", "isn't supported"),
    ],
)
def test_macro_files_and_unsupported_office_files_are_refused(school, content_type, message):
    response = upload(school.teacher, school.science, data=_office(content_type), filename="x.docx")

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_size_and_unpacking_limits(school, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "document_max_mb", 1)
    too_big = b"%PDF-1.4\n" + b"0" * (1024 * 1024)
    response = upload(school.teacher, school.science, data=too_big)
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]

    monkeypatch.setattr(settings, "document_max_mb", 25)
    monkeypatch.setattr(settings, "document_max_unzipped_mb", 0)
    docx = make_docx([("paragraph", "Synthetic text.")])
    response = upload(school.teacher, school.science, data=docx, filename="x.docx")
    assert response.status_code == 422
    assert "unpacks" in response.json()["detail"]


def test_a_damaged_pdf_fails_with_a_reason_and_can_be_retried(school, db: Session) -> None:
    created = uploaded(school.teacher, school.science, data=b"%PDF-1.4 synthetic but broken")

    latest = get(school.teacher, created["id"])["latest"]
    assert latest["status"] == "failed"
    assert "damaged" in latest["error"]
    assert act(school.teacher, created["id"], "versions/1/approve", {}).status_code == 409

    response = act(school.teacher, created["id"], "versions/1/retry")
    assert response.status_code == 200, response.text
    latest = get(school.teacher, created["id"])["latest"]
    assert (latest["status"], latest["attempts"]) == ("failed", 2)
    assert act(school.teacher, created["id"], "versions/1/retry").status_code == 200
    assert act(school.teacher, created["id"], "versions/1/reject", {"note": "x"}).status_code == 409


def test_the_same_file_cant_be_uploaded_twice_in_a_subject(school) -> None:
    first = uploaded(school.teacher, school.science)

    response = upload(school.teacher, school.science, title="Again")
    assert response.status_code == 409
    assert "version 1 of “Synthetic notes”" in response.json()["detail"]
    response = school.teacher.client.post(
        f"{D}/{first['id']}/versions",
        files={"file": ("same.pdf", CLEAN_PDF, "application/pdf")},
        headers=school.teacher.headers,
    )
    assert response.status_code == 409
    # Another subject may have the same file.
    assert upload(school.admin, school.physics).status_code == 201


def test_uploaded_names_are_cleaned_and_never_used_for_storage(school, db: Session) -> None:
    created = uploaded(school.teacher, school.science, filename="../../etc/passwd.pdf")

    version = db.scalar(select(DocumentVersion))
    assert created["latest"]["filename"] == "passwd.pdf"
    assert "passwd" not in version.storage_key
    assert _filename("C:\\Users\\x\\\x07notes\x00.pdf") == "notes.pdf"
    assert _filename("") == "upload"


# --- Who can do what ----------------------------------------------------------------------------


def test_only_staff_of_the_subject_can_reach_its_materials(school, make_tenant, make_user, sign_in):
    created = uploaded(school.teacher, school.science)

    assert upload(school.other_teacher, school.science, title="x").status_code == 403
    assert school.other_teacher.client.get(f"{D}/{created['id']}").status_code == 403
    assert school.student.client.get(f"{D}/{created['id']}").status_code == 403
    assert upload(school.student, school.science, title="x").status_code == 403
    assert school.student.client.get(D).status_code == 403
    # School admins can use every subject's materials.
    assert get(school.admin, created["id"])["id"] == created["id"]

    other = make_tenant()
    make_user(tenant=other, username="head", role="school_admin", password=TEST_PASSWORD)
    stranger = sign_in(other, "head")
    assert stranger.client.get(f"{D}/{created['id']}").status_code == 404
    response = upload(stranger, school.science, title="x")
    assert response.status_code == 422  # another school's subject doesn't exist for them


def test_listing_shows_teachers_only_their_subjects(school) -> None:
    mine = uploaded(school.teacher, school.science, topic_ids=[school.cells.id])
    theirs = uploaded(school.admin, school.physics, data=NOTES_PDF, title="Physics notes")

    listed = school.teacher.client.get(D).json()["documents"]
    assert [d["id"] for d in listed] == [mine["id"]]
    assert {d["id"] for d in school.admin.client.get(D).json()["documents"]} == {
        mine["id"],
        theirs["id"],
    }
    by_topic = school.admin.client.get(D, params={"topic_id": school.cells.id}).json()
    assert [d["id"] for d in by_topic["documents"]] == [mine["id"]]
    assert school.teacher.client.get(D, params={"subject_id": school.physics.id}).status_code == 403


def test_topics_must_belong_to_the_documents_subject(school) -> None:
    response = upload(school.teacher, school.science, topic_ids=[school.motion.id])
    assert response.status_code == 422

    created = uploaded(school.teacher, school.science)
    response = school.teacher.client.put(
        f"{D}/{created['id']}/topics",
        json={"topic_ids": [school.cells.id]},
        headers=school.teacher.headers,
    )
    assert response.json()["topic_ids"] == [school.cells.id]


# --- Review and approval ------------------------------------------------------------------------


def test_approving_a_clean_version(school, db: Session) -> None:
    created = uploaded(school.teacher, school.science)

    response = act(school.teacher, created["id"], "versions/1/approve", {})

    assert response.status_code == 200, response.text
    document = response.json()
    assert document["approved_version"] == 1
    assert document["latest"]["status"] == "approved"
    # Approving your own upload is allowed: it confirms the text is faithful to the file.
    assert document["latest"]["reviewed_by_name"] == "Synthetic mrs.okafor"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.approved"))
    assert entry.details == {"version": 1, "warnings": 0}
    assert act(school.teacher, created["id"], "versions/1/approve", {}).status_code == 409


def test_warnings_must_be_acknowledged_before_approving(school) -> None:
    created = uploaded(school.teacher, school.science, data=NOTES_PDF)

    response = act(school.teacher, created["id"], "versions/1/approve", {})
    assert response.status_code == 409
    assert "warnings" in response.json()["detail"]

    response = act(
        school.teacher, created["id"], "versions/1/approve", {"acknowledge_warnings": True}
    )
    assert response.status_code == 200
    assert response.json()["approved_version"] == 1


def test_a_version_with_no_readable_text_cant_be_approved(school, monkeypatch) -> None:
    # Without OCR on the server, a scanned PDF has nothing to read.
    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    created = uploaded(school.teacher, school.science, data=make_pdf([None, None]))

    latest = get(school.teacher, created["id"])["latest"]
    assert "looks scanned" in latest["warnings"][0]
    assert "isn't set up on this server" in latest["warnings"][0]
    response = act(
        school.teacher, created["id"], "versions/1/approve", {"acknowledge_warnings": True}
    )
    assert response.status_code == 422
    assert "No readable text" in response.json()["detail"]


def test_rejecting_needs_a_note_and_ends_the_review(school) -> None:
    created = uploaded(school.teacher, school.science)

    assert act(school.teacher, created["id"], "versions/1/reject", {"note": ""}).status_code == 422
    response = act(school.teacher, created["id"], "versions/1/reject", {"note": "Wrong chapter"})
    assert response.status_code == 200
    latest = response.json()["latest"]
    assert (latest["status"], latest["review_note"]) == ("rejected", "Wrong chapter")
    assert act(school.teacher, created["id"], "versions/1/approve", {}).status_code == 409


def test_a_new_version_leaves_the_approved_one_in_use_until_it_is_approved(school) -> None:
    created = uploaded(school.teacher, school.science)
    act(school.teacher, created["id"], "versions/1/approve", {})

    response = school.teacher.client.post(
        f"{D}/{created['id']}/versions",
        data={"note": "Second edition"},
        files={"file": ("notes-v2.pdf", NOTES_PDF, "application/pdf")},
        headers=school.teacher.headers,
    )
    assert response.status_code == 201, response.text
    document = get(school.teacher, created["id"])
    assert (document["latest_version"], document["approved_version"]) == (2, 1)
    assert [(v["version"], v["status"]) for v in document["versions"]] == [
        (2, "extracted"),
        (1, "approved"),
    ]
    assert document["versions"][0]["note"] == "Second edition"
    act(school.teacher, created["id"], "versions/2/approve", {"acknowledge_warnings": True})
    assert get(school.teacher, created["id"])["approved_version"] == 2


def test_the_original_file_downloads_exactly_as_uploaded(school) -> None:
    created = uploaded(
        school.teacher, school.science, data=NOTES_PDF, filename="Notes (week 1).pdf"
    )

    response = school.teacher.client.get(f"{D}/{created['id']}/versions/1/file")

    assert response.status_code == 200
    assert response.content == NOTES_PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="Notes (week 1).pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert school.student.client.get(f"{D}/{created['id']}/versions/1/file").status_code == 403


def test_extracted_text_pages(school) -> None:
    created = uploaded(
        school.teacher,
        school.science,
        data=make_pdf([f"Page {n} of synthetic text." for n in range(1, 6)]),
    )

    first = segments(school.teacher, created["id"], limit=2)
    assert [s["number"] for s in first["segments"]] == [1, 2]
    rest = segments(school.teacher, created["id"], after=first["next_after"], limit=10)
    assert [s["number"] for s in rest["segments"]] == [3, 4, 5]
    assert rest["next_after"] is None


# --- Archiving and deleting ---------------------------------------------------------------------


def test_deleting_is_only_for_documents_never_approved(school, storage, db: Session) -> None:
    draft = uploaded(school.teacher, school.science)
    key = db.scalar(select(DocumentVersion.storage_key))
    response = school.teacher.client.delete(f"{D}/{draft['id']}", headers=school.teacher.headers)
    assert response.status_code == 204
    with pytest.raises(FileNotFoundError):
        storage.get(key)

    used = uploaded(school.teacher, school.science, data=NOTES_PDF)
    act(school.teacher, used["id"], "versions/1/approve", {"acknowledge_warnings": True})
    response = school.teacher.client.delete(f"{D}/{used['id']}", headers=school.teacher.headers)
    assert response.status_code == 409
    assert "Archive" in response.json()["detail"]

    assert act(school.teacher, used["id"], "archive").json()["status"] == "archived"
    assert school.teacher.client.get(D).json()["documents"] == []
    archived = school.teacher.client.get(D, params={"status": "archived"}).json()["documents"]
    assert [d["id"] for d in archived] == [used["id"]]
    response = school.teacher.client.post(
        f"{D}/{used['id']}/versions",
        files={"file": ("v2.pdf", CLEAN_PDF, "application/pdf")},
        headers=school.teacher.headers,
    )
    assert response.status_code == 409
    assert act(school.teacher, used["id"], "restore").json()["status"] == "active"


def test_title_and_description_can_change(school) -> None:
    created = uploaded(school.teacher, school.science)

    response = school.teacher.client.patch(
        f"{D}/{created['id']}",
        json={"title": "  Week 1 notes ", "description": "Synthetic"},
        headers=school.teacher.headers,
    )
    assert (response.json()["title"], response.json()["description"]) == (
        "Week 1 notes",
        "Synthetic",
    )
    response = school.teacher.client.patch(
        f"{D}/{created['id']}", json={"title": None}, headers=school.teacher.headers
    )
    assert response.status_code == 422


# --- The processing queue -----------------------------------------------------------------------


def test_in_worker_mode_uploads_wait_for_the_worker(
    school, storage, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "document_processing", "worker")
    created = uploaded(school.teacher, school.science)
    assert get(school.teacher, created["id"])["latest"]["status"] == "queued"

    assert process_queued(db, storage) == 1
    assert get(school.teacher, created["id"])["latest"]["status"] == "extracted"
    assert process_queued(db, storage) == 0


def test_a_version_is_only_claimed_once(school, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "document_processing", "worker")
    uploaded(school.teacher, school.science)
    version_id = db.scalar(select(DocumentVersion.id))

    assert claim(db, version_id) is True
    assert claim(db, version_id) is False


def test_abandoned_processing_is_retried_then_given_up(school, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "document_processing", "worker")
    uploaded(school.teacher, school.science)
    version_id = db.scalar(select(DocumentVersion.id))
    long_ago = now() - timedelta(hours=1)

    claim(db, version_id)
    db.execute(update(DocumentVersion).values(processing_started_at=long_ago))
    db.commit()
    assert recover_stuck(db) == 1
    db.expire_all()
    assert db.get(DocumentVersion, version_id).status == "queued"

    db.execute(
        update(DocumentVersion).values(
            status="processing", processing_started_at=long_ago, attempts=MAX_ATTEMPTS
        )
    )
    db.commit()
    assert recover_stuck(db) == 0
    db.expire_all()
    version = db.get(DocumentVersion, version_id)
    assert version.status == "failed"
    assert "couldn't read" in version.error


# --- The database keeps files and extracted text as they were ------------------------------------


def test_a_versions_file_and_extracted_text_never_change(school, db: Session) -> None:
    uploaded(school.teacher, school.science)
    version = db.scalar(select(DocumentVersion))
    segment = db.scalar(select(DocumentSegment))

    version.sha256 = "0" * 64
    with pytest.raises(ValueError, match="can't be changed"):
        db.flush()
    db.rollback()

    segment.text = "Something else"
    with pytest.raises(ValueError, match="can't be changed"):
        db.flush()
    db.rollback()

    # Review state does change.
    version = db.scalar(select(DocumentVersion))
    version.review_note = "Checked"
    db.flush()
