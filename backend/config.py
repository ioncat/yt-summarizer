from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    debug: bool = True

    database_path: str = "../data/db/yt_summarizer.sqlite"

    cors_origins: list[str] = ["http://localhost:3000"]

    cookies_path: str = "../data/www.youtube.com_cookies.txt"
    ytdlp_path: str = "C:/ytdlp/yt-dlp.exe"

    subtitle_extraction_timeout: int = 30
    text_formatting_timeout: int = 10
    max_retries: int = 3

    # Ollama (Phase 1.5 text cleanup + Phase 2 summarization)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
