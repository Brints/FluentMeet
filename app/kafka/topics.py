from typing import Final

# Email notification topics
NOTIFICATIONS_EMAIL: Final = "notifications.email"

# Media processing topics
MEDIA_UPLOAD: Final = "media.upload"
MEDIA_PROCESS_RECORDING: Final = "media.process_recording"

# Real-time audio pipeline topics
AUDIO_RAW: Final = "audio.raw"
AUDIO_SYNTHESIZED: Final = "audio.synthesized"

# Real-time text pipeline topics
TEXT_ORIGINAL: Final = "text.original"
TEXT_TRANSLATED: Final = "text.translated"

# Dead-letter topics
DLQ_PREFIX: Final = "dlq."

# All standard topics that should be auto-created on startup
TOPICS_TO_CREATE: Final = [
    NOTIFICATIONS_EMAIL,
    MEDIA_UPLOAD,
    MEDIA_PROCESS_RECORDING,
    AUDIO_RAW,
    AUDIO_SYNTHESIZED,
    TEXT_ORIGINAL,
    TEXT_TRANSLATED,
]
