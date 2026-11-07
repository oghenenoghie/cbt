# Local Infrastructure

Docker Compose runs the portable local services. Today that is PostgreSQL 17 with the pgvector extension available (`compose.yaml`). Redis will be added when background jobs are introduced.

## PostgreSQL

From the repository root:

```bash
cp infrastructure/docker/.env.example infrastructure/docker/.env   # untracked; set a local-only password
docker compose -f infrastructure/docker/compose.yaml up -d
docker compose -f infrastructure/docker/compose.yaml ps            # wait for "healthy"
```

This creates two databases:

| Database | Used for |
|---|---|
| `cbt` (`POSTGRES_DB`) | Development: point the API's `DATABASE_URL` at it and run `alembic upgrade head` |
| `cbt_test` | The test suite (`TEST_DATABASE_URL`). Tests drop every table they create, so never point them at `cbt` |

Connection strings use SQLAlchemy's psycopg 3 driver (note `+psycopg`):

```bash
DATABASE_URL="postgresql+psycopg://cbt:<password>@localhost:5432/cbt"
TEST_DATABASE_URL="postgresql+psycopg://cbt:<password>@localhost:5432/cbt_test"
```

- The port is bound to `127.0.0.1` only. Change `POSTGRES_PORT` in `.env` if 5432 is taken.
- `cbt_test` is created by `postgres/init/01-create-test-database.sql`, which only runs when the data volume is first created. To start over: `docker compose -f infrastructure/docker/compose.yaml down -v` (this deletes all local data).
- The image tag (`pgvector/pgvector:0.8.0-pg17`) matches the PostgreSQL job in `.github/workflows/backend-api.yml`. Change both together.
- pgvector is installed in the image but not enabled. The migration that introduces vector columns (Phase 4) should run `CREATE EXTENSION IF NOT EXISTS vector`, so development, CI and production all get it the same way.

## Production

Production deployments should support Railway and standard VPS environments. Keep configuration in environment variables, and provide documented backup, restore, migration and health-check procedures before production use.
