import pathlib
import tomllib

from pydantic_settings import BaseSettings, SettingsConfigDict


def get_version() -> str:
    pyproject_path = pathlib.Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
            return str(data.get("project", {}).get("version", "1.0.0"))
    return "1.0.0"


class Settings(BaseSettings):
    PROJECT_NAME: str = "FluentMeet"
    VERSION: str = get_version()
    API_V1_STR: str = "/routers/v1"

    # Security
    SECRET_KEY: str = "placeholder_secret_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Account Lockout
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_DAYS: int = 5

    # Database
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "fluentmeet"
    DATABASE_URL: str | None = None

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_PRODUCER_ACK: str = "all"
    KAFKA_CONSUMER_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_MAX_RETRIES: int = 3
    KAFKA_RETRY_BACKOFF_MS: int = 1000
    KAFKA_EMAIL_CONSUMER_GROUP_ID: str = "email-worker"

    # External Services Keys
    DEEPGRAM_API_KEY: str | None = None
    DEEPL_API_KEY: str | None = None
    VOICE_AI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # Mailgun Email Service
    MAILGUN_API_KEY: str | None = None
    MAILGUN_DOMAIN: str | None = None
    MAILGUN_FROM_ADDRESS: str = "no-reply@fluentmeet.com"
    MAILGUN_TIMEOUT_SECONDS: float = 10.0

    # URL used in transactional email links
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


settings = Settings()
