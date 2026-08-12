from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "VeriLens"
    APP_VERSION: str = "1.0.0"
    DB_PATH: str = "./data/verilens.db"
    UPLOAD_DIR: str = "./data/uploads"
    CORS_ORIGINS: list[str] = ["*"]

    # Optional API keys (leave empty to use free/scraped paths)
    BING_API_KEY: str = ""
    NEWSAPI_KEY: str = ""
    GOOGLE_FACTCHECK_KEY: str = ""

    TIMEOUT: float = 25.0
    MAX_UPLOAD_MB: int = 15
    MAX_VIDEO_MB: int = 300
    FRAME_DIR: str = "./data/frames"

    class Config:
        env_prefix = "VERILENS_"


settings = Settings()
