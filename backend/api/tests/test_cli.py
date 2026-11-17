import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.cli
from app.cli import main
from app.models import AuditLog, PlatformAdmin, Tenant, User

STRONG = "Kettle-Orchard-17"
SCHOOL_ADMIN = (
    "create-school-admin",
    "--school-code",
    "Greenfield",
    "--school-name",
    "Greenfield College",
    "--username",
    "Head.Admin",
    "--display-name",
    "Head Admin",
)


def run(session_factory, *args: str, password: str = STRONG) -> int:
    return main(list(args), session_factory=session_factory, read_password=lambda: password)


def test_signing_key_fingerprint_command_does_not_need_a_database(monkeypatch, capsys) -> None:
    from app.offline import crypto

    fingerprint = "ab" * 32
    monkeypatch.setattr(crypto, "signing_key_fingerprint", lambda: fingerprint)

    assert main(["signing-key-fingerprint"]) == 0
    assert capsys.readouterr().out.strip() == f"SHA-256 public-key fingerprint: {fingerprint}"



def test_signing_public_key_command_does_not_need_a_database(monkeypatch, capsys) -> None:
    from app.offline import crypto

    public_key = "AA==" * 16
    monkeypatch.setattr(crypto, "signing_public_key", lambda: public_key)

    assert main(["signing-public-key"]) == 0
    assert capsys.readouterr().out.strip() == public_key


def test_generate_trust_root_cli_prompts_for_passphrase_without_database(
    tmp_path, monkeypatch, capsys
) -> None:
    answers = iter(["offline-root-passphrase-2026", "offline-root-passphrase-2026"])
    monkeypatch.setattr(app.cli.getpass, "getpass", lambda prompt: next(answers))
    private_file = tmp_path / "root-private.pem"
    public_file = tmp_path / "root-public.txt"

    assert main([
        "generate-trust-root",
        "--private-key-file", str(private_file),
        "--public-key-file", str(public_file),
    ]) == 0

    output = capsys.readouterr().out
    assert "Created encrypted Ed25519 root private key" in output
    assert "SHA-256 fingerprint:" in output
    assert private_file.exists() and public_file.exists()

def test_school_admin_can_be_created_and_then_log_in(
    client: TestClient, db: Session, session_factory, capsys
) -> None:
    assert run(session_factory, *SCHOOL_ADMIN) == 0
    assert "Created school admin 'head.admin'" in capsys.readouterr().out

    school = db.scalar(select(Tenant).where(Tenant.slug == "greenfield"))
    admin = db.scalar(select(User).where(User.tenant_id == school.id))
    assert (school.name, admin.username, admin.role) == (
        "Greenfield College",
        "head.admin",
        "school_admin",
    )
    assert admin.password_hash.startswith("$argon2id$") and STRONG not in admin.password_hash
    assert {e.action for e in db.scalars(select(AuditLog))} == {"tenant.created", "user.created"}

    response = client.post(
        "/api/v1/auth/login",
        json={"school_code": "greenfield", "username": "head.admin", "password": STRONG},
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "school_admin"


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short-pass", "at least 12"),
        ("password1234", "too easy to guess"),
        ("head.admin-rules", "username or school code"),
    ],
)
def test_weak_passwords_are_refused_and_nothing_is_created(
    db: Session, session_factory, capsys, password: str, message: str
) -> None:
    assert run(session_factory, *SCHOOL_ADMIN, password=password) == 1

    assert message in capsys.readouterr().err
    assert db.scalars(select(Tenant)).first() is None
    assert db.scalars(select(User)).first() is None


def test_an_unknown_school_code_needs_a_school_name(db: Session, session_factory, capsys) -> None:
    args = (
        "create-school-admin",
        "--school-code",
        "newschool",
        "--username",
        "admin",
        "--display-name",
        "Admin",
    )

    assert run(session_factory, *args) == 1
    assert "Pass --school-name" in capsys.readouterr().err


def test_a_taken_username_is_refused(db: Session, session_factory, capsys) -> None:
    assert run(session_factory, *SCHOOL_ADMIN) == 0

    assert run(session_factory, *SCHOOL_ADMIN) == 1
    assert "already has a user named 'head.admin'" in capsys.readouterr().err


def test_an_invalid_school_code_is_refused(db: Session, session_factory, capsys) -> None:
    args = (
        "create-school-admin",
        "--school-code",
        "bad code!",
        "--school-name",
        "X",
        "--username",
        "admin",
        "--display-name",
        "Admin",
    )

    assert run(session_factory, *args) == 1
    assert "School codes may contain only" in capsys.readouterr().err


def test_platform_admin_can_be_created_and_then_log_in(
    client: TestClient, db: Session, session_factory
) -> None:
    args = ("create-platform-admin", "--email", "Ops@Platform.Example", "--display-name", "Ops")

    assert run(session_factory, *args) == 0

    assert db.scalar(select(PlatformAdmin)).email == "ops@platform.example"
    audit = db.scalar(select(AuditLog))
    assert (audit.action, audit.tenant_id) == ("platform_admin.created", None)
    response = client.post(
        "/api/v1/auth/platform-admin/login",
        json={"email": "ops@platform.example", "password": STRONG},
    )
    assert response.status_code == 200


def test_mismatched_password_prompts_are_refused(
    db: Session, session_factory, capsys, monkeypatch
) -> None:
    answers = iter([STRONG, STRONG + "x"])
    monkeypatch.setattr(app.cli.getpass, "getpass", lambda prompt: next(answers))

    assert main(list(SCHOOL_ADMIN), session_factory=session_factory) == 1
    assert "don't match" in capsys.readouterr().err
    assert db.scalars(select(Tenant)).first() is None
