"""More question types and teacher marking.

Revision ID: 0014_question_types_marking
Revises: 0013_more_material_kinds

See docs/architecture/decisions/0006-question-types-and-marking.md. Adds the new question types
and their answer keys, text answers on attempts, and teachers' marks for written answers.
SQLite can't alter constraints, so batch mode rebuilds those tables there.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_question_types_marking"
down_revision = "0013_more_material_kinds"
branch_labels = None
depends_on = None

OLD_TYPES = "type IN ('mcq_single', 'true_false')"
NEW_TYPES = (
    "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay')"
)


def upgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.add_column(sa.Column("answer_key", sa.JSON(), nullable=True))
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint("ck_question_versions_type", NEW_TYPES)

    op.add_column("answer_events", sa.Column("text", sa.Text(), nullable=True))

    # The unique (id, tenant_id) comes first: teachers' marks point at it.
    with op.batch_alter_table("attempt_responses") as batch:
        batch.add_column(sa.Column("text", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("needs_marking", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_unique_constraint("uq_attempt_responses_id_tenant_id", ["id", "tenant_id"])

    op.create_table(
        "response_marks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("response_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("marked_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0", name="ck_response_marks_score"),
        sa.ForeignKeyConstraint(
            ["marked_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_response_marks_marked_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["response_id", "tenant_id"],
            ["attempt_responses.id", "attempt_responses.tenant_id"],
            name="fk_response_marks_response_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("response_id", "number", name="uq_response_marks_response_number"),
    )
    op.create_index(
        op.f("ix_response_marks_response_id"), "response_marks", ["response_id"], unique=False
    )
    op.create_index(
        op.f("ix_response_marks_tenant_id"), "response_marks", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    # Fails while any question of a new type exists: delete those first.
    op.drop_index(op.f("ix_response_marks_tenant_id"), table_name="response_marks")
    op.drop_index(op.f("ix_response_marks_response_id"), table_name="response_marks")
    op.drop_table("response_marks")
    with op.batch_alter_table("attempt_responses") as batch:
        batch.drop_constraint("uq_attempt_responses_id_tenant_id", type_="unique")
        batch.drop_column("needs_marking")
        batch.drop_column("text")
    op.drop_column("answer_events", "text")
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint("ck_question_versions_type", OLD_TYPES)
        batch.drop_column("answer_key")
