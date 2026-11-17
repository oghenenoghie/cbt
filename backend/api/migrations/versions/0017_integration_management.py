"""Integration management by school admins.

Revision ID: 0017_integration_management
Revises: 0016_offline_exams

See docs/architecture/decisions/0008-integrations.md. Records who registered each integration and
who issued and revoked each API key, ties every key to its integration's school, allows each
permission once per integration, limits statuses, and adds the per-minute request counter.
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_integration_management"
down_revision = "0016_offline_exams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode so SQLite can add the constraints (it rebuilds each table).
    with op.batch_alter_table("integrations") as batch:
        batch.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))
        batch.create_unique_constraint("uq_integrations_id_tenant_id", ["id", "tenant_id"])
        batch.create_foreign_key(
            "fk_integrations_created_by_same_tenant",
            "users",
            ["created_by_id", "tenant_id"],
            ["id", "tenant_id"],
        )
        batch.create_check_constraint(
            "ck_integrations_status", "status IN ('active', 'disabled')"
        )

    with op.batch_alter_table("api_credentials") as batch:
        batch.add_column(sa.Column("created_by_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("revoked_by_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_api_credentials_integration_same_tenant",
            "integrations",
            ["integration_id", "tenant_id"],
            ["id", "tenant_id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_api_credentials_created_by_same_tenant",
            "users",
            ["created_by_id", "tenant_id"],
            ["id", "tenant_id"],
        )
        batch.create_foreign_key(
            "fk_api_credentials_revoked_by_same_tenant",
            "users",
            ["revoked_by_id", "tenant_id"],
            ["id", "tenant_id"],
        )
        batch.create_check_constraint(
            "ck_api_credentials_status", "status IN ('active', 'revoked')"
        )

    with op.batch_alter_table("integration_scopes") as batch:
        batch.create_unique_constraint(
            "uq_integration_scopes_integration_scope", ["integration_id", "scope"]
        )

    op.create_table(
        "integration_rate_windows",
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("window_minute", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id", "tenant_id"],
            ["integrations.id", "integrations.tenant_id"],
            name="fk_integration_rate_windows_integration_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("integration_id"),
    )
    op.create_index(
        op.f("ix_integration_rate_windows_tenant_id"),
        "integration_rate_windows",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_integration_rate_windows_tenant_id"), table_name="integration_rate_windows"
    )
    op.drop_table("integration_rate_windows")
    with op.batch_alter_table("integration_scopes") as batch:
        batch.drop_constraint("uq_integration_scopes_integration_scope", type_="unique")
    with op.batch_alter_table("api_credentials") as batch:
        batch.drop_constraint("ck_api_credentials_status", type_="check")
        batch.drop_constraint("fk_api_credentials_revoked_by_same_tenant", type_="foreignkey")
        batch.drop_constraint("fk_api_credentials_created_by_same_tenant", type_="foreignkey")
        batch.drop_constraint("fk_api_credentials_integration_same_tenant", type_="foreignkey")
        batch.drop_column("revoked_by_id")
        batch.drop_column("created_by_id")
    with op.batch_alter_table("integrations") as batch:
        batch.drop_constraint("ck_integrations_status", type_="check")
        batch.drop_constraint("fk_integrations_created_by_same_tenant", type_="foreignkey")
        batch.drop_constraint("uq_integrations_id_tenant_id", type_="unique")
        batch.drop_column("created_by_id")
