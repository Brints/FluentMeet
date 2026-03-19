from app.core.sanitize import LogSanitizer, sanitize_for_log, sanitize_log_args


def test_sanitize_for_log_escapes_control_characters() -> None:
    value = "hello\nworld\r\t\x01"

    result = sanitize_for_log(value)

    assert result == r"hello\nworld\r\t?"


def test_log_sanitizer_truncates_long_values() -> None:
    sanitizer = LogSanitizer(max_length=5)

    result = sanitizer.sanitize("abcdefgh")

    assert result == "abcde...<truncated>"


def test_sanitize_log_args_returns_sanitized_tuple() -> None:
    values = sanitize_log_args("email\n@example.com", 42)

    assert values == (r"email\n@example.com", "42")
