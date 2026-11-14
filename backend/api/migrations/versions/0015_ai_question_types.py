"""AI drafts of every question type.

Revision ID: 0015_ai_question_types
Revises: 0014_question_types_marking

See docs/architecture/decisions/0006-question-types-and-marking.md (stage C). Drafts keep the
answer key of short-answer, numeric and essay questions, as bank versions do.
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_ai_question_types"
down_revision = "0014_question_types_marking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("question_drafts", sa.Column("answer_key", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("question_drafts", "answer_key")
