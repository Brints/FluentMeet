"""Logging sanitization module.

Automatically replaces control characters and dynamically truncates values
to prevent log injection.
"""

import re
from collections.abc import Iterable


class LogSanitizer:
    """Sanitizes user-controlled values before they are written to logs."""

    _CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def __init__(self, max_length: int = 256) -> None:
        self._max_length = max_length

    def sanitize(self, value: object) -> str:
        text = str(value)
        text = text.replace("\r", r"\r").replace("\n", r"\n").replace("\t", r"\t")
        text = self._CONTROL_CHARS.sub("?", text)
        if len(text) <= self._max_length:
            return text

        return f"{text[: self._max_length]}...<truncated>"

    def sanitize_many(self, values: Iterable[object]) -> tuple[str, ...]:
        return tuple(self.sanitize(value) for value in values)


log_sanitizer = LogSanitizer()


def sanitize_for_log(value: object) -> str:
    return log_sanitizer.sanitize(value)


def sanitize_log_args(*values: object) -> tuple[str, ...]:
    return log_sanitizer.sanitize_many(values)
