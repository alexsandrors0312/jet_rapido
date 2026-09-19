"""Adiciona revisão geográfica e matrizes pedestres.

Revision ID: 20260919_0002
Revises: 20260919_0001
"""
from collections.abc import Sequence
from datetime import datetime, timezone
from hashlib import sha256
import unicodedata
from uuid import uuid4

from alembic import context, op
import sqlalchemy as sa


revision: str = "20260919_0002"
down_revision: str | None = "20260919_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(character for character in value if not unicodedata.combining(character))
        .casefold()
        .split()
    )


def _address_key(row: sa.RowMapping) -> str:
    identity = "|".join(
        _normalized(str(row[field]))
        for field in ("address", "neighborhood", "city", "postal_code")
    )
    return sha256(identity.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "delivery_points",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "import_batch_id", sa.String(36),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "route_id", sa.String(36),
            sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("address_key", sa.String(64), nullable=False),
        sa.Column("original_address", sa.String(1000), nullable=False),
        sa.Column("original_neighborhood", sa.String(255), nullable=False),
        sa.Column("original_city", sa.String(255), nullable=False),
        sa.Column("original_postal_code", sa.String(32), nullable=False),
        sa.Column("imported_latitude", sa.Float(), nullable=False),
        sa.Column("imported_longitude", sa.Float(), nullable=False),
        sa.Column("effective_latitude", sa.Float(), nullable=False),
        sa.Column("effective_longitude", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("review_source", sa.String(32), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("route_id", "address_key", name="uq_delivery_point_route_address"),
    )
    op.create_index("ix_delivery_points_import_batch_id", "delivery_points", ["import_batch_id"])
    op.create_index("ix_delivery_points_route_id", "delivery_points", ["route_id"])

    with op.batch_alter_table("packages") as batch_op:
        batch_op.add_column(sa.Column("delivery_point_id", sa.String(36), nullable=True))
        batch_op.create_index("ix_packages_delivery_point_id", ["delivery_point_id"])
        batch_op.create_foreign_key(
            "fk_packages_delivery_point_id", "delivery_points", ["delivery_point_id"], ["id"],
            ondelete="RESTRICT",
        )

    if context.is_offline_mode():
        # O SQL offline não pode ler resultados em Python. Para PostgreSQL, o
        # backfill é inteiramente relacional e mantém um ponto por endereço/rota.
        if op.get_context().dialect.name != "postgresql":
            raise RuntimeError("O backfill offline desta migração é suportado somente para PostgreSQL.")
        normalized = (
            "md5(lower(trim(address)) || '|' || lower(trim(neighborhood)) || '|' || "
            "lower(trim(city)) || '|' || lower(trim(postal_code)))"
        )
        op.execute(sa.text(f"""
            WITH candidates AS (
                SELECT p.*, {normalized} AS generated_address_key
                FROM packages p
            ), firsts AS (
                SELECT DISTINCT ON (route_id, generated_address_key) *
                FROM candidates
                ORDER BY route_id, generated_address_key, source_row, id
            ), identified AS (
                SELECT *, md5(route_id || '|' || generated_address_key) AS generated_id
                FROM firsts
            )
            INSERT INTO delivery_points (
                id, import_batch_id, route_id, address_key, original_address,
                original_neighborhood, original_city, original_postal_code, imported_latitude,
                imported_longitude, effective_latitude, effective_longitude, review_status,
                review_source, review_note, reviewed_at, created_at, updated_at
            )
            SELECT
                substr(generated_id, 1, 8) || '-' || substr(generated_id, 9, 4) || '-' ||
                substr(generated_id, 13, 4) || '-' || substr(generated_id, 17, 4) || '-' ||
                substr(generated_id, 21, 12),
                import_batch_id, route_id, generated_address_key, address, neighborhood, city,
                postal_code, latitude, longitude, latitude, longitude, 'pending', NULL, NULL,
                NULL, created_at, created_at
            FROM identified
        """))
        op.execute(sa.text(f"""
            UPDATE packages AS p
            SET delivery_point_id = dp.id
            FROM delivery_points AS dp
            WHERE dp.route_id = p.route_id AND dp.address_key = {normalized}
        """))
    else:
        connection = op.get_bind()
        packages = connection.execute(sa.text(
            "SELECT id, import_batch_id, route_id, address, neighborhood, city, postal_code, "
            "latitude, longitude, created_at FROM packages ORDER BY source_row, id"
        )).mappings()
        points: dict[tuple[str, str], str] = {}
        for package in packages:
            key = _address_key(package)
            group_key = (str(package["route_id"]), key)
            point_id = points.get(group_key)
            if point_id is None:
                point_id = str(uuid4())
                points[group_key] = point_id
                timestamp = package["created_at"] or datetime.now(timezone.utc)
                connection.execute(sa.text(
                    "INSERT INTO delivery_points ("
                    "id, import_batch_id, route_id, address_key, original_address, "
                    "original_neighborhood, original_city, original_postal_code, imported_latitude, "
                    "imported_longitude, effective_latitude, effective_longitude, review_status, "
                    "review_source, review_note, reviewed_at, created_at, updated_at"
                    ") VALUES ("
                    ":id, :import_batch_id, :route_id, :address_key, :address, :neighborhood, :city, "
                    ":postal_code, :latitude, :longitude, :latitude, :longitude, 'pending', "
                    "NULL, NULL, NULL, :created_at, :updated_at)"
                ), {
                    "id": point_id,
                    "import_batch_id": package["import_batch_id"],
                    "route_id": package["route_id"],
                    "address_key": key,
                    "address": package["address"],
                    "neighborhood": package["neighborhood"],
                    "city": package["city"],
                    "postal_code": package["postal_code"],
                    "latitude": package["latitude"],
                    "longitude": package["longitude"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                })
            connection.execute(
                sa.text("UPDATE packages SET delivery_point_id = :point_id WHERE id = :package_id"),
                {"point_id": point_id, "package_id": package["id"]},
            )

    with op.batch_alter_table("packages") as batch_op:
        batch_op.alter_column("delivery_point_id", existing_type=sa.String(36), nullable=False)

    op.create_table(
        "walking_matrices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "route_id", sa.String(36),
            sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("quality", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("reachable_pairs", sa.Integer(), nullable=False),
        sa.Column("unreachable_pairs", sa.Integer(), nullable=False),
        sa.Column("dataset_version", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "route_id", "provider", "profile", "input_hash",
            name="uq_walking_matrix_route_input",
        ),
    )
    op.create_index("ix_walking_matrices_route_id", "walking_matrices", ["route_id"])
    op.create_table(
        "walking_matrix_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "matrix_id", sa.String(36),
            sa.ForeignKey("walking_matrices.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "origin_delivery_point_id", sa.String(36),
            sa.ForeignKey("delivery_points.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "destination_delivery_point_id", sa.String(36),
            sa.ForeignKey("delivery_points.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.UniqueConstraint(
            "matrix_id", "origin_delivery_point_id", "destination_delivery_point_id",
            name="uq_walking_matrix_entry_pair",
        ),
    )
    op.create_index("ix_walking_matrix_entries_matrix_id", "walking_matrix_entries", ["matrix_id"])
    op.create_index(
        "ix_walking_matrix_entries_origin_delivery_point_id",
        "walking_matrix_entries", ["origin_delivery_point_id"],
    )
    op.create_index(
        "ix_walking_matrix_entries_destination_delivery_point_id",
        "walking_matrix_entries", ["destination_delivery_point_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_walking_matrix_entries_destination_delivery_point_id",
        table_name="walking_matrix_entries",
    )
    op.drop_index(
        "ix_walking_matrix_entries_origin_delivery_point_id",
        table_name="walking_matrix_entries",
    )
    op.drop_index("ix_walking_matrix_entries_matrix_id", table_name="walking_matrix_entries")
    op.drop_table("walking_matrix_entries")
    op.drop_index("ix_walking_matrices_route_id", table_name="walking_matrices")
    op.drop_table("walking_matrices")
    with op.batch_alter_table("packages") as batch_op:
        batch_op.drop_constraint("fk_packages_delivery_point_id", type_="foreignkey")
        batch_op.drop_index("ix_packages_delivery_point_id")
        batch_op.drop_column("delivery_point_id")
    op.drop_index("ix_delivery_points_route_id", table_name="delivery_points")
    op.drop_index("ix_delivery_points_import_batch_id", table_name="delivery_points")
    op.drop_table("delivery_points")
