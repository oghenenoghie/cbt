"""Add exams: the editable exam, its classes and items, and the frozen paper; and exam coordinators.

Revision ID: 0008_exams
Revises: 0007_passages

See docs/architecture/decisions/0003-exams.md. Composite foreign keys keep every link inside one
school. Subjects, terms, levels, arms, questions and passages that exams use can't be deleted.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_exams"
down_revision = "0007_passages"
branch_labels = None
depends_on = None


def _exam_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["exam_id", "tenant_id"], ["exams.id", "exams.tenant_id"], name=name, ondelete="CASCADE"
    )


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def upgrade() -> None:
    # Exam coordinators: a designation on staff accounts. Batch mode so SQLite can add the check.
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "is_exam_coordinator", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch.create_check_constraint(
            "ck_users_exam_coordinator_is_staff",
            "NOT is_exam_coordinator OR role IN ('school_admin', 'teacher')",
        )

    # Exam papers pin passage versions, so they need an (id, tenant_id) target first.
    with op.batch_alter_table("passage_versions") as batch:
        batch.create_unique_constraint("uq_passage_versions_id_tenant_id", ["id", "tenant_id"])

    op.create_table(
        "exams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("term_id", sa.String(length=36), nullable=False),
        sa.Column("level_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("shuffle_questions", sa.Boolean(), nullable=False),
        sa.Column("shuffle_options", sa.Boolean(), nullable=False),
        sa.Column("results_release", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("copied_from_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "results_release IN ('teacher', 'immediate')", name="ck_exams_results_release"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'published', 'withdrawn')", name="ck_exams_status"
        ),
        sa.CheckConstraint("closes_at > opens_at", name="ck_exams_window"),
        sa.CheckConstraint(
            "duration_minutes >= 1 AND duration_minutes <= 600", name="ck_exams_duration"
        ),
        sa.CheckConstraint("max_attempts >= 1 AND max_attempts <= 10", name="ck_exams_attempts"),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_exams_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["level_id", "tenant_id"],
            ["class_levels.id", "class_levels.tenant_id"],
            name="fk_exams_level_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_exams_reviewed_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_exams_subject_same_tenant",
        ),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["term_id", "tenant_id"],
            ["terms.id", "terms.tenant_id"],
            name="fk_exams_term_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_exams_id_tenant_id"),
    )
    for column in ("created_by_id", "status", "subject_id", "tenant_id", "term_id"):
        op.create_index(op.f(f"ix_exams_{column}"), "exams", [column], unique=False)

    op.create_table(
        "exam_arms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("arm_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["arm_id", "tenant_id"],
            ["class_arms.id", "class_arms.tenant_id"],
            name="fk_exam_arms_arm_same_tenant",
        ),
        _exam_fk("fk_exam_arms_exam_same_tenant"),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "arm_id", name="uq_exam_arms_exam_id_arm_id"),
    )
    op.create_index(op.f("ix_exam_arms_arm_id"), "exam_arms", ["arm_id"], unique=False)
    op.create_index(op.f("ix_exam_arms_tenant_id"), "exam_arms", ["tenant_id"], unique=False)

    op.create_table(
        "exam_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=True),
        sa.Column("passage_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "(question_id IS NULL) <> (passage_id IS NULL)", name="ck_exam_items_one_kind"
        ),
        sa.CheckConstraint("position >= 1", name="ck_exam_items_position"),
        _exam_fk("fk_exam_items_exam_same_tenant"),
        sa.ForeignKeyConstraint(
            ["passage_id", "tenant_id"],
            ["passages.id", "passages.tenant_id"],
            name="fk_exam_items_passage_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_exam_items_question_same_tenant",
        ),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "passage_id", name="uq_exam_items_exam_id_passage_id"),
        sa.UniqueConstraint("exam_id", "position", name="uq_exam_items_exam_id_position"),
        sa.UniqueConstraint("exam_id", "question_id", name="uq_exam_items_exam_id_question_id"),
    )
    for column in ("passage_id", "question_id", "tenant_id"):
        op.create_index(op.f(f"ix_exam_items_{column}"), "exam_items", [column], unique=False)

    op.create_table(
        "exam_paper_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("block", sa.Integer(), nullable=False),
        sa.Column("question_version_id", sa.String(length=36), nullable=False),
        sa.Column("passage_version_id", sa.String(length=36), nullable=True),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("block >= 1", name="ck_exam_paper_items_block"),
        sa.CheckConstraint("marks >= 1", name="ck_exam_paper_items_marks"),
        sa.CheckConstraint("position >= 1", name="ck_exam_paper_items_position"),
        _exam_fk("fk_exam_paper_items_exam_same_tenant"),
        sa.ForeignKeyConstraint(
            ["passage_version_id", "tenant_id"],
            ["passage_versions.id", "passage_versions.tenant_id"],
            name="fk_exam_paper_items_passage_version_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["question_version_id", "tenant_id"],
            ["question_versions.id", "question_versions.tenant_id"],
            name="fk_exam_paper_items_question_version_same_tenant",
        ),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "position", name="uq_exam_paper_items_exam_id_position"),
    )
    for column in ("exam_id", "question_version_id", "tenant_id"):
        op.create_index(
            op.f(f"ix_exam_paper_items_{column}"), "exam_paper_items", [column], unique=False
        )


def downgrade() -> None:
    for column in ("exam_id", "question_version_id", "tenant_id"):
        op.drop_index(op.f(f"ix_exam_paper_items_{column}"), table_name="exam_paper_items")
    op.drop_table("exam_paper_items")
    for column in ("passage_id", "question_id", "tenant_id"):
        op.drop_index(op.f(f"ix_exam_items_{column}"), table_name="exam_items")
    op.drop_table("exam_items")
    op.drop_index(op.f("ix_exam_arms_tenant_id"), table_name="exam_arms")
    op.drop_index(op.f("ix_exam_arms_arm_id"), table_name="exam_arms")
    op.drop_table("exam_arms")
    for column in ("created_by_id", "status", "subject_id", "tenant_id", "term_id"):
        op.drop_index(op.f(f"ix_exams_{column}"), table_name="exams")
    op.drop_table("exams")
    with op.batch_alter_table("passage_versions") as batch:
        batch.drop_constraint("uq_passage_versions_id_tenant_id", type_="unique")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_exam_coordinator_is_staff", type_="check")
        batch.drop_column("is_exam_coordinator")
