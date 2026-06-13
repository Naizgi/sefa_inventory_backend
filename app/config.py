from pydantic_settings import BaseSettings
import os
from typing import Optional
from pathlib import Path

class Settings(BaseSettings):
    # Database Type Selection
    # Set to "sqlite" or "mysql" - defaults to sqlite for Railway
    DATABASE_TYPE: str = os.getenv("DATABASE_TYPE", "sqlite")
    
    # ==================== SQLITE CONFIGURATION ====================
    # SQLite database directory (important for Railway volume)
    DB_DIR: str = os.getenv("DB_DIR", "/app/data" if os.path.exists("/app") else ".")
    DB_FILENAME: str = os.getenv("DB_FILENAME", "sifa_inventory.db")
    
    # ==================== MYSQL DATABASE CONFIGURATION ====================
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "inventory_db"
    
    # Connection Pool Settings (for MySQL)
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    # Construct DATABASE_URL dynamically based on DATABASE_TYPE
    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_TYPE == "sqlite":
            # Ensure directory exists
            Path(self.DB_DIR).mkdir(parents=True, exist_ok=True)
            
            # SQLite database path
            db_path = os.path.join(self.DB_DIR, self.DB_FILENAME)
            
            # SQLite connection string with recommended settings
            # timeout=30: Wait 30 seconds for locked database
            # check_same_thread=False: Allow multiple threads (needed for FastAPI)
            return f"sqlite:///{db_path}?check_same_thread=False&timeout=30"
        else:
            # MySQL connection string
            return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    # SQLite-specific connection arguments
    @property
    def SQLITE_CONNECT_ARGS(self) -> dict:
        if self.DATABASE_TYPE == "sqlite":
            return {
                "check_same_thread": False,
                "timeout": 30
            }
        return {}

    # Security - These MUST have values
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-minimum-32-chars")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # App
    APP_NAME: str = "Sefa Inventory Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

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
    
    # Scheduler enabled (only for production, disable for development if needed)
    ENABLE_SCHEDULER: bool = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # This ignores extra environment variables

    def get_database_info(self) -> dict:
        """Get database configuration information (for debugging)"""
        if self.DATABASE_TYPE == "sqlite":
            db_path = os.path.join(self.DB_DIR, self.DB_FILENAME)
            return {
                "type": "SQLite",
                "path": db_path,
                "directory_exists": os.path.exists(self.DB_DIR),
                "file_exists": os.path.exists(db_path),
                "directory_writable": os.access(self.DB_DIR, os.W_OK) if os.path.exists(self.DB_DIR) else False
            }
        else:
            return {
                "type": "MySQL",
                "host": self.DB_HOST,
                "port": self.DB_PORT,
                "database": self.DB_NAME,
                "user": self.DB_USER
            }

settings = Settings()

# Print database info on startup (for debugging)
if settings.DEBUG:
    print(f"📊 Database Type: {settings.get_database_info()['type']}")
    print(f"📁 Database Info: {settings.get_database_info()}")