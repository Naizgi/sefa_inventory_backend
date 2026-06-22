
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal

from app.database import get_db
from app import models, schemas
from app.utils.dependencies import get_current_user, get_current_active_user, require_admin
from .wallet import process_wallet_transaction

router = APIRouter(prefix="/debts", tags=["Debts"])

print("✅ Debt router module loaded!")


# ==================== HELPER FUNCTIONS ====================

def generate_debt_number(db: Session) -> str:
    """Generate a unique debt number"""
    today = datetime.now()
    prefix = f"DEBT-{today.year}{today.month:02d}{today.day:02d}-"
    
    count = db.query(models.Debt).filter(
        models.Debt.created_at >= today.replace(hour=0, minute=0, second=0)
    ).count()
    
    return f"{prefix}{count + 1:04d}"


def generate_payment_number(db: Session) -> str:
    """Generate a unique payment number"""
    today = datetime.now()
    prefix = f"PAY-{today.year}{today.month:02d}{today.day:02d}-"
    
    count = db.query(models.DebtPayment).filter(
        models.DebtPayment.created_at >= today.replace(hour=0, minute=0, second=0)
    ).count()
    
    return f"{prefix}{count + 1:04d}"


def update_debt_status(debt: models.Debt) -> None:
    """Update debt status based on paid amount"""
    if debt.remaining_amount <= 0:
        debt.status = models.DebtStatus.SETTLED.value
    elif debt.paid_amount > 0:
        debt.status = models.DebtStatus.PARTIALLY_PAID.value
    else:
        debt.status = models.DebtStatus.ACTIVE.value


def process_product_payment(
    db: Session,
    debt_payment: models.DebtPayment,
    product_items: List[schemas.DebtProductPaymentItem],
    branch_id: int,
    user_id: int
) -> List[models.DebtProductPayment]:
    """Process product payments and deduct from stock"""
    product_payments = []
    
    for item in product_items:
        # Get product stock
        stock = db.query(models.Stock).filter(
            models.Stock.branch_id == branch_id,
            models.Stock.product_id == item.product_id
        ).first()
        
        if not stock:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item.product_id} not found in stock"
            )
        
        if stock.quantity < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for product {item.product_id}. Available: {stock.quantity}, Required: {item.quantity}"
            )
        
        # Deduct from stock
        stock.quantity -= item.quantity
        
        # Create stock movement
        stock_movement = models.StockMovement(
            branch_id=branch_id,
            product_id=item.product_id,
            user_id=user_id,
            change_qty=-item.quantity,
            movement_type="debt_payment",
            with_vat=True,
            notes=f"Debt payment - product used to settle debt"
        )
        db.add(stock_movement)
        db.flush()
        
        # Create debt product payment record
        product_payment = models.DebtProductPayment(
            debt_payment_id=debt_payment.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            total_amount=item.total_amount,
            stock_movement_id=stock_movement.id
        )
        db.add(product_payment)
        db.flush()
        
        product_payments.append(product_payment)
    
    return product_payments


# ==================== DEBT CRUD OPERATIONS ====================

@router.post("/", response_model=schemas.DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_debt(
    debt_data: schemas.DebtCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Create a new debt record"""
    debt_number = generate_debt_number(db)
    
    debt = models.Debt(
        debt_number=debt_number,
        branch_id=debt_data.branch_id,
        supplier_name=debt_data.supplier_name,
        supplier_phone=debt_data.supplier_phone,
        supplier_email=debt_data.supplier_email,
        total_amount=debt_data.amount,
        paid_amount=debt_data.initial_payment_amount if debt_data.initial_payment_amount else 0,
        remaining_amount=debt_data.amount - (debt_data.initial_payment_amount if debt_data.initial_payment_amount else 0),
        description=debt_data.description,
        notes=debt_data.notes,
        status=models.DebtStatus.ACTIVE.value,
        created_by=current_user.id,
        requires_approval=current_user.role != "admin",
        approval_status="pending" if current_user.role != "admin" else "approved"
    )
    
    db.add(debt)
    db.flush()
    
    if debt_data.initial_payment_amount and debt_data.initial_payment_amount > 0:
        payment_number = generate_payment_number(db)
        
        payment = models.DebtPayment(
            debt_id=debt.id,
            payment_number=payment_number,
            amount=debt_data.initial_payment_amount,
            payment_method=debt_data.initial_payment_method or models.DebtPaymentMethod.CASH.value,
            payment_type=debt_data.initial_payment_method or models.DebtPaymentMethod.CASH.value,
            reference_number=debt_data.initial_payment_reference,
            notes=f"Initial payment for debt {debt_number}",
            recorded_by=current_user.id,
            bank_account_id=debt_data.bank_account_id,
            wallet_id=debt_data.wallet_id
        )
        
        db.add(payment)
        db.flush()
        
        if debt_data.initial_payment_method == models.DebtPaymentMethod.WALLET.value and debt_data.wallet_id:
            wallet_transaction = process_wallet_transaction(
                db=db,
                wallet_id=debt_data.wallet_id,
                amount=debt_data.initial_payment_amount,
                transaction_type="withdrawal",
                description=f"Debt payment - {debt_number}",
                reference_type="debt_payment",
                reference_id=payment.id,
                user_id=current_user.id
            )
            payment.wallet_transaction_id = wallet_transaction.id
        
        debt.paid_amount += debt_data.initial_payment_amount
        debt.remaining_amount = debt.total_amount - debt.paid_amount
        update_debt_status(debt)
    
    if current_user.role == "admin":
        debt.approved_by = current_user.id
        debt.approved_at = datetime.now()
        debt.approval_status = "approved"
    
    db.commit()
    db.refresh(debt)
    
    return debt


@router.get("/", response_model=List[schemas.DebtResponse])
async def get_debts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    branch_id: Optional[int] = None,
    status: Optional[models.DebtStatus] = None,
    supplier_name: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get all debts with filters"""
    query = db.query(models.Debt)
    
    if branch_id:
        query = query.filter(models.Debt.branch_id == branch_id)
    elif current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    if status:
        query = query.filter(models.Debt.status == status.value)
    
    if supplier_name:
        query = query.filter(models.Debt.supplier_name.ilike(f"%{supplier_name}%"))
    
    if date_from:
        query = query.filter(func.date(models.Debt.debt_date) >= date_from)
    if date_to:
        query = query.filter(func.date(models.Debt.debt_date) <= date_to)
    
    query = query.order_by(desc(models.Debt.created_at))
    debts = query.offset(skip).limit(limit).all()
    
    return debts


@router.get("/{debt_id}", response_model=schemas.DebtResponse)
async def get_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get a specific debt by ID"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if current_user.role != "admin":
        if current_user.branch_id and debt.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this debt"
            )
    
    return debt


@router.put("/{debt_id}", response_model=schemas.DebtResponse)
async def update_debt(
    debt_id: int,
    debt_update: schemas.DebtUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Update a debt record"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if current_user.role != "admin":
        if current_user.branch_id and debt.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this debt"
            )
    
    update_data = debt_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            if value == models.DebtStatus.SETTLED.value and debt.remaining_amount > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot mark debt as settled when there's still remaining amount"
                )
            setattr(debt, field, value)
        else:
            setattr(debt, field, value)
    
    db.commit()
    db.refresh(debt)
    
    return debt


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)  # FIXED: Use require_admin
):
    """Delete a debt (Admin only)"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if debt.payments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete debt with existing payments"
        )
    
    db.delete(debt)
    db.commit()


# ==================== DEBT PAYMENT OPERATIONS ====================

@router.post("/{debt_id}/pay", response_model=schemas.DebtResponse)
async def make_debt_payment(
    debt_id: int,
    payment_data: schemas.DebtSettleRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Make a payment towards a debt"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if current_user.role != "admin":
        if current_user.branch_id and debt.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this debt"
            )
    
    if debt.status == models.DebtStatus.SETTLED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debt is already settled"
        )
    
    if payment_data.amount > debt.remaining_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment amount exceeds remaining balance. Remaining: {debt.remaining_amount}"
        )
    
    payment_number = generate_payment_number(db)
    
    payment = models.DebtPayment(
        debt_id=debt.id,
        payment_number=payment_number,
        amount=payment_data.amount,
        payment_method=payment_data.payment_method.value,
        payment_type=payment_data.payment_method.value,
        reference_number=payment_data.reference_number,
        notes=payment_data.notes,
        recorded_by=current_user.id,
        bank_account_id=payment_data.bank_account_id,
        wallet_id=payment_data.wallet_id
    )
    
    db.add(payment)
    db.flush()
    
    if payment_data.payment_method == models.DebtPaymentMethod.WALLET.value:
        if not payment_data.wallet_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wallet ID required for wallet payment"
            )
        
        wallet_transaction = process_wallet_transaction(
            db=db,
            wallet_id=payment_data.wallet_id,
            amount=payment_data.amount,
            transaction_type="withdrawal",
            description=f"Debt payment - {debt.debt_number}",
            reference_type="debt_payment",
            reference_id=payment.id,
            user_id=current_user.id
        )
        payment.wallet_transaction_id = wallet_transaction.id
    
    elif payment_data.payment_method == models.DebtPaymentMethod.PRODUCT.value:
        if not payment_data.product_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product items required for product payment"
            )
        
        product_payments = process_product_payment(
            db=db,
            debt_payment=payment,
            product_items=payment_data.product_items,
            branch_id=debt.branch_id,
            user_id=current_user.id
        )
        payment.payment_type = "product"
    
    elif payment_data.payment_method == models.DebtPaymentMethod.MIXED.value:
        if not payment_data.product_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product items required for mixed payment"
            )
        
        product_payments = process_product_payment(
            db=db,
            debt_payment=payment,
            product_items=payment_data.product_items,
            branch_id=debt.branch_id,
            user_id=current_user.id
        )
        payment.payment_type = "mixed"
        
        if payment_data.wallet_id:
            wallet_transaction = process_wallet_transaction(
                db=db,
                wallet_id=payment_data.wallet_id,
                amount=payment_data.amount,
                transaction_type="withdrawal",
                description=f"Debt payment (mixed) - {debt.debt_number}",
                reference_type="debt_payment",
                reference_id=payment.id,
                user_id=current_user.id
            )
            payment.wallet_transaction_id = wallet_transaction.id
    
    debt.paid_amount += payment_data.amount
    debt.remaining_amount = debt.total_amount - debt.paid_amount
    update_debt_status(debt)
    
    db.commit()
    db.refresh(debt)
    
    return debt


# ==================== DEBT APPROVAL OPERATIONS ====================

@router.post("/{debt_id}/approve", response_model=schemas.DebtResponse)
async def approve_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)  # FIXED: Use require_admin
):
    """Approve a debt (Admin only)"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if debt.approval_status == "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debt is already approved"
        )
    
    debt.approval_status = "approved"
    debt.approved_by = current_user.id
    debt.approved_at = datetime.now()
    
    db.commit()
    db.refresh(debt)
    
    return debt


@router.post("/{debt_id}/reject", response_model=schemas.DebtResponse)
async def reject_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)  # FIXED: Use require_admin
):
    """Reject a debt (Admin only)"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if debt.approval_status == "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reject an approved debt"
        )
    
    debt.approval_status = "rejected"
    debt.approved_by = current_user.id
    debt.approved_at = datetime.now()
    debt.status = models.DebtStatus.CANCELLED.value
    
    db.commit()
    db.refresh(debt)
    
    return debt


# ==================== DEBT REPORTS AND SUMMARIES ====================

@router.get("/summary/", response_model=schemas.DebtSummaryResponse)
async def get_debt_summary(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get debt summary"""
    query = db.query(models.Debt)
    
    if branch_id:
        query = query.filter(models.Debt.branch_id == branch_id)
    elif current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    total_debts = query.count()
    total_debt_amount = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.total_amount)).scalar() or 0
    
    total_repayments = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.paid_amount)).scalar() or 0
    
    total_outstanding = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.remaining_amount)).scalar() or 0
    
    active_debts = query.filter(
        models.Debt.status == models.DebtStatus.ACTIVE.value
    ).count()
    
    overdue_debts = query.filter(
        models.Debt.status == models.DebtStatus.OVERDUE.value
    ).count()
    
    summary = schemas.DebtSummaryResponse(
        summary_date=date.today(),
        branch_id=branch_id or current_user.branch_id or 0,
        total_debts_issued=total_debts,
        total_debt_amount=Decimal(str(total_debt_amount)),
        total_repayments=Decimal(str(total_repayments)),
        total_outstanding=Decimal(str(total_outstanding)),
        active_debts_count=active_debts,
        overdue_debts_count=overdue_debts
    )
    
    return summary


@router.get("/report/", response_model=schemas.DebtReport)
async def get_debt_report(
    date_from: date = Query(..., description="Start date"),
    date_to: date = Query(..., description="End date"),
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get comprehensive debt report"""
    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from must be before date_to"
        )
    
    query = db.query(models.Debt).filter(
        func.date(models.Debt.debt_date) >= date_from,
        func.date(models.Debt.debt_date) <= date_to
    )
    
    if branch_id:
        query = query.filter(models.Debt.branch_id == branch_id)
    elif current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    debts = query.all()
    
    total_debts = len(debts)
    total_debt_value = sum(d.total_amount for d in debts)
    total_repayments = sum(d.paid_amount for d in debts)
    total_outstanding = sum(d.remaining_amount for d in debts)
    
    average_debt_size = total_debt_value / total_debts if total_debts > 0 else 0
    repayment_rate = (total_repayments / total_debt_value * 100) if total_debt_value > 0 else 0
    
    debts_by_status = {}
    for debt in debts:
        status = debt.status
        debts_by_status[status] = debts_by_status.get(status, 0) + 1
    
    daily_breakdown = []
    current_date = date_from
    while current_date <= date_to:
        day_debts = [d for d in debts if d.debt_date.date() == current_date]
        daily_breakdown.append({
            "date": current_date.isoformat(),
            "count": len(day_debts),
            "total_amount": sum(d.total_amount for d in day_debts),
            "repayments": sum(d.paid_amount for d in day_debts)
        })
        current_date += timedelta(days=1)
    
    supplier_breakdown = []
    suppliers = {}
    for debt in debts:
        if debt.supplier_name not in suppliers:
            suppliers[debt.supplier_name] = {
                "supplier": debt.supplier_name,
                "total_debts": 0,
                "total_amount": 0,
                "repayments": 0,
                "outstanding": 0
            }
        suppliers[debt.supplier_name]["total_debts"] += 1
        suppliers[debt.supplier_name]["total_amount"] += float(debt.total_amount)
        suppliers[debt.supplier_name]["repayments"] += float(debt.paid_amount)
        suppliers[debt.supplier_name]["outstanding"] += float(debt.remaining_amount)
    
    supplier_breakdown = list(suppliers.values())
    
    payment_method_breakdown = {}
    for debt in debts:
        for payment in debt.payments:
            method = payment.payment_method
            payment_method_breakdown[method] = payment_method_breakdown.get(method, 0) + float(payment.amount)
    
    report = schemas.DebtReport(
        date_range=schemas.DateRange(from_date=date_from, to_date=date_to),
        total_debts=total_debts,
        total_debt_value=Decimal(str(total_debt_value)),
        total_repayments=Decimal(str(total_repayments)),
        total_outstanding=Decimal(str(total_outstanding)),
        average_debt_size=Decimal(str(average_debt_size)),
        repayment_rate=repayment_rate,
        debts_by_status=debts_by_status,
        daily_breakdown=daily_breakdown,
        supplier_breakdown=supplier_breakdown,
        payment_method_breakdown=payment_method_breakdown
    )
    
    return report


@router.get("/by-supplier/{supplier_name}", response_model=List[schemas.DebtResponse])
async def get_debts_by_supplier(
    supplier_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get all debts for a specific supplier"""
    query = db.query(models.Debt).filter(
        models.Debt.supplier_name.ilike(f"%{supplier_name}%")
    )
    
    if current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    debts = query.order_by(desc(models.Debt.created_at)).all()
    
    return debts


@router.get("/{debt_id}/payments", response_model=List[schemas.DebtPaymentResponse])
async def get_debt_payments(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get all payments for a specific debt"""
    debt = db.query(models.Debt).filter(models.Debt.id == debt_id).first()
    
    if not debt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Debt not found"
        )
    
    if current_user.role != "admin":
        if current_user.branch_id and debt.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this debt"
            )
    
    payments = db.query(models.DebtPayment).filter(
        models.DebtPayment.debt_id == debt_id
    ).order_by(desc(models.DebtPayment.payment_date)).all()
    
    return payments


@router.get("/payment/{payment_id}", response_model=schemas.DebtPaymentResponse)
async def get_payment_details(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get details of a specific payment"""
    payment = db.query(models.DebtPayment).filter(
        models.DebtPayment.id == payment_id
    ).first()
    
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )
    
    debt = db.query(models.Debt).filter(models.Debt.id == payment.debt_id).first()
    if current_user.role != "admin":
        if current_user.branch_id and debt.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this payment"
            )
    
    return payment


@router.get("/dashboard/stats/")
async def get_debt_dashboard_stats(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get dashboard statistics for debts"""
    query = db.query(models.Debt)
    
    if branch_id:
        query = query.filter(models.Debt.branch_id == branch_id)
    elif current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    total_debt = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.total_amount)).scalar() or 0
    
    total_paid = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.paid_amount)).scalar() or 0
    
    total_outstanding = query.filter(
        models.Debt.status != models.DebtStatus.CANCELLED.value
    ).with_entities(func.sum(models.Debt.remaining_amount)).scalar() or 0
    
    status_counts = {}
    for status in models.DebtStatus:
        count = query.filter(models.Debt.status == status.value).count()
        status_counts[status.value] = count
    
    recent_debts = query.order_by(desc(models.Debt.created_at)).limit(5).all()
    
    return {
        "total_debt": float(total_debt),
        "total_paid": float(total_paid),
        "total_outstanding": float(total_outstanding),
        "status_counts": status_counts,
        "recent_debts": recent_debts,
        "total_debts_count": query.count()
    }


print("✅ Debt router endpoints registered successfully!")