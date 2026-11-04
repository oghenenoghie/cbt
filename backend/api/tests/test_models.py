from sqlalchemy import create_engine

from app.db.base import Base
from app.models import ApiCredential, AuditLog, Integration, IntegrationScope, Tenant


def test_tenant_and_integration_tables_create_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    assert {"tenants", "integrations", "api_credentials", "integration_scopes", "audit_logs"}.issubset(Base.metadata.tables)
    assert Tenant.__tablename__ == "tenants"
    assert Integration.__tablename__ == "integrations"
    assert ApiCredential.__tablename__ == "api_credentials"
    assert IntegrationScope.__tablename__ == "integration_scopes"
    assert AuditLog.__tablename__ == "audit_logs"
