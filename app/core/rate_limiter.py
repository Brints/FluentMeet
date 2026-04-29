"""API Route Rate Limiter configuration module.

Leverages slowapi to configure IP-based throttling across global routes natively.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.error_responses import create_error_response

limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exception_handler(
    _request: Request,
    _exc: RateLimitExceeded,
) -> JSONResponse:
    """Handle Rate Limit errors converting them to standardized HTTP 429 schemas.

    Args:
        _request (Request): Starlette HTTP request mapping object.
        _exc (RateLimitExceeded): Fastapi Limiter exceeded bounds exception
            tracking model.

    Returns:
        JSONResponse: Standardized HTTP 429 JSONResponse entity.
    """
    return create_error_response(
        status_code=429,
        code="RATE_LIMIT_EXCEEDED",
        message="Too many requests. Please try again later.",
    )
