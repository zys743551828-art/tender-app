"""Opt-in HTTP surface for tests; production main/router files remain untouched."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.work_context_routes import router
from packages.contracts import work_context_api
from packages.domain.runtime import DomainError


def context_app():
    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError):
        return JSONResponse(
            {
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "details": error.details,
            },
            status_code=error.status,
            headers={"Cache-Control": "private, no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, _error: RequestValidationError):
        return await domain_error(
            request, DomainError("INVALID_REQUEST", "请求字段或标识不符合协议", 422)
        )

    return app


def openapi(app):
    actual = app.openapi()
    actual.setdefault("components", {}).setdefault("schemas", {})
    actual["components"].setdefault("securitySchemes", {})["SessionCookie"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "session",
    }
    work_context_api.extend_openapi(actual)
    return actual
