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
