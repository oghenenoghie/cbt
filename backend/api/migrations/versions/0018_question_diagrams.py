"""Store reviewed structured diagrams with immutable question versions.

Revision ID: 0018_question_diagrams
Revises: 0017_integration_management
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_question_diagrams"
down_revision = "0017_integration_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.add_column(sa.Column("diagram_spec", sa.JSON(), nullable=True))
    with op.batch_alter_table("question_drafts") as batch:
        batch.add_column(sa.Column("diagram_spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("question_versions") as batch:
        batch.drop_column("diagram_spec")
    with op.batch_alter_table("question_drafts") as batch:
        batch.drop_column("diagram_spec")
