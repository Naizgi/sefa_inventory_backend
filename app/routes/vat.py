from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta, date
from typing import Optional, List
from decimal import Decimal
import json

from app.database import get_db
from app.models import (
    User, Branch, Product, PurchaseOrder, PurchaseOrderItem,
    Sale, SaleItem, VATPurchase, VATSale, VATSummary, VATRateHistory,
    VATStatus, Stock, StockMovement
)
# FIXED: Import from app.schemas directly (not app.schemas.vat_schemas)
from app.schemas import (
    VATPurchaseCreate, VATPurchaseUpdate, VATPurchaseResponse,
    VATSaleCreate, VATSaleResponse, VATPurchaseStockResponse,
    VATSummaryCreate, VATSummaryUpdate, VATSummaryResponse,
    VATRateHistoryCreate, VATRateHistoryResponse,
    VATPeriodReport, VATProductGroupReport, VATDashboardSummary,
    calculate_vat_amount, calculate_selling_price, calculate_cogs_and_profit
)
from app.utils.dependencies import get_current_user, require_privileged, require_admin

router = APIRouter(prefix="/api/vat", tags=["VAT Tracking"])


# ==================== HELPER FUNCTIONS ====================

def generate_vat_number(prefix: str = "VAT", branch_id: int = None) -> str:
    """Generate unique VAT transaction number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if branch_id:
        return f"{prefix}-{branch_id}-{timestamp}"
    return f"{prefix}-{timestamp}"


def update_vat_purchase_stock(vat_purchase: VATPurchase, db: Session):
    """Update current stock and value for a VAT purchase"""
    vat_purchase.current_stock = vat_purchase.quantity - vat_purchase.sold_quantity
    vat_purchase.current_value = vat_purchase.current_stock * vat_purchase.unit_cost
    vat_purchase.current_vat = vat_purchase.current_value * (vat_purchase.vat_rate / 100)
    db.commit()


# ==================== VAT PURCHASE ENDPOINTS ====================

@router.post("/purchases", response_model=VATPurchaseResponse)
def create_vat_purchase(
    purchase_data: VATPurchaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Create a new VAT purchase record (when receiving stock)"""
    
    # Get branch for current user
    branch_id = current_user.branch_id
    if current_user.is_admin() and purchase_data.purchase_order_id:
        # For admin, get branch from purchase order
        purchase_order = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == purchase_data.purchase_order_id
        ).first()
        if purchase_order:
            branch_id = purchase_order.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned to user")
    
    # Get product details
    product = db.query(Product).filter(Product.id == purchase_data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Calculate totals
    total_cost = purchase_data.quantity * purchase_data.unit_cost
    vat_calc = calculate_vat_amount(total_cost, purchase_data.vat_rate)
    
    # Calculate selling price (15% markup by default)
    selling_price_calc = calculate_selling_price(
        purchase_data.unit_cost, 
        markup_percentage=15.0, 
        vat_rate=purchase_data.vat_rate
    )
    
    # Create VAT purchase record
    vat_purchase = VATPurchase(
        vat_number=generate_vat_number("VAT-PUR", branch_id),
        purchase_order_id=purchase_data.purchase_order_id,
        branch_id=branch_id,
        product_id=purchase_data.product_id,
        product_name=product.name,
        product_group=purchase_data.product_group or "Uncategorized",
        sku=product.sku,
        quantity=purchase_data.quantity,
        unit_cost=purchase_data.unit_cost,
        total_cost=total_cost,
        vat_rate=purchase_data.vat_rate,
        vat_amount=vat_calc["vat_amount"],
        total_with_vat=vat_calc["incl_vat"],
        calculated_selling_price=selling_price_calc["selling_price_excl_vat"],
        calculated_selling_price_with_vat=selling_price_calc["selling_price_incl_vat"],
        current_stock=purchase_data.quantity,
        supplier_name=purchase_data.supplier_name,
        invoice_number=purchase_data.invoice_number,
        purchase_date=purchase_data.purchase_date,
        notes=purchase_data.notes,
        created_by=current_user.id
    )
    
    db.add(vat_purchase)
    db.commit()
    db.refresh(vat_purchase)
    
    # Record stock movement
    stock_movement = StockMovement(
        branch_id=branch_id,
        product_id=purchase_data.product_id,
        user_id=current_user.id,
        change_qty=purchase_data.quantity,
        movement_type="vat_purchase_in",
        with_vat=True,
        reference_id=vat_purchase.id,
        notes=f"VAT Purchase #{vat_purchase.vat_number} - Cost: {purchase_data.unit_cost}"
    )
    db.add(stock_movement)
    
    # Update stock
    stock = db.query(Stock).filter(
        Stock.branch_id == branch_id,
        Stock.product_id == purchase_data.product_id
    ).first()
    
    if stock:
        stock.quantity += purchase_data.quantity
        if purchase_data.vat_rate > 0:
            stock.quantity_with_vat += purchase_data.quantity
        else:
            stock.quantity_without_vat += purchase_data.quantity
    else:
        stock = Stock(
            branch_id=branch_id,
            product_id=purchase_data.product_id,
            quantity=purchase_data.quantity,
            quantity_with_vat=purchase_data.quantity if purchase_data.vat_rate > 0 else 0,
            quantity_without_vat=purchase_data.quantity if purchase_data.vat_rate == 0 else 0,
            reorder_level=0
        )
        db.add(stock)
    
    db.commit()
    
    return vat_purchase


@router.get("/purchases", response_model=List[VATPurchaseResponse])
def get_vat_purchases(
    product_id: Optional[int] = None,
    product_group: Optional[str] = None,
    status: Optional[VATStatus] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get all VAT purchases with filters"""
    
    query = db.query(VATPurchase)
    
    # Filter by branch
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    if product_id:
        query = query.filter(VATPurchase.product_id == product_id)
    
    if product_group:
        query = query.filter(VATPurchase.product_group == product_group)
    
    if status:
        query = query.filter(VATPurchase.status == status)
    
    if from_date:
        query = query.filter(VATPurchase.purchase_date >= from_date)
    
    if to_date:
        query = query.filter(VATPurchase.purchase_date <= to_date)
    
    purchases = query.order_by(VATPurchase.purchase_date.desc()).all()
    
    return purchases


@router.get("/purchases/{purchase_id}", response_model=VATPurchaseResponse)
def get_vat_purchase(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get single VAT purchase by ID"""
    
    purchase = db.query(VATPurchase).filter(VATPurchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
    
    # Check branch access
    if not current_user.is_admin() and purchase.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return purchase


@router.put("/purchases/{purchase_id}", response_model=VATPurchaseResponse)
def update_vat_purchase(
    purchase_id: int,
    update_data: VATPurchaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update VAT purchase (admin only)"""
    
    purchase = db.query(VATPurchase).filter(VATPurchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(purchase, field, value)
    
    purchase.updated_at = datetime.now()
    db.commit()
    db.refresh(purchase)
    
    return purchase


# ==================== VAT SALE ENDPOINTS ====================

@router.post("/sales", response_model=VATSaleResponse)
def create_vat_sale(
    sale_data: VATSaleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Create a VAT sale record (when selling from stock)"""
    
    # Get the VAT purchase record
    vat_purchase = db.query(VATPurchase).filter(
        VATPurchase.id == sale_data.vat_purchase_id
    ).first()
    
    if not vat_purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
    
    # Check if enough stock
    if vat_purchase.current_stock < sale_data.quantity:
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient stock. Available: {vat_purchase.current_stock}"
        )
    
    # Get sale details
    sale = db.query(Sale).filter(Sale.id == sale_data.sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    # Get sale item
    sale_item = None
    if sale_data.sale_item_id:
        sale_item = db.query(SaleItem).filter(SaleItem.id == sale_data.sale_item_id).first()
    
    # Calculate values
    vat_calc = calculate_vat_amount(
        sale_data.quantity * sale_data.selling_price, 
        vat_purchase.vat_rate
    )
    
    cogs_calc = calculate_cogs_and_profit(
        sale_data.quantity,
        vat_purchase.unit_cost,
        sale_data.selling_price
    )
    
    # Create VAT sale record
    vat_sale = VATSale(
        vat_sale_number=generate_vat_number("VAT-SALE", sale.branch_id),
        sale_id=sale_data.sale_id,
        sale_item_id=sale_data.sale_item_id,
        vat_purchase_id=sale_data.vat_purchase_id,
        branch_id=sale.branch_id,
        product_id=vat_purchase.product_id,
        product_name=vat_purchase.product_name,
        product_group=vat_purchase.product_group,
        sku=vat_purchase.sku,
        quantity=sale_data.quantity,
        unit_cost=vat_purchase.unit_cost,
        selling_price=sale_data.selling_price,
        selling_price_with_vat=vat_calc["incl_vat"] / sale_data.quantity if sale_data.quantity > 0 else 0,
        vat_rate=vat_purchase.vat_rate,
        vat_amount=vat_calc["vat_amount"],
        total_amount=vat_calc["excl_vat"],
        total_amount_with_vat=vat_calc["incl_vat"],
        cost_of_goods_sold=cogs_calc["cogs"],
        profit=cogs_calc["profit"],
        profit_margin=cogs_calc["profit_margin"],
        customer_name=sale.customer_name,
        invoice_number=sale.invoice_number,
        sale_date=sale.created_at,
        created_by=current_user.id
    )
    
    db.add(vat_sale)
    
    # Update VAT purchase stock
    vat_purchase.sold_quantity += sale_data.quantity
    vat_purchase.sold_value += sale_data.quantity * sale_data.selling_price
    vat_purchase.sold_vat += vat_calc["vat_amount"]
    update_vat_purchase_stock(vat_purchase, db)
    
    # Record stock movement (sale out)
    stock_movement = StockMovement(
        branch_id=sale.branch_id,
        product_id=vat_purchase.product_id,
        user_id=current_user.id,
        change_qty=-sale_data.quantity,
        movement_type="vat_sale_out",
        with_vat=True,
        reference_id=vat_sale.id,
        notes=f"VAT Sale #{vat_sale.vat_sale_number} - Price: {sale_data.selling_price}"
    )
    db.add(stock_movement)
    
    # Update stock
    stock = db.query(Stock).filter(
        Stock.branch_id == sale.branch_id,
        Stock.product_id == vat_purchase.product_id
    ).first()
    
    if stock:
        stock.quantity -= sale_data.quantity
        if vat_purchase.vat_rate > 0:
            stock.quantity_with_vat -= sale_data.quantity
        else:
            stock.quantity_without_vat -= sale_data.quantity
    
    db.commit()
    db.refresh(vat_sale)
    
    return vat_sale


@router.get("/sales", response_model=List[VATSaleResponse])
def get_vat_sales(
    product_id: Optional[int] = None,
    vat_purchase_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get all VAT sales with filters"""
    
    query = db.query(VATSale)
    
    # Filter by branch
    if not current_user.is_admin():
        query = query.filter(VATSale.branch_id == current_user.branch_id)
    
    if product_id:
        query = query.filter(VATSale.product_id == product_id)
    
    if vat_purchase_id:
        query = query.filter(VATSale.vat_purchase_id == vat_purchase_id)
    
    if from_date:
        query = query.filter(VATSale.sale_date >= from_date)
    
    if to_date:
        query = query.filter(VATSale.sale_date <= to_date)
    
    sales = query.order_by(VATSale.sale_date.desc()).all()
    
    return sales


@router.get("/sales/{sale_id}", response_model=VATSaleResponse)
def get_vat_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get single VAT sale by ID"""
    
    sale = db.query(VATSale).filter(VATSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="VAT sale not found")
    
    # Check branch access
    if not current_user.is_admin() and sale.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return sale


# ==================== STOCK TRACKING ENDPOINTS ====================

@router.get("/stock", response_model=List[VATPurchaseStockResponse])
def get_vat_stock_by_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get available stock from VAT purchases for a product (FIFO tracking)"""
    
    query = db.query(VATPurchase).filter(
        VATPurchase.product_id == product_id,
        VATPurchase.current_stock > 0,
        VATPurchase.status == VATStatus.PENDING.value
    )
    
    # Filter by branch
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    # Order by purchase date (FIFO)
    purchases = query.order_by(VATPurchase.purchase_date.asc()).all()
    
    return purchases


@router.get("/stock-summary")
def get_vat_stock_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get summary of all VAT stock"""
    
    query = db.query(VATPurchase).filter(VATPurchase.current_stock > 0)
    
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    purchases = query.all()
    
    total_stock_value = sum(p.current_value for p in purchases)
    total_stock_vat = sum(p.current_vat for p in purchases)
    total_items = sum(p.current_stock for p in purchases)
    
    return {
        "total_items": total_items,
        "total_stock_value": total_stock_value,
        "total_stock_vat": total_stock_vat,
        "total_stock_with_vat": total_stock_value + total_stock_vat,
        "unique_products": len(set(p.product_id for p in purchases)),
        "purchase_batches": len(purchases)
    }


# ==================== VAT SUMMARY ENDPOINTS ====================

@router.post("/summaries/generate", response_model=VATSummaryResponse)
def generate_vat_summary(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Generate VAT summary for a specific month"""
    
    # Check if summary already exists
    summary_month = f"{year}-{month:02d}"
    existing = db.query(VATSummary).filter(
        VATSummary.summary_month == summary_month,
        VATSummary.branch_id == current_user.branch_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Summary already exists for this month")
    
    # Get date range for the month
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
    
    # Get VAT purchases for the month
    purchases = db.query(VATPurchase).filter(
        VATPurchase.purchase_date >= start_date,
        VATPurchase.purchase_date <= end_date
    )
    
    if not current_user.is_admin():
        purchases = purchases.filter(VATPurchase.branch_id == current_user.branch_id)
    
    purchases = purchases.all()
    
    # Calculate purchase totals
    total_purchases_excl_vat = sum(p.total_cost for p in purchases)
    total_purchase_vat = sum(p.vat_amount for p in purchases)
    total_purchases_incl_vat = sum(p.total_with_vat for p in purchases)
    
    # Group purchases by product group
    purchase_by_group = {}
    for p in purchases:
        group = p.product_group or "Uncategorized"
        if group not in purchase_by_group:
            purchase_by_group[group] = {"excl_vat": 0, "vat": 0, "incl_vat": 0}
        purchase_by_group[group]["excl_vat"] += p.total_cost
        purchase_by_group[group]["vat"] += p.vat_amount
        purchase_by_group[group]["incl_vat"] += p.total_with_vat
    
    # Get VAT sales for the month
    sales = db.query(VATSale).filter(
        VATSale.sale_date >= start_date,
        VATSale.sale_date <= end_date
    )
    
    if not current_user.is_admin():
        sales = sales.filter(VATSale.branch_id == current_user.branch_id)
    
    sales = sales.all()
    
    # Calculate sale totals
    total_sales_excl_vat = sum(s.total_amount for s in sales)
    total_sale_vat = sum(s.vat_amount for s in sales)
    total_sales_incl_vat = sum(s.total_amount_with_vat for s in sales)
    total_profit = sum(s.profit for s in sales)
    avg_profit_margin = (total_profit / total_sales_excl_vat * 100) if total_sales_excl_vat > 0 else 0
    
    # Group sales by product group
    sale_by_group = {}
    for s in sales:
        group = s.product_group or "Uncategorized"
        if group not in sale_by_group:
            sale_by_group[group] = {"excl_vat": 0, "vat": 0, "incl_vat": 0, "profit": 0}
        sale_by_group[group]["excl_vat"] += s.total_amount
        sale_by_group[group]["vat"] += s.vat_amount
        sale_by_group[group]["incl_vat"] += s.total_amount_with_vat
        sale_by_group[group]["profit"] += s.profit
    
    # Calculate VAT payable/receivable
    vat_payable = total_sale_vat - total_purchase_vat
    vat_receivable = total_purchase_vat - total_sale_vat if vat_payable < 0 else 0
    net_vat = vat_payable if vat_payable > 0 else -vat_receivable
    
    # Create summary
    summary = VATSummary(
        branch_id=current_user.branch_id if not current_user.is_admin() else 1,
        summary_month=summary_month,
        summary_year=year,
        summary_month_num=month,
        total_purchases_excl_vat=total_purchases_excl_vat,
        total_purchase_vat=total_purchase_vat,
        total_purchases_incl_vat=total_purchases_incl_vat,
        purchase_count=len(purchases),
        purchase_by_group=json.dumps(purchase_by_group),
        total_sales_excl_vat=total_sales_excl_vat,
        total_sale_vat=total_sale_vat,
        total_sales_incl_vat=total_sales_incl_vat,
        sale_count=len(sales),
        sale_by_group=json.dumps(sale_by_group),
        vat_payable=vat_payable if vat_payable > 0 else 0,
        vat_receivable=vat_receivable,
        net_vat=net_vat,
        total_profit_excl_vat=total_profit,
        average_profit_margin=avg_profit_margin,
        status=VATStatus.PENDING.value,
        created_by=current_user.id
    )
    
    db.add(summary)
    db.commit()
    db.refresh(summary)
    
    return summary


@router.get("/summaries", response_model=List[VATSummaryResponse])
def get_vat_summaries(
    year: Optional[int] = None,
    status: Optional[VATStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get all VAT summaries"""
    
    query = db.query(VATSummary)
    
    if year:
        query = query.filter(VATSummary.summary_year == year)
    
    if status:
        query = query.filter(VATSummary.status == status)
    
    if not current_user.is_admin():
        query = query.filter(VATSummary.branch_id == current_user.branch_id)
    
    summaries = query.order_by(VATSummary.summary_year.desc(), VATSummary.summary_month_num.desc()).all()
    
    # Parse JSON fields
    for summary in summaries:
        if summary.purchase_by_group:
            summary.purchase_by_group = json.loads(summary.purchase_by_group)
        if summary.sale_by_group:
            summary.sale_by_group = json.loads(summary.sale_by_group)
    
    return summaries


@router.put("/summaries/{summary_id}", response_model=VATSummaryResponse)
def update_vat_summary(
    summary_id: int,
    update_data: VATSummaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update VAT summary status (filed, paid, etc.)"""
    
    summary = db.query(VATSummary).filter(VATSummary.id == summary_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="VAT summary not found")
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(summary, field, value)
    
    summary.updated_at = datetime.now()
    db.commit()
    db.refresh(summary)
    
    return summary


# ==================== VAT RATE HISTORY ENDPOINTS ====================

@router.post("/rates", response_model=VATRateHistoryResponse)
def create_vat_rate(
    rate_data: VATRateHistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create new VAT rate record (when rate changes)"""
    
    # Set end date for previous rate
    previous_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    if previous_rate:
        previous_rate.effective_to = rate_data.effective_from - timedelta(days=1)
        db.commit()
    
    vat_rate = VATRateHistory(
        vat_rate=rate_data.vat_rate,
        effective_from=rate_data.effective_from,
        effective_to=rate_data.effective_to,
        notes=rate_data.notes,
        created_by=current_user.id
    )
    
    db.add(vat_rate)
    db.commit()
    db.refresh(vat_rate)
    
    return vat_rate


@router.get("/rates", response_model=List[VATRateHistoryResponse])
def get_vat_rates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get all VAT rate history"""
    
    rates = db.query(VATRateHistory).order_by(VATRateHistory.effective_from.desc()).all()
    return rates


@router.get("/rates/current")
def get_current_vat_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get current active VAT rate"""
    
    current_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    if not current_rate:
        return {"vat_rate": 15.0, "message": "Default rate 15%"}
    
    return {"vat_rate": current_rate.vat_rate, "effective_from": current_rate.effective_from}


# ==================== VAT REPORT ENDPOINTS ====================

@router.get("/reports/period", response_model=VATPeriodReport)
def get_vat_period_report(
    from_date: date,
    to_date: date,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Generate VAT report for a specific period"""
    
    start_datetime = datetime.combine(from_date, datetime.min.time())
    end_datetime = datetime.combine(to_date, datetime.max.time())
    
    # Get purchases
    purchase_query = db.query(VATPurchase).filter(
        VATPurchase.purchase_date >= start_datetime,
        VATPurchase.purchase_date <= end_datetime
    )
    
    if branch_id:
        purchase_query = purchase_query.filter(VATPurchase.branch_id == branch_id)
    
    purchases = purchase_query.all()
    
    # Get sales
    sale_query = db.query(VATSale).filter(
        VATSale.sale_date >= start_datetime,
        VATSale.sale_date <= end_datetime
    )
    
    if branch_id:
        sale_query = sale_query.filter(VATSale.branch_id == branch_id)
    
    sales = sale_query.all()
    
    # Calculate totals
    total_purchases = sum(p.total_cost for p in purchases)
    total_purchase_vat = sum(p.vat_amount for p in purchases)
    total_sales = sum(s.total_amount for s in sales)
    total_sale_vat = sum(s.vat_amount for s in sales)
    
    # Group by product group
    purchases_by_group = {}
    for p in purchases:
        group = p.product_group or "Uncategorized"
        purchases_by_group[group] = purchases_by_group.get(group, 0) + p.total_cost
    
    sales_by_group = {}
    for s in sales:
        group = s.product_group or "Uncategorized"
        sales_by_group[group] = sales_by_group.get(group, 0) + s.total_amount
    
    # VAT calculation
    vat_payable = max(0, total_sale_vat - total_purchase_vat)
    vat_receivable = max(0, total_purchase_vat - total_sale_vat)
    
    # Profit
    gross_profit = total_sales - total_purchases
    profit_margin = (gross_profit / total_sales * 100) if total_sales > 0 else 0
    
    return VATPeriodReport(
        period_start=from_date,
        period_end=to_date,
        branch_id=branch_id,
        total_purchases=total_purchases,
        total_purchase_vat=total_purchase_vat,
        purchases_by_group=purchases_by_group,
        total_sales=total_sales,
        total_sale_vat=total_sale_vat,
        sales_by_group=sales_by_group,
        vat_payable=vat_payable,
        vat_receivable=vat_receivable,
        net_vat_due=vat_payable - vat_receivable,
        gross_profit=gross_profit,
        profit_margin=profit_margin,
        purchase_transactions=purchases,
        sale_transactions=sales
    )


@router.get("/reports/product-groups", response_model=List[VATProductGroupReport])
def get_vat_product_group_report(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get VAT report grouped by product category"""
    
    query = db.query(VATPurchase)
    
    if year and month:
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)
        query = query.filter(
            VATPurchase.purchase_date >= start_date, 
            VATPurchase.purchase_date <= end_date
        )
    
    purchases = query.all()
    
    # Aggregate by product group
    groups = {}
    for p in purchases:
        group = p.product_group or "Uncategorized"
        if group not in groups:
            groups[group] = {
                "product_group": group,
                "total_purchases_excl_vat": 0,
                "total_purchase_vat": 0,
                "total_sales_excl_vat": 0,
                "total_sale_vat": 0,
                "vat_contribution": 0,
                "profit": 0,
                "profit_margin": 0,
                "quantity_purchased": 0,
                "quantity_sold": 0
            }
        
        groups[group]["total_purchases_excl_vat"] += p.total_cost
        groups[group]["total_purchase_vat"] += p.vat_amount
        groups[group]["quantity_purchased"] += p.quantity
        
        # Get sales for this purchase
        for sale in p.vat_sales:
            groups[group]["total_sales_excl_vat"] += sale.total_amount
            groups[group]["total_sale_vat"] += sale.vat_amount
            groups[group]["profit"] += sale.profit
            groups[group]["quantity_sold"] += sale.quantity
    
    # Calculate derived fields
    result = []
    for group in groups.values():
        group["vat_contribution"] = group["total_sale_vat"] - group["total_purchase_vat"]
        group["profit_margin"] = (group["profit"] / group["total_sales_excl_vat"] * 100) if group["total_sales_excl_vat"] > 0 else 0
        result.append(group)
    
    return result


@router.get("/dashboard", response_model=VATDashboardSummary)
def get_vat_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get VAT dashboard summary"""
    
    now = datetime.now()
    current_month = f"{now.year}-{now.month:02d}"
    previous_month_date = now.replace(day=1) - timedelta(days=1)
    previous_month = f"{previous_month_date.year}-{previous_month_date.month:02d}"
    
    # Get current month summary
    current_summary = db.query(VATSummary).filter(
        VATSummary.summary_month == current_month
    ).first()
    
    if current_summary and current_summary.purchase_by_group:
        current_summary.purchase_by_group = json.loads(current_summary.purchase_by_group)
        current_summary.sale_by_group = json.loads(current_summary.sale_by_group)
    
    # Get previous month summary
    previous_summary = db.query(VATSummary).filter(
        VATSummary.summary_month == previous_month
    ).first()
    
    if previous_summary and previous_summary.purchase_by_group:
        previous_summary.purchase_by_group = json.loads(previous_summary.purchase_by_group)
        previous_summary.sale_by_group = json.loads(previous_summary.sale_by_group)
    
    # Year to date totals
    year_start = datetime(now.year, 1, 1)
    year_to_date_purchases = db.query(VATPurchase).filter(
        VATPurchase.purchase_date >= year_start
    ).all()
    
    year_to_date_sales = db.query(VATSale).filter(
        VATSale.sale_date >= year_start
    ).all()
    
    ytd_purchases = sum(p.total_cost for p in year_to_date_purchases)
    ytd_sales = sum(s.total_amount for s in year_to_date_sales)
    ytd_purchase_vat = sum(p.vat_amount for p in year_to_date_purchases)
    ytd_sale_vat = sum(s.vat_amount for s in year_to_date_sales)
    
    # Pending returns
    pending_returns = db.query(VATSummary).filter(
        VATSummary.status == VATStatus.PENDING.value
    ).count()
    
    # Current VAT rate
    current_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    # Rate history
    rate_history = db.query(VATRateHistory).order_by(VATRateHistory.effective_from.desc()).limit(5).all()
    
    # Top product groups
    top_groups = get_vat_product_group_report(db=db, current_user=current_user)
    
    return VATDashboardSummary(
        current_month_summary=current_summary,
        previous_month_summary=previous_summary,
        year_to_date_purchases=ytd_purchases,
        year_to_date_sales=ytd_sales,
        year_to_date_vat_payable=ytd_sale_vat - ytd_purchase_vat,
        pending_vat_returns=pending_returns,
        current_vat_rate=current_rate.vat_rate if current_rate else 15.0,
        vat_rate_history=rate_history,
        top_product_groups_by_vat=top_groups[:5]
    )


# ==================== CALCULATION UTILITY ENDPOINTS ====================

@router.post("/calculate-selling-price")
def calculate_selling_price_endpoint(
    unit_cost: float,
    markup_percentage: float = Query(15.0, ge=0, le=100),
    vat_rate: float = Query(15.0, ge=0, le=100)
):
    """Calculate selling price based on cost, markup, and VAT"""
    result = calculate_selling_price(unit_cost, markup_percentage, vat_rate)
    return result


@router.post("/calculate-vat")
def calculate_vat_endpoint(
    amount: float,
    vat_rate: float = Query(15.0, ge=0, le=100)
):
    """Calculate VAT amount and total including VAT"""
    result = calculate_vat_amount(amount, vat_rate)
    return result