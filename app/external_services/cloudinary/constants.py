"""Constants for the Cloudinary storage module."""

# ── Allowed MIME types ────────────────────────────────────────────────
ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/svg+xml",
    }
)

ALLOWED_VIDEO_TYPES: frozenset[str] = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-msvideo",
    }
)

ALLOWED_STATIC_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/zip",
        "text/plain",
        "text/csv",
    }
)

# ── Cloudinary resource types ─────────────────────────────────────────
RESOURCE_TYPE_IMAGE = "image"
RESOURCE_TYPE_VIDEO = "video"
RESOURCE_TYPE_RAW = "raw"

# ── Default folder structure ──────────────────────────────────────────
FOLDER_AVATARS = "fluentmeet/avatars"
FOLDER_RECORDINGS = "fluentmeet/recordings"
FOLDER_UPLOADS = "fluentmeet/uploads"

# ── Size constants (bytes) ────────────────────────────────────────────
MB = 1024 * 1024
