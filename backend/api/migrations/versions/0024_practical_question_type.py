"""Add the structured practical question type.

Revision ID: 0024_practical_question_type
Revises: 0023_webhooks

See docs/architecture/decisions/0006-question-types-and-marking.md, decision 8.
"""

from alembic import op

revision = "0024_practical_question_type"
down_revision = "0023_webhooks"
branch_labels = None
depends_on = None

BEFORE = (
    "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay', "
    "'diagram_label', 'matching', 'calculation')"
)
AFTER = (
    "type IN ('mcq_single', 'mcq_multiple', 'true_false', 'short_answer', 'numeric', 'essay', "
    "'diagram_label', 'matching', 'calculation', 'practical')"
)


def upgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint("ck_question_versions_type", AFTER)


def downgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_constraint("ck_question_versions_type", type_="check")
        batch.create_check_constraint("ck_question_versions_type", BEFORE)
