"""Application settings loaded from environment variables.

All configurable limits and paths live here so there are no magic numbers
scattered through the codebase.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration, read from env vars or .env file."""

    # Database connection string – works with both SQLite and Postgres
    DATABASE_URL: str = "sqlite:///./geospatial.db"

    # Upload limits
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50 MB
    UPLOAD_DIR: str = "./uploads"

    # Zip-bomb protection
    MAX_ZIP_UNCOMPRESSED_SIZE: int = 500 * 1024 * 1024  # 500 MB
    MAX_ZIP_ENTRIES: int = 1000

    # Pagination defaults
    DEFAULT_PAGE_LIMIT: int = 100
    MAX_PAGE_LIMIT: int = 1000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
