# CBT API

FastAPI service shared by the web application and Windows desktop client.

## Local setup

```bash
cd backend/api
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
# Copy .env.example to .env, then:
alembic upgrade head
uvicorn app.main:app --reload
```

## Checks

CI (`.github/workflows/backend-api.yml`) runs these from `backend/api` on Python 3.11 and 3.13:

```bash
ruff check .
pytest
alembic upgrade head && alembic check   # fails if models changed without a migration
```

Tests use a throwaway SQLite database per test (see `tests/conftest.py`) and never touch your local `cbt.db`.

## Database configuration

The default local database is SQLite. Set `DATABASE_URL` to a PostgreSQL connection string for shared development or production. Never commit real credentials.

## Database foundation

The first migration creates tenants, integrations, API credentials, integration scopes and audit logs. Run `alembic upgrade head` to apply it and `alembic downgrade -1` to roll back one revision.

API credentials are generated using cryptographically secure randomness. Persist only the SHA-256 digest and display the raw value once at creation time. The helper is in `app/core/api_keys.py`.

## Security implementation status

The database models, migration and API-key utility are foundational components, not a complete authentication service. Do not expose integration management or customer-data endpoints until administrator authentication, tenant-scoped authorization, credential lifecycle routes, audit writes, rate limits and security tests are implemented. Do not use a client-side-only check as access control.

See [Integration Developer Guide](../../docs/integrations/README.md) and [Integration Architecture](../../docs/integrations/overview.md).
