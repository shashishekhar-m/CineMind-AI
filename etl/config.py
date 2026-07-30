from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    app_name: str = Field(alias="APP_NAME")

    environment: str = Field(alias="ENVIRONMENT")

    postgres_host: str = Field(alias="POSTGRES_HOST")
    postgres_port: int = Field(alias="POSTGRES_PORT")
    postgres_database: str = Field(alias="POSTGRES_DATABASE")
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")

    tmdb_api_key: str = Field(default="", alias="TMDB_API_KEY")

    log_level: str = Field(alias="LOG_LEVEL")

    batch_size: int = Field(alias="BATCH_SIZE")

    max_workers: int = Field(alias="MAX_WORKERS")

    imdb_data_path: Path = Field(alias="IMDB_DATA_PATH")
    tmdb_data_path: Path = Field(alias="TMDB_DATA_PATH")
    processed_data_path: Path = Field(alias="PROCESSED_DATA_PATH")
    log_path: Path = Field(alias="LOG_PATH")

    model_config = {
        "case_sensitive": False,
        "extra": "ignore",
    }

    @property
    def sqlalchemy_database_uri(self) -> str:
        return (
            f"postgresql+psycopg2://"
            f"{self.postgres_user}:"
            f"{self.postgres_password}@"
            f"{self.postgres_host}:"
            f"{self.postgres_port}/"
            f"{self.postgres_database}"
        )


settings = Settings()