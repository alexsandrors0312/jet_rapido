"""Rascunhos de macro-paradas e revisão humana.

Revision ID: 20261001_0004
Revises: 20260919_0003
"""
from alembic import op
import sqlalchemy as sa


revision = "20261001_0004"
down_revision = "20260919_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "macro_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("walking_matrix_id", sa.String(36), sa.ForeignKey("walking_matrices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("max_packages", sa.Integer(), nullable=False),
        sa.Column("max_pairwise_m", sa.Float(), nullable=False),
        sa.Column("max_base_roundtrip_m", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("route_id", "input_hash", name="uq_macro_plan_route_input"),
    )
    op.create_index("ix_macro_plans_route_id", "macro_plans", ["route_id"])
    op.create_index("ix_macro_plans_walking_matrix_id", "macro_plans", ["walking_matrix_id"])
    op.create_table(
        "macro_stops",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("macro_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("candidate_base_point_id", sa.String(36), sa.ForeignKey("delivery_points.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("max_pairwise_m", sa.Float(), nullable=False),
        sa.Column("max_base_roundtrip_m", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_macro_stop_plan_ordinal"),
    )
    op.create_index("ix_macro_stops_plan_id", "macro_stops", ["plan_id"])
    op.create_table(
        "macro_stop_points",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("macro_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stop_id", sa.String(36), sa.ForeignKey("macro_stops.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delivery_point_id", sa.String(36), sa.ForeignKey("delivery_points.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("plan_id", "delivery_point_id", name="uq_macro_plan_point"),
    )
    op.create_index("ix_macro_stop_points_stop_id", "macro_stop_points", ["stop_id"])


def downgrade():
    op.drop_table("macro_stop_points")
    op.drop_table("macro_stops")
    op.drop_table("macro_plans")
