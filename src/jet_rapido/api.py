"""API da etapa 2: importar, consultar e revisar rotas."""

from collections.abc import Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session
import uvicorn

from .archive import validate_xlsx_archive
from .config import Settings
from .database import create_database_engine, create_session_factory
from .importer import ImportValidationError, import_workbook
from .repository import get_import, get_route, list_routes, persist_import, set_route_reviewed
from .schemas import (
    HealthResponse, ImportResponse, RouteResponse, RouteReviewRequest, RouteSummary,
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    app = FastAPI(
        title="Jet Rápido API",
        version="0.2.0",
        description="Importação auditável de rotas last-mile.",
    )
    app.state.settings = settings
    app.state.engine = engine

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

    return app


app = create_app()


def run() -> None:
    uvicorn.run("jet_rapido.api:app", host="127.0.0.1", port=8000, reload=False)
