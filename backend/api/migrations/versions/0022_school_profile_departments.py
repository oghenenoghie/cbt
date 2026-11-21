"""School profile and departments.

Revision ID: 0022_school_profile_departments
Revises: 0021_calculation_question_type

See docs/architecture/decisions/0002-school-structure.md, decisions 11 and 12. Adds the
school profile (address, phone, email, motto and logo) to tenants, and departments: groups of
subjects with an optional head, kept inside one school by composite foreign keys.
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_school_profile_departments"
down_revision = "0021_calculation_question_type"
branch_labels = None
depends_on = None

PROFILE = [
    sa.Column("address", sa.String(length=500), nullable=True),
    sa.Column("phone", sa.String(length=50), nullable=True),
    sa.Column("email", sa.String(length=254), nullable=True),
    sa.Column("motto", sa.String(length=200), nullable=True),
    sa.Column("logo_key", sa.String(length=255), nullable=True),
    sa.Column("logo_updated_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        for column in PROFILE:
            batch.add_column(column.copy())

    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("head_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["head_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_departments_head_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_departments_id_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_departments_tenant_id_name"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"])
    op.create_index("ix_departments_head_id", "departments", ["head_id"])

    with op.batch_alter_table("subjects") as batch:
        batch.add_column(sa.Column("department_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_subjects_department_id", ["department_id"])
        batch.create_foreign_key(
            "fk_subjects_department_same_tenant",
            "departments",
            ["department_id", "tenant_id"],
            ["id", "tenant_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.drop_constraint("fk_subjects_department_same_tenant", type_="foreignkey")
        batch.drop_index("ix_subjects_department_id")
        batch.drop_column("department_id")

    op.drop_index("ix_departments_head_id", table_name="departments")
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")

    with op.batch_alter_table("tenants") as batch:
        for column in reversed(PROFILE):
            batch.drop_column(column.name)
