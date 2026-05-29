from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ==================== DATABASE ====================
    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    @property
    def DATABASE_URL(self) -> str:
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

<<<<<<< HEAD
    # ==================== SECURITY ====================
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ==================== APP ====================
    APP_NAME: str = "IRailway Inventory"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ==================== BREVO ====================
    BREVO_API_KEY: Optional[str] = None
    BREVO_SENDER_EMAIL: str
    BREVO_SENDER_NAME: str = "SmartLink"
    EMAIL_ENABLED: bool = True

    # ==================== SMTP ====================
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: Optional[int] = 465
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None

    # ==================== URLS ====================
    DASHBOARD_URL: str
    FRONTEND_URL: str

    # ==================== ENV ====================
    ENVIRONMENT: str = "development"
=======
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
>>>>>>> cce9ba9a6d31acaa35036fa61e0c0541d56d0805

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # This ignores extra environment variables

<<<<<<< HEAD

settings = Settings()
=======
settings = Settings()
>>>>>>> cce9ba9a6d31acaa35036fa61e0c0541d56d0805
