"""Transações e consultas da etapa de importação."""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .geography import delivery_point_key, haversine_meters
from .models import (
    DeliveryPoint, DeliveryPointReview, ImportBatch, Package, Route, WalkingMatrix, WalkingMatrixEntry, new_uuid,
)


def get_import_by_hash(session: Session, source_sha256: str) -> ImportBatch | None:
    return session.scalar(
        select(ImportBatch)
        .where(ImportBatch.source_sha256 == source_sha256)
        .options(selectinload(ImportBatch.routes))
    )


def get_import(session: Session, import_id: str) -> ImportBatch | None:
    return session.scalar(
        select(ImportBatch)
        .where(ImportBatch.id == import_id)
        .options(selectinload(ImportBatch.routes))
    )


def get_route(session: Session, route_id: str) -> Route | None:
    return session.scalar(
        select(Route).where(Route.id == route_id).options(selectinload(Route.packages))
    )


def get_delivery_point(session: Session, point_id: str) -> DeliveryPoint | None:
    return session.scalar(
        select(DeliveryPoint)
        .where(DeliveryPoint.id == point_id)
        .options(selectinload(DeliveryPoint.packages))
    )


def list_delivery_points(session: Session, route_id: str) -> list[DeliveryPoint]:
    return list(session.scalars(
        select(DeliveryPoint)
        .where(DeliveryPoint.route_id == route_id)
        .options(selectinload(DeliveryPoint.packages))
        .order_by(DeliveryPoint.original_address, DeliveryPoint.id)
    ))


def list_routes(
    session: Session,
    import_id: str | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Route]:
    statement = select(Route).order_by(Route.created_at.desc(), Route.external_id).limit(limit).offset(offset)
    if import_id:
        statement = statement.where(Route.import_batch_id == import_id)
    return list(session.scalars(statement))


def persist_import(session: Session, result: dict, filename: str) -> tuple[ImportBatch, bool]:
    source_hash = result["source"]["sha256"]
    existing = get_import_by_hash(session, source_hash)
    if existing:
        return existing, True

    by_route: dict[str, list[dict]] = defaultdict(list)
    for package in result["packages"]:
        by_route[package["route_id"]].append(package)

    geographic_issues: list[dict] = []
    points_by_route_and_address: dict[tuple[str, str], DeliveryPoint] = {}
    batch = ImportBatch(
        id=new_uuid(),
        source_sha256=source_hash,
        source_filename=filename[:255],
        sheet_name=result["source"]["sheet"][:255],
        declared_dimension=result["source"]["declared_dimension"][:64],
        schema_version=result["schema_version"],
        package_count=result["summary"]["packages"],
        warning_count=0,
        analysis={},
    )
    session.add(batch)
    for external_id, packages in sorted(by_route.items()):
        route = Route(
            id=new_uuid(),
            import_batch=batch,
            external_id=external_id,
            package_count=len(packages),
            original_stop_count=len({p["original_stop"] for p in packages if p["original_stop"] is not None}),
        )
        session.add(route)
        for item in packages:
            address_key = delivery_point_key(
                item["address"], item["neighborhood"], item["city"], item["postal_code"]
            )
            group_key = (external_id, address_key)
            point = points_by_route_and_address.get(group_key)
            if point is None:
                point = DeliveryPoint(
                    id=new_uuid(),
                    import_batch=batch,
                    route=route,
                    address_key=address_key,
                    original_address=item["address"],
                    original_neighborhood=item["neighborhood"],
                    original_city=item["city"],
                    original_postal_code=item["postal_code"],
                    imported_latitude=item["latitude"],
                    imported_longitude=item["longitude"],
                    effective_latitude=item["latitude"],
                    effective_longitude=item["longitude"],
                )
                points_by_route_and_address[group_key] = point
                session.add(point)
            else:
                difference = haversine_meters(
                    point.imported_latitude, point.imported_longitude,
                    item["latitude"], item["longitude"],
                )
                if difference > 15:
                    geographic_issues.append({
                        "code": "ADDRESS_COORDINATE_CONFLICT",
                        "route_id": external_id,
                        "delivery_point_id": point.id,
                        "source_row": item["source_row"],
                        "distance_m": round(difference, 1),
                    })
            session.add(Package(
                id=new_uuid(),
                import_batch_id=batch.id,
                route=route,
                delivery_point=point,
                tracking_id=item["tracking_id"],
                source_row=item["source_row"],
                original_sequence=item["original_sequence"],
                original_stop=item["original_stop"],
                address=item["address"],
                neighborhood=item["neighborhood"],
                city=item["city"],
                postal_code=item["postal_code"],
                latitude=item["latitude"],
                longitude=item["longitude"],
                street_key=item["street_key"],
            ))
    batch.warning_count = len(result["warnings"]) + len(geographic_issues)
    batch.analysis = {
        "warnings": result["warnings"],
        "split_streets": result["split_streets"],
        "geographic_issues": geographic_issues,
    }
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # Outra requisição pode ter gravado o mesmo hash entre SELECT e COMMIT.
        existing = get_import_by_hash(session, source_hash)
        if existing:
            return existing, True
        raise
    return get_import(session, batch.id) or batch, False


def set_route_reviewed(session: Session, route: Route, reviewed: bool) -> Route:
    route.reviewed_at = datetime.now(timezone.utc) if reviewed else None
    session.commit()
    session.refresh(route)
    return route


def review_delivery_point(
    session: Session,
    point: DeliveryPoint,
    *,
    review_status: str,
    review_source: str,
    review_note: str | None,
    latitude: float | None,
    longitude: float | None,
    expected_revision: int | None = None,
    commit: bool = True,
) -> DeliveryPoint:
    revision = point.revision
    if expected_revision is not None and expected_revision != revision:
        raise ReviewConflict("O ponto foi alterado. Recarregue antes de salvar.")
    if review_status == "corrected" and (latitude is None or longitude is None):
        raise ValueError("Coordenadas obrigatórias para correção.")
    before = review_snapshot(point)
    values = dict(
        effective_latitude=latitude if review_status == "corrected" else point.imported_latitude,
        effective_longitude=longitude if review_status == "corrected" else point.imported_longitude,
        review_status=review_status,
        review_source=review_source,
        review_note=review_note,
        reviewed_at=datetime.now(timezone.utc),
        revision=revision + 1,
    )
    changed = session.execute(
        update(DeliveryPoint).where(DeliveryPoint.id == point.id, DeliveryPoint.revision == revision)
        .values(**values).execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise ReviewConflict("O ponto foi alterado. Recarregue antes de salvar.")
    session.refresh(point)
    session.add(DeliveryPointReview(
        delivery_point_id=point.id, revision=point.revision,
        before=before, after=review_snapshot(point),
    ))
    if commit:
        session.commit()
    return get_delivery_point(session, point.id) or point


class ReviewConflict(ValueError):
    pass


def review_snapshot(point: DeliveryPoint) -> dict:
    return {key: getattr(point, key) for key in (
        "effective_latitude", "effective_longitude", "review_status", "review_source", "review_note",
    )}


def confirm_imported_delivery_points(session: Session, route_id: str) -> tuple[int, list[DeliveryPoint]]:
    points = list_delivery_points(session, route_id)
    confirmed = 0
    for point in points:
        if point.review_status == "pending":
            review_delivery_point(
                session, point, review_status="confirmed", review_source="operator",
                review_note=None, latitude=None, longitude=None, commit=False,
            )
            confirmed += 1
    session.commit()
    return confirmed, list_delivery_points(session, route_id)


def get_walking_matrix(session: Session, matrix_id: str) -> WalkingMatrix | None:
    return session.get(WalkingMatrix, matrix_id)


def find_walking_matrix(
    session: Session,
    *,
    route_id: str,
    provider: str,
    profile: str,
    input_hash: str,
) -> WalkingMatrix | None:
    return session.scalar(select(WalkingMatrix).where(
        WalkingMatrix.route_id == route_id,
        WalkingMatrix.provider == provider,
        WalkingMatrix.profile == profile,
        WalkingMatrix.input_hash == input_hash,
    ))


def save_walking_matrix(
    session: Session,
    *,
    route_id: str,
    input_hash: str,
    computation,
    input_snapshot: dict,
) -> tuple[WalkingMatrix, bool]:
    existing = find_walking_matrix(
        session,
        route_id=route_id,
        provider=computation.provider,
        profile=computation.profile,
        input_hash=input_hash,
    )
    if existing:
        return existing, True
    reachable_pairs = sum(cell.reachable for cell in computation.cells)
    matrix = WalkingMatrix(
        id=new_uuid(),
        route_id=route_id,
        provider=computation.provider,
        profile=computation.profile,
        quality=computation.quality,
        input_hash=input_hash,
        input_snapshot=input_snapshot,
        point_count=len({cell.origin_id for cell in computation.cells}),
        reachable_pairs=reachable_pairs,
        unreachable_pairs=len(computation.cells) - reachable_pairs,
        dataset_version=computation.dataset_version,
    )
    session.add(matrix)
    for cell in computation.cells:
        session.add(WalkingMatrixEntry(
            matrix=matrix,
            origin_delivery_point_id=cell.origin_id,
            destination_delivery_point_id=cell.destination_id,
            distance_m=cell.distance_m,
            duration_s=cell.duration_s,
            reachable=cell.reachable,
            error_code=cell.error_code,
        ))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = find_walking_matrix(
            session,
            route_id=route_id,
            provider=computation.provider,
            profile=computation.profile,
            input_hash=input_hash,
        )
        if existing:
            return existing, True
        raise
    return matrix, False


def list_walking_matrix_entries(
    session: Session,
    matrix_id: str,
    *,
    limit: int,
    offset: int,
) -> list[WalkingMatrixEntry]:
    return list(session.scalars(
        select(WalkingMatrixEntry)
        .where(WalkingMatrixEntry.matrix_id == matrix_id)
        .order_by(
            WalkingMatrixEntry.origin_delivery_point_id,
            WalkingMatrixEntry.destination_delivery_point_id,
        )
        .limit(limit)
        .offset(offset)
    ))
