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
from app.schemas import (
    VATPurchaseCreate, VATPurchaseUpdate, VATPurchaseResponse,
    VATSaleCreate, VATSaleResponse, VATPurchaseStockResponse,
    VATSummaryCreate, VATSummaryUpdate, VATSummaryResponse,
    VATRateHistoryCreate, VATRateHistoryResponse,
    VATPeriodReport, VATProductGroupReport, VATDashboardSummary,
    calculate_vat_amount, calculate_selling_price, calculate_cogs_and_profit
)
from app.utils.dependencies import (
    get_current_user, require_privileged, require_admin, require_salesman
)

router = APIRouter(prefix="/api/vat", tags=["VAT Tracking"])


# ==================== HELPER FUNCTIONS ====================

def generate_vat_number(prefix: str = "VAT", branch_id: int = None) -> str:
    """Generate unique VAT transaction number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if branch_id:
        return f"{prefix}-{branch_id}-{timestamp}"
    return f"{prefix}-{timestamp}"


def generate_sale_number(branch_id: int = None) -> str:
    """Generate a simple sale number for auto-created sales"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if branch_id:
        return f"SALE-{branch_id}-{timestamp}"
    return f"SALE-{timestamp}"


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
        purchase_order = db.query(PurchaseOrder).filter(
            PurchaseOrder.id == purchase_data.purchase_order_id
        ).first()
        if purchase_order:
            branch_id = purchase_order.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="No branch assigned to user")
    
    # Convert to Decimal to ensure proper type
    quantity = Decimal(str(purchase_data.quantity))
    unit_cost = Decimal(str(purchase_data.unit_cost))
    vat_rate = Decimal(str(purchase_data.vat_rate))
    
    # Calculate totals
    total_cost = quantity * unit_cost
    vat_calc = calculate_vat_amount(float(total_cost), float(vat_rate))
    
    # Calculate selling price as unit_cost / 0.85 (approx 17.65% markup)
    selling_price_excl_vat = float(unit_cost) / 0.85
    selling_price_incl_vat = selling_price_excl_vat * (1 + float(vat_rate) / 100)
    
    # Use product_name from product_group if not provided
    product_name = purchase_data.product_name or purchase_data.product_group or "General Stock"
    
    # Create VAT purchase record - product_id is now optional
    vat_purchase = VATPurchase(
        vat_number=generate_vat_number("VAT-PUR", branch_id),
        purchase_order_id=purchase_data.purchase_order_id,
        branch_id=branch_id,
        product_id=purchase_data.product_id,  # Can be None
        product_name=product_name,
        product_group=purchase_data.product_group or "Uncategorized",
        sku=purchase_data.sku,
        quantity=quantity,
        unit_cost=unit_cost,
        total_cost=total_cost,
        vat_rate=vat_rate,
        vat_amount=Decimal(str(vat_calc["vat_amount"])),
        total_with_vat=Decimal(str(vat_calc["incl_vat"])),
        calculated_selling_price=Decimal(str(selling_price_excl_vat)),
        calculated_selling_price_with_vat=Decimal(str(selling_price_incl_vat)),
        current_stock=quantity,
        supplier_name=purchase_data.supplier_name,
        invoice_number=purchase_data.invoice_number,
        purchase_date=purchase_data.purchase_date,
        notes=purchase_data.notes,
        status='paid',  # Set status to 'paid' for stock that's ready to sell
        created_by=current_user.id
    )
    
    db.add(vat_purchase)
    db.commit()
    db.refresh(vat_purchase)
    
    # Record stock movement
    stock_movement = StockMovement(
        branch_id=branch_id,
        product_id=purchase_data.product_id,  # Can be None
        user_id=current_user.id,
        change_qty=quantity,
        movement_type="vat_purchase_in",
        with_vat=True,
        reference_id=vat_purchase.id,
        notes=f"VAT Purchase #{vat_purchase.vat_number} - SKU: {purchase_data.sku} - Cost: {unit_cost}"
    )
    db.add(stock_movement)
    
    # Update or create stock record
    stock = None
    if purchase_data.product_id:
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == purchase_data.product_id
        ).first()
    else:
        # For SKU-based stock, find by sku or create generic
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id.is_(None)
        ).first()
    
    if stock:
        stock.quantity += quantity
        if vat_rate > 0:
            stock.quantity_with_vat += quantity
        else:
            stock.quantity_without_vat += quantity
    else:
        stock = Stock(
            branch_id=branch_id,
            product_id=purchase_data.product_id,  # Can be None
            quantity=quantity,
            quantity_with_vat=quantity if vat_rate > 0 else Decimal('0'),
            quantity_without_vat=quantity if vat_rate == 0 else Decimal('0'),
            reorder_level=0
        )
        db.add(stock)
    
    db.commit()
    
    return vat_purchase


@router.get("/purchases", response_model=List[VATPurchaseResponse])
def get_vat_purchases(
    product_id: Optional[int] = None,
    product_group: Optional[str] = None,
    sku: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    query = db.query(VATPurchase)
    
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    if product_id:
        query = query.filter(VATPurchase.product_id == product_id)
    if sku:
        query = query.filter(VATPurchase.sku == sku)
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
    purchase = db.query(VATPurchase).filter(VATPurchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
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
    purchase = db.query(VATPurchase).filter(VATPurchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        if field in ['quantity', 'unit_cost', 'vat_rate'] and value is not None:
            value = Decimal(str(value))
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
    current_user: User = Depends(require_salesman)
):
    """Create a VAT sale record (when selling from stock)
       If sale_id is not provided, it will auto-create a regular sale."""
    
    vat_purchase = db.query(VATPurchase).filter(
        VATPurchase.id == sale_data.vat_purchase_id
    ).first()
    
    if not vat_purchase:
        raise HTTPException(status_code=404, detail="VAT purchase not found")
    
    quantity = Decimal(str(sale_data.quantity))
    selling_price = Decimal(str(sale_data.selling_price))
    
    if vat_purchase.current_stock < quantity:
        raise HTTPException(
            status_code=400, 
            detail=f"Insufficient stock. Available: {vat_purchase.current_stock}"
        )
    
    # Check if sale_id is provided, if not, create a regular sale automatically
    sale = None
    if sale_data.sale_id:
        sale = db.query(Sale).filter(Sale.id == sale_data.sale_id).first()
        if not sale:
            raise HTTPException(status_code=404, detail="Sale not found")
    else:
        # Auto-create a regular sale for this VAT sale
        branch_id = current_user.branch_id or vat_purchase.branch_id
        total_amount = float(quantity * selling_price)
        
        sale = Sale(
            invoice_number=generate_sale_number(branch_id),
            branch_id=branch_id,
            user_id=current_user.id,
            customer_name=sale_data.customer_name or "Walk-in Customer",
            customer_phone=None,
            customer_email=None,
            subtotal=Decimal(str(total_amount)),
            tax_amount=Decimal('0'),
            tax_rate=Decimal('0'),
            discount_amount=Decimal('0'),
            discount_type="fixed",
            shipping_cost=Decimal('0'),
            total_amount=Decimal(str(total_amount)),
            total_cost=quantity * vat_purchase.unit_cost,
            payment_method="cash",
            bank_account_id=None,
            transaction_reference=None,
            status="completed",
            refund_amount=Decimal('0'),
            refund_status="none",
            notes=sale_data.notes
        )
        db.add(sale)
        db.flush()  # Get the sale ID without committing yet
    
    vat_calc = calculate_vat_amount(
        float(quantity * selling_price), 
        float(vat_purchase.vat_rate)
    )
    
    cogs_calc = calculate_cogs_and_profit(
        float(quantity),
        float(vat_purchase.unit_cost),
        float(selling_price)
    )
    
    vat_sale = VATSale(
        vat_sale_number=generate_vat_number("VAT-SALE", sale.branch_id),
        sale_id=sale.id,
        sale_item_id=sale_data.sale_item_id,
        vat_purchase_id=sale_data.vat_purchase_id,
        branch_id=sale.branch_id,
        product_id=vat_purchase.product_id,
        product_name=vat_purchase.product_name,
        product_group=vat_purchase.product_group,
        sku=vat_purchase.sku,
        quantity=quantity,
        unit_cost=vat_purchase.unit_cost,
        selling_price=selling_price,
        selling_price_with_vat=Decimal(str(vat_calc["incl_vat"] / float(quantity))) if quantity > 0 else Decimal('0'),
        vat_rate=vat_purchase.vat_rate,
        vat_amount=Decimal(str(vat_calc["vat_amount"])),
        total_amount=Decimal(str(vat_calc["excl_vat"])),
        total_amount_with_vat=Decimal(str(vat_calc["incl_vat"])),
        cost_of_goods_sold=Decimal(str(cogs_calc["cogs"])),
        profit=Decimal(str(cogs_calc["profit"])),
        profit_margin=Decimal(str(cogs_calc["profit_margin"])),
        customer_name=sale.customer_name,
        invoice_number=sale.invoice_number,
        sale_date=sale.created_at,
        created_by=current_user.id
    )
    
    db.add(vat_sale)
    
    vat_purchase.sold_quantity += quantity
    vat_purchase.sold_value += quantity * selling_price
    vat_purchase.sold_vat += Decimal(str(vat_calc["vat_amount"]))
    update_vat_purchase_stock(vat_purchase, db)
    
    stock_movement = StockMovement(
        branch_id=sale.branch_id,
        product_id=vat_purchase.product_id,
        user_id=current_user.id,
        change_qty=-quantity,
        movement_type="vat_sale_out",
        with_vat=True,
        reference_id=vat_sale.id,
        notes=f"VAT Sale #{vat_sale.vat_sale_number} - SKU: {vat_purchase.sku} - Price: {selling_price}"
    )
    db.add(stock_movement)
    
    stock = db.query(Stock).filter(
        Stock.branch_id == sale.branch_id,
        Stock.product_id == vat_purchase.product_id
    ).first()
    
    if stock:
        stock.quantity -= quantity
        if vat_purchase.vat_rate > 0:
            stock.quantity_with_vat -= quantity
        else:
            stock.quantity_without_vat -= quantity
    
    db.commit()
    db.refresh(vat_sale)
    
    return vat_sale


@router.get("/sales", response_model=List[VATSaleResponse])
def get_vat_sales(
    product_id: Optional[int] = None,
    sku: Optional[str] = None,
    product_group: Optional[str] = None,
    vat_purchase_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_salesman)
):
    """Get all VAT sales with filters"""
    
    query = db.query(VATSale)
    
    if not current_user.is_admin():
        query = query.filter(VATSale.branch_id == current_user.branch_id)
    
    if product_id:
        query = query.filter(VATSale.product_id == product_id)
    if sku:
        query = query.filter(VATSale.sku == sku)
    if product_group:
        query = query.filter(VATSale.product_group == product_group)
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
    current_user: User = Depends(require_salesman)
):
    """Get single VAT sale by ID"""
    
    sale = db.query(VATSale).filter(VATSale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="VAT sale not found")
    
    if not current_user.is_admin() and sale.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return sale


# ==================== STOCK TRACKING ENDPOINTS ====================

@router.get("/stock", response_model=List[VATPurchaseStockResponse])
def get_vat_stock_by_product(
    product_id: Optional[int] = None,
    sku: Optional[str] = None,
    product_group: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_salesman)
):
    """Get available stock from PAID VAT purchases for a product or SKU group.
       Only shows purchases with status 'paid' (fully paid) and positive stock."""
    
    # Filter by status 'paid' and current_stock > 0
    query = db.query(VATPurchase).filter(
        VATPurchase.current_stock > 0,
        VATPurchase.status == 'paid'
    )
    
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    # Apply filters only if provided
    if product_id:
        query = query.filter(VATPurchase.product_id == product_id)
    if sku:
        query = query.filter(VATPurchase.sku == sku)
    if product_group:
        query = query.filter(VATPurchase.product_group == product_group)
    
    # Order by purchase date for FIFO
    purchases = query.order_by(VATPurchase.purchase_date.asc()).all()
    
    # Convert to response format
    stock_items = []
    for p in purchases:
        # Calculate selling price as unit_cost / 0.85 (approx 17.65% markup)
        selling_price_excl_vat = float(p.unit_cost) / 0.85
        
        stock_items.append({
            "id": p.id,
            "vat_number": p.vat_number,
            "product_id": p.product_id,
            "product_name": p.product_name,
            "product_group": p.product_group,
            "sku": p.sku,
            "current_stock": float(p.current_stock),
            "unit_cost": float(p.unit_cost),
            "current_value": float(p.current_value),
            "purchase_date": p.purchase_date,
            "supplier_name": p.supplier_name,
            "calculated_selling_price": selling_price_excl_vat,
            "vat_rate": float(p.vat_rate),
            "status": p.status
        })
    
    print(f"Found {len(stock_items)} stock items from PAID purchases for user {current_user.id}")
    
    return stock_items


@router.get("/stock-summary")
def get_vat_stock_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_salesman)
):
    """Get summary of all VAT stock from PAID purchases only"""
    
    query = db.query(VATPurchase).filter(
        VATPurchase.current_stock > 0,
        VATPurchase.status == 'paid'
    )
    
    if not current_user.is_admin():
        query = query.filter(VATPurchase.branch_id == current_user.branch_id)
    
    purchases = query.all()
    
    total_stock_value = sum(p.current_value for p in purchases)
    total_stock_vat = sum(p.current_vat for p in purchases)
    total_items = sum(p.current_stock for p in purchases)
    
    return {
        "total_items": float(total_items),
        "total_stock_value": float(total_stock_value),
        "total_stock_vat": float(total_stock_vat),
        "total_stock_with_vat": float(total_stock_value + total_stock_vat),
        "unique_products": len(set(p.product_id for p in purchases if p.product_id)),
        "unique_sku_groups": len(set(p.sku for p in purchases if p.sku)),
        "purchase_batches": len(purchases)
    }


@router.get("/stock/debug")
def debug_vat_stock(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Debug endpoint to check what VAT purchases exist"""
    
    # Get all VAT purchases
    all_purchases = db.query(VATPurchase).all()
    
    # Get purchases with current_stock > 0
    purchases_with_stock = db.query(VATPurchase).filter(VATPurchase.current_stock > 0).all()
    
    # Get purchases by status
    paid_purchases = db.query(VATPurchase).filter(VATPurchase.status == 'paid').all()
    pending_purchases = db.query(VATPurchase).filter(VATPurchase.status == 'pending').all()
    completed_purchases = db.query(VATPurchase).filter(VATPurchase.status == 'completed').all()
    null_status = db.query(VATPurchase).filter(VATPurchase.status.is_(None)).all()
    
    # Get paid purchases with stock > 0 (what should show in POS)
    available_stock = db.query(VATPurchase).filter(
        VATPurchase.status == 'paid',
        VATPurchase.current_stock > 0
    ).all()
    
    return {
        "total_vat_purchases": len(all_purchases),
        "purchases_with_positive_stock": len(purchases_with_stock),
        "purchases_with_status_paid": len(paid_purchases),
        "purchases_with_status_pending": len(pending_purchases),
        "purchases_with_status_completed": len(completed_purchases),
        "purchases_with_null_status": len(null_status),
        "available_for_sale (paid + stock>0)": len(available_stock),
        "all_purchases": [
            {
                "id": p.id,
                "vat_number": p.vat_number,
                "product_name": p.product_name,
                "current_stock": float(p.current_stock),
                "quantity": float(p.quantity),
                "sold_quantity": float(p.sold_quantity),
                "status": p.status,
                "unit_cost": float(p.unit_cost),
                "selling_price": float(p.calculated_selling_price) if p.calculated_selling_price else None,
                "branch_id": p.branch_id,
                "product_group": p.product_group,
                "sku": p.sku
            }
            for p in all_purchases[:20]
        ]
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
    
    summary_month = f"{year}-{month:02d}"
    existing = db.query(VATSummary).filter(
        VATSummary.summary_month == summary_month,
        VATSummary.branch_id == current_user.branch_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Summary already exists for this month")
    
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
    
    purchases = db.query(VATPurchase).filter(
        VATPurchase.purchase_date >= start_date,
        VATPurchase.purchase_date <= end_date
    )
    
    if not current_user.is_admin():
        purchases = purchases.filter(VATPurchase.branch_id == current_user.branch_id)
    
    purchases = purchases.all()
    
    total_purchases_excl_vat = sum(p.total_cost for p in purchases)
    total_purchase_vat = sum(p.vat_amount for p in purchases)
    total_purchases_incl_vat = sum(p.total_with_vat for p in purchases)
    
    purchase_by_group = {}
    for p in purchases:
        group = p.product_group or "Uncategorized"
        if group not in purchase_by_group:
            purchase_by_group[group] = {"excl_vat": 0, "vat": 0, "incl_vat": 0}
        purchase_by_group[group]["excl_vat"] += float(p.total_cost)
        purchase_by_group[group]["vat"] += float(p.vat_amount)
        purchase_by_group[group]["incl_vat"] += float(p.total_with_vat)
    
    sales = db.query(VATSale).filter(
        VATSale.sale_date >= start_date,
        VATSale.sale_date <= end_date
    )
    
    if not current_user.is_admin():
        sales = sales.filter(VATSale.branch_id == current_user.branch_id)
    
    sales = sales.all()
    
    total_sales_excl_vat = sum(s.total_amount for s in sales)
    total_sale_vat = sum(s.vat_amount for s in sales)
    total_sales_incl_vat = sum(s.total_amount_with_vat for s in sales)
    total_profit = sum(s.profit for s in sales)
    avg_profit_margin = (float(total_profit) / float(total_sales_excl_vat) * 100) if total_sales_excl_vat > 0 else 0
    
    sale_by_group = {}
    for s in sales:
        group = s.product_group or "Uncategorized"
        if group not in sale_by_group:
            sale_by_group[group] = {"excl_vat": 0, "vat": 0, "incl_vat": 0, "profit": 0}
        sale_by_group[group]["excl_vat"] += float(s.total_amount)
        sale_by_group[group]["vat"] += float(s.vat_amount)
        sale_by_group[group]["incl_vat"] += float(s.total_amount_with_vat)
        sale_by_group[group]["profit"] += float(s.profit)
    
    vat_payable = float(total_sale_vat - total_purchase_vat)
    vat_receivable = float(total_purchase_vat - total_sale_vat) if vat_payable < 0 else 0
    net_vat = vat_payable if vat_payable > 0 else -vat_receivable
    
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
        average_profit_margin=Decimal(str(avg_profit_margin)),
        status='pending',
        created_by=current_user.id
    )
    
    db.add(summary)
    db.commit()
    db.refresh(summary)
    
    if summary.purchase_by_group:
        summary.purchase_by_group = json.loads(summary.purchase_by_group)
    if summary.sale_by_group:
        summary.sale_by_group = json.loads(summary.sale_by_group)
    
    return summary


@router.get("/summaries", response_model=List[VATSummaryResponse])
def get_vat_summaries(
    year: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    query = db.query(VATSummary)
    
    if year:
        query = query.filter(VATSummary.summary_year == year)
    if status:
        query = query.filter(VATSummary.status == status)
    if not current_user.is_admin():
        query = query.filter(VATSummary.branch_id == current_user.branch_id)
    
    summaries = query.order_by(VATSummary.summary_year.desc(), VATSummary.summary_month_num.desc()).all()
    
    for summary in summaries:
        if summary.purchase_by_group:
            summary.purchase_by_group = json.loads(summary.purchase_by_group)
        else:
            summary.purchase_by_group = {}
        if summary.sale_by_group:
            summary.sale_by_group = json.loads(summary.sale_by_group)
        else:
            summary.sale_by_group = {}
    
    return summaries


@router.put("/summaries/{summary_id}", response_model=VATSummaryResponse)
def update_vat_summary(
    summary_id: int,
    update_data: VATSummaryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    summary = db.query(VATSummary).filter(VATSummary.id == summary_id).first()
    if not summary:
        raise HTTPException(status_code=404, detail="VAT summary not found")
    
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(summary, field, value)
    
    summary.updated_at = datetime.now()
    db.commit()
    db.refresh(summary)
    
    if summary.purchase_by_group:
        summary.purchase_by_group = json.loads(summary.purchase_by_group)
    if summary.sale_by_group:
        summary.sale_by_group = json.loads(summary.sale_by_group)
    
    return summary


# ==================== VAT RATE HISTORY ENDPOINTS ====================

@router.post("/rates", response_model=VATRateHistoryResponse)
def create_vat_rate(
    rate_data: VATRateHistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    previous_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    if previous_rate:
        previous_rate.effective_to = rate_data.effective_from - timedelta(days=1)
        db.commit()
    
    vat_rate = VATRateHistory(
        vat_rate=Decimal(str(rate_data.vat_rate)),
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
    rates = db.query(VATRateHistory).order_by(VATRateHistory.effective_from.desc()).all()
    return rates


@router.get("/rates/current")
def get_current_vat_rate(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    current_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    if not current_rate:
        return {"vat_rate": 15.0, "message": "Default rate 15%"}
    
    return {"vat_rate": float(current_rate.vat_rate), "effective_from": current_rate.effective_from}


# ==================== VAT REPORT ENDPOINTS ====================

@router.get("/reports/period", response_model=VATPeriodReport)
def get_vat_period_report(
    from_date: date,
    to_date: date,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    start_datetime = datetime.combine(from_date, datetime.min.time())
    end_datetime = datetime.combine(to_date, datetime.max.time())
    
    purchase_query = db.query(VATPurchase).filter(
        VATPurchase.purchase_date >= start_datetime,
        VATPurchase.purchase_date <= end_datetime
    )
    if branch_id:
        purchase_query = purchase_query.filter(VATPurchase.branch_id == branch_id)
    purchases = purchase_query.all()
    
    sale_query = db.query(VATSale).filter(
        VATSale.sale_date >= start_datetime,
        VATSale.sale_date <= end_datetime
    )
    if branch_id:
        sale_query = sale_query.filter(VATSale.branch_id == branch_id)
    sales = sale_query.all()
    
    total_purchases = sum(p.total_cost for p in purchases)
    total_purchase_vat = sum(p.vat_amount for p in purchases)
    total_sales = sum(s.total_amount for s in sales)
    total_sale_vat = sum(s.vat_amount for s in sales)
    
    purchases_by_group = {}
    for p in purchases:
        group = p.product_group or "Uncategorized"
        purchases_by_group[group] = purchases_by_group.get(group, 0) + float(p.total_cost)
    
    sales_by_group = {}
    for s in sales:
        group = s.product_group or "Uncategorized"
        sales_by_group[group] = sales_by_group.get(group, 0) + float(s.total_amount)
    
    vat_payable = max(0, float(total_sale_vat - total_purchase_vat))
    vat_receivable = max(0, float(total_purchase_vat - total_sale_vat))
    
    gross_profit = float(total_sales - total_purchases)
    profit_margin = (gross_profit / float(total_sales) * 100) if total_sales > 0 else 0
    
    return VATPeriodReport(
        period_start=from_date,
        period_end=to_date,
        branch_id=branch_id,
        total_purchases=float(total_purchases),
        total_purchase_vat=float(total_purchase_vat),
        purchases_by_group=purchases_by_group,
        total_sales=float(total_sales),
        total_sale_vat=float(total_sale_vat),
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
        
        groups[group]["total_purchases_excl_vat"] += float(p.total_cost)
        groups[group]["total_purchase_vat"] += float(p.vat_amount)
        groups[group]["quantity_purchased"] += float(p.quantity)
        
        for sale in p.vat_sales:
            groups[group]["total_sales_excl_vat"] += float(sale.total_amount)
            groups[group]["total_sale_vat"] += float(sale.vat_amount)
            groups[group]["profit"] += float(sale.profit)
            groups[group]["quantity_sold"] += float(sale.quantity)
    
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
    now = datetime.now()
    current_month = f"{now.year}-{now.month:02d}"
    previous_month_date = now.replace(day=1) - timedelta(days=1)
    previous_month = f"{previous_month_date.year}-{previous_month_date.month:02d}"
    
    current_summary = db.query(VATSummary).filter(
        VATSummary.summary_month == current_month
    ).first()
    
    if current_summary:
        if current_summary.purchase_by_group:
            current_summary.purchase_by_group = json.loads(current_summary.purchase_by_group)
        else:
            current_summary.purchase_by_group = {}
        if current_summary.sale_by_group:
            current_summary.sale_by_group = json.loads(current_summary.sale_by_group)
        else:
            current_summary.sale_by_group = {}
    
    previous_summary = db.query(VATSummary).filter(
        VATSummary.summary_month == previous_month
    ).first()
    
    if previous_summary:
        if previous_summary.purchase_by_group:
            previous_summary.purchase_by_group = json.loads(previous_summary.purchase_by_group)
        else:
            previous_summary.purchase_by_group = {}
        if previous_summary.sale_by_group:
            previous_summary.sale_by_group = json.loads(previous_summary.sale_by_group)
        else:
            previous_summary.sale_by_group = {}
    
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
    
    pending_returns = db.query(VATSummary).filter(
        VATSummary.status == 'pending'
    ).count()
    
    current_rate = db.query(VATRateHistory).filter(
        VATRateHistory.effective_to.is_(None)
    ).first()
    
    rate_history = db.query(VATRateHistory).order_by(VATRateHistory.effective_from.desc()).limit(5).all()
    top_groups = get_vat_product_group_report(db=db, current_user=current_user)
    
    return VATDashboardSummary(
        current_month_summary=current_summary,
        previous_month_summary=previous_summary,
        year_to_date_purchases=float(ytd_purchases),
        year_to_date_sales=float(ytd_sales),
        year_to_date_vat_payable=float(ytd_sale_vat - ytd_purchase_vat),
        pending_vat_returns=pending_returns,
        current_vat_rate=float(current_rate.vat_rate) if current_rate else 15.0,
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
    result = calculate_selling_price(unit_cost, markup_percentage, vat_rate)
    return result


@router.post("/calculate-vat")
def calculate_vat_endpoint(
    amount: float,
    vat_rate: float = Query(15.0, ge=0, le=100)
):
    result = calculate_vat_amount(amount, vat_rate)
    return result