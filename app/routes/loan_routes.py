from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid

from app.database import get_db
from app.models import User, Loan, LoanPayment, LoanItem, Product, Stock, StockMovement, Wallet, WalletTransaction, BankAccount
from app.schemas import (
    LoanCreate, LoanResponse, LoanUpdate, LoanPaymentCreate,
    LoanPaymentResponse, LoanSettleRequest
)
from app.utils.dependencies import get_current_user, require_admin
from app.utils.permissions import require_loan_creation_privilege, require_loan_approval_privilege, require_privileged

# Import wallet functions from the wallet router
from app.routes.wallet import get_or_create_wallet, process_wallet_transaction
from app.models import WalletTransactionType

router = APIRouter(prefix="/api/loans", tags=["Loans"])

def generate_loan_number():
    return f"LN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

def generate_payment_number():
    return f"PMT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

# POST - Create loan
@router.post("", response_model=LoanResponse)
@router.post("/", response_model=LoanResponse)
def create_loan(
    loan_data: LoanCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_loan_creation_privilege)
):
    """Create a new loan - deducts stock and records stock movement"""
    
    branch_id = current_user.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
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
        
        # Determine if loan requires approval
        requires_approval = not current_user.is_admin()
        approval_status = "pending" if requires_approval else "approved"
        
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
            status='active',
            requires_approval=requires_approval,
            approval_status=approval_status
        )
        
        # If admin created, auto-approve
        if current_user.is_admin():
            loan.approved_by = current_user.id
            loan.approved_at = datetime.now()
        
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
        
        approver_name = None
        if loan.approved_by:
            approver = db.query(User).filter(User.id == loan.approved_by).first()
            approver_name = approver.name if approver else "System"
        
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
            "approved_by": approver_name,
            "approved_at": loan.approved_at,
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


# POST - Approve loan (Admin only)
@router.post("/{loan_id}/approve")
def approve_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_loan_approval_privilege)
):
    """Approve a loan (Admin only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if loan.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Loan already approved")
    
    loan.approval_status = "approved"
    loan.approved_by = current_user.id
    loan.approved_at = datetime.now()
    
    db.commit()
    
    approver = db.query(User).filter(User.id == loan.approved_by).first()
    approver_name = approver.name if approver else "System"
    
    return {
        "message": "Loan approved successfully",
        "loan_id": loan.id,
        "loan_number": loan.loan_number,
        "approved_by": approver_name,
        "approved_at": loan.approved_at
    }


# GET - Get all loans
@router.get("", response_model=List[LoanResponse])
@router.get("/", response_model=List[LoanResponse])
def get_loans(
    customer_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all loans with filters"""
    
    query = db.query(Loan)
    
    if not current_user.is_privileged():
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
        
        approver_name = None
        if loan.approved_by:
            approver = db.query(User).filter(User.id == loan.approved_by).first()
            approver_name = approver.name if approver else "System"
        
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
                "created_at": payment.created_at,
                "bank_account_id": payment.bank_account_id
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
            "approved_by": approver_name,
            "approved_at": loan.approved_at,
            "created_at": loan.created_at,
            "updated_at": loan.updated_at
        })
    
    return result


# GET by ID
@router.get("/{loan_id}", response_model=LoanResponse)
def get_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get loan by ID"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if not current_user.is_privileged():
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        if loan.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this loan")
    
    creator = db.query(User).filter(User.id == loan.created_by).first()
    creator_name = creator.name if creator else "System"
    
    approver_name = None
    if loan.approved_by:
        approver = db.query(User).filter(User.id == loan.approved_by).first()
        approver_name = approver.name if approver else "System"
    
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
            "created_at": payment.created_at,
            "bank_account_id": payment.bank_account_id
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
        "approved_by": approver_name,
        "approved_at": loan.approved_at,
        "created_at": loan.created_at,
        "updated_at": loan.updated_at
    }


# PUT - Update loan (Admin only)
@router.put("/{loan_id}", response_model=LoanResponse)
def update_loan(
    loan_id: int,
    loan_update: LoanUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update loan details (Admin only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if loan_update.due_date:
        loan.due_date = datetime.combine(loan_update.due_date, datetime.min.time())
    if loan_update.interest_rate is not None:
        loan.interest_rate = Decimal(str(loan_update.interest_rate))
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
    
    approver_name = None
    if loan.approved_by:
        approver = db.query(User).filter(User.id == loan.approved_by).first()
        approver_name = approver.name if approver else "System"
    
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
            "created_at": payment.created_at,
            "bank_account_id": payment.bank_account_id
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
        "approved_by": approver_name,
        "approved_at": loan.approved_at,
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
    
    if loan.paid_amount > 0 and loan.status != 'settled':
        raise HTTPException(status_code=400, detail="Cannot delete loan with existing payments")
    
    for item in loan.items:
        stock = db.query(Stock).filter(
            Stock.branch_id == loan.branch_id,
            Stock.product_id == item.product_id
        ).first()
        if stock:
            stock.quantity += item.quantity
        
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


# POST - Add payment (Privileged users only)
@router.post("/{loan_id}/payments", response_model=LoanPaymentResponse)
def add_loan_payment(
    loan_id: int,
    payment_data: LoanPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Add a payment to a loan (Admin & Privileged Sales only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if loan.status == 'settled':
        raise HTTPException(status_code=400, detail="Loan already settled")
    
    if payment_data.amount > loan.remaining_amount:
        raise HTTPException(status_code=400, detail="Payment amount exceeds remaining balance")
    
    # Handle wallet payment - deposit to wallet first
    if payment_data.payment_method == 'wallet':
        # Check if bank_account_id is provided
        if not hasattr(payment_data, 'bank_account_id') or not payment_data.bank_account_id:
            raise HTTPException(status_code=400, detail="Bank account ID required for wallet payment")
        
        # Verify bank account exists and is active
        bank_account = db.query(BankAccount).filter(
            BankAccount.id == payment_data.bank_account_id,
            BankAccount.branch_id == loan.branch_id,
            BankAccount.is_active == True
        ).first()
        
        if not bank_account:
            raise HTTPException(status_code=404, detail="Bank account not found or inactive")
        
        # Get or create wallet for the branch - using the wallet router function
        wallet = get_or_create_wallet(db, loan.branch_id, "regular")
        
        # Process the deposit using the wallet router function
        transaction = process_wallet_transaction(
            db=db,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.DEPOSIT.value,
            amount=payment_data.amount,
            description=f"Loan payment from {loan.customer_name} - {loan.loan_number}",
            user_id=current_user.id,
            transaction_method="cash",
            reference_type="loan_payment",
            reference_id=loan.id,
            bank_reference=str(payment_data.bank_account_id) if payment_data.bank_account_id else None
        )
        print(f"✅ Wallet deposited: {transaction.transaction_number} - Amount: {payment_data.amount} to wallet '{wallet.wallet_name}'")
    
    # Create payment record
    payment = LoanPayment(
        loan_id=loan_id,
        payment_number=generate_payment_number(),
        amount=payment_data.amount,
        payment_method=payment_data.payment_method.value if hasattr(payment_data.payment_method, 'value') else payment_data.payment_method,
        reference_number=payment_data.reference_number,
        notes=payment_data.notes,
        recorded_by=current_user.id,
        sale_id=getattr(payment_data, 'sale_id', None),
        bank_account_id=getattr(payment_data, 'bank_account_id', None) if payment_data.payment_method == 'wallet' else None
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
        "created_at": payment.created_at,
        "bank_account_id": payment.bank_account_id
    }


# POST - Settle loan (Privileged users only)
@router.post("/{loan_id}/settle")
def settle_loan(
    loan_id: int,
    settle_data: LoanSettleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Settle a loan completely (Admin & Privileged Sales only)"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if loan.status == 'settled':
        raise HTTPException(status_code=400, detail="Loan already settled")
    
    if settle_data.amount < loan.remaining_amount:
        raise HTTPException(status_code=400, detail=f"Amount must be at least {loan.remaining_amount} to settle")
    
    # Handle wallet payment - deposit to wallet first
    if settle_data.payment_method == 'wallet':
        # Check if bank_account_id is provided
        if not hasattr(settle_data, 'bank_account_id') or not settle_data.bank_account_id:
            raise HTTPException(status_code=400, detail="Bank account ID required for wallet payment")
        
        # Verify bank account exists and is active
        bank_account = db.query(BankAccount).filter(
            BankAccount.id == settle_data.bank_account_id,
            BankAccount.branch_id == loan.branch_id,
            BankAccount.is_active == True
        ).first()
        
        if not bank_account:
            raise HTTPException(status_code=404, detail="Bank account not found or inactive")
        
        # Get or create wallet for the branch - using the wallet router function
        wallet = get_or_create_wallet(db, loan.branch_id, "regular")
        
        # Process the deposit using the wallet router function
        transaction = process_wallet_transaction(
            db=db,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.DEPOSIT.value,
            amount=loan.remaining_amount,
            description=f"Loan settlement from {loan.customer_name} - {loan.loan_number}",
            user_id=current_user.id,
            transaction_method="cash",
            reference_type="loan",
            reference_id=loan.id,
            bank_reference=str(settle_data.bank_account_id) if settle_data.bank_account_id else None
        )
        print(f"✅ Wallet deposited for settlement: {transaction.transaction_number} - Amount: {loan.remaining_amount} to wallet '{wallet.wallet_name}'")
    
    # Create payment for remaining amount
    payment = LoanPayment(
        loan_id=loan_id,
        payment_number=generate_payment_number(),
        amount=loan.remaining_amount,
        payment_method=settle_data.payment_method.value if hasattr(settle_data.payment_method, 'value') else settle_data.payment_method,
        reference_number=settle_data.reference_number,
        notes=settle_data.notes,
        recorded_by=current_user.id,
        bank_account_id=getattr(settle_data, 'bank_account_id', None) if settle_data.payment_method == 'wallet' else None
    )
    
    db.add(payment)
    
    # Update loan
    loan.paid_amount = loan.total_amount
    loan.remaining_amount = 0
    loan.status = 'settled'
    loan.updated_at = datetime.now()
    
    db.commit()
    
    # Get bank account details for response
    bank_account_details = None
    if payment.bank_account_id:
        bank_account = db.query(BankAccount).filter(BankAccount.id == payment.bank_account_id).first()
        if bank_account:
            bank_account_details = {
                "id": bank_account.id,
                "bank_name": bank_account.bank_name,
                "account_number": bank_account.account_number,
                "account_name": bank_account.account_name
            }
    
    return {
        "message": "Loan settled successfully", 
        "payment_id": payment.id,
        "payment_number": payment.payment_number,
        "amount": float(payment.amount),
        "payment_method": payment.payment_method,
        "reference_number": payment.reference_number,
        "bank_account_id": payment.bank_account_id,
        "bank_account_details": bank_account_details
    }


# GET - Get loan payment history
@router.get("/{loan_id}/payments", response_model=List[LoanPaymentResponse])
def get_loan_payments(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all payments for a specific loan"""
    
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")
    
    if not current_user.is_privileged():
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        if loan.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this loan")
    
    payments = db.query(LoanPayment).filter(LoanPayment.loan_id == loan_id).order_by(LoanPayment.payment_date.desc()).all()
    
    result = []
    for payment in payments:
        recorder = db.query(User).filter(User.id == payment.recorded_by).first()
        result.append({
            "id": payment.id,
            "payment_number": payment.payment_number,
            "payment_date": payment.payment_date,
            "amount": float(payment.amount),
            "payment_method": payment.payment_method,
            "reference_number": payment.reference_number,
            "notes": payment.notes,
            "recorded_by": recorder.name if recorder else "System",
            "sale_id": payment.sale_id,
            "created_at": payment.created_at,
            "bank_account_id": payment.bank_account_id
        })
    
    return result


# GET - Loan summary
@router.get("/summary")
def get_loan_summary(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get loan summary statistics"""
    
    query = db.query(Loan)
    
    if not current_user.is_privileged():
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        query = query.filter(Loan.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(Loan.branch_id == branch_id)
    
    loans = query.all()
    
    total_loans = len(loans)
    total_amount = sum(float(l.total_amount) for l in loans)
    total_paid = sum(float(l.paid_amount) for l in loans)
    total_remaining = sum(float(l.remaining_amount) for l in loans)
    
    active_loans = sum(1 for l in loans if l.status in ['active', 'partially_paid'])
    settled_loans = sum(1 for l in loans if l.status == 'settled')
    overdue_loans = sum(1 for l in loans if l.due_date < datetime.now() and l.status != 'settled')
    
    # Payment method breakdown
    payment_methods = {}
    for loan in loans:
        for payment in loan.payments:
            method = payment.payment_method
            if method not in payment_methods:
                payment_methods[method] = 0
            payment_methods[method] += float(payment.amount)
    
    return {
        "summary": {
            "total_loans": total_loans,
            "total_amount": total_amount,
            "total_paid": total_paid,
            "total_remaining": total_remaining,
            "active_loans": active_loans,
            "settled_loans": settled_loans,
            "overdue_loans": overdue_loans
        },
        "payment_methods": payment_methods
    }