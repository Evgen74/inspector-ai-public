"""Internal ml-api (90 §3.4 N): FastAPI on localhost, called only by the Node API (apps/api, module render).

    POST /v1/render/page-info  {file_id, page_no}                         → PageInfo JSON (+ tile pyramid)
    POST /v1/render/page       {file_id, page_no, dpi? | width?, bbox?}   → image/png (whole page or crop)
    POST /v1/render/crop       {file_id, page_no, bbox, dpi? | width?}    → image/png (bbox required)
    POST /v1/render/tile       {file_id, page_no, level, x, y}            → image/png (Deep Zoom tile)
    GET  /health

Errors are application/problem+json with the codes of packages/contracts/errors.yaml. With
INSPECTOR_ML_API_TOKEN set, every /v1 call needs the same value in `X-Service-Token`. Train objects only.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from inspector_common.errors import InspectorError
from inspector_ml_api import __version__
from inspector_ml_api.files import FileResolver, RegistryFileResolver
from inspector_ml_api.render import PageRenderer, RenderRequestError

SERVICE = "inspector-ml-api"
PROBLEM = "application/problem+json; charset=utf-8"

FileId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^!/\\]+$")]
PageNo = Annotated[int, Field(ge=1, le=100_000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageRef(_Strict):
    file_id: FileId
    page_no: PageNo


class ImageRequest(PageRef):
    dpi: Annotated[float | None, Field(ge=9, le=600)] = None
    width: Annotated[int | None, Field(ge=16, le=8192)] = None
    bbox: Annotated[list[float] | None, Field(min_length=4, max_length=4)] = None


class CropRequest(ImageRequest):
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]


class TileRequest(PageRef):
    level: Annotated[int, Field(ge=0, le=40)]
    x: Annotated[int, Field(ge=0, le=100_000)]
    y: Annotated[int, Field(ge=0, le=100_000)]


def _problem(request: Request, err: InspectorError, status: int | None = None) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or secrets.token_hex(8)
    body = err.problem(instance=request.url.path, request_id=request_id, status=status)
    return JSONResponse(
        body, status_code=body["status"], media_type=PROBLEM, headers={"X-Request-Id": request_id}
    )


def create_app(
    resolver: FileResolver | None = None,
    renderer: PageRenderer | None = None,
    *,
    token: str | None = None,
) -> FastAPI:
    resolver = resolver or RegistryFileResolver()
    renderer = renderer or PageRenderer()
    token = token if token is not None else (os.environ.get("INSPECTOR_ML_API_TOKEN") or None)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        renderer.close()  # release MuPDF documents before the interpreter exits

    app = FastAPI(
        title="Инспектор ИИ — ml-api",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.renderer = renderer
    app.state.resolver = resolver

    @app.middleware("http")
    async def service_token(request: Request, call_next: Any) -> Response:
        if token and request.url.path.startswith("/v1/"):
            given = request.headers.get("x-service-token", "")
            if not secrets.compare_digest(given, token):
                return _problem(request, InspectorError("UNAUTHENTICATED"))
        return await call_next(request)

    @app.exception_handler(InspectorError)
    async def inspector_error(request: Request, err: InspectorError) -> JSONResponse:
        return _problem(request, err)

    @app.exception_handler(RenderRequestError)
    async def render_error(request: Request, err: RenderRequestError) -> JSONResponse:
        details = dict(err.details)
        if err.code == "PAGE_NOT_FOUND":
            details.setdefault("file_id", request.state.file_id if hasattr(request.state, "file_id") else "?")
        return _problem(request, InspectorError(err.code, **details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, err: RequestValidationError) -> JSONResponse:
        first = err.errors()[0] if err.errors() else {}
        where = "/".join(str(p) for p in first.get("loc", ()) if p != "body")
        summary = f"{where or 'body'} — {first.get('msg', 'некорректный запрос')}"
        return _problem(request, InspectorError("VALIDATION_ERROR", summary=summary))

    def _resolve(request: Request, ref: PageRef):
        request.state.file_id = ref.file_id
        return resolver.resolve(ref.file_id)

    def _png(png: bytes, file_sha256: str, started: float, extra: dict[str, str] | None = None) -> Response:
        headers = {
            "X-File-Sha256": file_sha256,
            "X-Render-Ms": str(round((time.perf_counter() - started) * 1000)),
            **(extra or {}),
        }
        return Response(content=png, media_type="image/png", headers=headers)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": SERVICE, "version": __version__, "renderer": renderer.stats}

    @app.post("/v1/render/page-info")
    def page_info(body: PageRef, request: Request) -> dict[str, Any]:
        pdf = _resolve(request, body)
        info = renderer.info(pdf.path, body.page_no)
        return {"file_id": pdf.file_id, "object_id": pdf.object_id, "sha256": pdf.sha256, **info.to_json()}

    def _image(body: ImageRequest, request: Request) -> Response:
        started = time.perf_counter()
        pdf = _resolve(request, body)
        bbox = tuple(body.bbox) if body.bbox else None
        png, meta = renderer.render_image(pdf.path, body.page_no, dpi=body.dpi, width=body.width, bbox=bbox)  # type: ignore[arg-type]
        return _png(
            png,
            pdf.sha256,
            started,
            {
                "X-Render-Width": str(meta["width_px"]),
                "X-Render-Height": str(meta["height_px"]),
                "X-Render-Dpi": str(meta["dpi"]),
                "X-Render-Capped": "true" if meta["capped"] else "false",
            },
        )

    @app.post("/v1/render/page")
    def render_page(body: ImageRequest, request: Request) -> Response:
        return _image(body, request)

    @app.post("/v1/render/crop")
    def render_crop(body: CropRequest, request: Request) -> Response:
        return _image(body, request)

    @app.post("/v1/render/tile")
    def render_tile(body: TileRequest, request: Request) -> Response:
        started = time.perf_counter()
        pdf = _resolve(request, body)
        png = renderer.render_tile(pdf.path, body.page_no, body.level, body.x, body.y)
        return _png(png, pdf.sha256, started)

    return app
