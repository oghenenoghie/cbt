import os
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.api_keys import generate_api_key
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ApiCredential, Integration, IntegrationScope, Tenant


@dataclass
class IssuedCredential:
    """A stored credential plus the raw key, which is only known at creation time."""

    raw_key: str
    tenant: Tenant
    integration: Integration
    credential: ApiCredential


# Set TEST_DATABASE_URL (e.g. postgresql+psycopg://cbt:...@localhost:5432/cbt_test) to run the
# suite against PostgreSQL instead of a throwaway SQLite file.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def pytest_configure(config: pytest.Config) -> None:
    # Tests drop every table they create, so refuse anything that could be a real database.
    if TEST_DATABASE_URL:
        database = make_url(TEST_DATABASE_URL).database or ""
        if not database.endswith("_test"):
            raise pytest.UsageError(
                f"TEST_DATABASE_URL must name a database ending in '_test' (got {database!r}): "
                "the test suite drops all application tables in it."
            )


def _empty_database(engine: Engine) -> None:
    """Drop the application tables and any Alembic stamp, leaving the database empty.

    Dropping alembic_version too matters: a stamp left without its tables would make a later
    `alembic upgrade head` believe the schema already exists.
    """
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def session_factory(tmp_path: Path) -> Generator[sessionmaker[Session], None, None]:
    """Empty application tables per test, never on a developer's working database.

    Default: a fresh SQLite file under tmp_path. With TEST_DATABASE_URL: the given PostgreSQL
    database, emptied before (in case an earlier run was interrupted) and after each test.
    """
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        _empty_database(engine)
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'test.db'}",
            connect_args={"check_same_thread": False},
        )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _empty_database(engine)
    engine.dispose()


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Session for arranging test data and inspecting results."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    """Test client whose requests each get their own session on the test database."""

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_tenant(db: Session) -> Callable[..., Tenant]:
    def _make_tenant(*, status: str = "active") -> Tenant:
        suffix = uuid4().hex[:8]
        tenant = Tenant(name=f"School {suffix}", slug=f"school-{suffix}", status=status)
        db.add(tenant)
        db.commit()
        return tenant

    return _make_tenant


@pytest.fixture
def make_credential(
    db: Session, make_tenant: Callable[..., Tenant]
) -> Callable[..., IssuedCredential]:
    def _make_credential(
        *,
        tenant: Tenant | None = None,
        granted_scopes: Iterable[str] = ("candidates:read",),
        denied_scopes: Iterable[str] = (),
        expires_at: datetime | None = None,
    ) -> IssuedCredential:
        tenant = tenant or make_tenant()
        integration = Integration(tenant_id=tenant.id, name="School portal", redirect_uris=[])
        db.add(integration)
        db.flush()

        for scope in granted_scopes:
            db.add(IntegrationScope(integration_id=integration.id, scope=scope, granted=True))
        for scope in denied_scopes:
            db.add(IntegrationScope(integration_id=integration.id, scope=scope, granted=False))

        raw_key, prefix, digest = generate_api_key()
        credential = ApiCredential(
            tenant_id=tenant.id,
            integration_id=integration.id,
            name="Server key",
            key_prefix=prefix,
            secret_hash=digest,
            expires_at=expires_at,
        )
        db.add(credential)
        db.commit()
        return IssuedCredential(
            raw_key=raw_key, tenant=tenant, integration=integration, credential=credential
        )

    return _make_credential
