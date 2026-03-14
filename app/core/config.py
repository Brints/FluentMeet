import pathlib

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from pydantic_settings import BaseSettings, SettingsConfigDict


def get_version() -> str:
    pyproject_path = pathlib.Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
            return str(data.get("project", {}).get("version", "1.0.0"))
    return "1.0.0"


class Settings(BaseSettings):
    PROJECT_NAME: str = "FluentMeet"
    VERSION: str = get_version()
    API_V1_STR: str = "/api/v1"

    # Security
    SECRET_KEY: str = "placeholder_secret_key"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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

    # External Services Keys
    DEEPGRAM_API_KEY: str | None = None
    DEEPL_API_KEY: str | None = None
    VOICE_AI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, extra="ignore"
    )


settings = Settings()
