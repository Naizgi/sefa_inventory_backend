from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure engine based on database type
if settings.DATABASE_TYPE == "sqlite":
    # SQLite doesn't need connection pooling like MySQL
    # SQLite uses file-based locking instead
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        connect_args=settings.SQLITE_CONNECT_ARGS,
        # SQLite ignores these pooling parameters, but we'll keep them for compatibility
        pool_size=1,
        max_overflow=0,
        pool_timeout=30,
        pool_recycle=3600,
        pool_pre_ping=True
    )
    logger.info(f"✅ SQLite database configured: {settings.get_database_info()['path']}")
else:
    # MySQL configuration with connection pooling
    engine = create_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING
    )
    logger.info(f"✅ MySQL database configured: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

def get_db():
    """Dependency that provides a database session"""
    db = SessionLocal()
    try:
        # Verify connection is alive
        db.execute(text("SELECT 1"))
        yield db
    except Exception as e:
        logger.error(f"Database error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def check_db_health():
    """Check if database is accessible"""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

def init_db():
    """Initialize database - create all tables"""
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully!")
        
        # For SQLite, verify the database file was created
        if settings.DATABASE_TYPE == "sqlite":
            db_info = settings.get_database_info()
            if os.path.exists(db_info['path']):
                size = os.path.getsize(db_info['path'])
                logger.info(f"✅ SQLite database file created: {db_info['path']} ({size} bytes)")
            else:
                logger.warning(f"⚠️ SQLite database file not found at {db_info['path']}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create database tables: {e}")
        return False