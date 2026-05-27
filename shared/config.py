import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("a2a_travel")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_name: str = Field(default="A2A Travel")
    app_version: str = Field(default="0.1.0")
    env: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    host: str = Field(default="0.0.0.0")

    # Ports
    gateway_port: int = Field(default=8000)
    weather_agent_port: int = Field(default=8001)
    domestic_flight_agent_port: int = Field(default=8002)
    intl_flight_agent_port: int = Field(default=8003)
    hotel_agent_port: int = Field(default=8004)
    budget_agent_port: int = Field(default=8005)

    # Agent endpoints
    weather_agent_url: str = Field(default="http://localhost:8001")
    domestic_flight_agent_url: str = Field(default="http://localhost:8002")
    intl_flight_agent_url: str = Field(default="http://localhost:8003")
    hotel_agent_url: str = Field(default="http://localhost:8004")
    budget_agent_url: str = Field(default="http://localhost:8005")

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"]
    )

    # LLM
    openrouter_base_url: str   = Field(default="https://openrouter.ai/api/v1")
    llm_api_key:      str   = Field(default="")
    llm_model:        str   = Field(default="")
    temperature:         float = Field(default=0.1)
    max_tokens:          int   = Field(default=2048)
    

    # Redis
    redis_url: str = Field(default="")
    redis_ttl: int = Field(default=3600)

    # Database
    database_url: str = Field(default="")

    # Timeouts
    default_timeout: float = Field(default=30.0)

    # External APIs
    serper_api_key: str = Field(default="")
    tripturbo_domestic_api: str = Field(default="")
    esewa_intl_api: str = Field(default="")
    default_nationality: str = Field(default="NP")

class YAMLConfigManager:
    REGISTRY: dict[str, str] = {
        "agents": "config/agents.yaml",
        "events": "config/events.yaml",
        "planner_system": "prompts/planner/system.yaml",
        "planner_routing": "prompts/planner/routing.yaml",
    }

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self._cache: dict[str, Any] = {}

    def load(self, name: str) -> dict[str, Any]:
        if name not in self.REGISTRY:
            raise KeyError(
                f"Config '{name}' not in registry. "
                f"Available: {list(self.REGISTRY)}"
            )

        if name in self._cache:
            return self._cache[name]

        path = self.base_path / self.REGISTRY[name]

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._cache[name] = data

        logger.debug(
            "Loaded config '%s' from %s",
            name,
            self.REGISTRY[name],
        )

        return data

    def reload(self, name: str) -> dict[str, Any]:
        self._cache.pop(name, None)
        return self.load(name)

    def clear_cache(self) -> None:
        self._cache.clear()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

config_manager: YAMLConfigManager = YAMLConfigManager(
    Path(__file__).parent.parent
)