"""Allow questions whose answers label a supplied diagram.

Revision ID: 0019_diagram_label_question_type
Revises: 0018_question_diagrams
"""

from alembic import op

revision = "0019_diagram_label_question_type"
down_revision = "0018_question_diagrams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint(
            "ck_question_versions_type",
            "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay', 'diagram_label')",
        )


def downgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint(
            "ck_question_versions_type",
            "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay')",
        )

