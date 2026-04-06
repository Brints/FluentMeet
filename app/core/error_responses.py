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
    details: list[ErrorDetail] = []


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """
    Helper to create a standardized JSON error response.
    """
    error_details = []
    if details:
        for detail in details:
            error_details.append(
                ErrorDetail(
                    field=detail.get("field"),
                    message=detail.get("msg") or detail.get("message") or "Unknown error",
                )
            )

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
