"""Command-line tools for creating the first accounts, before any admin screens exist.

    python -m app.cli create-school-admin --school-code greenfield \\
        --school-name "Greenfield College" --username admin --display-name "School Admin"
    python -m app.cli create-platform-admin --email ops@example.com --display-name "Platform Ops"

Passwords are prompted for, never passed as arguments (which would land in shell history), and
must meet the staff password policy. Uses DATABASE_URL, like the API. `--school-name` creates
the school if the code doesn't exist yet.
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.passwords import PasswordPolicyError, hash_password, validate_new_password
from app.models import PlatformAdmin, Tenant, User
from app.models.identity import normalize_email, normalize_username
from app.models.tenant import normalize_school_code


class CliError(Exception):
    """A problem with the command's input, reported without a traceback."""


def create_school_admin(
    db: Session,
    *,
    school_code: str,
    school_name: str | None,
    username: str,
    display_name: str,
    password: str,
) -> User:
    code = normalize_school_code(school_code)
    username = normalize_username(username)
    validate_new_password(password, staff=True, context=(username, code))

    tenant = db.scalar(select(Tenant).where(Tenant.slug == code))
    if tenant is None:
        if not school_name:
            raise CliError(f"No school has the code {code!r}. Pass --school-name to create it.")
        tenant = Tenant(name=school_name, slug=code)
        db.add(tenant)
        db.flush()
        record_audit(
            db,
            tenant_id=tenant.id,
            actor_type="system",
            actor_id="cli",
            action="tenant.created",
            resource_type="tenant",
            resource_id=tenant.id,
        )
    elif db.scalar(select(User).where(User.tenant_id == tenant.id, User.username == username)):
        raise CliError(f"School {code!r} already has a user named {username!r}.")

    user = User(
        tenant_id=tenant.id,
        username=username,
        display_name=display_name,
        role="school_admin",
        password_hash=hash_password(password),
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="system",
        actor_id="cli",
        action="user.created",
        resource_type="user",
        resource_id=user.id,
        details={"role": "school_admin"},
    )
    db.commit()
    return user


def create_platform_admin(
    db: Session, *, email: str, display_name: str, password: str
) -> PlatformAdmin:
    email = normalize_email(email)
    validate_new_password(password, staff=True, context=(email.split("@")[0],))
    if db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email)):
        raise CliError(f"A platform admin with email {email!r} already exists.")

    admin = PlatformAdmin(
        email=email, display_name=display_name, password_hash=hash_password(password)
    )
    db.add(admin)
    db.flush()
    record_audit(
        db,
        tenant_id=None,
        actor_type="system",
        actor_id="cli",
        action="platform_admin.created",
        resource_type="platform_admin",
        resource_id=admin.id,
    )
    db.commit()
    return admin


def _prompt_password() -> str:
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise CliError("The passwords don't match.")
    return first


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    school = commands.add_parser("create-school-admin", help="Create a school administrator.")
    school.add_argument("--school-code", required=True)
    school.add_argument("--school-name", help="Creates the school if the code doesn't exist.")
    school.add_argument("--username", required=True)
    school.add_argument("--display-name", required=True)

    admin = commands.add_parser("create-platform-admin", help="Create a platform administrator.")
    admin.add_argument("--email", required=True)
    admin.add_argument("--display-name", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    read_password: Callable[[], str] = _prompt_password,
) -> int:
    args = _parser().parse_args(argv)
    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal
    try:
        password = read_password()
        with session_factory() as db:
            if args.command == "create-school-admin":
                user = create_school_admin(
                    db,
                    school_code=args.school_code,
                    school_name=args.school_name,
                    username=args.username,
                    display_name=args.display_name,
                    password=password,
                )
                print(f"Created school admin {user.username!r} (user id {user.id}).")
            else:
                admin = create_platform_admin(
                    db, email=args.email, display_name=args.display_name, password=password
                )
                print(f"Created platform admin {admin.email!r} (id {admin.id}).")
    except (CliError, PasswordPolicyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
