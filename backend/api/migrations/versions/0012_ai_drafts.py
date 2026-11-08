"""AI question drafts: requests, the evidence they used, drafts, and citations.

Revision ID: 0012_ai_drafts
Revises: 0011_documents

See docs/architecture/decisions/0005-ai-question-drafts.md.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_ai_drafts"
down_revision = "0011_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=True),
        sa.Column("question_types", sa.JSON(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=True),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("topic_ids", sa.JSON(), nullable=False),
        sa.Column("document_ids", sa.JSON(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("provider_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'done', 'failed')", name="ck_ai_requests_status"
        ),
        sa.CheckConstraint("count >= 1", name="ck_ai_requests_count"),
        sa.CheckConstraint("marks >= 1", name="ck_ai_requests_marks"),
        sa.ForeignKeyConstraint(
            ["requested_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_ai_requests_requested_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_ai_requests_subject_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_ai_requests_id_tenant_id"),
    )
    op.create_index(op.f("ix_ai_requests_created_at"), "ai_requests", ["created_at"], unique=False)
    op.create_index(op.f("ix_ai_requests_status"), "ai_requests", ["status"], unique=False)
    op.create_index(op.f("ix_ai_requests_subject_id"), "ai_requests", ["subject_id"], unique=False)
    op.create_index(op.f("ix_ai_requests_tenant_id"), "ai_requests", ["tenant_id"], unique=False)
    op.create_table(
        "question_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("correct_option_ids", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=True),
        sa.Column("topic_ids", sa.JSON(), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("answer_check", sa.JSON(), nullable=True),
        sa.Column("edited_by_id", sa.String(length=36), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("question_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'dismissed', 'rejected')",
            name="ck_question_drafts_status",
        ),
        sa.CheckConstraint("position >= 1", name="ck_question_drafts_position"),
        sa.ForeignKeyConstraint(
            ["edited_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_question_drafts_edited_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "tenant_id"],
            ["questions.id", "questions.tenant_id"],
            name="fk_question_drafts_question_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["ai_requests.id", "ai_requests.tenant_id"],
            name="fk_question_drafts_request_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_question_drafts_reviewed_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_question_drafts_subject_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_question_drafts_id_tenant_id"),
        sa.UniqueConstraint("request_id", "position", name="uq_question_drafts_request_position"),
    )
    op.create_index(
        op.f("ix_question_drafts_question_id"), "question_drafts", ["question_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_drafts_request_id"), "question_drafts", ["request_id"], unique=False
    )
    op.create_index(op.f("ix_question_drafts_status"), "question_drafts", ["status"], unique=False)
    op.create_index(
        op.f("ix_question_drafts_subject_id"), "question_drafts", ["subject_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_drafts_tenant_id"), "question_drafts", ["tenant_id"], unique=False
    )
    op.create_table(
        "ai_request_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id", "tenant_id"],
            ["ai_requests.id", "ai_requests.tenant_id"],
            name="fk_ai_request_sources_request_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_ai_request_sources_segment_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "label", name="uq_ai_request_sources_request_label"),
    )
    op.create_index(
        op.f("ix_ai_request_sources_request_id"), "ai_request_sources", ["request_id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_request_sources_segment_id"), "ai_request_sources", ["segment_id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_request_sources_tenant_id"), "ai_request_sources", ["tenant_id"], unique=False
    )
    op.create_table(
        "question_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("question_version_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_question_citations_position"),
        sa.ForeignKeyConstraint(
            ["question_version_id", "tenant_id"],
            ["question_versions.id", "question_versions.tenant_id"],
            name="fk_question_citations_version_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_question_citations_segment_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_version_id", "position", name="uq_question_citations_version_position"
        ),
    )
    op.create_index(
        op.f("ix_question_citations_question_version_id"),
        "question_citations",
        ["question_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_citations_segment_id"), "question_citations", ["segment_id"], unique=False
    )
    op.create_index(
        op.f("ix_question_citations_tenant_id"), "question_citations", ["tenant_id"], unique=False
    )
    op.create_table(
        "question_draft_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("draft_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_label", sa.String(length=20), nullable=False),
        sa.Column("segment_id", sa.String(length=36), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_question_draft_citations_position"),
        sa.ForeignKeyConstraint(
            ["draft_id", "tenant_id"],
            ["question_drafts.id", "question_drafts.tenant_id"],
            name="fk_question_draft_citations_draft_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id", "tenant_id"],
            ["document_segments.id", "document_segments.tenant_id"],
            name="fk_question_draft_citations_segment_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "position", name="uq_question_draft_citations_position"),
    )
    op.create_index(
        op.f("ix_question_draft_citations_draft_id"),
        "question_draft_citations",
        ["draft_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_question_draft_citations_tenant_id"),
        "question_draft_citations",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_question_draft_citations_tenant_id"), table_name="question_draft_citations"
    )
    op.drop_index(
        op.f("ix_question_draft_citations_draft_id"), table_name="question_draft_citations"
    )
    op.drop_table("question_draft_citations")
    op.drop_index(op.f("ix_question_citations_tenant_id"), table_name="question_citations")
    op.drop_index(op.f("ix_question_citations_segment_id"), table_name="question_citations")
    op.drop_index(
        op.f("ix_question_citations_question_version_id"), table_name="question_citations"
    )
    op.drop_table("question_citations")
    op.drop_index(op.f("ix_ai_request_sources_tenant_id"), table_name="ai_request_sources")
    op.drop_index(op.f("ix_ai_request_sources_segment_id"), table_name="ai_request_sources")
    op.drop_index(op.f("ix_ai_request_sources_request_id"), table_name="ai_request_sources")
    op.drop_table("ai_request_sources")
    op.drop_index(op.f("ix_question_drafts_tenant_id"), table_name="question_drafts")
    op.drop_index(op.f("ix_question_drafts_subject_id"), table_name="question_drafts")
    op.drop_index(op.f("ix_question_drafts_status"), table_name="question_drafts")
    op.drop_index(op.f("ix_question_drafts_request_id"), table_name="question_drafts")
    op.drop_index(op.f("ix_question_drafts_question_id"), table_name="question_drafts")
    op.drop_table("question_drafts")
    op.drop_index(op.f("ix_ai_requests_tenant_id"), table_name="ai_requests")
    op.drop_index(op.f("ix_ai_requests_subject_id"), table_name="ai_requests")
    op.drop_index(op.f("ix_ai_requests_status"), table_name="ai_requests")
    op.drop_index(op.f("ix_ai_requests_created_at"), table_name="ai_requests")
    op.drop_table("ai_requests")
