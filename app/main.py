# app/main.py
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal, get_db
from app.config import settings
from app.services import SettingsService, EmailScheduler
from app.seeders.user_seeder import seed_users
from app.utils.dependencies import get_current_user
from app.models import User
from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ROUTES ====================
from app.routes import settings_router
from app.routes import (
    alerts_router, auth_router, branches_router, dashboard_router,
    loan_router, products_router, purchase_router, reports_router,
    sales_router, stock_router, temp_items_router, users_router
)

# ==================== SCHEDULER ====================
scheduler = BackgroundScheduler()

def run_low_stock_check():
    """Run low stock check in a new database session"""
    db = SessionLocal()
    try:
        logger.info("Running low stock check...")
        EmailScheduler.check_and_send_low_stock_alerts(db)
    except Exception as e:
        logger.error(f"Error in low stock check: {e}")
    finally:
        db.close()

def run_daily_report():
    """Run daily report in a new database session"""
    db = SessionLocal()
    try:
        logger.info("Running daily report...")
        EmailScheduler.send_daily_report(db)
    except Exception as e:
        logger.error(f"Error in daily report: {e}")
    finally:
        db.close()

def start_scheduler():
    """Start the background scheduler for email notifications"""
    if settings.ENVIRONMENT == "production":
        scheduler.add_job(
            func=run_low_stock_check,
            trigger="interval",
            hours=1,
            id="low_stock_check",
            replace_existing=True
        )
        logger.info("✅ Low stock check scheduler started (every hour)")
        
        scheduler.add_job(
            func=run_daily_report,
            trigger="cron",
            hour=8,
            minute=0,
            id="daily_report",
            replace_existing=True
        )
        logger.info("✅ Daily report scheduler started (8:00 AM)")
        
        scheduler.start()
    else:
        logger.info("Email scheduler disabled in development mode")

def stop_scheduler():
    """Stop the background scheduler"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")

# ==================== FASTAPI APP ====================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# ==================== STARTUP & SHUTDOWN EVENTS ====================
@app.on_event("startup")
def startup():
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        SettingsService.initialize_default_settings(db)
        logger.info("✅ Default settings initialized")

        seed_users(db)
        logger.info("✅ Users seeded successfully")
        
        EmailScheduler.check_and_send_low_stock_alerts(db)
        logger.info("✅ Initial low stock check completed")

    except Exception as e:
        logger.error(f"⚠️ Error during startup: {e}")
    finally:
        db.close()
    
    start_scheduler()

@app.on_event("shutdown")
def shutdown():
    logger.info("Shutting down application...")
    stop_scheduler()

# ==================== CORS ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173", 
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "https://smartlink.mellainnovation.com",
        "http://smartlink.mellainnovation.com",
        "https://smartlink-inventory.up.railway.app",
        "http://smartlink-inventory.up.railway.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ROUTERS ====================
app.include_router(auth_router)
app.include_router(branches_router)
app.include_router(products_router)
app.include_router(users_router)
app.include_router(stock_router)
app.include_router(sales_router)
app.include_router(reports_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)
app.include_router(loan_router)
app.include_router(purchase_router)
app.include_router(temp_items_router)
app.include_router(settings_router)

# ==================== TEST EMAIL ENDPOINT ====================
@app.post("/api/test/email")
def test_email(
   
    current_user: User = Depends(get_current_user)
):
    """Test email sending (Admin only)"""
    from app.services import EmailService
    
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = EmailService.send_email(
        to_emails=[current_user.email],
        subject="Test Email from Inventory System",
        template_name="daily_report.html",
        context={
            "user_name": current_user.name,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_sales": 0,
            "total_revenue": 0,
            "total_refunds": 0,
            "net_revenue": 0,
            "top_products": [],
            "low_stock_items": []
        }
    )
    
    if result:
        return {"message": "Test email sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email")

# ==================== ROOT ====================
@app.get("/")
def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }