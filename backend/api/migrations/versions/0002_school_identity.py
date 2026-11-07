"""Create school identity tables: users, platform admins, sessions and candidates.

Revision ID: 0002_school_identity
Revises: 0001_tenants_integrations

See docs/architecture/decisions/0001-school-identity-model.md. Composite foreign keys on
(id, tenant_id) keep candidate links, sessions and external IDs inside one school.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_school_identity"
down_revision = "0001_tenants_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_admins_email"), "platform_admins", ["email"], unique=True)
    op.create_index(op.f("ix_platform_admins_status"), "platform_admins", ["status"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_users_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "username", name="uq_users_tenant_id_username"),
    )
    op.create_index(op.f("ix_users_status"), "users", ["status"], unique=False)
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND tenant_id IS NOT NULL AND platform_admin_id IS NULL) OR (user_id IS NULL AND tenant_id IS NULL AND platform_admin_id IS NOT NULL)",
            name="ck_auth_sessions_one_principal",
        ),
        sa.ForeignKeyConstraint(["platform_admin_id"], ["platform_admins.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_auth_sessions_user_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"], unique=False
    )
    op.create_index(
        op.f("ix_auth_sessions_platform_admin_id"),
        "auth_sessions",
        ["platform_admin_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_sessions_tenant_id"), "auth_sessions", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_auth_sessions_token_hash"), "auth_sessions", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_candidates_user_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_candidates_id_tenant_id"),
        sa.UniqueConstraint("user_id", name="uq_candidates_user_id"),
    )
    op.create_index(op.f("ix_candidates_status"), "candidates", ["status"], unique=False)
    op.create_index(op.f("ix_candidates_tenant_id"), "candidates", ["tenant_id"], unique=False)
    op.create_table(
        "candidate_external_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("external_system_id", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_candidate_external_identities_candidate_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "external_system_id",
            name="uq_candidate_external_identities_candidate_system",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "external_system_id",
            "external_id",
            name="uq_candidate_external_identities_source_id",
        ),
    )
    op.create_index(
        op.f("ix_candidate_external_identities_tenant_id"),
        "candidate_external_identities",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_candidate_external_identities_tenant_id"),
        table_name="candidate_external_identities",
    )
    op.drop_table("candidate_external_identities")
    op.drop_index(op.f("ix_candidates_tenant_id"), table_name="candidates")
    op.drop_index(op.f("ix_candidates_status"), table_name="candidates")
    op.drop_table("candidates")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_token_hash"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_tenant_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_platform_admin_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_expires_at"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_platform_admins_status"), table_name="platform_admins")
    op.drop_index(op.f("ix_platform_admins_email"), table_name="platform_admins")
    op.drop_table("platform_admins")
