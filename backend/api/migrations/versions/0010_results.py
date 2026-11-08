"""Record when an exam's results are released to students, and by whom.

Revision ID: 0010_results
Revises: 0009_attempts

See docs/architecture/decisions/0003-exams.md (Exams D).
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_results"
down_revision = "0009_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode so SQLite can add the foreign key (it rebuilds the table).
    with op.batch_alter_table("exams") as batch:
        batch.add_column(
            sa.Column("results_released_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("results_released_by_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_exams_results_released_by_same_tenant",
            "users",
            ["results_released_by_id", "tenant_id"],
            ["id", "tenant_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("exams") as batch:
        batch.drop_constraint("fk_exams_results_released_by_same_tenant", type_="foreignkey")
        batch.drop_column("results_released_by_id")
        batch.drop_column("results_released_at")
