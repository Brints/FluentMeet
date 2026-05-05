"""Standardized API Error Response architectures module.

Defines Pydantic representations guaranteeing frontend API structures
respond homogenously.
"""

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str
    details: list[Any] = []


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Helper to create a standardized JSON error response.

    Args:
        status_code (int): HTTP status code targeting fastAPI.
        code (str): Application specific string error code identifier.
        message (str): Human-readable exception descriptor.
        details (list[dict[str, Any]] | None): Additional list of error dictionaries
            defining problem fields. Defaults to None.

    Returns:
        JSONResponse: Standardized FastAPI JSON response strictly
        bound to ErrorResponse schema.
    """
    error_details = []
    if details:
        for detail in details:
            if "msg" in detail and "field" in detail:
                # Map FastApi Validation Errors explicitly
                error_details.append(
                    {
                        "field": detail.get("field"),
                        "message": detail.get("msg") or "Validation error",
                    }
                )
            else:
                # Preserve standard custom metadata cleanly
                error_details.append(detail)

    response_content = ErrorResponse(
        status="error",
        code=code,
        message=message,
        details=error_details,
    )

    return JSONResponse(
        status_code=status_code,
        content=response_content.model_dump(),
    )
