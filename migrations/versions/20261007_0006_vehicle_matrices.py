"""Matriz dirigida de rede veicular e ordem das bases por macro-parada.

Revision ID: 20261007_0006
Revises: 20261006_0005
"""
from alembic import op
import sqlalchemy as sa


revision = "20261007_0006"
down_revision = "20261006_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vehicle_matrices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("routes.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column("dataset_revision", sa.String(255), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("reachable_pairs", sa.Integer(), nullable=False),
        sa.Column("unreachable_pairs", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("route_id", "provider", "profile", "input_hash",
                            name="uq_vehicle_matrix_route_input"),
    )
    op.create_index("ix_vehicle_matrices_route_id", "vehicle_matrices", ["route_id"])
    op.create_table(
        "vehicle_matrix_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("matrix_id", sa.String(36),
                  sa.ForeignKey("vehicle_matrices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin_node_id", sa.String(64), nullable=False),
        sa.Column("destination_node_id", sa.String(64), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.UniqueConstraint("matrix_id", "origin_node_id", "destination_node_id",
                            name="uq_vehicle_matrix_entry_pair"),
    )
    op.create_index("ix_vehicle_matrix_entries_matrix_id", "vehicle_matrix_entries", ["matrix_id"])


def downgrade():
    op.drop_index("ix_vehicle_matrix_entries_matrix_id", table_name="vehicle_matrix_entries")
    op.drop_table("vehicle_matrix_entries")
    op.drop_index("ix_vehicle_matrices_route_id", table_name="vehicle_matrices")
    op.drop_table("vehicle_matrices")
