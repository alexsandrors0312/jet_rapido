"""Cria importações, rotas e pacotes.

Revision ID: 20260919_0001
Revises:
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260919_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("sheet_name", sa.String(255), nullable=False),
        sa.Column("declared_dimension", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "routes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("original_stop_count", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_batch_id", "external_id", name="uq_route_import_external"),
    )
    op.create_index("ix_routes_import_batch_id", "routes", ["import_batch_id"])
    op.create_table(
        "packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tracking_id", sa.String(255), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("original_sequence", sa.Integer(), nullable=True),
        sa.Column("original_stop", sa.Integer(), nullable=True),
        sa.Column("address", sa.String(1000), nullable=False),
        sa.Column("neighborhood", sa.String(255), nullable=False),
        sa.Column("city", sa.String(255), nullable=False),
        sa.Column("postal_code", sa.String(32), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("street_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("import_batch_id", "tracking_id", name="uq_package_import_tracking"),
    )
    op.create_index("ix_packages_import_batch_id", "packages", ["import_batch_id"])
    op.create_index("ix_packages_route_id", "packages", ["route_id"])
    op.create_index("ix_packages_street_key", "packages", ["street_key"])


def downgrade() -> None:
    op.drop_index("ix_packages_street_key", table_name="packages")
    op.drop_index("ix_packages_route_id", table_name="packages")
    op.drop_index("ix_packages_import_batch_id", table_name="packages")
    op.drop_table("packages")
    op.drop_index("ix_routes_import_batch_id", table_name="routes")
    op.drop_table("routes")
    op.drop_table("import_batches")
