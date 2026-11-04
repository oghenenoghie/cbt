# Local Infrastructure

The development environment will use Docker Compose for portable local services, initially PostgreSQL with pgvector and Redis when background jobs are introduced.

Production deployments should support Railway and standard VPS environments. Keep configuration in environment variables and provide documented backup, restore, migration and health-check procedures before production use.
