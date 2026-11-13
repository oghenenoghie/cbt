"""More kinds of learning material: PowerPoint, Excel, CSV and photos, and their segments.

Revision ID: 0013_more_material_kinds
Revises: 0012_ai_drafts

See docs/architecture/decisions/0004-learning-materials.md (stages B and C). Only the CHECK
constraints on the kinds change. SQLite can't alter a constraint, so batch mode rebuilds the
two tables there; PostgreSQL drops and recreates the constraints.
"""

from alembic import op

revision = "0013_more_material_kinds"
down_revision = "0012_ai_drafts"
branch_labels = None
depends_on = None

OLD_FILE_KINDS = "kind IN ('pdf', 'docx', 'txt')"
NEW_FILE_KINDS = "kind IN ('pdf', 'docx', 'pptx', 'xlsx', 'csv', 'txt', 'jpeg', 'png')"
OLD_SEGMENT_KINDS = "kind IN ('page', 'section', 'lines')"
NEW_SEGMENT_KINDS = "kind IN ('page', 'section', 'slide', 'sheet', 'rows', 'lines', 'image')"


def _replace(table: str, name: str, condition: str) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(name, condition)


def upgrade() -> None:
    _replace("document_versions", "ck_document_versions_kind", NEW_FILE_KINDS)
    _replace("document_segments", "ck_document_segments_kind", NEW_SEGMENT_KINDS)


def downgrade() -> None:
    # Fails while any version or segment of a new kind exists: delete those first.
    _replace("document_segments", "ck_document_segments_kind", OLD_SEGMENT_KINDS)
    _replace("document_versions", "ck_document_versions_kind", OLD_FILE_KINDS)
