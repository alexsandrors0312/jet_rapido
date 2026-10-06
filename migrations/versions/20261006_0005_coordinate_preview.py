"""Modo explícito de proposta por coordenadas efetivas.

Revision ID: 20261006_0005
Revises: 20261001_0004
"""
from alembic import op
import sqlalchemy as sa


revision = "20261006_0005"
down_revision = "20261001_0004"
branch_labels = None
depends_on = None


def upgrade():
    # Propostas existentes foram criadas no modo estrito; o modo por coordenadas
    # precisa ser solicitado explicitamente na criação e nunca é presumido.
    op.add_column(
        "macro_plans",
        sa.Column("planning_mode", sa.String(32), nullable=False, server_default="strict"),
    )


def downgrade():
    op.drop_column("macro_plans", "planning_mode")
