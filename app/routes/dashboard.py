from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta
from decimal import Decimal
from app.database import get_db
from app.models import (
    Product, Stock, Sale, Alert, Branch, 
    PurchaseOrder, PurchaseStatus, Loan, LoanStatus,
    Refund, RefundStatus, DamagedGoods, DamagedGoodsStatus,
    TempItem, TempItemStatus, SaleItem, User, BankAccount
)
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

def safe_float(value):
    """Safely convert a value to float, handling None and Decimal"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

def safe_int(value):
    """Safely convert a value to int"""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

# GET dashboard - handle both with and without trailing slash
@router.get("")   # No slash - /api/dashboard
@router.get("/")  # With slash - /api/dashboard/
def get_dashboard(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get dashboard statistics with enhanced features"""
    try:
        # Use user's branch if salesman
        branch_id = None
        is_admin = current_user.role == "admin"
        is_privileged = current_user.role in ["admin", "privileged_sales"]
        
        if current_user.role == "salesman":
            branch_id = current_user.branch_id
        
        # ==================== LOW STOCK PRODUCTS ====================
        low_stock_query = db.query(Stock).filter(
            Stock.quantity <= Stock.reorder_level,
            Stock.quantity > 0
        )
        
        # ==================== OUT OF STOCK PRODUCTS ====================
        out_of_stock_query = db.query(Stock).filter(Stock.quantity == 0)
        
        if branch_id:
            low_stock_query = low_stock_query.filter(Stock.branch_id == branch_id)
            out_of_stock_query = out_of_stock_query.filter(Stock.branch_id == branch_id)
        
        low_stock_products = []
        for stock in low_stock_query.limit(10).all():
            product = db.query(Product).filter(Product.id == stock.product_id).first()
            if product and product.active:
                low_stock_products.append({
                    "id": product.id,
                    "product_name": product.name if product else "Unknown",
                    "sku": product.sku if product else "N/A",
                    "current_stock": safe_float(stock.quantity),
                    "reorder_level": safe_float(stock.reorder_level),
                    "branch_id": stock.branch_id
                })
        
        out_of_stock_products = []
        for stock in out_of_stock_query.limit(10).all():
            product = db.query(Product).filter(Product.id == stock.product_id).first()
            if product and product.active:
                out_of_stock_products.append({
                    "id": product.id,
                    "product_name": product.name if product else "Unknown",
                    "sku": product.sku if product else "N/A",
                    "current_stock": safe_float(stock.quantity),
                    "reorder_level": safe_float(stock.reorder_level),
                    "branch_id": stock.branch_id
                })
        
        # ==================== TOTAL INVENTORY VALUE ====================
        inventory_value = 0
        stock_query = db.query(Stock)
        if branch_id:
            stock_query = stock_query.filter(Stock.branch_id == branch_id)
        
        for stock in stock_query.all():
            product = db.query(Product).filter(Product.id == stock.product_id).first()
            if product:
                inventory_value += safe_float(stock.quantity) * safe_float(product.cost)
        
        # ==================== PENDING PURCHASE ORDERS ====================
        pending_purchase_query = db.query(PurchaseOrder).filter(
            PurchaseOrder.status == PurchaseStatus.PENDING.value
        )
        if branch_id:
            pending_purchase_query = pending_purchase_query.filter(PurchaseOrder.branch_id == branch_id)
        
        pending_purchases = pending_purchase_query.all()
        pending_purchase_value = sum(safe_float(order.total_amount) for order in pending_purchases)
        pending_purchase_count = len(pending_purchases)
        
        # ==================== TODAY'S SALES ====================
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        sales_query = db.query(Sale).filter(
            Sale.created_at >= today_start,
            Sale.created_at <= today_end,
            Sale.status == "completed"
        )
        
        if branch_id:
            sales_query = sales_query.filter(Sale.branch_id == branch_id)
        
        today_sales = sales_query.all()
        today_revenue = sum(safe_float(sale.total_amount) for sale in today_sales)
        
        # ==================== TOP SELLING PRODUCTS (LAST 30 DAYS) ====================
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        top_products_query = db.query(
            Product.id,
            Product.name,
            Product.sku,
            func.sum(SaleItem.quantity).label('total_sold'),
            func.sum(SaleItem.line_total).label('revenue')
        ).join(
            SaleItem, SaleItem.product_id == Product.id
        ).join(
            Sale, Sale.id == SaleItem.sale_id
        ).filter(
            Sale.created_at >= thirty_days_ago,
            Sale.status == "completed"
        )
        
        if branch_id:
            top_products_query = top_products_query.filter(Sale.branch_id == branch_id)
        
        top_products = top_products_query.group_by(Product.id).order_by(
            func.sum(SaleItem.quantity).desc()
        ).limit(5).all()
        
        top_products_data = []
        for product in top_products:
            top_products_data.append({
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "total_sold": safe_int(product.total_sold),
                "revenue": safe_float(product.revenue)
            })
        
        # ==================== PENDING APPROVALS ====================
        pending_approvals = []
        
        # Pending Loans (only for privileged users)
        if is_privileged:
            pending_loans = db.query(Loan).filter(
                Loan.status == LoanStatus.ACTIVE.value,
                Loan.requires_approval == True,
                Loan.approved_by == None
            ).limit(5).all()
            
            for loan in pending_loans:
                creator = db.query(User).filter(User.id == loan.created_by).first()
                pending_approvals.append({
                    "id": loan.id,
                    "type": "loan",
                    "title": f"Loan #{loan.loan_number}",
                    "description": f"Customer: {loan.customer_name} | Amount: {safe_float(loan.total_amount):,.2f}",
                    "requested_by": creator.name if creator else "Unknown",
                    "created_at": loan.created_at.isoformat() if loan.created_at else None,
                    "status": "pending"
                })
            
            # Pending Purchase Orders with pre-payment
            pending_purchase_approvals = db.query(PurchaseOrder).filter(
                PurchaseOrder.status == PurchaseStatus.PENDING.value,
                PurchaseOrder.payment_reference.isnot(None)
            ).limit(5).all()
            
            for purchase in pending_purchase_approvals:
                creator = db.query(User).filter(User.id == purchase.created_by).first()
                pending_approvals.append({
                    "id": purchase.id,
                    "type": "purchase",
                    "title": f"Purchase Order #{purchase.order_number}",
                    "description": f"Supplier: {purchase.supplier} | Amount: {safe_float(purchase.total_amount):,.2f}",
                    "requested_by": creator.name if creator else "Unknown",
                    "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
                    "status": "pending"
                })
            
            # Pending Refunds
            pending_refunds = db.query(Refund).filter(
                Refund.status == RefundStatus.PENDING.value
            ).limit(5).all()
            
            for refund in pending_refunds:
                user = db.query(User).filter(User.id == refund.user_id).first()
                pending_approvals.append({
                    "id": refund.id,
                    "type": "refund",
                    "title": f"Refund #{refund.refund_number}",
                    "description": f"Amount: {safe_float(refund.refund_amount):,.2f} | Reason: {refund.refund_reason[:50] if refund.refund_reason else 'N/A'}",
                    "requested_by": user.name if user else "Unknown",
                    "created_at": refund.created_at.isoformat() if refund.created_at else None,
                    "status": "pending"
                })
            
            # Pending Damaged Goods
            pending_damaged = db.query(DamagedGoods).filter(
                DamagedGoods.status == DamagedGoodsStatus.PENDING.value
            ).limit(5).all()
            
            for damaged in pending_damaged:
                product = db.query(Product).filter(Product.id == damaged.product_id).first()
                reporter = db.query(User).filter(User.id == damaged.reported_by).first()
                pending_approvals.append({
                    "id": damaged.id,
                    "type": "damaged",
                    "title": f"Damaged Goods Report #{damaged.report_number}",
                    "description": f"Product: {product.name if product else 'Unknown'} | Quantity: {safe_float(damaged.quantity)}",
                    "requested_by": reporter.name if reporter else "Unknown",
                    "created_at": damaged.reported_at.isoformat() if damaged.reported_at else None,
                    "status": "pending"
                })
            
            # Pending Temp Items (only for admin)
            if is_admin:
                pending_temp_items = db.query(TempItem).filter(
                    TempItem.status == TempItemStatus.PENDING.value
                ).limit(5).all()
                
                for temp_item in pending_temp_items:
                    registrar = db.query(User).filter(User.id == temp_item.registered_by).first()
                    pending_approvals.append({
                        "id": temp_item.id,
                        "type": "temp_item",
                        "title": f"Temp Item #{temp_item.item_number}",
                        "description": f"Item: {temp_item.item_name} | Quantity: {temp_item.quantity}",
                        "requested_by": registrar.name if registrar else "Unknown",
                        "created_at": temp_item.registered_at.isoformat() if temp_item.registered_at else None,
                        "status": "pending"
                    })
        
        # Sort pending approvals by created_at (newest first)
        pending_approvals.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # ==================== ACTIVE ALERTS ====================
        alerts_query = db.query(Alert).filter(Alert.resolved == False)
        if branch_id:
            alerts_query = alerts_query.filter(Alert.branch_id == branch_id)
        
        recent_alerts = []
        for alert in alerts_query.order_by(Alert.created_at.desc()).limit(5).all():
            recent_alerts.append({
                "id": alert.id,
                "message": alert.message,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
                "type": "warning"
            })
        
        # ==================== TOTAL COUNTS ====================
        products_count = db.query(Product).filter(Product.active == True).count()
        branches_count = db.query(Branch).count() if is_admin else 1
        low_stock_alerts_count = len(low_stock_products)
        active_alerts_count = alerts_query.count()
        
        # ==================== BANK PURCHASE SUMMARY ====================
        bank_purchase_summary = []
        if is_privileged:
            thirty_days_ago = datetime.now() - timedelta(days=30)
            
            bank_summary_query = db.query(
                PurchaseOrder.bank_account_id,
                func.sum(PurchaseOrder.total_amount).label('total_amount'),
                func.count(PurchaseOrder.id).label('order_count')
            ).filter(
                PurchaseOrder.created_at >= thirty_days_ago,
                PurchaseOrder.status == PurchaseStatus.COMPLETED.value,
                PurchaseOrder.bank_account_id.isnot(None)
            )
            
            if branch_id:
                bank_summary_query = bank_summary_query.filter(PurchaseOrder.branch_id == branch_id)
            
            bank_summary = bank_summary_query.group_by(PurchaseOrder.bank_account_id).all()
            
            for summary in bank_summary:
                bank_account = db.query(BankAccount).filter(BankAccount.id == summary.bank_account_id).first()
                if bank_account:
                    bank_purchase_summary.append({
                        "bank_name": bank_account.bank_name,
                        "account_number": bank_account.account_number[-4:] if bank_account.account_number else "****",
                        "total_amount": safe_float(summary.total_amount),
                        "order_count": safe_int(summary.order_count)
                    })
        
        # ==================== VAT SUMMARY ====================
        thirty_days_ago = datetime.now() - timedelta(days=30)
        vat_query = db.query(PurchaseOrder).filter(
            PurchaseOrder.created_at >= thirty_days_ago
        )
        
        if branch_id:
            vat_query = vat_query.filter(PurchaseOrder.branch_id == branch_id)
        
        vat_orders = vat_query.all()
        
        total_vat_paid = 0
        vat_rate_sum = 0
        vat_purchases = 0
        non_vat_purchases = 0
        
        for order in vat_orders:
            if order.vat_amount and safe_float(order.vat_amount) > 0:
                total_vat_paid += safe_float(order.vat_amount)
                vat_rate_sum += safe_float(order.vat_rate)
                vat_purchases += 1
            else:
                non_vat_purchases += 1
        
        vat_summary_data = {
            "total_vat_paid": total_vat_paid,
            "average_vat_rate": vat_rate_sum / vat_purchases if vat_purchases > 0 else 0,
            "vat_purchases_count": vat_purchases,
            "non_vat_purchases_count": non_vat_purchases
        }
        
        # ==================== RECENT ACTIVITIES ====================
        recent_activities = []
        
        # Recent sales
        recent_sales = db.query(Sale).order_by(Sale.created_at.desc()).limit(5).all()
        for sale in recent_sales:
            recent_activities.append({
                "id": f"sale_{sale.id}",
                "type": "sale",
                "message": f"Sale #{sale.invoice_number} - {safe_float(sale.total_amount):,.2f}",
                "timestamp": sale.created_at.isoformat() if sale.created_at else None,
                "icon": "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
            })
        
        # Recent purchase orders
        recent_purchases = db.query(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()).limit(3).all()
        for purchase in recent_purchases:
            recent_activities.append({
                "id": f"purchase_{purchase.id}",
                "type": "stock",
                "message": f"Purchase Order #{purchase.order_number} - {purchase.supplier}",
                "timestamp": purchase.created_at.isoformat() if purchase.created_at else None,
                "icon": "M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H7a3 3 0 00-3 3v8a3 3 0 003 3z"
            })
        
        # Sort activities by timestamp
        recent_activities.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        recent_activities = recent_activities[:10]
        
        # ==================== RESPONSE ====================
        return {
            # Basic stats
            "total_products": products_count,
            "total_branches": branches_count,
            "low_stock_alerts": low_stock_alerts_count,
            "active_alerts": active_alerts_count,
            
            # Enhanced stats
            "total_inventory_value": inventory_value,
            "pending_purchase_value": pending_purchase_value,
            "pending_purchase_count": pending_purchase_count,
            
            # Stock data
            "low_stock_products": low_stock_products,
            "out_of_stock_products": out_of_stock_products,
            
            # Sales data
            "today_sales": {
                "count": len(today_sales),
                "revenue": today_revenue
            },
            
            # Charts & Analytics
            "top_products": top_products_data,
            
            # Approvals
            "pending_approvals": pending_approvals,
            "pending_approval_count": len(pending_approvals),
            
            # Alerts
            "recent_alerts": recent_alerts,
            
            # Financial summaries
            "bank_purchase_summary": bank_purchase_summary,
            "vat_summary": vat_summary_data,
            
            # Activity
            "recent_activities": recent_activities
        }
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Dashboard error: {str(e)}")


# ==================== SALES CHART ENDPOINT ====================
@router.get("/sales-chart")
def get_sales_chart(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get sales data for chart visualization"""
    try:
        branch_id = None
        if current_user.role == "salesman":
            branch_id = current_user.branch_id
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Generate date labels and data
        labels = []
        sales_data = []
        
        current_date = start_date
        while current_date <= end_date:
            labels.append(current_date.strftime("%Y-%m-%d"))
            
            day_start = datetime.combine(current_date.date(), datetime.min.time())
            day_end = datetime.combine(current_date.date(), datetime.max.time())
            
            query = db.query(func.coalesce(func.sum(Sale.total_amount), 0)).filter(
                Sale.created_at >= day_start,
                Sale.created_at <= day_end,
                Sale.status == "completed"
            )
            
            if branch_id:
                query = query.filter(Sale.branch_id == branch_id)
            
            daily_total = query.scalar() or 0
            sales_data.append(safe_float(daily_total))
            
            current_date += timedelta(days=1)
        
        # Get previous period data for comparison
        prev_end_date = start_date
        prev_start_date = prev_end_date - timedelta(days=days)
        
        prev_sales_data = []
        current_date = prev_start_date
        while current_date <= prev_end_date:
            day_start = datetime.combine(current_date.date(), datetime.min.time())
            day_end = datetime.combine(current_date.date(), datetime.max.time())
            
            query = db.query(func.coalesce(func.sum(Sale.total_amount), 0)).filter(
                Sale.created_at >= day_start,
                Sale.created_at <= day_end,
                Sale.status == "completed"
            )
            
            if branch_id:
                query = query.filter(Sale.branch_id == branch_id)
            
            daily_total = query.scalar() or 0
            prev_sales_data.append(safe_float(daily_total))
            
            current_date += timedelta(days=1)
        
        # Calculate summary statistics
        total_sales = sum(sales_data)
        average_daily_sales = total_sales / len(sales_data) if sales_data else 0
        max_daily_sales = max(sales_data) if sales_data else 0
        min_daily_sales = min(sales_data) if sales_data else 0
        
        prev_total_sales = sum(prev_sales_data)
        growth_percentage = ((total_sales - prev_total_sales) / prev_total_sales * 100) if prev_total_sales > 0 else 0
        
        return {
            "labels": labels,
            "values": sales_data,
            "previous_values": prev_sales_data,
            "summary": {
                "total_sales": total_sales,
                "average_daily_sales": average_daily_sales,
                "max_daily_sales": max_daily_sales,
                "min_daily_sales": min_daily_sales,
                "period_days": days,
                "growth_percentage": growth_percentage,
                "comparison_period": {
                    "total_sales": prev_total_sales,
                    "days": days
                }
            }
        }
    except Exception as e:
        print(f"Sales chart error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Sales chart error: {str(e)}")