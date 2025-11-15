"""
Configuration settings for MTG API
Loads environment variables and provides application settings
"""

import os
from typing import Optional
from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # API Configuration
    api_key: str = Field(..., env="API_KEY")
    environment: str = Field(default="production", env="ENVIRONMENT")
    port: int = Field(default=8000, env="PORT")
    
    # Database Configuration
    mongodb_url: str = Field(default="mongodb://localhost:27017/mtg_api", env="MONGODB_URL")
    
    # Cache Configuration
    cache_ttl: int = Field(default=3600, env="CACHE_TTL")  # 1 hour default
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # External Services
    # Scryfall doesn't require API key for basic usage
    # Add other service keys as needed
    
    # CORS Configuration
    allowed_origins: list = Field(
        default=["*"],
        env="ALLOWED_ORIGINS"
    )
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings"""
    return Settings()


# Global settings instance
settings = get_settings()