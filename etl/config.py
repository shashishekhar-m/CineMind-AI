from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()

# etl/ package directory. Used to anchor default data paths so behavior
# doesn't depend on the process's current working directory (running
# `python pipeline.py` from etl/ vs. `python etl/pipeline.py` from the
# repo root must resolve to the same files).
_ETL_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Centralized, environment-driven configuration for the ETL layer.

    All values are overridable via environment variables / `.env`
    (see `etl/.env.example`). Defaults are safe for local development
    only and must be overridden for any shared or production environment.
    """

    app_name: str = Field(default="CineMind AI", alias="APP_NAME")

    environment: str = Field(default="development", alias="ENVIRONMENT")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_database: str = Field(default="cinemind", alias="POSTGRES_DATABASE")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", alias="POSTGRES_PASSWORD")
    postgres_schema: str = Field(default="cinemind", alias="POSTGRES_SCHEMA")

    tmdb_api_key: str = Field(default="", alias="TMDB_API_KEY")

    tmdb_api_base_url: str = Field(
        default="https://api.themoviedb.org/3",
        alias="TMDB_API_BASE_URL",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Master prompt (docs/00_MASTER_PROMPT.md) mandates a default chunk
    # size of 5000 for streaming ETL reads/batches.
    batch_size: int = Field(default=5000, alias="BATCH_SIZE")

    max_workers: int = Field(default=4, alias="MAX_WORKERS")

    imdb_data_path: Path = Field(default=_ETL_DIR / "data" / "imdb" / "raw", alias="IMDB_DATA_PATH")
    tmdb_data_path: Path = Field(default=_ETL_DIR / "data" / "tmdb", alias="TMDB_DATA_PATH")
    processed_data_path: Path = Field(
        default=_ETL_DIR / "data" / "processed", alias="PROCESSED_DATA_PATH"
    )
    log_path: Path = Field(default=_ETL_DIR / "data" / "logs", alias="LOG_PATH")

    checkpoint_path: Path = Field(
        default=_ETL_DIR / "checkpoints", alias="CHECKPOINT_PATH"
    )

    model_config = {
        "case_sensitive": False,
        "extra": "ignore",
    }

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.postgres_user}:"
            f"{self.postgres_password}@"
            f"{self.postgres_host}:"
            f"{self.postgres_port}/"
            f"{self.postgres_database}"
        )


settings = Settings()