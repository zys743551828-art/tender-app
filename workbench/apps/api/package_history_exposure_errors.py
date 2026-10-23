"""Optional bridge conflicts for existing API routes; no eligibility switches."""

import inspect

import psycopg
from fastapi.responses import JSONResponse


def install(app):
    """Preserve the application's ordinary database handler for other errors."""
    if getattr(app.state, "package_history_exposure_errors_installed", False):
        return
    previous = app.exception_handlers.get(psycopg.Error)

    async def bridge_database_error(request, error):
        message = error.diag.message_primary or ""
        if error.sqlstate == "55000" and message == "package_history_bridge_final_already_exposed":
            return JSONResponse(
                {
                    "code": "PACKAGE_HISTORY_FINAL_ALREADY_EXPOSED",
                    "message": "此工程或关联原始字节已进入最终评估，不能重新准入、重选或开始新的研究用途。",
                    "retryable": False,
                    "details": {"exposure_scope": "complete_registered_cross_namespace_closure"},
                },
                status_code=409,
                headers={"Cache-Control": "private,no-store"},
            )
        if previous is not None:
            response = previous(request, error)
            return await response if inspect.isawaitable(response) else response
        return JSONResponse(
            {
                "code": "DATABASE_TRANSACTION_FAILED",
                "message": "资料事务未完成，请保留输入并重试。",
            },
            status_code=503,
            headers={"Cache-Control": "private,no-store"},
        )

    app.add_exception_handler(psycopg.Error, bridge_database_error)
    app.state.package_history_exposure_errors_installed = True
