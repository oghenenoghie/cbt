"""Learning materials: documents, their uploaded versions, extracted segments and topic tags.

Revision ID: 0011_documents
Revises: 0010_results

See docs/architecture/decisions/0004-learning-materials.md.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_documents"
down_revision = "0010_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_documents_created_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "tenant_id"],
            ["subjects.id", "subjects.tenant_id"],
            name="fk_documents_subject_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_documents_id_tenant_id"),
    )
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index(op.f("ix_documents_subject_id"), "documents", ["subject_id"], unique=False)
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)
    op.create_table(
        "document_topics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            name="fk_document_topics_document_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["topic_id", "tenant_id"],
            ["topics.id", "topics.tenant_id"],
            name="fk_document_topics_topic_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "topic_id", name="uq_document_topics_document_id_topic_id"
        ),
    )
    op.create_index(
        op.f("ix_document_topics_tenant_id"), "document_topics", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_topics_topic_id"), "document_topics", ["topic_id"], unique=False
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("uploaded_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("reviewed_by_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('pdf', 'docx', 'txt')", name="ck_document_versions_kind"),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'extracted', 'failed', 'approved', 'rejected')",
            name="ck_document_versions_status",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_document_versions_size"),
        sa.CheckConstraint("version >= 1", name="ck_document_versions_version"),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id"],
            ["documents.id", "documents.tenant_id"],
            name="fk_document_versions_document_same_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_document_versions_reviewed_by_same_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_document_versions_uploaded_by_same_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_document_versions_document_id_version"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_document_versions_id_tenant_id"),
    )
    op.create_index(
        op.f("ix_document_versions_document_id"), "document_versions", ["document_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_versions_status"), "document_versions", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_document_versions_tenant_id"), "document_versions", ["tenant_id"], unique=False
    )
    op.create_table(
        "document_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('page', 'section', 'lines')", name="ck_document_segments_kind"
        ),
        sa.CheckConstraint("method IN ('text', 'ocr')", name="ck_document_segments_method"),
        sa.CheckConstraint("position >= 1", name="ck_document_segments_position"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id", "tenant_id"],
            ["document_versions.id", "document_versions.tenant_id"],
            name="fk_document_segments_version_same_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_document_segments_id_tenant_id"),
        sa.UniqueConstraint("version_id", "position", name="uq_document_segments_version_position"),
    )
    op.create_index(
        op.f("ix_document_segments_tenant_id"), "document_segments", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_segments_version_id"), "document_segments", ["version_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_segments_version_id"), table_name="document_segments")
    op.drop_index(op.f("ix_document_segments_tenant_id"), table_name="document_segments")
    op.drop_table("document_segments")
    op.drop_index(op.f("ix_document_versions_tenant_id"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_status"), table_name="document_versions")
    op.drop_index(op.f("ix_document_versions_document_id"), table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index(op.f("ix_document_topics_topic_id"), table_name="document_topics")
    op.drop_index(op.f("ix_document_topics_tenant_id"), table_name="document_topics")
    op.drop_table("document_topics")
    op.drop_index(op.f("ix_documents_tenant_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_subject_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_table("documents")
