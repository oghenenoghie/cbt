"""Create the question bank: questions, their unchangeable versions, and topic tags.

Revision ID: 0006_question_bank
Revises: 0005_classrooms

See docs/architecture/decisions/0003-exams.md. Composite foreign keys on (id, tenant_id) keep
questions, versions and tags inside one school; subjects and topics in use can't be deleted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_question_bank"
down_revision = "0005_classrooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_questions_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_questions_subject_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_questions_id_tenant_id"),
    )
    op.create_index(op.f("ix_questions_status"), "questions", ["status"], unique=False)
    op.create_index(op.f("ix_questions_subject_id"), "questions", ["subject_id"], unique=False)
    op.create_index(op.f("ix_questions_tenant_id"), "questions", ["tenant_id"], unique=False)
    op.create_table(
        "question_topics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_question_topics_question_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["topic_id", "tenant_id"],
            ["topics.id", "topics.tenant_id"],
            name="fk_question_topics_topic_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_id", "topic_id", name="uq_question_topics_question_id_topic_id"
        ),
    )
    op.create_index(
        op.f("ix_question_topics_tenant_id"), "question_topics", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_topics_topic_id"), "question_topics", ["topic_id"], unique=False
    )
    op.create_table(
        "question_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct_option_ids", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type IN ('mcq_single', 'true_false')", name="ck_question_versions_type"
        ),
        sa.CheckConstraint("marks >= 1", name="ck_question_versions_marks"),
        sa.CheckConstraint("version >= 1", name="ck_question_versions_version"),
        sa.ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_question_versions_question_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_question_versions_id_tenant_id"),
        sa.UniqueConstraint(
            "question_id", "version", name="uq_question_versions_question_id_version"
        ),
    )
    op.create_index(
        op.f("ix_question_versions_question_id"), "question_versions", ["question_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_versions_tenant_id"), "question_versions", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_question_versions_tenant_id"), table_name="question_versions")
    op.drop_index(op.f("ix_question_versions_question_id"), table_name="question_versions")
    op.drop_table("question_versions")
    op.drop_index(op.f("ix_question_topics_topic_id"), table_name="question_topics")
    op.drop_index(op.f("ix_question_topics_tenant_id"), table_name="question_topics")
    op.drop_table("question_topics")
    op.drop_index(op.f("ix_questions_tenant_id"), table_name="questions")
    op.drop_index(op.f("ix_questions_subject_id"), table_name="questions")
    op.drop_index(op.f("ix_questions_status"), table_name="questions")
    op.drop_table("questions")
