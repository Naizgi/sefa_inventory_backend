from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid

from app.database import get_db
from app.models import User, Loan, LoanPayment, LoanItem, Product, Stock, StockMovement
from app.schemas import (
    LoanCreate, LoanResponse, LoanUpdate, LoanPaymentCreate,
    LoanPaymentResponse, LoanSettleRequest
)
from app.utils.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/loans", tags=["Loans"])

def generate_loan_number():
    return f"LN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

def generate_payment_number():
    return f"PMT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

# POST - Create loan (handle both with and without trailing slash)
@router.post("", response_model=LoanResponse)
@router.post("/", response_model=LoanResponse)
def create_loan(  # Removed async
    loan_data: LoanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new loan - deducts stock and records stock movement (Admin & Salesman)"""
    
    branch_id = current_user.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    # Salesman can only create loans for their branch
    if current_user.role == "salesman" and current_user.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="Not authorized to create loans for this branch")
    
    try:
        # Calculate totals and validate stock
        total_amount = Decimal('0')
        loan_items_data = []
        
        for item_data in loan_data.items:
            product = db.query(Product).filter(Product.id == item_data.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
            
            # Check stock availability
            stock = db.query(Stock).filter(
                Stock.branch_id == branch_id,
                Stock.product_id == item_data.product_id
            ).first()
            
            if not stock or stock.quantity < item_data.quantity:
                available = stock.quantity if stock else 0
                raise HTTPException(
                    status_code=400, 
                    detail=f"Insufficient stock for {product.name}. Available: {available}, Requested: {item_data.quantity}"
                )
            
            line_total = item_data.quantity * item_data.unit_price
            total_amount += line_total
            
            loan_items_data.append({
                "product": product,
                "stock": stock,
                "data": item_data,
                "line_total": line_total
            })
        
        # Calculate interest
        interest_amount = total_amount * (Decimal(str(loan_data.interest_rate)) / 100)
        total_with_interest = total_amount + interest_amount
        
        # Create loan
        loan = Loan(
            loan_number=generate_loan_number(),
            branch_id=branch_id,
            customer_name=loan_data.customer_name,
            customer_phone=loan_data.customer_phone,
            customer_email=loan_data.customer_email,
            due_date=datetime.combine(loan_data.due_date, datetime.min.time()),
            total_amount=total_with_interest,
            paid_amount=Decimal('0'),
            remaining_amount=total_with_interest,
            interest_rate=Decimal(str(loan_data.interest_rate)),
            interest_amount=interest_amount,
            notes=loan_data.notes,
            created_by=current_user.id,
            status='active'
        )
        
        db.add(loan)
        db.flush()
        
        # Add loan items and update stock
        for item_info in loan_items_data:
            loan_item = LoanItem(
                loan_id=loan.id,
                product_id=item_info["data"].product_id,
                quantity=item_info["data"].quantity,
                unit_price=item_info["data"].unit_price,
                line_total=item_info["line_total"]
            )
            db.add(loan_item)
            
            # Deduct stock
            stock = item_info["stock"]
            stock.quantity -= item_info["data"].quantity
            
            # Record stock movement
            stock_movement = StockMovement(
                branch_id=branch_id,
                product_id=item_info["data"].product_id,
                user_id=current_user.id,
                change_qty=-item_info["data"].quantity,
                movement_type="loan",
                reference_id=loan.id,
                notes=f"Loan #{loan.loan_number} - {loan_data.customer_name} - Deducted {item_info['data'].quantity} units"
            )
            db.add(stock_movement)
        
        db.commit()
        db.refresh(loan)
        
        creator = db.query(User).filter(User.id == loan.created_by).first()
        creator_name = creator.name if creator else "System"
        
        items_response = []
        for item in loan.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            items_response.append({
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "product_name": product.name if product else None
            })
        
        return {
            "id": loan.id,
            "loan_number": loan.loan_number,
            "branch_id": loan.branch_id,
            "customer_name": loan.customer_name,
            "customer_phone": loan.customer_phone,
            "customer_email": loan.customer_email,
            "loan_date": loan.loan_date.date(),
            "due_date": loan.due_date.date(),
            "total_amount": float(loan.total_amount),
            "paid_amount": float(loan.paid_amount),
            "remaining_amount": float(loan.remaining_amount),
            "interest_rate": float(loan.interest_rate),
            "interest_amount": float(loan.interest_amount),
            "status": loan.status,
            "notes": loan.notes,
            "items": items_response,
            "payments": [],
            "created_by": creator_name,
            "approved_by": None,
            "approved_at": None,
            "created_at": loan.created_at,
            "updated_at": loan.updated_at
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error creating loan: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# GET - Get all loans (handle both with and without trailing slash)
@router.get("", response_model=List[LoanResponse])
@router.get("/", response_model=List[LoanResponse])
def get_loans(  # Removed async
    customer_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all loans with filters (Admin sees all, Salesman sees only their branch)"""
    
    query = db.query(Loan)
    
    if current_user.role == "salesman":
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        query = query.filter(Loan.branch_id == current_user.branch_id)
    
    if customer_name:
        query = query.filter(Loan.customer_name.ilike(f"%{customer_name}%"))
    if status:
        query = query.filter(Loan.status == status)
    
    loans = query.order_by(Loan.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for loan in loans:
        creator = db.query(User).filter(User.id == loan.created_by).first()
        creator_name = creator.name if creator else "System"
        
        items_response = []
        for item in loan.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            items_response.append({
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
                "product_name": product.name if product else None
            })
        
        # Get payment history for each loan
        payments_response = []
        for payment in loan.payments:
            recorder = db.query(User).filter(User.id == payment.recorded_by).first()
            payments_response.append({
                "id": payment.id,
                "payment_number": payment.payment_number,
                "payment_date": payment.payment_date,
                "amount": float(payment.amount),
                "payment_method": payment.payment_method,
                "reference_number": payment.reference_number,
                "notes": payment.notes,
                "recorded_by": recorder.name if recorder else "System",
                "sale_id": payment.sale_id,
                "created_at": payment.created_at
            })
        
        result.append({
            "id": loan.id,
            "loan_number": loan.loan_number,
            "branch_id": loan.branch_id,
            "customer_name": loan.customer_name,
            "customer_phone": loan.customer_phone,
            "customer_email": loan.customer_email,
            "loan_date": loan.loan_date.date(),
            "due_date": loan.due_date.date(),
            "total_amount": float(loan.total_amount),
            "paid_amount": float(loan.paid_amount),
            "remaining_amount": float(loan.remaining_amount),
            "interest_rate": float(loan.interest_rate),
            "interest_amount": float(loan.interest_amount),
            "status": loan.status,
            "notes": loan.notes,
            "items": items_response,
            "payments": payments_response,
            "created_by": creator_name,
            "approved_by": None,
            "approved_at": None,
            "created_at": loan.created_at,
            "updated_at": loan.updated_at
        })
    
    return result

# GET by ID - no change needed
@router.get("/{loan_id}", response_model=LoanResponse)
def get_loan(  # Removed async
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get loan by ID (Admin sees all, Salesman sees only their branch)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    # Check permission for salesman
    if current_user.role == "salesman":
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        if loan.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this loan")
    
    creator = db.query(User).filter(User.id == loan.created_by).first()
    creator_name = creator.name if creator else "System"
    
    items_response = []
    for item in loan.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items_response.append({
            "id": item.id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "product_name": product.name if product else None
        })
    
    # Get payment history
    payments_response = []
    for payment in loan.payments:
        recorder = db.query(User).filter(User.id == payment.recorded_by).first()
        payments_response.append({
            "id": payment.id,
            "payment_number": payment.payment_number,
            "payment_date": payment.payment_date,
            "amount": float(payment.amount),
            "payment_method": payment.payment_method,
            "reference_number": payment.reference_number,
            "notes": payment.notes,
            "recorded_by": recorder.name if recorder else "System",
            "sale_id": payment.sale_id,
            "created_at": payment.created_at
        })
    
    return {
        "id": loan.id,
        "loan_number": loan.loan_number,
        "branch_id": loan.branch_id,
        "customer_name": loan.customer_name,
        "customer_phone": loan.customer_phone,
        "customer_email": loan.customer_email,
        "loan_date": loan.loan_date.date(),
        "due_date": loan.due_date.date(),
        "total_amount": float(loan.total_amount),
        "paid_amount": float(loan.paid_amount),
        "remaining_amount": float(loan.remaining_amount),
        "interest_rate": float(loan.interest_rate),
        "interest_amount": float(loan.interest_amount),
        "status": loan.status,
        "notes": loan.notes,
        "items": items_response,
        "payments": payments_response,
        "created_by": creator_name,
        "approved_by": None,
        "approved_at": None,
        "created_at": loan.created_at,
        "updated_at": loan.updated_at
    }

# PUT - Update loan (handle both with and without trailing slash for collection? No, this is by ID)
@router.put("/{loan_id}", response_model=LoanResponse)
def update_loan(
    loan_id: int,
    loan_update: LoanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)  # Only admin can update loans
):
    """Update loan details (Admin only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if loan_update.due_date:
        loan.due_date = datetime.combine(loan_update.due_date, datetime.min.time())
    if loan_update.interest_rate is not None:
        loan.interest_rate = Decimal(str(loan_update.interest_rate))
        # Recalculate interest amount
        loan.interest_amount = (loan.total_amount - loan.interest_amount) * (loan.interest_rate / 100)
        loan.total_amount = (loan.total_amount - loan.interest_amount) + loan.interest_amount
        loan.remaining_amount = loan.total_amount - loan.paid_amount
    if loan_update.status:
        loan.status = loan_update.status
    if loan_update.notes:
        loan.notes = loan_update.notes
    
    loan.updated_at = datetime.now()
    
    db.commit()
    db.refresh(loan)
    
    creator = db.query(User).filter(User.id == loan.created_by).first()
    creator_name = creator.name if creator else "System"
    
    items_response = []
    for item in loan.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items_response.append({
            "id": item.id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "product_name": product.name if product else None
        })
    
    payments_response = []
    for payment in loan.payments:
        recorder = db.query(User).filter(User.id == payment.recorded_by).first()
        payments_response.append({
            "id": payment.id,
            "payment_number": payment.payment_number,
            "payment_date": payment.payment_date,
            "amount": float(payment.amount),
            "payment_method": payment.payment_method,
            "reference_number": payment.reference_number,
            "notes": payment.notes,
            "recorded_by": recorder.name if recorder else "System",
            "sale_id": payment.sale_id,
            "created_at": payment.created_at
        })
    
    return {
        "id": loan.id,
        "loan_number": loan.loan_number,
        "branch_id": loan.branch_id,
        "customer_name": loan.customer_name,
        "customer_phone": loan.customer_phone,
        "customer_email": loan.customer_email,
        "loan_date": loan.loan_date.date(),
        "due_date": loan.due_date.date(),
        "total_amount": float(loan.total_amount),
        "paid_amount": float(loan.paid_amount),
        "remaining_amount": float(loan.remaining_amount),
        "interest_rate": float(loan.interest_rate),
        "interest_amount": float(loan.interest_amount),
        "status": loan.status,
        "notes": loan.notes,
        "items": items_response,
        "payments": payments_response,
        "created_by": creator_name,
        "approved_by": None,
        "approved_at": None,
        "created_at": loan.created_at,
        "updated_at": loan.updated_at
    }

# DELETE - Delete loan (Admin only)
@router.delete("/{loan_id}", status_code=204)
def delete_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a loan (Admin only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    # Only allow deletion of loans with no payments or settled status
    if loan.paid_amount > 0 and loan.status != 'settled':
        raise HTTPException(status_code=400, detail="Cannot delete loan with existing payments")
    
    # Restore stock for items
    for item in loan.items:
        stock = db.query(Stock).filter(
            Stock.branch_id == loan.branch_id,
            Stock.product_id == item.product_id
        ).first()
        if stock:
            stock.quantity += item.quantity
        
        # Record stock movement for restoration
        stock_movement = StockMovement(
            branch_id=loan.branch_id,
            product_id=item.product_id,
            user_id=current_user.id,
            change_qty=item.quantity,
            movement_type="loan_restore",
            reference_id=loan.id,
            notes=f"Loan #{loan.loan_number} deleted - Stock restored"
        )
        db.add(stock_movement)
    
    db.delete(loan)
    db.commit()
    
    return None

# POST - Add payment (no change needed)
@router.post("/{loan_id}/payments", response_model=LoanPaymentResponse)
def add_loan_payment(  # Removed async
    loan_id: int,
    payment_data: LoanPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a payment to a loan (Both Admin and Salesman can record payments for their branch)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    # Check permission for salesman - can only record payments for their branch
    if current_user.role == "salesman":
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        if loan.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to record payment for this loan")
    
    if loan.status == 'settled':
        raise HTTPException(status_code=400, detail="Loan already settled")
    
    if payment_data.amount > loan.remaining_amount:
        raise HTTPException(status_code=400, detail="Payment amount exceeds remaining balance")
    
    # Create payment record
    payment = LoanPayment(
        loan_id=loan_id,
        payment_number=generate_payment_number(),
        amount=payment_data.amount,
        payment_method=payment_data.payment_method.value if hasattr(payment_data.payment_method, 'value') else payment_data.payment_method,
        reference_number=payment_data.reference_number,
        notes=payment_data.notes,
        recorded_by=current_user.id,
        sale_id=payment_data.sale_id
    )
    
    db.add(payment)
    
    # Update loan
    loan.paid_amount += payment_data.amount
    loan.remaining_amount -= payment_data.amount
    
    if loan.remaining_amount == 0:
        loan.status = 'settled'
    else:
        loan.status = 'partially_paid'
    
    loan.updated_at = datetime.now()
    
    db.commit()
    db.refresh(payment)
    
    recorder = db.query(User).filter(User.id == payment.recorded_by).first()
    recorder_name = recorder.name if recorder else "System"
    
    return {
        "id": payment.id,
        "payment_number": payment.payment_number,
        "payment_date": payment.payment_date,
        "amount": float(payment.amount),
        "payment_method": payment.payment_method,
        "reference_number": payment.reference_number,
        "notes": payment.notes,
        "recorded_by": recorder_name,
        "sale_id": payment.sale_id,
        "created_at": payment.created_at
    }

# POST - Settle loan (no change needed)
@router.post("/{loan_id}/settle")
def settle_loan(  # Removed async
    loan_id: int,
    settle_data: LoanSettleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Settle a loan completely (Both Admin and Salesman can settle loans for their branch)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    # Check permission for salesman - can only settle loans for their branch
    if current_user.role == "salesman":
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        if loan.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to settle this loan")
    
    if loan.status == 'settled':
        raise HTTPException(status_code=400, detail="Loan already settled")
    
    if settle_data.amount < loan.remaining_amount:
        raise HTTPException(status_code=400, detail=f"Amount must be at least {loan.remaining_amount} to settle")
    
    # Create payment for remaining amount
    payment = LoanPayment(
        loan_id=loan_id,
        payment_number=generate_payment_number(),
        amount=loan.remaining_amount,
        payment_method=settle_data.payment_method.value if hasattr(settle_data.payment_method, 'value') else settle_data.payment_method,
        reference_number=settle_data.reference_number,
        notes=settle_data.notes,
        recorded_by=current_user.id
    )
    
    db.add(payment)
    
    # Update loan
    loan.paid_amount = loan.total_amount
    loan.remaining_amount = 0
    loan.status = 'settled'
    loan.updated_at = datetime.now()
    
    db.commit()
    
    return {"message": "Loan settled successfully", "payment_id": payment.id}