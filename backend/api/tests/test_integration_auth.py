from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_integration_identity_requires_bearer_credentials() -> None:
    response = client.get("/api/v1/integrations/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
