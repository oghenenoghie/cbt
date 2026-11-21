"""The school profile and logo (ADR 0002 decision 12): who reads and changes it, the checks on
each field, and how an uploaded logo is cleaned before anyone else sees it."""

import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Tenant

P = "/api/v1/school/profile"
TEST_PASSWORD = "correct horse battery staple"  # what make_user(password=...) is given below


def picture(fmt="PNG", size=(800, 400), mode="RGBA", **save) -> bytes:
    image = Image.new(mode, size, (20, 90, 200, 128) if mode == "RGBA" else (20, 90, 200))
    out = BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def png_claiming(width: int, height: int) -> bytes:
    """A small, valid PNG whose header claims a very large black-and-white picture."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + b"\x00" * ((width + 7) // 8)
    pixels = zlib.compress(row * height, 9)
    header = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixels)
        + chunk(b"IEND", b"")
    )


def upload(who, data: bytes, name="logo.png", kind="image/png"):
    return who.client.put(
        f"{P}/logo", files={"file": (name, data, kind)}, headers=who.headers
    )


@pytest.fixture
def people(admin, make_user, sign_in):
    tenant = admin.school
    make_user(tenant=tenant, username="mrs.okafor", role="teacher", password=TEST_PASSWORD)
    make_user(tenant=tenant, username="amy", role="student", password=TEST_PASSWORD)
    return admin, sign_in(tenant, "mrs.okafor"), sign_in(tenant, "amy")


def test_every_member_of_the_school_reads_the_profile(people, client) -> None:
    admin, teacher, student = people
    for who in people:
        response = who.client.get(P)
        assert response.status_code == 200
        assert response.json() == {
            "name": admin.school.name,
            "code": admin.school.slug,
            "address": None,
            "phone": None,
            "email": None,
            "motto": None,
            "logo_url": None,
        }
    assert client.get(P).status_code == 401


def test_a_school_admin_edits_the_profile(people, db: Session) -> None:
    admin, teacher, student = people
    body = {
        "name": "  Greenfield Synthetic College ",
        "address": "1 Example Road\nSampletown",
        "phone": "+234 800 000 0000",
        "email": "Office@Greenfield.Example",
        "motto": "Learning by example",
    }
    response = admin.client.patch(P, json=body, headers=admin.headers)
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["name"] == "Greenfield Synthetic College"
    assert profile["address"] == "1 Example Road\nSampletown"
    assert profile["email"] == "office@greenfield.example"
    assert profile["code"] == admin.school.slug
    # Everyone sees the new name, including in who is signed in.
    assert student.client.get("/api/v1/auth/me").json()["school"]["name"] == (
        "Greenfield Synthetic College"
    )

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "school.profile_updated"))
    assert entry.resource_type == "school" and entry.resource_id == admin.school.id
    assert entry.details["fields"] == ["address", "email", "motto", "name", "phone"]
    assert entry.details["name"] == "Greenfield Synthetic College"

    # An empty string or null clears an optional field; omitted fields stay.
    cleared = admin.client.patch(P, json={"motto": "", "phone": None}, headers=admin.headers)
    assert cleared.json()["motto"] is None and cleared.json()["phone"] is None
    assert cleared.json()["email"] == "office@greenfield.example"


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": None},
        {"code": "another-code"},
        {"email": "not an email"},
        {"email": "office@localhost"},
        {"phone": "call the office"},
        {"phone": "12"},
        {"motto": "x" * 201},
        {"address": "x" * 501},
    ],
)
def test_profile_fields_are_checked(people, body) -> None:
    admin, _, _ = people
    response = admin.client.patch(P, json=body, headers=admin.headers)
    assert response.status_code == 422, body


def test_only_school_admins_change_the_profile(people) -> None:
    admin, teacher, student = people
    for who in (teacher, student):
        assert who.client.patch(P, json={"motto": "Mine"}, headers=who.headers).status_code == 403
        assert upload(who, picture()).status_code == 403
        assert who.client.delete(f"{P}/logo", headers=who.headers).status_code == 403
    # Changes need the CSRF token.
    assert admin.client.patch(P, json={"motto": "Mine"}).status_code == 403


def test_uploading_a_logo(people, db: Session, storage) -> None:
    admin, teacher, student = people
    response = upload(admin, picture(size=(1200, 600)))
    assert response.status_code == 200, response.text
    url = response.json()["logo_url"]
    assert url.startswith(f"{P}/logo?v=")
    assert student.client.get("/api/v1/auth/me").json()["school"]["logo_url"] == url

    served = student.client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-security-policy"] == "default-src 'none'"
    image = Image.open(BytesIO(served.content))
    assert image.format == "PNG"
    assert image.size == (512, 256)
    assert image.mode == "RGBA"  # transparency is kept

    db.expire_all()
    first_key = db.get(Tenant, admin.school.id).logo_key
    assert first_key.startswith(f"{admin.school.id}/school/logo-")
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "school.logo_updated"))
    assert entry.details["replaced"] is False

    # Replacing it gives a new URL and removes the old file.
    replaced = upload(admin, picture("JPEG", size=(300, 300), mode="RGB"), "logo.jpg", "image/jpeg")
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["logo_url"] != url
    with pytest.raises(FileNotFoundError):
        storage.get(first_key)
    image = Image.open(BytesIO(teacher.client.get(replaced.json()["logo_url"]).content))
    assert (image.format, image.size, image.mode) == ("PNG", (300, 300), "RGB")


def test_a_logos_hidden_metadata_is_dropped(people) -> None:
    """A phone photo carries EXIF data (here a made-up camera and a rotation); none is kept."""
    admin, _, student = people
    exif = Image.Exif()
    exif[0x0110] = "Synthetic Camera"  # Model
    exif[0x0112] = 6  # Orientation: rotate 90 degrees to display
    photo = picture("JPEG", size=(400, 200), mode="RGB", exif=exif.tobytes(), comment=b"secret")
    assert upload(admin, photo, "photo.jpg", "image/jpeg").status_code == 200
    url = student.client.get(P).json()["logo_url"]
    served = student.client.get(url).content
    image = Image.open(BytesIO(served))
    assert image.size == (200, 400)  # the rotation was applied, then dropped
    assert not image.getexif()
    assert "exif" not in image.info and "comment" not in image.info
    assert b"Synthetic Camera" not in served and b"secret" not in served


@pytest.mark.parametrize(
    "data, message",
    [
        (b"", "The file is empty."),
        (b"just some text, not a picture", "This picture looks damaged and couldn't be opened. Upload a PNG or JPEG."),
        (picture("GIF", mode="RGB"), "Upload the logo as a PNG or JPEG picture."),
        (picture()[:200], "This picture looks damaged and couldn't be opened. Upload a PNG or JPEG."),
        (png_claiming(6000, 5000), "This picture is larger than 25 million pixels. Make it smaller and upload it again."),
    ],
)
def test_unusable_logos_are_refused(people, db: Session, data, message) -> None:
    admin, _, _ = people
    response = upload(admin, data)
    assert response.status_code == 422
    assert response.json()["detail"] == message
    db.expire_all()
    assert db.get(Tenant, admin.school.id).logo_key is None


def test_a_logo_over_2_mb_is_refused(people) -> None:
    admin, _, _ = people
    response = upload(admin, b"\x89PNG" + b"\x00" * (2 * 1024 * 1024))
    assert response.status_code == 413
    assert response.json()["detail"] == "The logo is larger than 2 MB."


def test_removing_the_logo(people, db: Session, storage) -> None:
    admin, _, student = people
    url = upload(admin, picture()).json()["logo_url"]
    db.expire_all()
    key = db.get(Tenant, admin.school.id).logo_key
    response = admin.client.delete(f"{P}/logo", headers=admin.headers)
    assert response.status_code == 200
    assert response.json()["logo_url"] is None
    assert student.client.get(url).status_code == 404
    with pytest.raises(FileNotFoundError):
        storage.get(key)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "school.logo_removed")) is not None
    # Removing it again changes nothing.
    assert admin.client.delete(f"{P}/logo", headers=admin.headers).status_code == 200


def test_each_school_sees_only_its_own_profile_and_logo(
    people, make_tenant, make_user, sign_in
) -> None:
    admin, _, _ = people
    url = upload(admin, picture()).json()["logo_url"]
    admin.client.patch(P, json={"motto": "Ours"}, headers=admin.headers)

    other = make_tenant()
    make_user(tenant=other, username="ben", role="student", password=TEST_PASSWORD)
    elsewhere = sign_in(other, "ben")
    # The logo URL carries no school: it is always the signed-in person's own school's.
    assert elsewhere.client.get(url).status_code == 404
    profile = elsewhere.client.get(P).json()
    assert profile["name"] == other.name and profile["motto"] is None
