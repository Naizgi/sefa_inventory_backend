# app/main.py
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base, SessionLocal, get_db, init_db
from app.config import settings
from app.services import SettingsService, EmailScheduler
from app.seeders.user_seeder import seed_users
from app.utils.dependencies import get_current_user
from app.models import User
from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler
import os

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== ROUTES ====================
from app.routes import settings_router
from app.routes import (
    alerts_router, auth_router, branches_router, dashboard_router,
    loan_router, products_router, purchase_router, reports_router,
    sales_router, stock_router, temp_items_router, users_router,
    damaged_goods_router  # ADD THIS LINE
)
from app.routes.vat import router as vat_router
from app.routes.wallet import router as wallet_router
from app.routes.debts import router as debt_router  # ADD THIS LINE - Import debt router

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
    # Check if scheduler should run (only in production)
    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
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
        logger.info("Email scheduler disabled")

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
    # Log the database path
    logger.info(f"Database path: {settings.DATABASE_URL}")
    
    # Check if using SQLite and volume is mounted
    if "sqlite" in settings.DATABASE_URL:
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        if os.path.exists(os.path.dirname(db_path)):
            logger.info(f"✅ Database directory exists: {os.path.dirname(db_path)}")
        else:
            logger.warning(f"⚠️ Database directory does not exist: {os.path.dirname(db_path)}")
    
    # Initialize database tables
    logger.info("Creating database tables...")
    try:
        init_db()
        logger.info("✅ Database tables created successfully")
    except Exception as e:
        logger.error(f"❌ Failed to create database tables: {e}")
        raise

    # Initialize default data
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
    engine.dispose()
    logger.info("Database connections closed")

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
        "https://sefa-inventory.com",
        "http://sefa-inventory.com",
        "https://www.sefa-inventory.com",
        "http://localhost:52012",
         "*",
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
app.include_router(debt_router)  # ADD THIS LINE - Register the debt router
app.include_router(purchase_router)
app.include_router(temp_items_router)
app.include_router(settings_router)
app.include_router(vat_router)
app.include_router(wallet_router)
app.include_router(damaged_goods_router)  # ADD THIS LINE - Register the damaged goods router

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

# ==================== ROOT ENDPOINTS ====================
@app.get("/")
def root():
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "database": "SQLite" if "sqlite" in settings.DATABASE_URL else "MySQL/PostgreSQL",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    from app.database import check_db_health
    
    db_healthy = check_db_health()
    
    return {
        "status": "healthy" if db_healthy else "unhealthy",
        "database": "SQLite" if "sqlite" in settings.DATABASE_URL else "MySQL/PostgreSQL",
        "database_status": "connected" if db_healthy else "disconnected",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# ==================== DATABASE INFO ENDPOINT (optional, for debugging) ====================
@app.get("/api/db-info")
def db_info(current_user: User = Depends(get_current_user)):
    """Get database information (Admin only)"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    import os
    import sqlite3
    
    if "sqlite" in settings.DATABASE_URL:
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        
        try:
            db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            table_info = {}
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
                count = cursor.fetchone()[0]
                table_info[table[0]] = count
            
            conn.close()
            
            return {
                "database_type": "SQLite",
                "database_path": db_path,
                "database_size_mb": round(db_size / (1024 * 1024), 2),
                "tables": table_info
            }
        except Exception as e:
            return {
                "database_type": "SQLite",
                "database_path": db_path,
                "error": str(e)
            }
    else:
        return {
            "database_type": "Other",
            "url": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "hidden"
        }

# ==================== DEBT ROUTES OVERVIEW ====================
@app.get("/api/debt/info")
def debt_info(current_user: User = Depends(get_current_user)):
    """Get Debt system information"""
    return {
        "module": "Debt Tracking System",
        "version": "1.0.0",
        "description": "Track company debts to suppliers and manage repayments",
        "features": [
            "Record debts with supplier information",
            "Track payments via cash, wallet, or products",
            "Automatic stock deduction for product payments",
            "Wallet integration for cash payments",
            "Comprehensive debt reports and summaries",
            "Approval workflow for debt creation",
            "Supplier-specific debt tracking"
        ],
        "endpoints": [
            {"path": "/debts/", "methods": ["GET", "POST"], "description": "List and create debts"},
            {"path": "/debts/{debt_id}", "methods": ["GET", "PUT"], "description": "View and update debt"},
            {"path": "/debts/{debt_id}/pay", "methods": ["POST"], "description": "Make a payment towards debt"},
            {"path": "/debts/{debt_id}/payments", "methods": ["GET"], "description": "Get all payments for a debt"},
            {"path": "/debts/{debt_id}/approve", "methods": ["POST"], "description": "Approve a debt (Admin only)"},
            {"path": "/debts/{debt_id}/reject", "methods": ["POST"], "description": "Reject a debt (Admin only)"},
            {"path": "/debts/summary/", "methods": ["GET"], "description": "Get debt summary"},
            {"path": "/debts/report/", "methods": ["GET"], "description": "Get comprehensive debt report"},
            {"path": "/debts/by-supplier/{supplier_name}", "methods": ["GET"], "description": "Get debts by supplier"},
            {"path": "/debts/dashboard/stats/", "methods": ["GET"], "description": "Get dashboard statistics"},
            {"path": "/debts/payment/{payment_id}", "methods": ["GET"], "description": "Get payment details"}
        ],
        "payment_methods": [
            {"method": "cash", "description": "Cash payment"},
            {"method": "wallet", "description": "Payment from wallet (deducts from wallet balance)"},
            {"method": "product", "description": "Payment using products (deducts from stock)"},
            {"method": "mixed", "description": "Combination of wallet and product payment"},
            {"method": "bank_transfer", "description": "Bank transfer payment"}
        ],
        "debt_statuses": [
            {"status": "active", "description": "Debt is active with full balance"},
            {"status": "partially_paid", "description": "Some payments have been made"},
            {"status": "settled", "description": "Debt has been fully paid"},
            {"status": "overdue", "description": "Debt is overdue"},
            {"status": "cancelled", "description": "Debt has been cancelled"}
        ]
    }

# ==================== VAT ROUTES OVERVIEW ====================
@app.get("/api/vat/info")
def vat_info(current_user: User = Depends(get_current_user)):
    """Get VAT system information"""
    return {
        "module": "VAT Tracking System",
        "version": "1.0.0",
        "description": "Track VAT on purchases and sales, manage VAT returns, and calculate selling prices",
        "endpoints": [
            {"path": "/api/vat/purchases", "methods": ["GET", "POST"], "description": "Manage VAT purchases"},
            {"path": "/api/vat/sales", "methods": ["GET", "POST"], "description": "Manage VAT sales"},
            {"path": "/api/vat/stock", "methods": ["GET"], "description": "View available stock from VAT purchases"},
            {"path": "/api/vat/summaries", "methods": ["GET", "POST"], "description": "Monthly VAT summaries"},
            {"path": "/api/vat/rates", "methods": ["GET", "POST"], "description": "VAT rate history"},
            {"path": "/api/vat/reports", "methods": ["GET"], "description": "VAT reports and analytics"},
            {"path": "/api/vat/dashboard", "methods": ["GET"], "description": "VAT dashboard"},
            {"path": "/api/vat/calculate-selling-price", "methods": ["POST"], "description": "Calculate selling price from cost"},
            {"path": "/api/vat/calculate-vat", "methods": ["POST"], "description": "Calculate VAT amount"}
        ]
    }

# ==================== WALLET ROUTES OVERVIEW ====================
@app.get("/api/wallet/info")
def wallet_info(current_user: User = Depends(get_current_user)):
    """Get Wallet system information"""
    return {
        "module": "Wallet Management System",
        "version": "1.0.0",
        "description": "Manage wallets for VAT and regular stock operations",
        "features": [
            "Separate wallets for VAT and Regular stock",
            "Track deposits and withdrawals",
            "Auto-deduct when restocking and purchasing",
            "Wallet transfer between accounts",
            "Daily and monthly summaries",
            "Real-time balance tracking",
            "Profit/Loss calculation for wallet operations"
        ],
        "endpoints": [
            {"path": "/api/wallet/create", "methods": ["POST"], "description": "Create a wallet for a branch"},
            {"path": "/api/wallet/balances", "methods": ["GET"], "description": "Get wallet balances"},
            {"path": "/api/wallet/deposit", "methods": ["POST"], "description": "Deposit money into wallet"},
            {"path": "/api/wallet/withdraw", "methods": ["POST"], "description": "Withdraw money from wallet"},
            {"path": "/api/wallet/transfer", "methods": ["POST"], "description": "Transfer between wallets"},
            {"path": "/api/wallet/transactions", "methods": ["GET"], "description": "Get transaction history"},
            {"path": "/api/wallet/process-restock/{product_id}", "methods": ["POST"], "description": "Auto-deduct when restocking"},
            {"path": "/api/wallet/process-purchase/{purchase_order_id}", "methods": ["POST"], "description": "Auto-deduct for purchase orders"},
            {"path": "/api/wallet/process-refund/{refund_id}", "methods": ["POST"], "description": "Auto-deduct for refunds"},
            {"path": "/api/wallet/summary", "methods": ["GET"], "description": "Get daily wallet summary"},
            {"path": "/api/wallet/summary/range", "methods": ["GET"], "description": "Get summaries for date range"}
        ],
        "transaction_types": [
            {"type": "deposit", "description": "Money added to wallet"},
            {"type": "withdrawal", "description": "Money taken out"},
            {"type": "purchase", "description": "Money spent on purchase orders"},
            {"type": "restock", "description": "Money spent on restocking"},
            {"type": "refund", "description": "Money refunded to customer"},
            {"type": "adjustment", "description": "Manual adjustment"},
            {"type": "transfer", "description": "Transfer between wallets"}
        ],
        "wallets": [
            {"name": "VAT Wallet", "description": "For VAT-tracked purchases and expenses"},
            {"name": "Regular Wallet", "description": "For regular inventory purchases and restocking"}
        ]
    }