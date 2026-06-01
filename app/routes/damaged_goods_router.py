from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid

from app.database import get_db
from app.models import (
    User, Branch, Product, Stock, StockMovement, DamagedGoods, DamagedGoodsStatus
)
from app.schemas import (
    DamagedGoodsCreate, DamagedGoodsUpdate, DamagedGoodsResponse, 
    DamagedGoodsApprove
)
# FIXED: Import both from dependencies
from app.utils.dependencies import get_current_user, require_privileged

router = APIRouter(prefix="/api/damaged-goods", tags=["Damaged Goods"])

def generate_report_number():
    return f"DMG-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

# Create damaged goods report (Sales and privileged users)
@router.post("/reports", response_model=DamagedGoodsResponse, status_code=status.HTTP_201_CREATED)
def create_damaged_report(
    report_data: DamagedGoodsCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Create a damaged goods report and deduct stock immediately"""
    
    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    # Check product exists
    product = db.query(Product).filter(Product.id == report_data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Check stock availability
    stock = db.query(Stock).filter(
        Stock.branch_id == current_user.branch_id,
        Stock.product_id == report_data.product_id
    ).first()
    
    if not stock or stock.quantity < report_data.quantity:
        available = float(stock.quantity) if stock else 0
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {available}, Requested: {report_data.quantity}"
        )
    
    # Get current stock values before deduction
    old_quantity = float(stock.quantity)
    old_with_vat = float(stock.quantity_with_vat) if hasattr(stock, 'quantity_with_vat') and stock.quantity_with_vat else 0
    old_without_vat = float(stock.quantity_without_vat) if hasattr(stock, 'quantity_without_vat') and stock.quantity_without_vat else 0
    
    # Calculate proportion to deduct from VAT and non-VAT stock
    quantity_to_deduct = report_data.quantity
    vat_proportion = old_with_vat / old_quantity if old_quantity > 0 else 0
    without_vat_proportion = old_without_vat / old_quantity if old_quantity > 0 else 0
    
    # Deduct proportionally
    new_with_vat = max(0, old_with_vat - (quantity_to_deduct * vat_proportion))
    new_without_vat = max(0, old_without_vat - (quantity_to_deduct * without_vat_proportion))
    
    # Update stock
    stock.quantity -= Decimal(str(report_data.quantity))
    if hasattr(stock, 'quantity_with_vat'):
        stock.quantity_with_vat = Decimal(str(new_with_vat))
    if hasattr(stock, 'quantity_without_vat'):
        stock.quantity_without_vat = Decimal(str(new_without_vat))
    
    # Create damaged goods report
    damaged_report = DamagedGoods(
        report_number=generate_report_number(),
        branch_id=current_user.branch_id,
        product_id=report_data.product_id,
        quantity=Decimal(str(report_data.quantity)),
        reason=report_data.reason,
        notes=report_data.notes,
        reported_by=current_user.id,
        status=DamagedGoodsStatus.PROCESSED.value,  # Auto-process since stock is deducted
        processed_by=current_user.id,
        processed_at=datetime.now()
    )
    
    db.add(damaged_report)
    
    # Record stock movement
    stock_movement = StockMovement(
        branch_id=current_user.branch_id,
        product_id=report_data.product_id,
        user_id=current_user.id,
        change_qty=-Decimal(str(report_data.quantity)),
        movement_type="damaged",
        reference_id=damaged_report.id,
        notes=f"Damaged goods reported: {report_data.reason}"
    )
    db.add(stock_movement)
    
    db.commit()
    db.refresh(damaged_report)
    
    # Build response
    branch = db.query(Branch).filter(Branch.id == damaged_report.branch_id).first()
    reporter = db.query(User).filter(User.id == damaged_report.reported_by).first()
    
    return {
        "id": damaged_report.id,
        "report_number": damaged_report.report_number,
        "branch_id": damaged_report.branch_id,
        "branch_name": branch.name if branch else None,
        "product_id": damaged_report.product_id,
        "product_name": product.name,
        "product_sku": product.sku,
        "quantity": float(damaged_report.quantity),
        "reason": damaged_report.reason,
        "notes": damaged_report.notes,
        "reported_by": reporter.name if reporter else "System",
        "reported_at": damaged_report.reported_at,
        "status": damaged_report.status,
        "approved_by": None,
        "approved_at": None,
        "processed_by": current_user.name,
        "processed_at": damaged_report.processed_at,
        "created_at": damaged_report.created_at,
        "updated_at": damaged_report.updated_at
    }


# Get all damaged goods reports (Admin and privileged users)
@router.get("/reports", response_model=List[DamagedGoodsResponse])
def get_damaged_reports(
    status: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get damaged goods reports (Admin sees all, sales see their branch only)"""
    
    query = db.query(DamagedGoods)
    
    # Filter by branch for non-admin users
    if not current_user.is_admin():
        query = query.filter(DamagedGoods.branch_id == current_user.branch_id)
    
    if status:
        query = query.filter(DamagedGoods.status == status)
    if from_date:
        start_date = datetime.combine(from_date, datetime.min.time())
        query = query.filter(DamagedGoods.reported_at >= start_date)
    if to_date:
        end_date = datetime.combine(to_date, datetime.max.time())
        query = query.filter(DamagedGoods.reported_at <= end_date)
    
    reports = query.order_by(DamagedGoods.reported_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for report in reports:
        branch = db.query(Branch).filter(Branch.id == report.branch_id).first()
        product = db.query(Product).filter(Product.id == report.product_id).first()
        reporter = db.query(User).filter(User.id == report.reported_by).first()
        
        result.append({
            "id": report.id,
            "report_number": report.report_number,
            "branch_id": report.branch_id,
            "branch_name": branch.name if branch else None,
            "product_id": report.product_id,
            "product_name": product.name if product else None,
            "product_sku": product.sku if product else None,
            "quantity": float(report.quantity),
            "reason": report.reason,
            "notes": report.notes,
            "reported_by": reporter.name if reporter else "System",
            "reported_at": report.reported_at,
            "status": report.status,
            "approved_by": None,
            "approved_at": None,
            "processed_by": None,
            "processed_at": None,
            "created_at": report.created_at,
            "updated_at": report.updated_at
        })
    
    return result


# Get single damaged goods report
@router.get("/reports/{report_id}", response_model=DamagedGoodsResponse)
def get_damaged_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get a single damaged goods report by ID"""
    
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Damaged goods report not found")
    
    # Check branch access
    if not current_user.is_admin() and report.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    branch = db.query(Branch).filter(Branch.id == report.branch_id).first()
    product = db.query(Product).filter(Product.id == report.product_id).first()
    reporter = db.query(User).filter(User.id == report.reported_by).first()
    processor = db.query(User).filter(User.id == report.processed_by).first() if report.processed_by else None
    
    return {
        "id": report.id,
        "report_number": report.report_number,
        "branch_id": report.branch_id,
        "branch_name": branch.name if branch else None,
        "product_id": report.product_id,
        "product_name": product.name if product else None,
        "product_sku": product.sku if product else None,
        "quantity": float(report.quantity),
        "reason": report.reason,
        "notes": report.notes,
        "reported_by": reporter.name if reporter else "System",
        "reported_at": report.reported_at,
        "status": report.status,
        "approved_by": None,
        "approved_at": None,
        "processed_by": processor.name if processor else None,
        "processed_at": report.processed_at,
        "created_at": report.created_at,
        "updated_at": report.updated_at
    }


# Update damaged goods report (Admin only)
@router.put("/reports/{report_id}", response_model=DamagedGoodsResponse)
def update_damaged_report(
    report_id: int,
    update_data: DamagedGoodsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Update a damaged goods report (Admin only)"""
    
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Damaged goods report not found")
    
    # Only admin can update
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if update_data.status:
        report.status = update_data.status
    if update_data.notes:
        report.notes = update_data.notes
    
    report.updated_at = datetime.now()
    db.commit()
    db.refresh(report)
    
    branch = db.query(Branch).filter(Branch.id == report.branch_id).first()
    product = db.query(Product).filter(Product.id == report.product_id).first()
    reporter = db.query(User).filter(User.id == report.reported_by).first()
    
    return {
        "id": report.id,
        "report_number": report.report_number,
        "branch_id": report.branch_id,
        "branch_name": branch.name if branch else None,
        "product_id": report.product_id,
        "product_name": product.name if product else None,
        "product_sku": product.sku if product else None,
        "quantity": float(report.quantity),
        "reason": report.reason,
        "notes": report.notes,
        "reported_by": reporter.name if reporter else "System",
        "reported_at": report.reported_at,
        "status": report.status,
        "approved_by": None,
        "approved_at": None,
        "processed_by": None,
        "processed_at": None,
        "created_at": report.created_at,
        "updated_at": report.updated_at
    }


# Get damaged goods summary/stats
@router.get("/summary/stats")
def get_damaged_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get damaged goods summary statistics"""
    
    from_date = datetime.now() - timedelta(days=days)
    
    query = db.query(DamagedGoods).filter(DamagedGoods.reported_at >= from_date)
    
    # Filter by branch for non-admin
    if not current_user.is_admin():
        query = query.filter(DamagedGoods.branch_id == current_user.branch_id)
    
    total_reports = query.count()
    total_quantity = db.query(func.sum(DamagedGoods.quantity)).filter(
        DamagedGoods.reported_at >= from_date
    ).scalar() or 0
    
    # Group by reason
    reasons_breakdown = db.query(
        DamagedGoods.reason,
        func.sum(DamagedGoods.quantity).label('total_quantity'),
        func.count(DamagedGoods.id).label('report_count')
    ).filter(
        DamagedGoods.reported_at >= from_date
    ).group_by(DamagedGoods.reason).order_by(
        func.sum(DamagedGoods.quantity).desc()
    ).all()
    
    # Top damaged products
    top_products = db.query(
        DamagedGoods.product_id,
        Product.name,
        func.sum(DamagedGoods.quantity).label('total_quantity'),
        func.count(DamagedGoods.id).label('report_count')
    ).join(Product, DamagedGoods.product_id == Product.id).filter(
        DamagedGoods.reported_at >= from_date
    ).group_by(DamagedGoods.product_id, Product.name).order_by(
        func.sum(DamagedGoods.quantity).desc()
    ).limit(10).all()
    
    return {
        "period_days": days,
        "summary": {
            "total_reports": total_reports,
            "total_quantity": float(total_quantity)
        },
        "reasons_breakdown": [
            {
                "reason": r.reason,
                "total_quantity": float(r.total_quantity),
                "report_count": r.report_count
            }
            for r in reasons_breakdown
        ],
        "top_damaged_products": [
            {
                "product_id": p.product_id,
                "product_name": p.name,
                "total_quantity": float(p.total_quantity),
                "report_count": p.report_count
            }
            for p in top_products
        ]
    }


# Delete damaged goods report (Admin only)
@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_damaged_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Delete a damaged goods report (Admin only)"""
    
    # Only admin can delete
    if not current_user.is_admin():
        raise HTTPException(status_code=403, detail="Admin access required")
    
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Damaged goods report not found")
    
    # Note: This does NOT restore the stock
    db.delete(report)
    db.commit()
    
    return None