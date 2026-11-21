"""Add the matching question type.

Revision ID: 0020_matching_question_type
Revises: 0019_diagram_label_question_type
"""

from alembic import op

revision = "0020_matching_question_type"
down_revision = "0019_diagram_label_question_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint(
            "ck_question_versions_type",
            "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay', 'diagram_label', 'matching')",
        )


def downgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint(
            "ck_question_versions_type",
            "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay', 'diagram_label')",
        )
