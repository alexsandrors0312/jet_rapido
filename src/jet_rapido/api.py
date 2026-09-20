"""API de importação, revisão geográfica e matrizes pedestres."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, select
from sqlalchemy.orm import Session
import uvicorn

from .archive import validate_xlsx_archive
from .config import Settings
from .database import create_database_engine, create_session_factory
from .importer import ImportValidationError, import_workbook
from .maps import MapProviderError, WalkingMatrixProvider, build_walking_provider
from .models import DeliveryPointReview, WalkingMatrix
from .repository import (
    confirm_imported_delivery_points,
    get_delivery_point,
    get_import,
    get_route,
    get_walking_matrix,
    list_delivery_points,
    list_routes,
    list_walking_matrix_entries,
    persist_import,
    review_delivery_point,
    set_route_reviewed,
    ReviewConflict,
)
from .schemas import (
    DeliveryPointConfirmationResponse,
    DeliveryPointResponse,
    DeliveryPointReviewRequest,
    HealthResponse,
    ImportResponse,
    RouteResponse,
    RouteReviewRequest,
    RouteSummary,
    WalkingMatrixCreateRequest,
    WalkingMatrixEntryResponse,
    WalkingMatrixResponse,
    DeliveryPointReviewResponse,
)
from .walking_service import (
    GeographicReviewRequired, InvalidMatrixResult, MatrixLimitExceeded, create_walking_matrix,
    matrix_is_stale,
)


def _import_response(batch, *, idempotent: bool) -> ImportResponse:
    analysis = batch.analysis or {}
    return ImportResponse(
        id=batch.id,
        source_sha256=batch.source_sha256,
        source_filename=batch.source_filename,
        status=batch.status,
        package_count=batch.package_count,
        warning_count=batch.warning_count,
        warnings=analysis.get("warnings", []),
        split_streets=analysis.get("split_streets", []),
        geographic_issues=analysis.get("geographic_issues", []),
        routes=[RouteSummary.model_validate(route) for route in batch.routes],
        created_at=batch.created_at,
        idempotent=idempotent,
    )


async def _save_upload(upload: UploadFile, settings: Settings) -> Path:
    filename = Path(upload.filename or "").name
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=415, detail="Envie um arquivo com extensão .xlsx.")
    size = 0
    temporary = NamedTemporaryFile(prefix="jet-rapido-", suffix=".xlsx", delete=False)
    path = Path(temporary.name)
    try:
        while chunk := await upload.read(64 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="O arquivo excede o limite permitido.")
            temporary.write(chunk)
        temporary.close()
        if size == 0:
            raise HTTPException(status_code=422, detail="O arquivo está vazio.")
        return path
    except Exception:
        temporary.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def create_app(
    settings: Settings | None = None,
    walking_provider: WalkingMatrixProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    app = FastAPI(
        title="Jet Rápido API",
        version="0.3.1",
        description="Importação auditável, revisão geográfica e matrizes pedestres.",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.walking_provider = walking_provider or build_walking_provider(settings)
    static_root = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/", include_in_schema=False)
    def review_console():
        return FileResponse(static_root / "index.html")

    @app.get("/api/v1/maps/config", tags=["mapas"])
    def maps_config():
        provider = app.state.walking_provider
        return {"provider": provider.name, "quality": provider.quality,
                "profile": provider.profile, "max_matrix_points": settings.max_matrix_points}

    def matrix_response(session, matrix, idempotent=False):
        return WalkingMatrixResponse.model_validate(matrix).model_copy(update={
            "idempotent": idempotent,
            "stale": matrix_is_stale(session, matrix, app.state.walking_provider),
        })

    def get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    @app.get("/health", response_model=HealthResponse, tags=["sistema"])
    def health(session: Session = Depends(get_session)) -> HealthResponse:
        try:
            session.execute(text("SELECT 1"))
        except Exception as error:
            raise HTTPException(status_code=503, detail="Banco indisponível.") from error
        return HealthResponse(status="ok")

    @app.post(
        "/api/v1/imports",
        response_model=ImportResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["importações"],
    )
    async def create_import(
        request: Request,
        response: Response,
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> ImportResponse:
        # Content-Length inclui o envelope multipart, logo só rejeitamos quando
        # ultrapassa o limite com uma margem pequena. O fluxo continua limitado.
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > settings.max_upload_bytes + 1024 * 1024:
                raise HTTPException(status_code=413, detail="A requisição excede o limite permitido.")
        path = await _save_upload(file, settings)
        try:
            validate_xlsx_archive(
                path,
                max_entries=settings.max_xlsx_entries,
                max_uncompressed_bytes=settings.max_xlsx_uncompressed_bytes,
            )
            parsed = import_workbook(path)
            batch, idempotent = persist_import(session, parsed, Path(file.filename or "rota.xlsx").name)
            if idempotent:
                response.status_code = status.HTTP_200_OK
            return _import_response(batch, idempotent=idempotent)
        except ImportValidationError as error:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(error)) from error
        finally:
            path.unlink(missing_ok=True)

    @app.get("/api/v1/imports/{import_id}", response_model=ImportResponse, tags=["importações"])
    def read_import(import_id: str, session: Session = Depends(get_session)) -> ImportResponse:
        batch = get_import(session, import_id)
        if not batch:
            raise HTTPException(status_code=404, detail="Importação não encontrada.")
        return _import_response(batch, idempotent=False)

    @app.get("/api/v1/routes", response_model=list[RouteSummary], tags=["rotas"])
    def read_routes(
        import_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ) -> list[RouteSummary]:
        return [
            RouteSummary.model_validate(route)
            for route in list_routes(session, import_id, limit=limit, offset=offset)
        ]

    @app.get("/api/v1/routes/{route_id}", response_model=RouteResponse, tags=["rotas"])
    def read_route(route_id: str, session: Session = Depends(get_session)) -> RouteResponse:
        route = get_route(session, route_id)
        if not route:
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        return RouteResponse.model_validate(route)

    @app.patch("/api/v1/routes/{route_id}/review", response_model=RouteSummary, tags=["rotas"])
    def review_route(
        route_id: str,
        command: RouteReviewRequest,
        session: Session = Depends(get_session),
    ) -> RouteSummary:
        route = get_route(session, route_id)
        if not route:
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        return RouteSummary.model_validate(set_route_reviewed(session, route, command.reviewed))

    @app.get(
        "/api/v1/routes/{route_id}/delivery-points",
        response_model=list[DeliveryPointResponse],
        tags=["geografia"],
    )
    def read_delivery_points(
        route_id: str,
        session: Session = Depends(get_session),
    ) -> list[DeliveryPointResponse]:
        if not get_route(session, route_id):
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        return [
            DeliveryPointResponse.model_validate(point)
            for point in list_delivery_points(session, route_id)
        ]

    @app.patch(
        "/api/v1/delivery-points/{point_id}/review",
        response_model=DeliveryPointResponse,
        tags=["geografia"],
    )
    def review_point(
        point_id: str,
        command: DeliveryPointReviewRequest,
        session: Session = Depends(get_session),
    ) -> DeliveryPointResponse:
        point = get_delivery_point(session, point_id)
        if not point:
            raise HTTPException(status_code=404, detail="Ponto de entrega não encontrado.")
        try:
            updated = review_delivery_point(session, point, **command.model_dump())
        except ReviewConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return DeliveryPointResponse.model_validate(updated)

    @app.post(
        "/api/v1/routes/{route_id}/delivery-points/confirm-imported",
        response_model=DeliveryPointConfirmationResponse,
        tags=["geografia"],
    )
    def confirm_route_points(
        route_id: str,
        session: Session = Depends(get_session),
    ) -> DeliveryPointConfirmationResponse:
        if not get_route(session, route_id):
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        try:
            confirmed, points = confirm_imported_delivery_points(session, route_id)
        except ReviewConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return DeliveryPointConfirmationResponse(
            confirmed_count=confirmed,
            points=[DeliveryPointResponse.model_validate(point) for point in points],
        )

    @app.post(
        "/api/v1/routes/{route_id}/walking-matrices",
        response_model=WalkingMatrixResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["mapas"],
    )
    def compute_route_matrix(
        route_id: str,
        command: WalkingMatrixCreateRequest,
        response: Response,
        session: Session = Depends(get_session),
    ) -> WalkingMatrixResponse:
        if not get_route(session, route_id):
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        try:
            matrix, idempotent = create_walking_matrix(
                session,
                route_id=route_id,
                provider=app.state.walking_provider,
                max_points=settings.max_matrix_points,
                allow_unreviewed=command.allow_unreviewed,
            )
        except GeographicReviewRequired as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except MatrixLimitExceeded as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (MapProviderError, InvalidMatrixResult) as error:
            raise HTTPException(status_code=502, detail="Falha ao calcular a matriz pedestre.") from error
        if idempotent:
            response.status_code = status.HTTP_200_OK
        return matrix_response(session, matrix, idempotent)

    @app.get(
        "/api/v1/walking-matrices/{matrix_id}",
        response_model=WalkingMatrixResponse,
        tags=["mapas"],
    )
    def read_walking_matrix(
        matrix_id: str,
        session: Session = Depends(get_session),
    ) -> WalkingMatrixResponse:
        matrix = get_walking_matrix(session, matrix_id)
        if not matrix:
            raise HTTPException(status_code=404, detail="Matriz pedestre não encontrada.")
        return matrix_response(session, matrix)

    @app.get("/api/v1/routes/{route_id}/walking-matrices", response_model=list[WalkingMatrixResponse], tags=["mapas"])
    def list_matrices(route_id: str, limit: int = Query(20, ge=1, le=100),
                      offset: int = Query(0, ge=0), session: Session = Depends(get_session)):
        if not get_route(session, route_id):
            raise HTTPException(status_code=404, detail="Rota não encontrada.")
        matrices = session.scalars(select(WalkingMatrix).where(WalkingMatrix.route_id == route_id)
                                  .order_by(WalkingMatrix.created_at.desc(), WalkingMatrix.id)
                                  .limit(limit).offset(offset))
        return [matrix_response(session, matrix) for matrix in matrices]

    @app.get("/api/v1/delivery-points/{point_id}/reviews", response_model=list[DeliveryPointReviewResponse], tags=["geografia"])
    def review_history(point_id: str, limit: int = Query(50, ge=1, le=200),
                       offset: int = Query(0, ge=0), session: Session = Depends(get_session)):
        if not get_delivery_point(session, point_id):
            raise HTTPException(status_code=404, detail="Ponto de entrega não encontrado.")
        return list(session.scalars(select(DeliveryPointReview)
            .where(DeliveryPointReview.delivery_point_id == point_id)
            .order_by(DeliveryPointReview.revision.desc()).limit(limit).offset(offset)))

    @app.get(
        "/api/v1/walking-matrices/{matrix_id}/entries",
        response_model=list[WalkingMatrixEntryResponse],
        tags=["mapas"],
    )
    def read_walking_matrix_entries(
        matrix_id: str,
        limit: int = Query(default=1000, ge=1, le=10_000),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ) -> list[WalkingMatrixEntryResponse]:
        if not get_walking_matrix(session, matrix_id):
            raise HTTPException(status_code=404, detail="Matriz pedestre não encontrada.")
        return [
            WalkingMatrixEntryResponse.model_validate(entry)
            for entry in list_walking_matrix_entries(
                session, matrix_id, limit=limit, offset=offset
            )
        ]

    return app


app = create_app()


def run() -> None:
    uvicorn.run("jet_rapido.api:app", host="127.0.0.1", port=8000, reload=False)
