from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dev.db"
    SECRET_KEY: str
    OPENROUTER_API_KEY: str
    OPENROUTER_API_BASE_URL: str = "https://openrouter.ai/api/v1"
    TIMEZONE: str = "America/Monterrey"
    MODEL_AGENTE: str = "nvidia/nemotron-3.5-lightning:free"
    SCHEDULER_INTERVAL_SECONDS: int = 10
    CHAT_RATE_LIMIT_PER_MINUTE: int = 60
    MAX_AUDIO_SEGUNDOS: int = 60
    MEMORIA_MENSAJES_MAX: int = 20

    model_config = ConfigDict(env_file=".env", extra="ignore")


settings = Settings()
