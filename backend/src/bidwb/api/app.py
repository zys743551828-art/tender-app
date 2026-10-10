"""FastAPI 应用工厂：中间件、统一错误响应、路由装配。"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from bidwb import __version__, db
from bidwb.api import routes_auth, routes_files, routes_projects, routes_report, routes_review, routes_tasks
from bidwb.config import Settings, get_settings
from bidwb.errors import DomainError
from bidwb.logs import configure_logging, get_logger
from bidwb.runtime import Container, build_api_container

log = get_logger("bidwb.api")
_REQUEST_ID = re.compile(r"^[a-z][a-z0-9_-]{7,80}$")


def _error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", "req_unknown"),
        "retryable": retryable,
        "details": details or {},
    }
    return JSONResponse(body, status_code=status, headers=headers)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctr = container or build_api_container(settings)
        app.state.container = ctr
        log.info("api_started", version=__version__, environment=settings.environment)
        try:
            yield
        finally:
            if container is None:
                ctr.close()

    app = FastAPI(
        title="施组工作台 API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.environment == "production" else "/api/openapi.json",
    )
    if container is not None:  # 测试注入：不经 lifespan 也可用
        app.state.container = container

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = supplied if _REQUEST_ID.fullmatch(supplied) else f"req_{uuid.uuid4().hex[:16]}"
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request.state.request_id)
        started = time.perf_counter()
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        # 访问日志只记录路径，不记录查询串（可能含令牌）与请求体。
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        if exc.status >= 500:
            log.error("domain_error", code=exc.code)
        return _error_response(request, exc.status, exc.code, exc.message, retryable=exc.retryable, details=exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 只返回字段位置与原因，不回显请求值（可能包含不该出现在日志或响应里的内容）。
        fields = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "reason": e["msg"]} for e in exc.errors()]
        return _error_response(request, 422, "invalid_contract", "请求内容不符合接口要求", details={"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 416: "range_not_satisfiable"}
        return _error_response(
            request,
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            "请求的资源不存在或方法不被允许",
            headers=dict(exc.headers or {}),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", exc_info=exc, path=request.url.path)
        return _error_response(request, 500, "internal_error", "服务内部错误，请携带请求编号联系维护人员")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    def readyz(request: Request) -> Response:
        ctr: Container = request.app.state.container
        try:
            with ctr.engine.connect() as conn:
                db.scalar(conn, "SELECT 1")
        except Exception:
            log.warning("readyz_database_unavailable")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    for module in (routes_auth, routes_projects, routes_files, routes_review, routes_report, routes_tasks):
        app.include_router(module.router, prefix="/api/v1")
    return app
