from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Product, Stock, Sale, Alert, Branch
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

# GET dashboard - handle both with and without trailing slash
@router.get("")   # No slash - /api/dashboard
@router.get("/")  # With slash - /api/dashboard/
def get_dashboard(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get dashboard statistics"""
    # Use user's branch if salesman
    branch_id = None
    if current_user.role == "salesman":
        branch_id = current_user.branch_id
    
    # Get low stock products
    low_stock_query = db.query(Stock).filter(
        Stock.quantity <= Stock.reorder_level
    )
    
    if branch_id:
        low_stock_query = low_stock_query.filter(Stock.branch_id == branch_id)
    
    low_stock_products = []
    for stock in low_stock_query.limit(10).all():
        product = db.query(Product).filter(Product.id == stock.product_id).first()
        low_stock_products.append({
            "product_name": product.name if product else "Unknown",
            "sku": product.sku if product else "N/A",
            "current_stock": float(stock.quantity),
            "reorder_level": float(stock.reorder_level),
            "branch_id": stock.branch_id
        })
    
    # Get today's sales
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    
    sales_query = db.query(Sale).filter(
        Sale.created_at >= today_start,
        Sale.created_at <= today_end
    )
    
    if branch_id:
        sales_query = sales_query.filter(Sale.branch_id == branch_id)
    
    today_sales = sales_query.all()
    today_revenue = sum(float(sale.total_amount) for sale in today_sales)
    
    # Get total products count
    products_count = db.query(Product).filter(Product.active == True).count()
    
    # Get branches count for admin
    branches_count = 0
    if current_user.role == "admin":
        branches_count = db.query(Branch).count()
    
    # Get active alerts count
    alerts_count = db.query(Alert).filter(Alert.resolved == False).count()
    if branch_id:
        alerts_count = db.query(Alert).filter(
            Alert.resolved == False,
            Alert.branch_id == branch_id
        ).count()
    
    return {
        "total_products": products_count,
        "total_branches": branches_count if current_user.role == "admin" else 1,
        "low_stock_alerts": len(low_stock_products),
        "low_stock_products": low_stock_products,
        "today_sales": {
            "count": len(today_sales),
            "revenue": today_revenue
        },
        "active_alerts": alerts_count
    }