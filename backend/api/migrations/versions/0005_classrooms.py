"""Create enrolments and teaching assignments.

Revision ID: 0005_classrooms
Revises: 0004_school_structure

See docs/architecture/decisions/0002-school-structure.md. Enrolments reference their arm by
(id, session_id, tenant_id), so class_arms first gets a unique constraint on those columns.
SQLite can't add a constraint in place, so that uses batch mode, and it must exist before
PostgreSQL accepts the enrolments foreign key.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_classrooms"
down_revision = "0004_school_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("class_arms") as batch:
        batch.create_unique_constraint(
            "uq_class_arms_id_session_id_tenant_id", ["id", "session_id", "tenant_id"]
        )
    op.create_table(
        "enrolments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("arm_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["arm_id", "session_id", "tenant_id"],
            ["class_arms.id", "class_arms.session_id", "class_arms.tenant_id"],
            name="fk_enrolments_arm_same_session_and_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_enrolments_candidate_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_enrolments_id_tenant_id"),
        sa.UniqueConstraint(
            "session_id", "candidate_id", name="uq_enrolments_session_id_candidate_id"
        ),
    )
    op.create_index(op.f("ix_enrolments_arm_id"), "enrolments", ["arm_id"], unique=False)
    op.create_index(
        op.f("ix_enrolments_candidate_id"), "enrolments", ["candidate_id"], unique=False
    )
    op.create_index(op.f("ix_enrolments_tenant_id"), "enrolments", ["tenant_id"], unique=False)
    op.create_table(
        "teaching_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_id", sa.String(length=36), nullable=False),
        sa.Column("arm_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["arm_id", "tenant_id"],
            ["class_arms.id", "class_arms.tenant_id"],
            name="fk_teaching_assignments_arm_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_teaching_assignments_subject_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_teaching_assignments_teacher_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "teacher_id", "arm_id", "subject_id", name="uq_teaching_assignments_teacher_arm_subject"
        ),
    )
    op.create_index(
        op.f("ix_teaching_assignments_arm_id"), "teaching_assignments", ["arm_id"], unique=False
    )
    op.create_index(
        op.f("ix_teaching_assignments_subject_id"),
        "teaching_assignments",
        ["subject_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_teaching_assignments_teacher_id"),
        "teaching_assignments",
        ["teacher_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_teaching_assignments_tenant_id"),
        "teaching_assignments",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_teaching_assignments_tenant_id"), table_name="teaching_assignments")
    op.drop_index(op.f("ix_teaching_assignments_teacher_id"), table_name="teaching_assignments")
    op.drop_index(op.f("ix_teaching_assignments_subject_id"), table_name="teaching_assignments")
    op.drop_index(op.f("ix_teaching_assignments_arm_id"), table_name="teaching_assignments")
    op.drop_table("teaching_assignments")
    op.drop_index(op.f("ix_enrolments_tenant_id"), table_name="enrolments")
    op.drop_index(op.f("ix_enrolments_candidate_id"), table_name="enrolments")
    op.drop_index(op.f("ix_enrolments_arm_id"), table_name="enrolments")
    op.drop_table("enrolments")
    with op.batch_alter_table("class_arms") as batch:
        batch.drop_constraint("uq_class_arms_id_session_id_tenant_id", type_="unique")
