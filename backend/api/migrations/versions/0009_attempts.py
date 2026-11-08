"""Add exam attempts, append-only answer events and final responses.

Revision ID: 0009_attempts
Revises: 0008_exams

See docs/architecture/decisions/0003-exams.md (Exams C). Answers and responses reference their
attempt and paper item by (id, exam_id, tenant_id), so they always belong to one exam's paper.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_attempts"
down_revision = "0008_exams"
branch_labels = None
depends_on = None

IN_PROGRESS = sa.text("status = 'in_progress'")


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _belongs_to_attempt(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["attempt_id", "exam_id", "tenant_id"],
            ["exam_attempts.id", "exam_attempts.exam_id", "exam_attempts.tenant_id"],
            name=f"fk_{table}_attempt_same_exam",
        ),
        sa.ForeignKeyConstraint(
            ["paper_item_id", "exam_id", "tenant_id"],
            ["exam_paper_items.id", "exam_paper_items.exam_id", "exam_paper_items.tenant_id"],
            name=f"fk_{table}_paper_item_same_exam",
        ),
    ]


def upgrade() -> None:
    # Answers point at paper items by (id, exam_id, tenant_id), so that target comes first.
    with op.batch_alter_table("exam_paper_items") as batch:
        batch.create_unique_constraint(
            "uq_exam_paper_items_id_exam_id_tenant_id", ["id", "exam_id", "tenant_id"]
        )

    op.create_table(
        "exam_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_reason", sa.String(length=20), nullable=True),
        sa.Column("question_order", sa.JSON(), nullable=False),
        sa.Column("option_orders", sa.JSON(), nullable=False),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'submitted')", name="ck_exam_attempts_status"
        ),
        sa.CheckConstraint(
            "submitted_reason IS NULL OR submitted_reason IN ('student', 'time_up')",
            name="ck_exam_attempts_submitted_reason",
        ),
        sa.CheckConstraint("ends_at > started_at", name="ck_exam_attempts_times"),
        sa.CheckConstraint("number >= 1", name="ck_exam_attempts_number"),
        sa.ForeignKeyConstraint(
            ["candidate_id", "tenant_id"],
            ["candidates.id", "candidates.tenant_id"],
            name="fk_exam_attempts_candidate_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["exam_id", "tenant_id"],
            ["exams.id", "exams.tenant_id"],
            name="fk_exam_attempts_exam_same_tenant",
        ),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exam_id", "candidate_id", "number", name="uq_exam_attempts_exam_id_candidate_id_number"
        ),
        sa.UniqueConstraint(
            "id", "exam_id", "tenant_id", name="uq_exam_attempts_id_exam_id_tenant_id"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_exam_attempts_id_tenant_id"),
    )
    for column in ("candidate_id", "exam_id", "tenant_id"):
        op.create_index(op.f(f"ix_exam_attempts_{column}"), "exam_attempts", [column], unique=False)
    op.create_index(
        "uq_exam_attempts_one_in_progress",
        "exam_attempts",
        ["exam_id", "candidate_id"],
        unique=True,
        sqlite_where=IN_PROGRESS,
        postgresql_where=IN_PROGRESS,
    )

    op.create_table(
        "answer_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("paper_item_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("selected_option_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_answer_events_sequence"),
        *_belongs_to_attempt("answer_events"),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "sequence", name="uq_answer_events_attempt_id_sequence"),
    )
    op.create_index(
        op.f("ix_answer_events_tenant_id"), "answer_events", ["tenant_id"], unique=False
    )

    op.create_table(
        "attempt_responses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("exam_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("paper_item_id", sa.String(length=36), nullable=False),
        sa.Column("selected_option_ids", sa.JSON(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0", name="ck_attempt_responses_score"),
        *_belongs_to_attempt("attempt_responses"),
        _tenant_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id", "paper_item_id", name="uq_attempt_responses_attempt_id_paper_item_id"
        ),
    )
    for column in ("attempt_id", "tenant_id"):
        op.create_index(
            op.f(f"ix_attempt_responses_{column}"), "attempt_responses", [column], unique=False
        )


def downgrade() -> None:
    for column in ("attempt_id", "tenant_id"):
        op.drop_index(op.f(f"ix_attempt_responses_{column}"), table_name="attempt_responses")
    op.drop_table("attempt_responses")
    op.drop_index(op.f("ix_answer_events_tenant_id"), table_name="answer_events")
    op.drop_table("answer_events")
    op.drop_index("uq_exam_attempts_one_in_progress", table_name="exam_attempts")
    for column in ("candidate_id", "exam_id", "tenant_id"):
        op.drop_index(op.f(f"ix_exam_attempts_{column}"), table_name="exam_attempts")
    op.drop_table("exam_attempts")
    with op.batch_alter_table("exam_paper_items") as batch:
        batch.drop_constraint("uq_exam_paper_items_id_exam_id_tenant_id", type_="unique")
