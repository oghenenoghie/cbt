"""Webhooks: endpoints, events and deliveries.

Revision ID: 0023_webhooks
Revises: 0022_school_profile_departments

See docs/architecture/decisions/0008-integrations.md, decisions 12 to 16. An integration's
endpoints, the events recorded with the changes they report (an outbox), and each event's delivery
to each endpoint, all kept inside one school by composite foreign keys.
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_webhooks"
down_revision = "0022_school_profile_departments"
branch_labels = None
depends_on = None


def _when(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("actor_integration_id", sa.String(length=36), nullable=True),
        _when("created_at", nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_webhook_events_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "type", "dedupe_key", name="uq_webhook_events_dedupe"),
    )
    op.create_index("ix_webhook_events_tenant_id", "webhook_events", ["tenant_id"])

    op.create_table(
        "webhook_endpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        _when("created_at", nullable=False),
        _when("updated_at", nullable=False),
        _when("last_success_at"),
        _when("last_failure_at"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_webhook_endpoints_status"),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_webhook_endpoints_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["integration_id", "tenant_id"],
            ["integrations.id", "integrations.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_endpoints_integration_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_webhook_endpoints_id_tenant_id"),
    )
    op.create_index("ix_webhook_endpoints_integration_id", "webhook_endpoints", ["integration_id"])
    op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _when("next_attempt_at"),
        _when("claimed_at"),
        _when("last_attempt_at"),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        _when("delivered_at"),
        _when("created_at", nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'failed', 'cancelled')",
            name="ck_webhook_deliveries_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_webhook_deliveries_attempts"),
        sa.ForeignKeyConstraint(
            ["endpoint_id", "tenant_id"],
            ["webhook_endpoints.id", "webhook_endpoints.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_deliveries_endpoint_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "tenant_id"],
            ["webhook_events.id", "webhook_events.tenant_id"],
            ondelete="CASCADE",
            name="fk_webhook_deliveries_event_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint_id", "event_id", name="uq_webhook_deliveries_endpoint_event"),
    )
    op.create_index("ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
    op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_endpoints")
    op.drop_table("webhook_events")
