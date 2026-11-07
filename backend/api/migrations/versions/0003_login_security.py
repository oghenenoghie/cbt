"""Add login throttling and allow platform-level audit entries.

Revision ID: 0003_login_security
Revises: 0002_school_identity

- login_throttles: failed-login counters keyed by a hash of the login identifier.
- audit_logs.tenant_id becomes nullable: None marks platform-level events (platform admin
  activity, or a login attempt naming a school code that doesn't exist).

SQLite can't alter a column in place, so the audit_logs change uses Alembic's batch mode
(it rebuilds the table on SQLite and issues a plain ALTER on PostgreSQL).
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_login_security"
down_revision = "0002_school_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_login_throttles_key_hash"), "login_throttles", ["key_hash"], unique=True
    )
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    # The old schema can't hold platform-level entries, so they are deleted on downgrade.
    op.execute("DELETE FROM audit_logs WHERE tenant_id IS NULL")
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_index(op.f("ix_login_throttles_key_hash"), table_name="login_throttles")
    op.drop_table("login_throttles")
