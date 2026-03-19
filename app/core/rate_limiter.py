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
    return create_error_response(
        status_code=429,
        code="RATE_LIMIT_EXCEEDED",
        message="Too many requests. Please try again later.",
    )
