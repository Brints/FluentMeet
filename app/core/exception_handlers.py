import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_responses import create_error_response
from app.core.exceptions import FluentMeetException

logger = logging.getLogger(__name__)


async def fluentmeet_exception_handler(request: Request, exc: FluentMeetException):
    """
    Handler for all custom FluentMeetException exceptions.
    """
    return create_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handler for Pydantic validation errors (422 -> 400).
    """
    details = []
    for error in exc.errors():
        details.append(
            {
                "field": ".".join(str(loc) for loc in error["loc"]),
                "msg": error["msg"],
            }
        )

    return create_error_response(
        status_code=400,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=details,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handler for Starlette/FastAPI HTTP exceptions.
    """
    return create_error_response(
        status_code=exc.status_code,
        code=getattr(exc, "code", "HTTP_ERROR"),
        message=exc.detail,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Handler for all other unhandled exceptions (500).
    """
    logger.exception("Unhandled exception occurred: %s", str(exc))
    return create_error_response(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected server error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all custom exception handlers to the FastAPI app.
    """
    app.add_exception_handler(FluentMeetException, fluentmeet_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
