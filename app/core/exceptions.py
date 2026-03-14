from typing import Any


class FluentMeetException(Exception):
    """
    Base exception for all FluentMeet API errors.
    """

    def __init__(
        self,
        status_code: int = 500,
        code: str = "INTERNAL_SERVER_ERROR",
        message: str = "An unexpected error occurred",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(self.message)


class BadRequestException(FluentMeetException):
    def __init__(
        self,
        message: str = "Bad Request",
        code: str = "BAD_REQUEST",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(400, code, message, details)


class UnauthorizedException(FluentMeetException):
    def __init__(
        self,
        message: str = "Unauthorized",
        code: str = "UNAUTHORIZED",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(401, code, message, details)


class ForbiddenException(FluentMeetException):
    def __init__(
        self,
        message: str = "Forbidden",
        code: str = "FORBIDDEN",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(403, code, message, details)


class NotFoundException(FluentMeetException):
    def __init__(
        self,
        message: str = "Not Found",
        code: str = "NOT_FOUND",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(404, code, message, details)


class ConflictException(FluentMeetException):
    def __init__(
        self,
        message: str = "Conflict",
        code: str = "CONFLICT",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(409, code, message, details)


class InternalServerException(FluentMeetException):
    def __init__(
        self,
        message: str = "Internal Server Error",
        code: str = "INTERNAL_SERVER_ERROR",
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(500, code, message, details)
