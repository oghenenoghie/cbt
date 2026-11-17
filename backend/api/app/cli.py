"""Command-line tools for creating the first accounts, before any admin screens exist.

    python -m app.cli create-school-admin --school-code greenfield \\
        --school-name "Greenfield College" --username admin --display-name "School Admin"
    python -m app.cli create-platform-admin --email ops@example.com --display-name "Platform Ops"
    python -m app.cli publish-lab-app Intelligent-CBT-Lab-Setup-0.2.0.exe --version 0.2.0

Passwords are prompted for, never passed as arguments (which would land in shell history), and
must meet the staff password policy. Uses DATABASE_URL, like the API. `--school-name` creates
the school if the code doesn't exist yet.
"""

import argparse
import json
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

    commands.add_parser(
        "generate-signing-key",
        help="Print a new key for signing offline exam packages (OFFLINE_SIGNING_KEY).",
    )
    commands.add_parser(
        "signing-key-fingerprint",
        help="Print the SHA-256 fingerprint of the configured offline signing public key.",
    )
    commands.add_parser(
        "signing-public-key",
        help="Print the configured operational signing public key in base64 (public information).",
    )

    root = commands.add_parser(
        "generate-trust-root",
        help="Generate an encrypted Ed25519 root key pair on an offline operator workstation.",
    )
    root.add_argument("--private-key-file", required=True, help="Encrypted PEM output; keep it offline.")
    root.add_argument("--public-key-file", required=True, help="Base64 public-key output; safe to distribute.")

    template = commands.add_parser(
        "create-trust-set-template",
        help="Create an unsigned trust-set document from operational public-key metadata.",
    )
    template.add_argument("--keys-file", required=True, help="JSON array of public operational-key entries.")
    template.add_argument("--generation", type=int, required=True)
    template.add_argument("--expires-in-days", type=int, default=30)
    template.add_argument("--minimum-client-version")
    template.add_argument("--output-file", required=True)

    sign = commands.add_parser(
        "sign-trust-set",
        help="Sign and export a trust-set document with the encrypted offline root key.",
    )
    sign.add_argument("--document-file", required=True)
    sign.add_argument("--root-private-key-file", required=True)
    sign.add_argument("--output-file", required=True)

    verify = commands.add_parser(
        "verify-trust-set",
        help="Verify a signed trust-set export using the root public key.",
    )
    verify.add_argument("--envelope-file", required=True)
    verify.add_argument("--root-public-key-file", required=True)

    release = commands.add_parser(
        "publish-lab-app",
        help="Publish a lab app installer to this server's lab computers (ADR 0007, decision 10).",
    )
    release.add_argument("installer", help="The installer (.exe) built by CI.")
    release.add_argument("--version", required=True, help="Its version, for example 0.2.0.")
    release.add_argument("--notes", help="What changed, shown to staff on lab computers.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    read_password: Callable[[], str] = _prompt_password,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "generate-signing-key":
        from app.offline.crypto import new_signing_seed

        # Kept secret, like a password: lab computers trust packages signed with it (ADR 0007).
        print(new_signing_seed())
        return 0
    if args.command == "signing-key-fingerprint":
        from app.offline.crypto import SigningNotConfigured, signing_key_fingerprint

        try:
            fingerprint = signing_key_fingerprint()
        except SigningNotConfigured as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"SHA-256 public-key fingerprint: {fingerprint}")
        return 0

    if args.command == "signing-public-key":
        from app.offline.crypto import SigningNotConfigured, signing_public_key

        try:
            print(signing_public_key())
        except SigningNotConfigured as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command in {
        "generate-trust-root",
        "create-trust-set-template",
        "sign-trust-set",
        "verify-trust-set",
    }:
        from pathlib import Path

        from app.offline.root_tools import (
            RootKeyToolError,
            create_trust_set_template,
            generate_root_key,
            sign_trust_set_file,
            verify_trust_set_file,
        )

        try:
            if args.command == "generate-trust-root":
                first = getpass.getpass("Root-key passphrase (at least 16 characters): ")
                if getpass.getpass("Repeat root-key passphrase: ") != first:
                    raise RootKeyToolError("The passphrases do not match.")
                public_key, fingerprint = generate_root_key(
                    Path(args.private_key_file),
                    Path(args.public_key_file),
                    first.encode("utf-8"),
                )
                print(f"Created encrypted Ed25519 root private key: {args.private_key_file}")
                print(f"Created root public key: {args.public_key_file}")
                print(f"Root public key (base64): {public_key}")
                print(f"SHA-256 fingerprint: {fingerprint}")
            elif args.command == "create-trust-set-template":
                document = create_trust_set_template(
                    Path(args.keys_file),
                    Path(args.output_file),
                    generation=args.generation,
                    expires_in_days=args.expires_in_days,
                    minimum_client_version=args.minimum_client_version,
                )
                print(
                    f"Created unsigned trust-set generation {document['generation']} "
                    f"with {len(document['keys'])} operational key(s): {args.output_file}"
                )
            elif args.command == "sign-trust-set":
                passphrase = getpass.getpass("Root-key passphrase: ").encode("utf-8")
                envelope = sign_trust_set_file(
                    Path(args.document_file),
                    Path(args.root_private_key_file),
                    Path(args.output_file),
                    passphrase,
                )
                print(
                    f"Signed trust-set generation {json.loads(envelope['body'])['generation']} "
                    f"using {envelope['format']}: {args.output_file}"
                )
            else:
                document = verify_trust_set_file(
                    Path(args.envelope_file),
                    Path(args.root_public_key_file),
                )
                print(
                    f"Valid {args.envelope_file}: generation {document['generation']}, "
                    f"{len(document['keys'])} operational key(s), expires {document['expires_at']}."
                )
        except (RootKeyToolError, OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "publish-lab-app":
        from pathlib import Path

        from app.offline.crypto import SigningNotConfigured
        from app.offline.releases import ReleaseError, publish, release_dir

        try:
            body = publish(Path(args.installer), args.version, args.notes)
        except (ReleaseError, SigningNotConfigured) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Published lab app {body['version']} ({body['size']} bytes) in {release_dir()}.")
        return 0
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
