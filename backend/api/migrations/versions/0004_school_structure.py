"""Create school structure tables: sessions, terms, class levels and arms, subjects, topics.

Revision ID: 0004_school_structure
Revises: 0003_login_security

See docs/architecture/decisions/0002-school-structure.md. Composite foreign keys on
(id, tenant_id) keep every link inside one school; a partial unique index allows at most one
current session per school.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_school_structure"
down_revision = "0003_login_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_on > starts_on", name="ck_academic_sessions_dates"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_academic_sessions_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_academic_sessions_tenant_id_name"),
    )
    op.create_index(
        op.f("ix_academic_sessions_tenant_id"), "academic_sessions", ["tenant_id"], unique=False
    )
    op.create_index(
        "uq_academic_sessions_one_current",
        "academic_sessions",
        ["tenant_id"],
        unique=True,
        sqlite_where=sa.text("is_current"),
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "class_levels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_class_levels_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_class_levels_tenant_id_name"),
    )
    op.create_index(op.f("ix_class_levels_tenant_id"), "class_levels", ["tenant_id"], unique=False)
    op.create_table(
        "subjects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_subjects_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_subjects_tenant_id_code"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_subjects_tenant_id_name"),
    )
    op.create_index(op.f("ix_subjects_tenant_id"), "subjects", ["tenant_id"], unique=False)
    op.create_table(
        "class_arms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("level_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            name="fk_class_arms_level_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["academic_sessions.id", "academic_sessions.tenant_id"],
            name="fk_class_arms_session_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_class_arms_id_tenant_id"),
        sa.UniqueConstraint(
            "session_id", "level_id", "name", name="uq_class_arms_session_id_level_id_name"
        ),
    )
    op.create_index(op.f("ix_class_arms_level_id"), "class_arms", ["level_id"], unique=False)
    op.create_index(op.f("ix_class_arms_session_id"), "class_arms", ["session_id"], unique=False)
    op.create_index(op.f("ix_class_arms_tenant_id"), "class_arms", ["tenant_id"], unique=False)
    op.create_table(
        "class_level_subjects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("level_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            name="fk_class_level_subjects_level_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_class_level_subjects_subject_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "level_id", "subject_id", name="uq_class_level_subjects_level_id_subject_id"
        ),
    )
    op.create_index(
        op.f("ix_class_level_subjects_subject_id"),
        "class_level_subjects",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_class_level_subjects_tenant_id"),
        "class_level_subjects",
        ["tenant_id"],
        unique=False,
    )
    op.create_table(
        "terms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "starts_on IS NULL OR ends_on IS NULL OR ends_on > starts_on", name="ck_terms_dates"
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["academic_sessions.id", "academic_sessions.tenant_id"],
            name="fk_terms_session_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_terms_id_tenant_id"),
        sa.UniqueConstraint("session_id", "name", name="uq_terms_session_id_name"),
    )
    op.create_index(op.f("ix_terms_session_id"), "terms", ["session_id"], unique=False)
    op.create_index(op.f("ix_terms_tenant_id"), "terms", ["tenant_id"], unique=False)
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_topics_subject_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_topics_id_tenant_id"),
        sa.UniqueConstraint("subject_id", "name", name="uq_topics_subject_id_name"),
    )
    op.create_index(op.f("ix_topics_subject_id"), "topics", ["subject_id"], unique=False)
    op.create_index(op.f("ix_topics_tenant_id"), "topics", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_topics_tenant_id"), table_name="topics")
    op.drop_index(op.f("ix_topics_subject_id"), table_name="topics")
    op.drop_table("topics")
    op.drop_index(op.f("ix_terms_tenant_id"), table_name="terms")
    op.drop_index(op.f("ix_terms_session_id"), table_name="terms")
    op.drop_table("terms")
    op.drop_index(op.f("ix_class_level_subjects_tenant_id"), table_name="class_level_subjects")
    op.drop_index(op.f("ix_class_level_subjects_subject_id"), table_name="class_level_subjects")
    op.drop_table("class_level_subjects")
    op.drop_index(op.f("ix_class_arms_tenant_id"), table_name="class_arms")
    op.drop_index(op.f("ix_class_arms_session_id"), table_name="class_arms")
    op.drop_index(op.f("ix_class_arms_level_id"), table_name="class_arms")
    op.drop_table("class_arms")
    op.drop_index(op.f("ix_subjects_tenant_id"), table_name="subjects")
    op.drop_table("subjects")
    op.drop_index(op.f("ix_class_levels_tenant_id"), table_name="class_levels")
    op.drop_table("class_levels")
    op.drop_index(
        "uq_academic_sessions_one_current",
        table_name="academic_sessions",
        sqlite_where=sa.text("is_current"),
        postgresql_where=sa.text("is_current"),
    )
    op.drop_index(op.f("ix_academic_sessions_tenant_id"), table_name="academic_sessions")
    op.drop_table("academic_sessions")
