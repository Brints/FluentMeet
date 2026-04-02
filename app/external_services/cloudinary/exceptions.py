"""Exceptions specific to the Cloudinary storage module."""

from app.core.exceptions import BadRequestException, InternalServerException


class FileValidationError(BadRequestException):
    """Raised when an uploaded file fails MIME type or size validation."""

    def __init__(self, message: str, code: str = "FILE_VALIDATION_ERROR") -> None:
        super().__init__(message=message, code=code)


class StorageUploadError(InternalServerException):
    """Raised when the Cloudinary API returns an error during upload."""

    def __init__(
        self,
        message: str = "Failed to upload file to cloud storage.",
        code: str = "STORAGE_UPLOAD_ERROR",
    ) -> None:
        super().__init__(message=message, code=code)


class StorageDeleteError(InternalServerException):
    """Raised when the Cloudinary API returns an error during deletion."""

    def __init__(
        self,
        message: str = "Failed to delete file from cloud storage.",
        code: str = "STORAGE_DELETE_ERROR",
    ) -> None:
        super().__init__(message=message, code=code)
