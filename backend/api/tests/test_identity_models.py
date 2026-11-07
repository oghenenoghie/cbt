"""Integrity rules for school users, platform admins, sessions and candidates.

Most rules are enforced by the database (unique and composite foreign keys, a check constraint),
so these tests commit rows and expect IntegrityError. They run on SQLite with foreign keys
enabled and, in CI, on PostgreSQL.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AuthSession,
    Candidate,
    CandidateExternalIdentity,
    PlatformAdmin,
    Tenant,
    User,
)
from app.models.identity import SCHOOL_ROLES


def assert_rejected(db: Session, *rows: object) -> None:
    db.add_all(rows)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def token_hash() -> str:
    return hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest()


def expires() -> datetime:
    return datetime.now(UTC) + timedelta(hours=8)


def count(db: Session, model: type, tenant: Tenant) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant.id))


def make_platform_admin(db: Session, email: str = "ops@platform.example") -> PlatformAdmin:
    admin = PlatformAdmin(email=email, display_name="Synthetic Admin")
    db.add(admin)
    db.commit()
    return admin


# --- School users ----------------------------------------------------------------------


def test_username_is_normalized_and_unique_within_a_school(db: Session, make_user) -> None:
    user = make_user(username="  Ada.Obi ")
    assert user.username == "ada.obi"

    # Case and whitespace don't make a different username.
    assert_rejected(
        db,
        User(tenant_id=user.tenant_id, username="ADA.OBI", display_name="Other", role="student"),
    )


def test_same_username_is_allowed_in_different_schools(make_user, make_tenant) -> None:
    first = make_user(tenant=make_tenant(), username="ada.obi")
    second = make_user(tenant=make_tenant(), username="ada.obi")

    assert first.tenant_id != second.tenant_id


@pytest.mark.parametrize("username", ["", "   ", "has space", "semi;colon", "x" * 101])
def test_invalid_usernames_are_rejected(username: str) -> None:
    with pytest.raises(ValueError):
        User(tenant_id="t", username=username, display_name="X", role="student")


@pytest.mark.parametrize("role", sorted(SCHOOL_ROLES))
def test_school_roles_are_accepted(make_user, role: str) -> None:
    assert make_user(role=role).role == role


@pytest.mark.parametrize("role", ["platform_admin", "admin", "Teacher", ""])
def test_unknown_roles_are_rejected(role: str) -> None:
    with pytest.raises(ValueError):
        User(tenant_id="t", username="someone", display_name="X", role=role)


# --- Platform admins ---------------------------------------------------------------------


def test_platform_admin_email_is_normalized_and_unique(db: Session) -> None:
    admin = make_platform_admin(db, email=" Ops@Platform.Example ")
    assert admin.email == "ops@platform.example"

    assert_rejected(db, PlatformAdmin(email="OPS@platform.example", display_name="Duplicate"))


def test_platform_admin_needs_an_email_address() -> None:
    with pytest.raises(ValueError):
        PlatformAdmin(email="not-an-email", display_name="X")


# --- Candidates ---------------------------------------------------------------------------


def test_candidate_can_be_linked_to_a_student_at_the_same_school(make_user, make_candidate) -> None:
    student = make_user(role="student")

    candidate = make_candidate(user=student)

    assert candidate.tenant_id == student.tenant_id
    assert candidate.user_id == student.id


def test_candidate_cannot_be_linked_to_a_user_at_another_school(
    db: Session, make_user, make_tenant
) -> None:
    other_school_student = make_user(role="student")
    school = make_tenant()

    assert_rejected(
        db,
        Candidate(tenant_id=school.id, user_id=other_school_student.id, display_name="X"),
    )


def test_a_user_is_linked_to_at_most_one_candidate(db: Session, make_user, make_candidate) -> None:
    student = make_user(role="student")
    make_candidate(user=student)

    assert_rejected(
        db, Candidate(tenant_id=student.tenant_id, user_id=student.id, display_name="Second")
    )


def test_candidates_without_accounts_do_not_conflict(make_candidate, make_tenant) -> None:
    school = make_tenant()

    first = make_candidate(tenant=school)
    second = make_candidate(tenant=school)

    assert first.user_id is None and second.user_id is None


# --- Candidate external identities -----------------------------------------------------------


def external_id(candidate: Candidate, system: str = "sis", value: str = "student-00981"):
    return CandidateExternalIdentity(
        tenant_id=candidate.tenant_id,
        candidate_id=candidate.id,
        external_system_id=system,
        external_id=value,
    )


def test_external_ids_are_unique_per_school_and_source_system(
    db: Session, make_candidate, make_tenant
) -> None:
    school = make_tenant()
    first, second = make_candidate(tenant=school), make_candidate(tenant=school)
    db.add(external_id(first, "sis", "student-00981"))
    db.commit()

    # The same school can't reuse that SIS ID for another candidate...
    assert_rejected(db, external_id(second, "sis", "student-00981"))

    # ...but another source system, or another school, may use the same value.
    db.add(external_id(second, "lms", "student-00981"))
    db.add(external_id(make_candidate(), "sis", "student-00981"))
    db.commit()


def test_a_candidate_has_one_id_per_source_system(db: Session, make_candidate) -> None:
    candidate = make_candidate()
    db.add(external_id(candidate, "sis", "a-1"))
    db.commit()

    assert_rejected(db, external_id(candidate, "sis", "a-2"))


def test_external_id_cannot_point_to_another_schools_candidate(
    db: Session, make_candidate, make_tenant
) -> None:
    other_school_candidate = make_candidate()
    school = make_tenant()

    assert_rejected(
        db,
        CandidateExternalIdentity(
            tenant_id=school.id,
            candidate_id=other_school_candidate.id,
            external_system_id="sis",
            external_id="x-1",
        ),
    )


# --- Login sessions ----------------------------------------------------------------------


def test_sessions_for_school_users_and_platform_admins(db: Session, make_user) -> None:
    user = make_user()
    admin = make_platform_admin(db)

    db.add_all(
        [
            AuthSession(
                token_hash=token_hash(),
                tenant_id=user.tenant_id,
                user_id=user.id,
                expires_at=expires(),
            ),
            AuthSession(token_hash=token_hash(), platform_admin_id=admin.id, expires_at=expires()),
        ]
    )
    db.commit()


def test_a_session_cannot_claim_a_different_school_than_its_user(
    db: Session, make_user, make_tenant
) -> None:
    user = make_user()
    other_school = make_tenant()

    assert_rejected(
        db,
        AuthSession(
            token_hash=token_hash(),
            tenant_id=other_school.id,
            user_id=user.id,
            expires_at=expires(),
        ),
    )


@pytest.mark.parametrize(
    "principal",
    ["user_and_admin", "neither", "user_without_school", "admin_with_school"],
)
def test_a_session_has_exactly_one_principal(db: Session, make_user, principal: str) -> None:
    user = make_user()
    admin = make_platform_admin(db)
    fields = {
        "user_and_admin": {
            "tenant_id": user.tenant_id,
            "user_id": user.id,
            "platform_admin_id": admin.id,
        },
        "neither": {},
        "user_without_school": {"user_id": user.id},
        "admin_with_school": {"tenant_id": user.tenant_id, "platform_admin_id": admin.id},
    }[principal]

    assert_rejected(db, AuthSession(token_hash=token_hash(), expires_at=expires(), **fields))


def test_session_token_hashes_are_unique(db: Session, make_user) -> None:
    user = make_user()
    shared = token_hash()
    db.add(
        AuthSession(
            token_hash=shared, tenant_id=user.tenant_id, user_id=user.id, expires_at=expires()
        )
    )
    db.commit()

    assert_rejected(
        db,
        AuthSession(
            token_hash=shared, tenant_id=user.tenant_id, user_id=user.id, expires_at=expires()
        ),
    )


# --- Deletion ----------------------------------------------------------------------------


def test_deleting_a_school_removes_only_that_schools_identity_data(
    db: Session, make_tenant, make_user, make_candidate
) -> None:
    def populate(school: Tenant) -> None:
        student = make_user(tenant=school, role="student")
        candidate = make_candidate(user=student)
        db.add(external_id(candidate))
        db.add(
            AuthSession(
                token_hash=token_hash(),
                tenant_id=school.id,
                user_id=student.id,
                expires_at=expires(),
            )
        )
        db.commit()

    doomed, kept = make_tenant(), make_tenant()
    populate(doomed)
    populate(kept)

    db.delete(doomed)
    db.commit()
    db.expire_all()

    for model in (User, Candidate, CandidateExternalIdentity, AuthSession):
        assert count(db, model, doomed) == 0, model.__name__
        assert count(db, model, kept) == 1, model.__name__


def test_deleting_a_linked_user_is_refused_until_the_candidate_is_unlinked(
    db: Session, make_user, make_candidate
) -> None:
    student = make_user(role="student")
    candidate = make_candidate(user=student)
    db.add(
        AuthSession(
            token_hash=token_hash(),
            tenant_id=student.tenant_id,
            user_id=student.id,
            expires_at=expires(),
        )
    )
    db.commit()

    db.delete(student)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    candidate.user_id = None
    db.commit()
    db.delete(student)
    db.commit()

    # The candidate (and its exam history, later) survives; the user's sessions go with them.
    assert db.get(Candidate, candidate.id) is not None
    assert count(db, AuthSession, db.get(Tenant, candidate.tenant_id)) == 0
