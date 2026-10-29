from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "VeloShelf Backend"
    DATABASE_URL: str
    SECRET_KEY: str = "super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Redis — points at the local Docker container
    REDIS_URL: str = "redis://localhost:6379/0"
    # Cache TTL in seconds for availability aggregates (1 hour default)
    AVAILABILITY_CACHE_TTL: int = 3600

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()