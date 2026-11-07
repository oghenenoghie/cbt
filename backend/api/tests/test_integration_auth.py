from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.api_keys import generate_api_key
from app.integrations.auth import IntegrationPrincipal

ME_URL = "/api/v1/integrations/me"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_unauthorized(response, detail: str = "Invalid integration credentials.") -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": detail}


# --- Missing or malformed credentials -------------------------------------------------


def test_integration_identity_requires_bearer_credentials(client: TestClient) -> None:
    assert_unauthorized(client.get(ME_URL), detail="Missing bearer token.")


def test_non_bearer_scheme_is_rejected(client: TestClient, make_credential) -> None:
    issued = make_credential()

    response = client.get(ME_URL, headers={"Authorization": f"Basic {issued.raw_key}"})

    assert_unauthorized(response, detail="Missing bearer token.")


@pytest.mark.parametrize(
    "token",
    [
        "not-a-platform-key-but-long-enough-0123456789",  # wrong prefix
        "cbt_live_tooshort",  # right prefix, too short
    ],
)
def test_malformed_token_is_rejected(client: TestClient, token: str) -> None:
    assert_unauthorized(client.get(ME_URL, headers=bearer(token)))


def test_unknown_key_is_rejected(client: TestClient, make_credential) -> None:
    make_credential()
    never_stored_key, _, _ = generate_api_key()

    assert_unauthorized(client.get(ME_URL, headers=bearer(never_stored_key)))


def test_wrong_secret_with_matching_prefix_is_rejected(
    client: TestClient, db: Session, make_credential
) -> None:
    issued = make_credential()
    forged = issued.raw_key[:16] + "x" * (len(issued.raw_key) - 16)

    assert_unauthorized(client.get(ME_URL, headers=bearer(forged)))

    db.refresh(issued.credential)
    assert issued.credential.last_used_at is None


# --- Valid credentials ------------------------------------------------------------------


def test_valid_key_returns_tenant_bound_identity(client: TestClient, make_credential) -> None:
    issued = make_credential(
        granted_scopes=("results:read", "candidates:read"),
        denied_scopes=("results:write",),
    )

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": issued.tenant.id,
        "integration_id": issued.integration.id,
        # Only granted scopes, sorted.
        "scopes": ["candidates:read", "results:read"],
    }


def test_response_never_contains_secret_material(client: TestClient, make_credential) -> None:
    issued = make_credential()

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert response.status_code == 200
    assert issued.raw_key not in response.text
    assert issued.credential.secret_hash not in response.text


def test_successful_authentication_records_last_use(
    client: TestClient, db: Session, make_credential
) -> None:
    issued = make_credential()
    assert issued.credential.last_used_at is None

    assert client.get(ME_URL, headers=bearer(issued.raw_key)).status_code == 200

    db.refresh(issued.credential)
    assert issued.credential.last_used_at is not None


def test_credential_with_future_expiry_is_accepted(client: TestClient, make_credential) -> None:
    issued = make_credential(expires_at=datetime.now(UTC) + timedelta(days=1))

    assert client.get(ME_URL, headers=bearer(issued.raw_key)).status_code == 200


# --- Credential, integration and tenant lifecycle ----------------------------------------


def test_revoked_credential_is_rejected(
    client: TestClient, db: Session, make_credential
) -> None:
    issued = make_credential()
    issued.credential.status = "revoked"
    issued.credential.revoked_at = datetime.now(UTC)
    db.commit()

    assert_unauthorized(client.get(ME_URL, headers=bearer(issued.raw_key)))


def test_expired_credential_is_rejected(
    client: TestClient, db: Session, make_credential
) -> None:
    issued = make_credential(expires_at=datetime.now(UTC) - timedelta(minutes=1))

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert_unauthorized(response, detail="Integration credentials have expired.")
    db.refresh(issued.credential)
    assert issued.credential.last_used_at is None


@pytest.mark.parametrize("status", ["disabled", "suspended"])
def test_inactive_integration_is_rejected(
    client: TestClient, db: Session, make_credential, status: str
) -> None:
    issued = make_credential()
    issued.integration.status = status
    db.commit()

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert_unauthorized(response, detail="Integration access is disabled.")


@pytest.mark.parametrize("status", ["disabled", "suspended"])
def test_inactive_tenant_is_rejected(
    client: TestClient, db: Session, make_credential, status: str
) -> None:
    issued = make_credential()
    issued.tenant.status = status
    db.commit()

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert_unauthorized(response, detail="Integration access is disabled.")


# --- Tenant isolation ------------------------------------------------------------------


def test_credential_bound_to_a_different_tenant_than_its_integration_is_rejected(
    client: TestClient, db: Session, make_credential, make_tenant
) -> None:
    issued = make_credential()
    other_tenant = make_tenant()
    issued.credential.tenant_id = other_tenant.id
    db.commit()

    response = client.get(ME_URL, headers=bearer(issued.raw_key))

    assert_unauthorized(response, detail="Integration access is disabled.")


def test_each_key_resolves_only_to_its_own_tenant_and_scopes(
    client: TestClient, make_credential
) -> None:
    school_a = make_credential(granted_scopes=("candidates:read",))
    school_b = make_credential(granted_scopes=("results:write",))
    # A second integration inside school A must not leak its scopes either.
    school_a_other_app = make_credential(tenant=school_a.tenant, granted_scopes=("results:read",))

    body_a = client.get(ME_URL, headers=bearer(school_a.raw_key)).json()
    body_b = client.get(ME_URL, headers=bearer(school_b.raw_key)).json()
    body_a_other = client.get(ME_URL, headers=bearer(school_a_other_app.raw_key)).json()

    assert body_a["tenant_id"] == school_a.tenant.id
    assert body_a["scopes"] == ["candidates:read"]
    assert body_b["tenant_id"] == school_b.tenant.id
    assert body_b["scopes"] == ["results:write"]
    assert body_a_other["tenant_id"] == school_a.tenant.id
    assert body_a_other["integration_id"] != body_a["integration_id"]
    assert body_a_other["scopes"] == ["results:read"]


# --- Scope enforcement -----------------------------------------------------------------


def test_require_scope_allows_granted_and_forbids_missing_scopes() -> None:
    principal = IntegrationPrincipal(
        tenant_id="tenant-1",
        integration_id="integration-1",
        credential_id="credential-1",
        scopes=frozenset({"results:read"}),
    )

    principal.require_scope("results:read")

    with pytest.raises(HTTPException) as excinfo:
        principal.require_scope("results:write")
    assert excinfo.value.status_code == 403
