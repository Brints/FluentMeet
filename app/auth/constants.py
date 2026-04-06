import enum


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    USER = "user"


class SupportedLanguage(enum.StrEnum):
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    ITALIAN = "it"
    PORTUGUESE = "pt"
