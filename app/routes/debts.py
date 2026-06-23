# app/routes/debts.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, date, timedelta
from decimal import Decimal

from app.database import get_db
from app import models, schemas
from app.utils.dependencies import get_current_user, get_current_active_user, require_admin
from app.routes.wallet import process_wallet_transaction

router = APIRouter(prefix="/api/debts", tags=["Debts"])

print("=" * 60)
print("✅ DEBT ROUTER MODULE LOADED!")
print("=" * 60)


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


# ==================== DEBT CRUD OPERATIONS ====================

@router.post("/", response_model=schemas.DebtResponse, status_code=status.HTTP_201_CREATED)
async def create_debt(
    debt_data: schemas.DebtCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Create a new debt record"""
    print(f"📝 Creating debt for: {debt_data.supplier_name}")
    
    debt_number = generate_debt_number(db)
    
    debt = models.Debt(
        debt_number=debt_number,
        branch_id=debt_data.branch_id,
        supplier_name=debt_data.supplier_name,
        supplier_phone=debt_data.supplier_phone,
        supplier_email=debt_data.supplier_email,
        total_amount=debt_data.total_amount,  # Changed from amount to total_amount
        paid_amount=debt_data.initial_payment_amount if debt_data.initial_payment_amount else 0,
        remaining_amount=debt_data.total_amount - (debt_data.initial_payment_amount if debt_data.initial_payment_amount else 0),
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
    
    print(f"✅ Debt created: {debt.debt_number}")
    
    # Build response with user names
    return build_debt_response(debt, db)


@router.get("/", response_model=List[schemas.DebtResponse])
async def get_debts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    branch_id: Optional[int] = None,
    status: Optional[str] = Query(None, description="Filter by debt status"),
    supplier_name: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user)
):
    """Get all debts with filters"""
    print("📋 GET /debts called")
    
    query = db.query(models.Debt)
    
    if branch_id:
        query = query.filter(models.Debt.branch_id == branch_id)
    elif current_user.role != "admin" and current_user.branch_id:
        query = query.filter(models.Debt.branch_id == current_user.branch_id)
    
    # Handle status filter - only apply if status is not empty
    if status and status.strip():
        # Validate that status is a valid DebtStatus value
        valid_statuses = [s.value for s in models.DebtStatus]
        if status in valid_statuses:
            query = query.filter(models.Debt.status == status)
        else:
            print(f"⚠️ Invalid status value: {status}, ignoring filter")
    
    if supplier_name:
        query = query.filter(models.Debt.supplier_name.ilike(f"%{supplier_name}%"))
    
    if date_from:
        query = query.filter(func.date(models.Debt.debt_date) >= date_from)
    if date_to:
        query = query.filter(func.date(models.Debt.debt_date) <= date_to)
    
    query = query.order_by(models.Debt.created_at.desc())
    debts = query.offset(skip).limit(limit).all()
    
    print(f"✅ Found {len(debts)} debts")
    
    # Build response with user names for each debt
    result = []
    for debt in debts:
        result.append(build_debt_response(debt, db))
    
    return result


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
    
    return build_debt_response(debt, db)


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
    
    return build_debt_response(debt, db)


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
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
    print(f"💳 Recording payment for debt {debt_id}")
    
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
    
    debt.paid_amount += payment_data.amount
    debt.remaining_amount = debt.total_amount - debt.paid_amount
    update_debt_status(debt)
    
    db.commit()
    db.refresh(debt)
    
    print(f"✅ Payment recorded: {payment_number}")
    
    return build_debt_response(debt, db)


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
    ).order_by(models.DebtPayment.payment_date.desc()).all()
    
    return payments


# ==================== DEBT APPROVAL OPERATIONS ====================

@router.post("/{debt_id}/approve", response_model=schemas.DebtResponse)
async def approve_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
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
    
    return build_debt_response(debt, db)


@router.post("/{debt_id}/reject", response_model=schemas.DebtResponse)
async def reject_debt(
    debt_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
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
    
    return build_debt_response(debt, db)


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
    
    recent_debts = query.order_by(models.Debt.created_at.desc()).limit(5).all()
    
    # Build recent debts with user names
    recent_debts_response = []
    for debt in recent_debts:
        recent_debts_response.append(build_debt_response(debt, db))
    
    return {
        "total_debt": float(total_debt),
        "total_paid": float(total_paid),
        "total_outstanding": float(total_outstanding),
        "status_counts": status_counts,
        "recent_debts": recent_debts_response,
        "total_debts_count": query.count()
    }


# ==================== HELPER FUNCTION FOR BUILDING RESPONSE ====================

def build_debt_response(debt: models.Debt, db: Session) -> schemas.DebtResponse:
    """Build a DebtResponse with user names populated"""
    # Get creator name
    creator_name = None
    if debt.created_by:
        creator = db.query(models.User).filter(models.User.id == debt.created_by).first()
        creator_name = creator.name if creator else None
    
    # Get approver name
    approver_name = None
    if debt.approved_by:
        approver = db.query(models.User).filter(models.User.id == debt.approved_by).first()
        approver_name = approver.name if approver else None
    
    # Get payments
    payments = db.query(models.DebtPayment).filter(
        models.DebtPayment.debt_id == debt.id
    ).all()
    
    # Build payment responses
    payment_responses = []
    for payment in payments:
        payment_responses.append(schemas.DebtPaymentResponse(
            id=payment.id,
            payment_number=payment.payment_number,
            payment_date=payment.payment_date,
            amount=payment.amount,
            payment_method=payment.payment_method,
            reference_number=payment.reference_number,
            notes=payment.notes,
            bank_account_id=payment.bank_account_id,
            wallet_id=payment.wallet_id,
            recorded_by=str(payment.recorded_by) if payment.recorded_by else None,
            created_at=payment.created_at,
            payment_type=payment.payment_type,
            product_payment_items=None,
            stock_movement_ids=None
        ))
    
    return schemas.DebtResponse(
        id=debt.id,
        debt_number=debt.debt_number,
        branch_id=debt.branch_id,
        supplier_name=debt.supplier_name,
        supplier_phone=debt.supplier_phone,
        supplier_email=debt.supplier_email,
        debt_date=debt.debt_date,
        total_amount=debt.total_amount,
        paid_amount=debt.paid_amount,
        remaining_amount=debt.remaining_amount,
        status=debt.status,
        description=debt.description,
        notes=debt.notes,
        created_by=debt.created_by,  # Now an int
        created_by_name=creator_name,
        approved_by=debt.approved_by,  # Now Optional[int]
        approved_by_name=approver_name,
        approved_at=debt.approved_at,
        created_at=debt.created_at,
        updated_at=debt.updated_at,
        payments=payment_responses
    )


print("=" * 60)
print("✅ DEBT ROUTER ENDPOINTS REGISTERED SUCCESSFULLY!")
print("=" * 60)