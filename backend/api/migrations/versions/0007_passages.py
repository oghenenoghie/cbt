"""Add reading passages, their unchangeable versions, and the link from questions to them.

Revision ID: 0007_passages
Revises: 0006_question_bank

See docs/architecture/decisions/0003-exams.md. A question's passage is referenced by
(id, subject_id, tenant_id), so it is always in the question's school and subject.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_passages"
down_revision = "0006_question_bank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_passages_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_passages_subject_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "subject_id", "tenant_id", name="uq_passages_id_subject_id_tenant_id"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_passages_id_tenant_id"),
    )
    op.create_index(op.f("ix_passages_status"), "passages", ["status"], unique=False)
    op.create_index(op.f("ix_passages_subject_id"), "passages", ["subject_id"], unique=False)
    op.create_index(op.f("ix_passages_tenant_id"), "passages", ["tenant_id"], unique=False)

    op.create_table(
        "passage_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("passage_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_passage_versions_version"),
        sa.ForeignKeyConstraint(
            ["passage_id", "tenant_id"],
            ["passages.id", "passages.tenant_id"],
            name="fk_passage_versions_passage_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("passage_id", "version", name="uq_passage_versions_passage_id_version"),
    )
    op.create_index(
        op.f("ix_passage_versions_passage_id"), "passage_versions", ["passage_id"], unique=False
    )
    op.create_index(
        op.f("ix_passage_versions_tenant_id"), "passage_versions", ["tenant_id"], unique=False
    )

    # Batch mode so SQLite can add the foreign key (it rebuilds the table).
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("passage_id", sa.String(length=36), nullable=True))
        batch.create_index(op.f("ix_questions_passage_id"), ["passage_id"], unique=False)
        batch.create_foreign_key(
            "fk_questions_passage_same_subject",
            "passages",
            ["passage_id", "subject_id", "tenant_id"],
            ["id", "subject_id", "tenant_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.drop_constraint("fk_questions_passage_same_subject", type_="foreignkey")
        batch.drop_index(op.f("ix_questions_passage_id"))
        batch.drop_column("passage_id")
    op.drop_index(op.f("ix_passage_versions_tenant_id"), table_name="passage_versions")
    op.drop_index(op.f("ix_passage_versions_passage_id"), table_name="passage_versions")
    op.drop_table("passage_versions")
    op.drop_index(op.f("ix_passages_tenant_id"), table_name="passages")
    op.drop_index(op.f("ix_passages_subject_id"), table_name="passages")
    op.drop_index(op.f("ix_passages_status"), table_name="passages")
    op.drop_table("passages")
