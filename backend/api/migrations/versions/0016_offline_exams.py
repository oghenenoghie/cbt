"""Offline exams on lab computers.

Revision ID: 0016_offline_exams
Revises: 0015_ai_question_types

See docs/architecture/decisions/0007-offline-exams.md. Adds lab computers and their registration
codes, students' exam codes, the packages issued and the results received, the school's offline
key, each exam's offline settings, and where an attempt was sat.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_offline_exams"
down_revision = "0015_ai_question_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_offline_keys",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "lab_devices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("public_key", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("registered_by_id", sa.String(length=36), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint("method IN ('online', 'file')", name="ck_lab_devices_method"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_lab_devices_status"),
        sa.ForeignKeyConstraint(
            ["registered_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_lab_devices_registered_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_lab_devices_revoked_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_lab_devices_id_tenant_id"),
        sa.UniqueConstraint("token_hash", name="uq_lab_devices_token_hash"),
    )
    op.create_index(op.f("ix_lab_devices_tenant_id"), "lab_devices", ["tenant_id"], unique=False)
    op.create_table(
        "device_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_device_registrations_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_device_registrations_device_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_device_registrations_code_hash"),
    )
    op.create_index(
        op.f("ix_device_registrations_tenant_id"),
        "device_registrations",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "offline_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("salt", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("batch", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("iterations >= 1", name="ck_offline_codes_iterations"),
        sa.ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_offline_codes_candidate_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_offline_codes_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id", "tenant_id"],
            ["exams.id", "exams.tenant_id"],
            name="fk_offline_codes_exam_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exam_id", "candidate_id", name="uq_offline_codes_exam_id_candidate_id"
        ),
    )
    op.create_index(
        op.f("ix_offline_codes_candidate_id"), "offline_codes", ["candidate_id"], unique=False
    )
    op.create_index(op.f("ix_offline_codes_exam_id"), "offline_codes", ["exam_id"], unique=False)
    op.create_index(
        op.f("ix_offline_codes_tenant_id"), "offline_codes", ["tenant_id"], unique=False
    )
    op.create_table(
        "offline_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("exported_by_id", sa.String(length=36), nullable=True),
        sa.Column("paper_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_ids", sa.JSON(), nullable=False),
        sa.Column("codes_batch", sa.Integer(), nullable=False),
        sa.Column("instant_scores", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_offline_packages_device_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id", "tenant_id"],
            ["exams.id", "exams.tenant_id"],
            name="fk_offline_packages_exam_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exported_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_offline_packages_exported_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_offline_packages_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_offline_packages_device_id"), "offline_packages", ["device_id"], unique=False
    )
    op.create_index(
        op.f("ix_offline_packages_exam_id"), "offline_packages", ["exam_id"], unique=False
    )
    op.create_index(
        op.f("ix_offline_packages_tenant_id"), "offline_packages", ["tenant_id"], unique=False
    )
    op.create_table(
        "offline_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("received_via", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by_id", sa.String(length=36), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("received_via IN ('device', 'file')", name="ck_offline_submissions_via"),
        sa.CheckConstraint(
            "status IN ('accepted', 'conflict', 'rejected')", name="ck_offline_submissions_status"
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["exam_attempts.id", "exam_attempts.tenant_id"],
            name="fk_offline_submissions_attempt_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_offline_submissions_candidate_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["device_id", "tenant_id"],
            ["lab_devices.id", "lab_devices.tenant_id"],
            name="fk_offline_submissions_device_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id", "tenant_id"],
            ["exams.id", "exams.tenant_id"],
            name="fk_offline_submissions_exam_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_offline_submissions_uploaded_by_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "submission_id", name="uq_offline_submissions_tenant_submission"
        ),
    )
    op.create_index(
        op.f("ix_offline_submissions_candidate_id"),
        "offline_submissions",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_offline_submissions_device_id"), "offline_submissions", ["device_id"], unique=False
    )
    op.create_index(
        op.f("ix_offline_submissions_exam_id"), "offline_submissions", ["exam_id"], unique=False
    )
    op.create_index(
        op.f("ix_offline_submissions_tenant_id"), "offline_submissions", ["tenant_id"], unique=False
    )
    op.add_column(
        "exam_attempts",
        sa.Column("source", sa.String(length=10), server_default="online", nullable=False),
    )
    op.add_column(
        "exams",
        sa.Column("offline_allowed", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "exams",
        sa.Column(
            "offline_instant_scores", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("exams", "offline_instant_scores")
    op.drop_column("exams", "offline_allowed")
    op.drop_column("exam_attempts", "source")
    op.drop_index(op.f("ix_offline_submissions_tenant_id"), table_name="offline_submissions")
    op.drop_index(op.f("ix_offline_submissions_exam_id"), table_name="offline_submissions")
    op.drop_index(op.f("ix_offline_submissions_device_id"), table_name="offline_submissions")
    op.drop_index(op.f("ix_offline_submissions_candidate_id"), table_name="offline_submissions")
    op.drop_table("offline_submissions")
    op.drop_index(op.f("ix_offline_packages_tenant_id"), table_name="offline_packages")
    op.drop_index(op.f("ix_offline_packages_exam_id"), table_name="offline_packages")
    op.drop_index(op.f("ix_offline_packages_device_id"), table_name="offline_packages")
    op.drop_table("offline_packages")
    op.drop_index(op.f("ix_offline_codes_tenant_id"), table_name="offline_codes")
    op.drop_index(op.f("ix_offline_codes_exam_id"), table_name="offline_codes")
    op.drop_index(op.f("ix_offline_codes_candidate_id"), table_name="offline_codes")
    op.drop_table("offline_codes")
    op.drop_index(op.f("ix_device_registrations_tenant_id"), table_name="device_registrations")
    op.drop_table("device_registrations")
    op.drop_index(op.f("ix_lab_devices_tenant_id"), table_name="lab_devices")
    op.drop_table("lab_devices")
    op.drop_table("school_offline_keys")
