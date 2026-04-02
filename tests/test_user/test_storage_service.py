"""Unit tests for ``app.external_services.cloudinary.service.StorageService``.

All Cloudinary SDK calls are mocked — no real uploads occur.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile

from app.external_services.cloudinary.exceptions import (
    FileValidationError,
    StorageDeleteError,
    StorageUploadError,
)
from app.external_services.cloudinary.schemas import DeleteResult, UploadResult
from app.external_services.cloudinary.service import StorageService


# ── Helpers ───────────────────────────────────────────────────────────


def _make_upload_file(
    content: bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100,
    filename: str = "test.jpg",
    content_type: str = "image/jpeg",
    size: int | None = None,
) -> UploadFile:
    """Create a fake ``UploadFile`` for testing.

    Starlette's ``UploadFile.content_type`` is a read-only property
    derived from the ``content-type`` header, so we set it there.
    """
    from starlette.datastructures import Headers

    headers = Headers({"content-type": content_type})
    file = UploadFile(
        file=BytesIO(content),
        filename=filename,
        size=size if size is not None else len(content),
        headers=headers,
    )
    return file


# ── Fixture ───────────────────────────────────────────────────────────


@pytest.fixture
def storage_service() -> StorageService:
    with patch(
        "app.external_services.cloudinary.service.ensure_configured"
    ):
        return StorageService()


# ======================================================================
# Validation
# ======================================================================


class TestValidation:
    def test_rejects_invalid_image_type(self, storage_service: StorageService) -> None:
        file = _make_upload_file(content_type="application/pdf")
        with pytest.raises(FileValidationError, match="not allowed"):
            storage_service._validate_file(
                file,
                allowed_types=frozenset({"image/jpeg", "image/png"}),
                max_size_bytes=5 * 1024 * 1024,
            )

    def test_rejects_oversized_file(self, storage_service: StorageService) -> None:
        file = _make_upload_file(size=10 * 1024 * 1024)  # 10 MB
        with pytest.raises(FileValidationError, match="exceeds"):
            storage_service._validate_file(
                file,
                allowed_types=frozenset({"image/jpeg"}),
                max_size_bytes=5 * 1024 * 1024,
            )

    def test_accepts_valid_file(self, storage_service: StorageService) -> None:
        file = _make_upload_file(size=1024)
        # Should NOT raise.
        storage_service._validate_file(
            file,
            allowed_types=frozenset({"image/jpeg"}),
            max_size_bytes=5 * 1024 * 1024,
        )


# ======================================================================
# upload_image
# ======================================================================


class TestUploadImage:
    @pytest.mark.asyncio
    async def test_upload_image_success(
        self, storage_service: StorageService
    ) -> None:
        file = _make_upload_file()

        fake_response = {
            "public_id": "fluentmeet/avatars/abc",
            "secure_url": "https://res.cloudinary.com/demo/image/upload/v1/fluentmeet/avatars/abc.jpg",
            "resource_type": "image",
            "format": "jpg",
            "bytes": 12345,
            "width": 400,
            "height": 400,
        }

        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.upload",
            return_value=fake_response,
        ):
            result = await storage_service.upload_image(
                file, folder="fluentmeet/avatars"
            )

        assert isinstance(result, UploadResult)
        assert result.public_id == "fluentmeet/avatars/abc"
        assert result.secure_url.startswith("https://")
        assert result.width == 400

    @pytest.mark.asyncio
    async def test_upload_image_cloudinary_error_raises(
        self, storage_service: StorageService
    ) -> None:
        file = _make_upload_file()

        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.upload",
            side_effect=Exception("API error"),
        ):
            with pytest.raises(StorageUploadError):
                await storage_service.upload_image(
                    file, folder="fluentmeet/avatars"
                )


# ======================================================================
# upload_video
# ======================================================================


class TestUploadVideo:
    @pytest.mark.asyncio
    async def test_upload_video_success(
        self, storage_service: StorageService
    ) -> None:
        file = _make_upload_file(content_type="video/mp4", filename="clip.mp4")

        fake_response = {
            "public_id": "fluentmeet/recordings/clip",
            "secure_url": "https://res.cloudinary.com/demo/video/upload/v1/fluentmeet/recordings/clip.mp4",
            "resource_type": "video",
            "format": "mp4",
            "bytes": 500000,
        }

        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.upload",
            return_value=fake_response,
        ):
            result = await storage_service.upload_video(
                file, folder="fluentmeet/recordings"
            )

        assert isinstance(result, UploadResult)
        assert result.resource_type == "video"


# ======================================================================
# delete_asset
# ======================================================================


class TestDeleteAsset:
    @pytest.mark.asyncio
    async def test_delete_success(self, storage_service: StorageService) -> None:
        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.destroy",
            return_value={"result": "ok"},
        ):
            result = await storage_service.delete_asset("fluentmeet/avatars/abc")

        assert isinstance(result, DeleteResult)
        assert result.result == "ok"

    @pytest.mark.asyncio
    async def test_delete_not_found(self, storage_service: StorageService) -> None:
        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.destroy",
            return_value={"result": "not found"},
        ):
            result = await storage_service.delete_asset("nonexistent")

        assert result.result == "not found"

    @pytest.mark.asyncio
    async def test_delete_api_error_raises(
        self, storage_service: StorageService
    ) -> None:
        with patch(
            "app.external_services.cloudinary.service.cloudinary_uploader.destroy",
            side_effect=Exception("API error"),
        ):
            with pytest.raises(StorageDeleteError):
                await storage_service.delete_asset("fluentmeet/avatars/abc")
