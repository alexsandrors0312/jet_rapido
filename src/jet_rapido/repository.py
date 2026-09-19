"""Transações e consultas da etapa de importação."""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import ImportBatch, Package, Route, new_uuid


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

    batch = ImportBatch(
        id=new_uuid(),
        source_sha256=source_hash,
        source_filename=filename[:255],
        sheet_name=result["source"]["sheet"][:255],
        declared_dimension=result["source"]["declared_dimension"][:64],
        schema_version=result["schema_version"],
        package_count=result["summary"]["packages"],
        warning_count=len(result["warnings"]),
        analysis={"warnings": result["warnings"], "split_streets": result["split_streets"]},
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
            session.add(Package(
                id=new_uuid(),
                import_batch_id=batch.id,
                route=route,
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
