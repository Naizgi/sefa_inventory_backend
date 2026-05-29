from pydantic_settings import BaseSettings
import os
from typing import Optional

class Settings(BaseSettings):
    # MySQL Database Configuration
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "inventory_db"
    
    # Connection Pool Settings
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # Construct DATABASE_URL dynamically
    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    # Security - These MUST have values
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-minimum-32-chars")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # App
    APP_NAME: str = "Inventory Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ==================== BREVO EMAIL SETTINGS ====================
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    BREVO_SENDER_EMAIL: str = os.getenv("BREVO_SENDER_EMAIL", "minilik71@gmail.com")
    BREVO_SENDER_NAME: str = os.getenv("BREVO_SENDER_NAME", "SmartLink Inventory System")
    EMAIL_ENABLED: bool = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    
    # ==================== FALLBACK SMTP SETTINGS ====================
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "")
    
    # Frontend URL - This MUST have a value
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://smartlink-inventory.up.railway.app")
    
    # Dashboard URL (for links in emails)
    DASHBOARD_URL: str = os.getenv("DASHBOARD_URL", "https://smartlink-inventory.up.railway.app")
    
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # This ignores extra environment variables

settings = Settings()
