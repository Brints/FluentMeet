"""General-purpose Cloudinary storage service.

Supports uploading and deleting images, videos, and raw/static files.
Each public method validates the file before forwarding it to the
Cloudinary SDK, keeping the rest of the application free from
cloud-storage concerns.
"""

import logging
from typing import Any

from cloudinary import uploader as cloudinary_uploader
from fastapi import UploadFile

from app.core.config import settings
from app.external_services.cloudinary.config import ensure_configured
from app.external_services.cloudinary.constants import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_STATIC_TYPES,
    ALLOWED_VIDEO_TYPES,
    MB,
    RESOURCE_TYPE_IMAGE,
    RESOURCE_TYPE_RAW,
    RESOURCE_TYPE_VIDEO,
)
from app.external_services.cloudinary.exceptions import (
    FileValidationError,
    StorageDeleteError,
    StorageUploadError,
)
from app.external_services.cloudinary.schemas import DeleteResult, UploadResult

logger = logging.getLogger(__name__)


class StorageService:
    """Facade over the Cloudinary SDK for uploading and deleting assets.

    Usage::

        svc = StorageService()
        result = await svc.upload_image(file, folder="fluentmeet/avatars")
    """

    def __init__(self) -> None:
        ensure_configured()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_image(
        self,
        file: UploadFile,
        folder: str,
        public_id: str | None = None,
        transformation: dict[str, Any] | None = None,
    ) -> UploadResult:
        """Upload an image file to Cloudinary.

        Args:
            file: The uploaded file (JPEG, PNG, WebP, GIF, SVG).
            folder: Cloudinary folder path.
            public_id: Optional custom public ID.
            transformation: Optional Cloudinary transformation dict.

        Returns:
            An :class:`UploadResult` with the public URL and metadata.
        """
        max_bytes = settings.CLOUDINARY_MAX_IMAGE_SIZE_MB * MB
        self._validate_file(file, ALLOWED_IMAGE_TYPES, max_bytes)
        return await self._upload(
            file,
            resource_type=RESOURCE_TYPE_IMAGE,
            folder=folder,
            public_id=public_id,
            transformation=transformation,
        )

    async def upload_video(
        self,
        file: UploadFile,
        folder: str,
        public_id: str | None = None,
    ) -> UploadResult:
        """Upload a video file to Cloudinary.

        Args:
            file: The uploaded video (MP4, WebM, MOV, AVI).
            folder: Cloudinary folder path.
            public_id: Optional custom public ID.

        Returns:
            An :class:`UploadResult` with the public URL and metadata.
        """
        max_bytes = settings.CLOUDINARY_MAX_VIDEO_SIZE_MB * MB
        self._validate_file(file, ALLOWED_VIDEO_TYPES, max_bytes)
        return await self._upload(
            file,
            resource_type=RESOURCE_TYPE_VIDEO,
            folder=folder,
            public_id=public_id,
        )

    async def upload_raw(
        self,
        file: UploadFile,
        folder: str,
        public_id: str | None = None,
    ) -> UploadResult:
        """Upload a raw / static file to Cloudinary (PDF, ZIP, etc.).

        Args:
            file: The uploaded file.
            folder: Cloudinary folder path.
            public_id: Optional custom public ID.

        Returns:
            An :class:`UploadResult` with the public URL and metadata.
        """
        max_bytes = settings.CLOUDINARY_MAX_IMAGE_SIZE_MB * MB  # reuse image limit
        self._validate_file(file, ALLOWED_STATIC_TYPES, max_bytes)
        return await self._upload(
            file,
            resource_type=RESOURCE_TYPE_RAW,
            folder=folder,
            public_id=public_id,
        )

    async def delete_asset(
        self,
        public_id: str,
        resource_type: str = RESOURCE_TYPE_IMAGE,
    ) -> DeleteResult:
        """Delete an asset from Cloudinary by its public ID.

        Args:
            public_id: The Cloudinary public ID of the asset.
            resource_type: One of ``image``, ``video``, ``raw``.

        Returns:
            A :class:`DeleteResult` indicating success or not-found.
        """
        try:
            response = cloudinary_uploader.destroy(
                public_id, resource_type=resource_type
            )
            result = response.get("result", "error")
            logger.info(
                "Deleted asset %s (type=%s): %s", public_id, resource_type, result
            )
            return DeleteResult(public_id=public_id, result=result)
        except Exception as exc:
            logger.error("Cloudinary delete failed for %s: %s", public_id, exc)
            raise StorageDeleteError() from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_file(
        file: UploadFile,
        allowed_types: frozenset[str],
        max_size_bytes: int,
    ) -> None:
        """Validate MIME type and declared size of an uploaded file."""
        content_type = file.content_type or ""
        if content_type not in allowed_types:
            allowed = ", ".join(sorted(allowed_types))
            raise FileValidationError(
                message=(
                    f"File type '{content_type}' is not allowed."
                    f" Accepted types: {allowed}."
                ),
                code="INVALID_FILE_TYPE",
            )

        # ``file.size`` is populated by FastAPI/Starlette after reading
        # the multipart body.  It may be ``None`` for streamed uploads,
        # so we fall-back to the Content-Length hint when available.
        size = file.size or 0
        if size > max_size_bytes:
            max_mb = max_size_bytes // MB
            raise FileValidationError(
                message=f"File size exceeds the {max_mb} MB limit.",
                code="FILE_TOO_LARGE",
            )

    @staticmethod
    async def _upload(
        file: UploadFile,
        *,
        resource_type: str,
        folder: str,
        public_id: str | None = None,
        transformation: dict[str, Any] | None = None,
    ) -> UploadResult:
        """Perform the actual Cloudinary upload."""
        contents = await file.read()
        upload_options: dict[str, Any] = {
            "resource_type": resource_type,
            "folder": folder,
            "overwrite": True,
        }
        if public_id:
            upload_options["public_id"] = public_id
        if transformation:
            upload_options["transformation"] = transformation

        try:
            response = cloudinary_uploader.upload(contents, **upload_options)
        except Exception as exc:
            logger.error("Cloudinary upload failed: %s", exc)
            raise StorageUploadError() from exc

        return UploadResult(
            public_id=response["public_id"],
            secure_url=response["secure_url"],
            resource_type=response.get("resource_type", resource_type),
            format=response.get("format"),
            bytes=response.get("bytes", 0),
            width=response.get("width"),
            height=response.get("height"),
        )


# ── Module-level singleton & FastAPI dependency ───────────────────────
_storage_service: StorageService | None = None


def get_storage_service() -> StorageService | None:
    """FastAPI dependency returning the module-level StorageService."""
    global _storage_service  # noqa: PLW0603
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
