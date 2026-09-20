"""Histórico de revisão e entradas imutáveis das matrizes.

Revision ID: 20260919_0003
Revises: 20260919_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20260919_0003"
down_revision = "20260919_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("delivery_points", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("walking_matrices", sa.Column("input_snapshot", sa.JSON(), nullable=True))
    op.create_table(
        "delivery_point_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("delivery_point_id", sa.String(36), sa.ForeignKey("delivery_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("delivery_point_id", "revision", name="uq_point_review_revision"),
    )
    op.create_index("ix_delivery_point_reviews_delivery_point_id", "delivery_point_reviews", ["delivery_point_id"])


def downgrade():
    op.drop_table("delivery_point_reviews")
    op.drop_column("walking_matrices", "input_snapshot")
    op.drop_column("delivery_points", "revision")
