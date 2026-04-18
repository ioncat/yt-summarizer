from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    debug: bool = True

    database_path: str = "../data/db/yt_summarizer.sqlite"

    cors_origins: list[str] = ["http://localhost:3000"]

    subtitle_extraction_timeout: int = 30
    text_formatting_timeout: int = 10
    max_retries: int = 3

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
