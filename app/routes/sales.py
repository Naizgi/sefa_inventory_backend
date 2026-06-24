# app/routes/sales.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
import traceback
import random
import string

from app.database import get_db
from app.config import settings
from app.models import (
    User, Sale, SaleItem, Product, Stock, StockMovement, Branch, 
    BankAccount, Refund, RefundItem, SystemSetting, Wallet
)
from app.schemas import (
    SaleResponse, SaleCreate, SaleItemResponse, 
    RefundCreate, RefundResponse, RefundApprove,
    BankAccountResponse,
    BankAccountCreate,
    BankAccountUpdate
)
from app.utils.dependencies import get_current_user, require_admin
from app.services import EmailService, AuthService

# Import wallet functions
from app.routes.wallet import get_or_create_wallet, process_wallet_transaction
from app.models import WalletTransactionType

router = APIRouter(prefix="/api/sales", tags=["Sales"])

# ==================== PUBLIC BANK ACCOUNTS FOR POS ====================
# This endpoint is completely public - no authentication required

@router.get("/public-bank-accounts")
def get_public_bank_accounts(
    db: Session = Depends(get_db),
):
    """
    Get bank accounts for POS system.
    COMPLETELY PUBLIC - No authentication required.
    This is used by the POS frontend for bank transfer payments.
    """
    try:
        print("=" * 60)
        print("🚀 PUBLIC BANK ACCOUNTS ENDPOINT (in sales.py) CALLED")
        print("=" * 60)
        
        # Get all active bank accounts
        accounts = db.query(BankAccount).filter(BankAccount.is_active == True).all()
        
        result = []
        for acc in accounts:
            result.append({
                "id": acc.id,
                "bank_name": acc.bank_name,
                "branch_name": acc.branch_name or "",
                "account_number": acc.account_number,
                "account_name": acc.account_name,
                "account_type": acc.account_type,
                "currency": acc.currency,
                "is_active": acc.is_active,
                "is_primary": acc.is_primary,
                "account_category": getattr(acc, 'account_category', 'regular')
            })
        
        print(f"✅ Found {len(result)} bank accounts")
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return []  # Return empty array on error


def generate_invoice_number(db: Session) -> str:
    """Generate a unique invoice number"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"INV-{today}-"
    
    last_sale = db.query(Sale).filter(
        Sale.invoice_number.like(f"{prefix}%")
    ).order_by(Sale.id.desc()).first()
    
    if last_sale and last_sale.invoice_number:
        try:
            last_number = int(last_sale.invoice_number.split("-")[-1])
            new_number = last_number + 1
        except (ValueError, IndexError):
            new_number = 1
    else:
        new_number = 1
    
    return f"{prefix}{new_number:04d}"

def generate_refund_number(db: Session) -> str:
    """Generate a unique refund number"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"REF-{today}-"
    
    last_refund = db.query(Refund).filter(
        Refund.refund_number.like(f"{prefix}%")
    ).order_by(Refund.id.desc()).first()
    
    if last_refund and last_refund.refund_number:
        try:
            last_number = int(last_refund.refund_number.split("-")[-1])
            new_number = last_number + 1
        except (ValueError, IndexError):
            new_number = 1
    else:
        new_number = 1
    
    return f"{prefix}{new_number:04d}"

def get_default_tax_rate(db: Session) -> float:
    """Get default tax rate from settings"""
    setting = db.query(SystemSetting).filter(
        SystemSetting.category == "general",
        SystemSetting.key == "default_tax_rate"
    ).first()
    return float(setting.value) if setting else 15.0

def get_wallet_from_bank_account(db: Session, bank_account_id: int, branch_id: int) -> Optional[Wallet]:
    """Get the wallet associated with a bank account"""
    bank_account = db.query(BankAccount).filter(
        BankAccount.id == bank_account_id,
        BankAccount.branch_id == branch_id,
        BankAccount.is_active == True
    ).first()
    
    if not bank_account:
        return None
    
    # Find wallet linked to this bank account
    wallet = db.query(Wallet).filter(
        Wallet.bank_account_id == bank_account_id,
        Wallet.branch_id == branch_id,
        Wallet.is_active == True
    ).first()
    
    return wallet

# ==================== BANK ACCOUNT CRUD OPERATIONS ====================

@router.post("/bank-accounts", response_model=BankAccountResponse, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    account_data: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new bank account (Admin only)"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == account_data.branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        existing_account = db.query(BankAccount).filter(
            BankAccount.branch_id == account_data.branch_id,
            BankAccount.account_number == account_data.account_number
        ).first()
        
        if existing_account:
            raise HTTPException(
                status_code=400,
                detail=f"Account number {account_data.account_number} already exists for this branch"
            )
        
        new_account = BankAccount(
            branch_id=account_data.branch_id,
            bank_name=account_data.bank_name,
            branch_name=account_data.branch_name,
            account_number=account_data.account_number,
            account_name=account_data.account_name,
            account_type=account_data.account_type,
            iban=account_data.iban,
            swift_code=account_data.swift_code,
            currency=account_data.currency,
            is_active=account_data.is_active,
            is_primary=account_data.is_primary,
            notes=account_data.notes,
            created_by=current_user.id
        )
        
        db.add(new_account)
        db.commit()
        db.refresh(new_account)
        
        return BankAccountResponse(
            id=new_account.id,
            branch_id=new_account.branch_id,
            bank_name=new_account.bank_name,
            branch_name=new_account.branch_name,
            account_number=new_account.account_number,
            account_name=new_account.account_name,
            account_type=new_account.account_type,
            iban=new_account.iban,
            swift_code=new_account.swift_code,
            currency=new_account.currency,
            current_balance=float(new_account.current_balance),
            is_active=new_account.is_active,
            is_primary=new_account.is_primary,
            last_reconciled_at=new_account.last_reconciled_at,
            last_reconciled_balance=float(new_account.last_reconciled_balance) if new_account.last_reconciled_balance else None,
            notes=new_account.notes,
            created_by=new_account.created_by,
            created_at=new_account.created_at,
            updated_at=new_account.updated_at
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error creating bank account: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to create bank account: {str(e)}")

@router.get("/bank-accounts", response_model=List[BankAccountResponse])
def get_bank_accounts(
    branch_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all bank accounts"""
    
    query = db.query(BankAccount)
    
    if current_user.role == "salesman":
        if not current_user.branch_id:
            return []
        query = query.filter(BankAccount.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(BankAccount.branch_id == branch_id)
    
    if is_active is not None:
        query = query.filter(BankAccount.is_active == is_active)
    
    accounts = query.order_by(BankAccount.bank_name, BankAccount.account_number).all()
    
    result = []
    for account in accounts:
        result.append(BankAccountResponse(
            id=account.id,
            branch_id=account.branch_id,
            bank_name=account.bank_name,
            branch_name=account.branch_name,
            account_number=account.account_number,
            account_name=account.account_name,
            account_type=account.account_type,
            iban=account.iban,
            swift_code=account.swift_code,
            currency=account.currency,
            current_balance=float(account.current_balance),
            is_active=account.is_active,
            is_primary=account.is_primary,
            last_reconciled_at=account.last_reconciled_at,
            last_reconciled_balance=float(account.last_reconciled_balance) if account.last_reconciled_balance else None,
            notes=account.notes,
            created_by=account.created_by,
            created_at=account.created_at,
            updated_at=account.updated_at
        ))
    
    return result

@router.get("/bank-accounts/{account_id}", response_model=BankAccountResponse)
def get_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single bank account by ID"""
    
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    
    if current_user.role == "salesman" and account.branch_id != current_user.branch_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this bank account"
        )
    
    return BankAccountResponse(
        id=account.id,
        branch_id=account.branch_id,
        bank_name=account.bank_name,
        branch_name=account.branch_name,
        account_number=account.account_number,
        account_name=account.account_name,
        account_type=account.account_type,
        iban=account.iban,
        swift_code=account.swift_code,
        currency=account.currency,
        current_balance=float(account.current_balance),
        is_active=account.is_active,
        is_primary=account.is_primary,
        last_reconciled_at=account.last_reconciled_at,
        last_reconciled_balance=float(account.last_reconciled_balance) if account.last_reconciled_balance else None,
        notes=account.notes,
        created_by=account.created_by,
        created_at=account.created_at,
        updated_at=account.updated_at
    )

@router.put("/bank-accounts/{account_id}", response_model=BankAccountResponse)
def update_bank_account(
    account_id: int,
    account_update: BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a bank account (Admin only)"""
    
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    
    try:
        update_data = account_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(account, field, value)
        
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        
        return BankAccountResponse(
            id=account.id,
            branch_id=account.branch_id,
            bank_name=account.bank_name,
            branch_name=account.branch_name,
            account_number=account.account_number,
            account_name=account.account_name,
            account_type=account.account_type,
            iban=account.iban,
            swift_code=account.swift_code,
            currency=account.currency,
            current_balance=float(account.current_balance),
            is_active=account.is_active,
            is_primary=account.is_primary,
            last_reconciled_at=account.last_reconciled_at,
            last_reconciled_balance=float(account.last_reconciled_balance) if account.last_reconciled_balance else None,
            notes=account.notes,
            created_by=account.created_by,
            created_at=account.created_at,
            updated_at=account.updated_at
        )
        
    except Exception as e:
        db.rollback()
        print(f"Error updating bank account: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update bank account: {str(e)}")

@router.delete("/bank-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete (deactivate) a bank account (Admin only)"""
    
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    
    try:
        account.is_active = False
        account.updated_at = datetime.now()
        db.commit()
        return None
        
    except Exception as e:
        db.rollback()
        print(f"Error deleting bank account: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete bank account: {str(e)}")

@router.patch("/bank-accounts/{account_id}/activate", response_model=BankAccountResponse)
def activate_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Activate a bank account (Admin only)"""
    
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")
    
    try:
        account.is_active = True
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        
        return BankAccountResponse(
            id=account.id,
            branch_id=account.branch_id,
            bank_name=account.bank_name,
            branch_name=account.branch_name,
            account_number=account.account_number,
            account_name=account.account_name,
            account_type=account.account_type,
            iban=account.iban,
            swift_code=account.swift_code,
            currency=account.currency,
            current_balance=float(account.current_balance),
            is_active=account.is_active,
            is_primary=account.is_primary,
            last_reconciled_at=account.last_reconciled_at,
            last_reconciled_balance=float(account.last_reconciled_balance) if account.last_reconciled_balance else None,
            notes=account.notes,
            created_by=account.created_by,
            created_at=account.created_at,
            updated_at=account.updated_at
        )
        
    except Exception as e:
        db.rollback()
        print(f"Error activating bank account: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to activate bank account: {str(e)}")

# ==================== REFUND OPERATIONS ====================

@router.post("/refunds", response_model=RefundResponse, status_code=status.HTTP_201_CREATED)
def create_refund(
    refund_data: RefundCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new refund for a sale"""
    
    print(f"=== CREATE REFUND ===")
    print(f"User: {current_user.id} - {current_user.name}")
    print(f"Refund data: {refund_data}")
    
    try:
        original_sale = db.query(Sale).filter(Sale.id == refund_data.original_sale_id).first()
        if not original_sale:
            raise HTTPException(status_code=404, detail="Original sale not found")
        
        if original_sale.status == "refunded":
            raise HTTPException(status_code=400, detail="This sale has already been fully refunded")
        
        if current_user.role == "salesman" and original_sale.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to refund sales from other branches"
            )
        
        if refund_data.refund_method == "transfer":
            if not refund_data.bank_account_id:
                raise HTTPException(
                    status_code=400,
                    detail="Bank account ID is required for transfer refunds"
                )
            
            bank_account = db.query(BankAccount).filter(
                BankAccount.id == refund_data.bank_account_id,
                BankAccount.is_active == True
            ).first()
            
            if not bank_account:
                raise HTTPException(
                    status_code=404,
                    detail="Bank account not found or inactive"
                )
        
        total_refund_amount = Decimal('0')
        refund_items = []
        
        for refund_item in refund_data.items:
            sale_item = db.query(SaleItem).filter(SaleItem.id == refund_item.sale_item_id).first()
            if not sale_item:
                raise HTTPException(status_code=404, detail=f"Sale item {refund_item.sale_item_id} not found")
            
            if sale_item.sale_id != original_sale.id:
                raise HTTPException(status_code=400, detail="Item does not belong to this sale")
            
            # Check already refunded quantity
            already_refunded = db.query(RefundItem).filter(
                RefundItem.sale_item_id == sale_item.id
            ).all()
            
            already_refunded_qty = sum(r.quantity for r in already_refunded)
            max_refundable = sale_item.quantity - already_refunded_qty
            
            if refund_item.quantity > max_refundable:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot refund {refund_item.quantity} of item {sale_item.id}. Max refundable: {max_refundable}"
                )
            
            refund_amount = Decimal(str(refund_item.quantity)) * Decimal(str(sale_item.unit_price))
            total_refund_amount += refund_amount
            
            refund_items.append({
                "sale_item": sale_item,
                "quantity": Decimal(str(refund_item.quantity)),
                "refund_amount": refund_amount,
                "reason": refund_item.reason
            })
        
        refund_number = generate_refund_number(db)
        
        refund = Refund(
            refund_number=refund_number,
            original_sale_id=original_sale.id,
            branch_id=original_sale.branch_id,
            user_id=current_user.id,
            customer_name=original_sale.customer_name,
            refund_amount=total_refund_amount,
            refund_reason=refund_data.refund_reason,
            refund_method=refund_data.refund_method,
            bank_account_id=refund_data.bank_account_id,
            transaction_reference=refund_data.transaction_reference,
            status="completed",
            notes=refund_data.notes,
            completed_at=datetime.now()
        )
        db.add(refund)
        db.flush()
        
        for item in refund_items:
            refund_item = RefundItem(
                refund_id=refund.id,
                sale_item_id=item["sale_item"].id,
                product_id=item["sale_item"].product_id,
                quantity=item["quantity"],
                unit_price=item["sale_item"].unit_price,
                refund_amount=item["refund_amount"],
                reason=item["reason"]
            )
            db.add(refund_item)
            
            # Update stock - add back the refunded quantity
            stock = db.query(Stock).filter(
                Stock.branch_id == original_sale.branch_id,
                Stock.product_id == item["sale_item"].product_id
            ).first()
            
            if stock:
                stock.quantity = stock.quantity + item["quantity"]
                
                stock_movement = StockMovement(
                    branch_id=original_sale.branch_id,
                    product_id=item["sale_item"].product_id,
                    user_id=current_user.id,
                    change_qty=item["quantity"],
                    movement_type="refund",
                    reference_id=refund.id,
                    notes=f"Refund for sale {original_sale.invoice_number}"
                )
                db.add(stock_movement)
        
        # Update the original sale
        original_sale.refund_amount = original_sale.refund_amount + total_refund_amount
        
        # Check if sale is now fully refunded
        if original_sale.refund_amount >= original_sale.total_amount:
            original_sale.status = "refunded"
            original_sale.refund_status = "completed"
        else:
            original_sale.status = "partially_refunded"
            original_sale.refund_status = "partially_refunded"
        
        db.commit()
        db.refresh(refund)
        
        branch = db.query(Branch).filter(Branch.id == refund.branch_id).first()
        
        response_items = []
        for item in refund_items:
            product = db.query(Product).filter(Product.id == item["sale_item"].product_id).first()
            response_items.append({
                "id": 0,
                "sale_item_id": item["sale_item"].id,
                "product_id": item["sale_item"].product_id,
                "product_name": product.name if product else None,
                "quantity": float(item["quantity"]),
                "unit_price": float(item["sale_item"].unit_price),
                "refund_amount": float(item["refund_amount"]),
                "reason": item["reason"]
            })
        
        # Get bank account details if available
        bank_account_details = None
        if refund.bank_account_id:
            bank_account = db.query(BankAccount).filter(BankAccount.id == refund.bank_account_id).first()
            if bank_account:
                bank_account_details = BankAccountResponse(
                    id=bank_account.id,
                    branch_id=bank_account.branch_id,
                    bank_name=bank_account.bank_name,
                    branch_name=bank_account.branch_name,
                    account_number=bank_account.account_number,
                    account_name=bank_account.account_name,
                    account_type=bank_account.account_type,
                    iban=bank_account.iban,
                    swift_code=bank_account.swift_code,
                    currency=bank_account.currency,
                    current_balance=float(bank_account.current_balance),
                    is_active=bank_account.is_active,
                    is_primary=bank_account.is_primary,
                    last_reconciled_at=bank_account.last_reconciled_at,
                    last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                    notes=bank_account.notes,
                    created_by=bank_account.created_by,
                    created_at=bank_account.created_at,
                    updated_at=bank_account.updated_at
                )
        
        print(f"Refund created successfully! Refund: {refund_number}, Amount: {float(total_refund_amount)}")
        
        return RefundResponse(
            id=refund.id,
            refund_number=refund.refund_number,
            original_sale_id=refund.original_sale_id,
            original_invoice_number=original_sale.invoice_number,
            branch_id=refund.branch_id,
            branch_name=branch.name if branch else None,
            user_id=refund.user_id,
            user_name=current_user.name,
            customer_name=refund.customer_name,
            refund_amount=float(refund.refund_amount),
            refund_reason=refund.refund_reason,
            refund_method=refund.refund_method,
            bank_account_id=refund.bank_account_id,
            bank_account_details=bank_account_details,
            transaction_reference=refund.transaction_reference,
            status=refund.status,
            approved_by=None,
            approved_at=None,
            created_at=refund.created_at,
            completed_at=refund.completed_at,
            notes=refund.notes,
            items=response_items
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error creating refund: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
@router.get("/refunds", response_model=List[RefundResponse])
def get_refunds(
    branch_id: Optional[int] = None,
    sale_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all refunds with filters"""
    
    query = db.query(Refund)
    
    if current_user.role == "salesman":
        if not current_user.branch_id:
            return []
        query = query.filter(Refund.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(Refund.branch_id == branch_id)
    
    if sale_id:
        query = query.filter(Refund.original_sale_id == sale_id)
    
    if start_date:
        query = query.filter(Refund.created_at >= start_date)
    if end_date:
        query = query.filter(Refund.created_at <= end_date)
    
    refunds = query.order_by(Refund.created_at.desc()).limit(limit).all()
    
    result = []
    for refund in refunds:
        original_sale = db.query(Sale).filter(Sale.id == refund.original_sale_id).first()
        branch = db.query(Branch).filter(Branch.id == refund.branch_id).first()
        items = db.query(RefundItem).filter(RefundItem.refund_id == refund.id).all()
        
        response_items = []
        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            response_items.append({
                "id": item.id,
                "sale_item_id": item.sale_item_id,
                "product_id": item.product_id,
                "product_name": product.name if product else None,
                "quantity": float(item.quantity),
                "unit_price": float(item.unit_price),
                "refund_amount": float(item.refund_amount),
                "reason": item.reason
            })
        
        # Get bank account details if available
        bank_account_details = None
        if refund.bank_account_id:
            bank_account = db.query(BankAccount).filter(BankAccount.id == refund.bank_account_id).first()
            if bank_account:
                bank_account_details = BankAccountResponse(
                    id=bank_account.id,
                    branch_id=bank_account.branch_id,
                    bank_name=bank_account.bank_name,
                    branch_name=bank_account.branch_name,
                    account_number=bank_account.account_number,
                    account_name=bank_account.account_name,
                    account_type=bank_account.account_type,
                    iban=bank_account.iban,
                    swift_code=bank_account.swift_code,
                    currency=bank_account.currency,
                    current_balance=float(bank_account.current_balance),
                    is_active=bank_account.is_active,
                    is_primary=bank_account.is_primary,
                    last_reconciled_at=bank_account.last_reconciled_at,
                    last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                    notes=bank_account.notes,
                    created_by=bank_account.created_by,
                    created_at=bank_account.created_at,
                    updated_at=bank_account.updated_at
                )
        
        result.append(RefundResponse(
            id=refund.id,
            refund_number=refund.refund_number,
            original_sale_id=refund.original_sale_id,
            original_invoice_number=original_sale.invoice_number if original_sale else None,
            branch_id=refund.branch_id,
            branch_name=branch.name if branch else None,
            user_id=refund.user_id,
            user_name=refund.user.name if refund.user else None,
            customer_name=refund.customer_name,
            refund_amount=float(refund.refund_amount),
            refund_reason=refund.refund_reason,
            refund_method=refund.refund_method,
            bank_account_id=refund.bank_account_id,
            bank_account_details=bank_account_details,
            transaction_reference=refund.transaction_reference,
            status=refund.status,
            approved_by=refund.approver.name if refund.approver else None,
            approved_at=refund.approved_at,
            created_at=refund.created_at,
            completed_at=refund.completed_at,
            notes=refund.notes,
            items=response_items
        ))
    
    return result

@router.get("/refunds/{refund_id}", response_model=RefundResponse)
def get_refund(
    refund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a single refund by ID"""
    
    refund = db.query(Refund).filter(Refund.id == refund_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    
    if current_user.role == "salesman" and refund.branch_id != current_user.branch_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this refund"
        )
    
    original_sale = db.query(Sale).filter(Sale.id == refund.original_sale_id).first()
    branch = db.query(Branch).filter(Branch.id == refund.branch_id).first()
    items = db.query(RefundItem).filter(RefundItem.refund_id == refund.id).all()
    
    response_items = []
    for item in items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        response_items.append({
            "id": item.id,
            "sale_item_id": item.sale_item_id,
            "product_id": item.product_id,
            "product_name": product.name if product else None,
            "quantity": float(item.quantity),
            "unit_price": float(item.unit_price),
            "refund_amount": float(item.refund_amount),
            "reason": item.reason
        })
    
    # Get bank account details if available
    bank_account_details = None
    if refund.bank_account_id:
        bank_account = db.query(BankAccount).filter(BankAccount.id == refund.bank_account_id).first()
        if bank_account:
            bank_account_details = BankAccountResponse(
                id=bank_account.id,
                branch_id=bank_account.branch_id,
                bank_name=bank_account.bank_name,
                branch_name=bank_account.branch_name,
                account_number=bank_account.account_number,
                account_name=bank_account.account_name,
                account_type=bank_account.account_type,
                iban=bank_account.iban,
                swift_code=bank_account.swift_code,
                currency=bank_account.currency,
                current_balance=float(bank_account.current_balance),
                is_active=bank_account.is_active,
                is_primary=bank_account.is_primary,
                last_reconciled_at=bank_account.last_reconciled_at,
                last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                notes=bank_account.notes,
                created_by=bank_account.created_by,
                created_at=bank_account.created_at,
                updated_at=bank_account.updated_at
            )
    
    return RefundResponse(
        id=refund.id,
        refund_number=refund.refund_number,
        original_sale_id=refund.original_sale_id,
        original_invoice_number=original_sale.invoice_number if original_sale else None,
        branch_id=refund.branch_id,
        branch_name=branch.name if branch else None,
        user_id=refund.user_id,
        user_name=refund.user.name if refund.user else None,
        customer_name=refund.customer_name,
        refund_amount=float(refund.refund_amount),
        refund_reason=refund.refund_reason,
        refund_method=refund.refund_method,
        bank_account_id=refund.bank_account_id,
        bank_account_details=bank_account_details,
        transaction_reference=refund.transaction_reference,
        status=refund.status,
        approved_by=refund.approver.name if refund.approver else None,
        approved_at=refund.approved_at,
        created_at=refund.created_at,
        completed_at=refund.completed_at,
        notes=refund.notes,
        items=response_items
    )

# ==================== SALE OPERATIONS ====================

@router.post("", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=SaleResponse, status_code=status.HTTP_201_CREATED)
def create_sale(
    sale_data: SaleCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new sale transaction with tax, payment method, and bank account support.
       When payment method is 'transfer', the amount is added to the wallet linked to the bank account.
       Now supports shipping, labour, and other costs."""
    
    print(f"=== CREATE SALE ===")
    print(f"User: {current_user.id} - {current_user.name} - Role: {current_user.role}")
    print(f"Sale data: {sale_data}")
    
    try:
        branch_id = sale_data.branch_id or current_user.branch_id
        
        if not branch_id:
            raise HTTPException(
                status_code=400, 
                detail="Branch ID is required"
            )
        
        print(f"Branch ID: {branch_id}")
        
        if current_user.role == "salesman" and current_user.branch_id != branch_id:
            raise HTTPException(
                status_code=403,
                detail="Not authorized to sell from this branch"
            )
        
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Track if this is a bank transfer payment
        is_bank_transfer = sale_data.payment_method == "transfer"
        wallet_to_credit = None
        
        if is_bank_transfer:
            if not sale_data.bank_account_id:
                raise HTTPException(
                    status_code=400,
                    detail="Bank account ID is required for transfer payments"
                )
            
            bank_account = db.query(BankAccount).filter(
                BankAccount.id == sale_data.bank_account_id,
                BankAccount.branch_id == branch_id,
                BankAccount.is_active == True
            ).first()
            
            if not bank_account:
                raise HTTPException(
                    status_code=404,
                    detail="Bank account not found or inactive"
                )
            
            # Get the wallet associated with this bank account
            wallet_to_credit = get_wallet_from_bank_account(db, bank_account.id, branch_id)
            if wallet_to_credit:
                print(f"Found wallet for bank account: {wallet_to_credit.wallet_name} (ID: {wallet_to_credit.id})")
            else:
                print(f"No wallet linked to bank account ID: {bank_account.id}")
        
        subtotal = Decimal('0')
        total_cost = Decimal('0')
        sale_items = []
        
        for idx, item_data in enumerate(sale_data.items):
            print(f"Processing item {idx}: product_id={item_data.product_id}, quantity={item_data.quantity}, price={item_data.unit_price}")
            
            product = db.query(Product).filter(Product.id == item_data.product_id).first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
            
            print(f"Product found: {product.name}, cost={product.cost}")
            
            quantity_decimal = Decimal(str(item_data.quantity))
            unit_price_decimal = Decimal(str(item_data.unit_price))
            product_cost_decimal = Decimal(str(product.cost))
            item_discount = Decimal(str(item_data.discount_amount)) if item_data.discount_amount else Decimal('0')
            
            stock = db.query(Stock).filter(
                Stock.branch_id == branch_id,
                Stock.product_id == item_data.product_id
            ).first()
            
            if not stock:
                print(f"No stock record found for product {item_data.product_id} in branch {branch_id}")
                stock = Stock(
                    branch_id=branch_id,
                    product_id=item_data.product_id,
                    quantity=Decimal('0'),
                    reorder_level=Decimal('10')
                )
                db.add(stock)
                db.flush()
            
            if stock.quantity < quantity_decimal:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {product.name}. Available: {float(stock.quantity)}, Requested: {float(quantity_decimal)}"
                )
            
            line_subtotal = quantity_decimal * unit_price_decimal
            line_total = line_subtotal - item_discount
            line_cost = quantity_decimal * product_cost_decimal
            
            subtotal += line_subtotal
            total_cost += line_cost
            
            stock.quantity = stock.quantity - quantity_decimal
            print(f"Stock updated: new quantity = {stock.quantity}")
            
            stock_movement = StockMovement(
                branch_id=branch_id,
                product_id=item_data.product_id,
                user_id=current_user.id,
                change_qty=-quantity_decimal,
                movement_type="sale",
                notes=f"Sale by {current_user.name}"
            )
            db.add(stock_movement)
            
            sale_items.append({
                "product": product,
                "quantity": quantity_decimal,
                "unit_price": unit_price_decimal,
                "discount_amount": item_discount,
                "line_total": line_total
            })
        
        tax_rate = Decimal(str(sale_data.tax_rate)) / Decimal('100')
        tax_amount = subtotal * tax_rate if sale_data.tax_rate > 0 else Decimal('0')
        
        global_discount = Decimal(str(sale_data.discount_amount))
        if sale_data.discount_type == "percentage":
            global_discount = subtotal * (Decimal(str(sale_data.discount_amount)) / Decimal('100'))
        
        # Additional costs from the schema
        shipping_cost = Decimal(str(sale_data.shipping_cost)) if sale_data.shipping_cost else Decimal('0')
        labour_cost = Decimal(str(sale_data.labour_cost)) if sale_data.labour_cost else Decimal('0')
        other_cost = Decimal(str(sale_data.other_cost)) if sale_data.other_cost else Decimal('0')
        
        # Calculate total amount including all costs
        total_amount = subtotal + tax_amount + shipping_cost + labour_cost + other_cost - global_discount
        
        invoice_number = generate_invoice_number(db)
        
        sale = Sale(
            invoice_number=invoice_number,
            branch_id=branch_id,
            user_id=current_user.id,
            customer_name=sale_data.customer_name,
            customer_phone=sale_data.customer_phone,
            customer_email=sale_data.customer_email,
            subtotal=subtotal,
            tax_amount=tax_amount,
            tax_rate=Decimal(str(sale_data.tax_rate)),
            discount_amount=global_discount,
            discount_type=sale_data.discount_type,
            shipping_cost=shipping_cost,
            labour_cost=labour_cost,
            other_cost=other_cost,
            other_cost_description=sale_data.other_cost_description,
            total_amount=total_amount,
            total_cost=total_cost,
            gross_profit=subtotal - total_cost,
            profit_margin=((subtotal - total_cost) / subtotal * 100) if subtotal > 0 else Decimal('0'),
            payment_method=sale_data.payment_method,
            bank_account_id=sale_data.bank_account_id,
            transaction_reference=sale_data.transaction_reference,
            status="completed",
            refund_amount=Decimal('0'),
            refund_status="none",
            notes=sale_data.notes
        )
        db.add(sale)
        db.flush()
        
        for item in sale_items:
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=item["product"].id,
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                discount_amount=item["discount_amount"],
                line_total=item["line_total"]
            )
            db.add(sale_item)
        
        db.commit()
        db.refresh(sale)
        
        # ==================== ADD TO WALLET FOR BANK TRANSFER ====================
        if is_bank_transfer and wallet_to_credit and total_amount > 0:
            try:
                # Add the sale amount to the wallet (credit)
                transaction = process_wallet_transaction(
                    db=db,
                    wallet_id=wallet_to_credit.id,
                    transaction_type=WalletTransactionType.DEPOSIT.value,
                    amount=total_amount,
                    description=f"Sale #{invoice_number} - Customer: {sale_data.customer_name or 'Walk-in'}",
                    user_id=current_user.id,
                    transaction_method="bank_transfer",
                    reference_type="sale",
                    reference_id=sale.id,
                    bank_reference=sale_data.transaction_reference
                )
                print(f"✅ Wallet credited: {transaction.transaction_number} - Amount: {total_amount} to wallet '{wallet_to_credit.wallet_name}'")
                
                # Update sale record with wallet transaction ID
                sale.wallet_transaction_id = transaction.id
                db.commit()
                
            except Exception as wallet_error:
                print(f"⚠️ Wallet credit failed for sale #{invoice_number}: {wallet_error}")
                # Don't fail the sale if wallet credit fails, just log it
        else:
            if is_bank_transfer and not wallet_to_credit:
                print(f"⚠️ No wallet linked to bank account ID: {sale_data.bank_account_id}. Amount not added to wallet.")
        
        response_items = []
        for item in sale_items:
            response_items.append(SaleItemResponse(
                id=0,
                sale_id=sale.id,
                product_id=item["product"].id,
                product_name=item["product"].name,
                product_sku=item["product"].sku,
                quantity=float(item["quantity"]),
                unit_price=float(item["unit_price"]),
                discount_amount=float(item["discount_amount"]),
                line_total=float(item["line_total"])
            ))
        
        # Get bank account details if available
        bank_account_details = None
        if sale.bank_account_id:
            bank_account = db.query(BankAccount).filter(BankAccount.id == sale.bank_account_id).first()
            if bank_account:
                bank_account_details = BankAccountResponse(
                    id=bank_account.id,
                    branch_id=bank_account.branch_id,
                    bank_name=bank_account.bank_name,
                    branch_name=bank_account.branch_name,
                    account_number=bank_account.account_number,
                    account_name=bank_account.account_name,
                    account_type=bank_account.account_type,
                    iban=bank_account.iban,
                    swift_code=bank_account.swift_code,
                    currency=bank_account.currency,
                    current_balance=float(bank_account.current_balance),
                    is_active=bank_account.is_active,
                    is_primary=bank_account.is_primary,
                    last_reconciled_at=bank_account.last_reconciled_at,
                    last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                    notes=bank_account.notes,
                    created_by=bank_account.created_by,
                    created_at=bank_account.created_at,
                    updated_at=bank_account.updated_at
                )
        
        print(f"Sale created successfully! Invoice: {invoice_number}, Total: {float(total_amount)}")
        
        # ==================== SEND EMAIL NOTIFICATION ====================
        try:
            print("🔵 [SALE ROUTER] Attempting to send email notification...")
            
            # Get all admin emails from database
            admin_emails = AuthService.get_all_admin_emails(db)
            print(f"🔵 [SALE ROUTER] Admin emails found: {admin_emails}")
            
            if admin_emails and settings.EMAIL_ENABLED:
                sale_data_for_email = {
                    "sale_id": sale.id,
                    "customer_name": sale.customer_name or "Walk-in Customer",
                    "total_amount": float(sale.total_amount),
                    "item_count": len(sale_items),
                    "salesman_name": current_user.name,
                    "branch_name": branch.name,
                    "created_at": sale.created_at.strftime("%Y-%m-%d %H:%M:%S") if sale.created_at else datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "shipping_cost": float(sale.shipping_cost),
                    "labour_cost": float(sale.labour_cost),
                    "other_cost": float(sale.other_cost)
                }
                
                print(f"🔵 [SALE ROUTER] Sale data for email: {sale_data_for_email}")
                
                # Send email notification to all admins
                result = EmailService.send_sale_notification(admin_emails, sale_data_for_email)
                if result:
                    print(f"✅✅✅ Sale notification email sent to {len(admin_emails)} admins")
                else:
                    print(f"❌❌❌ Failed to send sale notification email - check Brevo configuration")
            else:
                print(f"⚠️ No admin emails found or email disabled. Admin emails: {admin_emails}, EMAIL_ENABLED: {settings.EMAIL_ENABLED}")
                
        except Exception as email_error:
            print(f"❌❌❌ Exception in sale notification: {str(email_error)}")
            import traceback
            traceback.print_exc()
        # ==================== END EMAIL NOTIFICATION ====================
        
        return SaleResponse(
            id=sale.id,
            invoice_number=sale.invoice_number,
            branch_id=sale.branch_id,
            branch_name=branch.name,
            user_id=sale.user_id,
            user_name=current_user.name,
            customer_name=sale.customer_name,
            customer_phone=sale.customer_phone,
            customer_email=sale.customer_email,
            subtotal=float(sale.subtotal),
            tax_amount=float(sale.tax_amount),
            tax_rate=float(sale.tax_rate),
            discount_amount=float(sale.discount_amount),
            discount_type=sale.discount_type,
            shipping_cost=float(sale.shipping_cost),
            labour_cost=float(sale.labour_cost),
            other_cost=float(sale.other_cost),
            other_cost_description=sale.other_cost_description,
            total_amount=float(sale.total_amount),
            total_cost=float(sale.total_cost),
            gross_profit=float(sale.gross_profit),
            profit_margin=float(sale.profit_margin),
            payment_method=sale.payment_method,
            bank_account_id=sale.bank_account_id,
            bank_account_details=bank_account_details,
            transaction_reference=sale.transaction_reference,
            status=sale.status,
            refund_amount=float(sale.refund_amount),
            refund_status=sale.refund_status,
            created_at=sale.created_at,
            updated_at=sale.updated_at,
            notes=sale.notes,
            items=response_items
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error creating sale: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("", response_model=List[SaleResponse])
@router.get("/", response_model=List[SaleResponse])
def get_sales(
    branch_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    payment_method: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get sales with filters including payment method and status"""
    
    try:
        print(f"🔍 GET_SALES called - User: {current_user.id}, Role: {current_user.role}")
        
        query = db.query(Sale)
        
        # Apply branch filter
        if current_user.role == "salesman":
            if branch_id and branch_id != current_user.branch_id:
                raise HTTPException(
                    status_code=403,
                    detail="Not authorized to view sales from other branches"
                )
            query = query.filter(Sale.branch_id == current_user.branch_id)
        elif branch_id:
            query = query.filter(Sale.branch_id == branch_id)
        
        # Apply date filters
        if start_date:
            query = query.filter(Sale.created_at >= start_date)
        if end_date:
            query = query.filter(Sale.created_at <= end_date)
        
        # Apply other filters
        if payment_method:
            query = query.filter(Sale.payment_method == payment_method)
        if status:
            query = query.filter(Sale.status == status)
        if search:
            query = query.filter(
                (Sale.invoice_number.ilike(f"%{search}%")) |
                (Sale.customer_name.ilike(f"%{search}%"))
            )
        
        # Execute query
        sales = query.order_by(Sale.created_at.desc()).limit(limit).all()
        print(f"✅ Found {len(sales)} sales")
        
        result = []
        for sale in sales:
            try:
                # Get sale items
                items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
                
                # Get bank account details if available
                bank_account_details = None
                if sale.bank_account_id:
                    try:
                        bank_account = db.query(BankAccount).filter(BankAccount.id == sale.bank_account_id).first()
                        if bank_account:
                            bank_account_details = BankAccountResponse(
                                id=bank_account.id,
                                branch_id=bank_account.branch_id,
                                bank_name=bank_account.bank_name,
                                branch_name=bank_account.branch_name,
                                account_number=bank_account.account_number,
                                account_name=bank_account.account_name,
                                account_type=bank_account.account_type,
                                iban=bank_account.iban,
                                swift_code=bank_account.swift_code,
                                currency=bank_account.currency,
                                current_balance=float(bank_account.current_balance) if bank_account.current_balance else 0,
                                is_active=bank_account.is_active,
                                is_primary=bank_account.is_primary,
                                last_reconciled_at=bank_account.last_reconciled_at,
                                last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                                notes=bank_account.notes,
                                created_by=bank_account.created_by,
                                created_at=bank_account.created_at,
                                updated_at=bank_account.updated_at
                            )
                    except Exception as bank_error:
                        print(f"⚠️ Bank account error for sale {sale.id}: {bank_error}")
                        bank_account_details = None
                
                # Calculate refund amount safely
                refund_amount = float(sale.refund_amount) if sale.refund_amount else 0
                
                # If refund_amount is 0 but status is partially_refunded, try to get it from refunds
                if refund_amount == 0 and sale.status in ["partially_refunded", "refunded"]:
                    try:
                        # Try to get refunds directly
                        refunds = db.query(Refund).filter(
                            Refund.original_sale_id == sale.id,
                            Refund.status == "completed"
                        ).all()
                        
                        if refunds:
                            total_refunded = 0
                            for refund in refunds:
                                if refund.refund_amount:
                                    total_refunded += float(refund.refund_amount)
                            refund_amount = total_refunded
                            
                            # Update the sale with correct refund amount if different
                            if refund_amount != float(sale.refund_amount or 0):
                                sale.refund_amount = Decimal(str(refund_amount))
                                db.commit()
                                print(f"✅ Updated refund_amount for sale {sale.id} to {refund_amount}")
                    except Exception as refund_error:
                        print(f"⚠️ Error getting refunds for sale {sale.id}: {refund_error}")
                
                # Determine refund status
                refund_status = sale.refund_status or "none"
                if sale.status == "partially_refunded" and refund_status == "none":
                    refund_status = "partially_refunded"
                elif sale.status == "refunded" and refund_status == "none":
                    refund_status = "completed"
                
                # Build the response
                sale_response = SaleResponse(
                    id=sale.id,
                    invoice_number=sale.invoice_number or "",
                    branch_id=sale.branch_id,
                    branch_name=sale.branch.name if sale.branch else None,
                    user_id=sale.user_id,
                    user_name=sale.user.name if sale.user else None,
                    customer_name=sale.customer_name,
                    customer_phone=sale.customer_phone,
                    customer_email=sale.customer_email,
                    subtotal=float(sale.subtotal) if sale.subtotal else 0,
                    tax_amount=float(sale.tax_amount) if sale.tax_amount else 0,
                    tax_rate=float(sale.tax_rate) if sale.tax_rate else 0,
                    discount_amount=float(sale.discount_amount) if sale.discount_amount else 0,
                    discount_type=sale.discount_type,
                    shipping_cost=float(sale.shipping_cost) if sale.shipping_cost else 0,
                    labour_cost=float(sale.labour_cost) if sale.labour_cost else 0,
                    other_cost=float(sale.other_cost) if sale.other_cost else 0,
                    other_cost_description=sale.other_cost_description,
                    total_amount=float(sale.total_amount) if sale.total_amount else 0,
                    total_cost=float(sale.total_cost) if sale.total_cost else 0,
                    gross_profit=float(sale.gross_profit) if sale.gross_profit else 0,
                    profit_margin=float(sale.profit_margin) if sale.profit_margin else 0,
                    payment_method=sale.payment_method,
                    bank_account_id=sale.bank_account_id,
                    bank_account_details=bank_account_details,
                    transaction_reference=sale.transaction_reference,
                    status=sale.status or "completed",
                    refund_amount=float(refund_amount),
                    refund_status=refund_status,
                    created_at=sale.created_at,
                    updated_at=sale.updated_at,
                    notes=sale.notes,
                    items=[
                        SaleItemResponse(
                            id=item.id,
                            sale_id=item.sale_id,
                            product_id=item.product_id,
                            product_name=item.product.name if item.product else None,
                            product_sku=item.product.sku if item.product else None,
                            quantity=float(item.quantity) if item.quantity else 0,
                            unit_price=float(item.unit_price) if item.unit_price else 0,
                            discount_amount=float(item.discount_amount) if item.discount_amount else 0,
                            line_total=float(item.line_total) if item.line_total else 0
                        )
                        for item in items
                    ]
                )
                result.append(sale_response)
                
            except Exception as sale_error:
                print(f"❌ Error processing sale {sale.id}: {sale_error}")
                traceback.print_exc()
                # Skip this sale and continue with others
                continue
        
        print(f"✅ Returning {len(result)} sales successfully")
        return result
        
    except Exception as e:
        print(f"❌ CRITICAL Error in get_sales: {e}")
        traceback.print_exc()
        # Return empty list instead of failing
        return []

@router.get("/{sale_id}", response_model=SaleResponse)
def get_sale(
    sale_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a single sale by ID with all details"""
    
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    if current_user.role == "salesman" and sale.branch_id != current_user.branch_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this sale"
        )
    
    items = db.query(SaleItem).filter(SaleItem.sale_id == sale.id).all()
    
    # Get bank account details if available
    bank_account_details = None
    if sale.bank_account_id:
        bank_account = db.query(BankAccount).filter(BankAccount.id == sale.bank_account_id).first()
        if bank_account:
            bank_account_details = BankAccountResponse(
                id=bank_account.id,
                branch_id=bank_account.branch_id,
                bank_name=bank_account.bank_name,
                branch_name=bank_account.branch_name,
                account_number=bank_account.account_number,
                account_name=bank_account.account_name,
                account_type=bank_account.account_type,
                iban=bank_account.iban,
                swift_code=bank_account.swift_code,
                currency=bank_account.currency,
                current_balance=float(bank_account.current_balance),
                is_active=bank_account.is_active,
                is_primary=bank_account.is_primary,
                last_reconciled_at=bank_account.last_reconciled_at,
                last_reconciled_balance=float(bank_account.last_reconciled_balance) if bank_account.last_reconciled_balance else None,
                notes=bank_account.notes,
                created_by=bank_account.created_by,
                created_at=bank_account.created_at,
                updated_at=bank_account.updated_at
            )
    
    return SaleResponse(
        id=sale.id,
        invoice_number=sale.invoice_number,
        branch_id=sale.branch_id,
        branch_name=sale.branch.name if sale.branch else None,
        user_id=sale.user_id,
        user_name=sale.user.name if sale.user else None,
        customer_name=sale.customer_name,
        customer_phone=sale.customer_phone,
        customer_email=sale.customer_email,
        subtotal=float(sale.subtotal),
        tax_amount=float(sale.tax_amount),
        tax_rate=float(sale.tax_rate),
        discount_amount=float(sale.discount_amount),
        discount_type=sale.discount_type,
        shipping_cost=float(sale.shipping_cost),
        labour_cost=float(sale.labour_cost),
        other_cost=float(sale.other_cost),
        other_cost_description=sale.other_cost_description,
        total_amount=float(sale.total_amount),
        total_cost=float(sale.total_cost),
        gross_profit=float(sale.gross_profit),
        profit_margin=float(sale.profit_margin),
        payment_method=sale.payment_method,
        bank_account_id=sale.bank_account_id,
        bank_account_details=bank_account_details,
        transaction_reference=sale.transaction_reference,
        status=sale.status,
        refund_amount=float(sale.refund_amount),
        refund_status=sale.refund_status,
        created_at=sale.created_at,
        updated_at=sale.updated_at,
        notes=sale.notes,
        items=[
            SaleItemResponse(
                id=item.id,
                sale_id=item.sale_id,
                product_id=item.product_id,
                product_name=item.product.name if item.product else None,
                product_sku=item.product.sku if item.product else None,
                quantity=float(item.quantity),
                unit_price=float(item.unit_price),
                discount_amount=float(item.discount_amount),
                line_total=float(item.line_total)
            )
            for item in items
        ]
    )
    
@router.put("/{sale_id}", response_model=SaleResponse)
def update_sale(
    sale_id: int,
    sale_update: dict,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update sale information (customer info, notes, etc.)"""
    
    sale = db.query(Sale).filter(Sale.id == sale_id).first()
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    
    if current_user.role == "salesman" and sale.branch_id != current_user.branch_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to update this sale"
        )
    
    allowed_fields = ["customer_name", "customer_phone", "customer_email", "notes", 
                     "shipping_cost", "labour_cost", "other_cost", "other_cost_description"]
    for field in allowed_fields:
        if field in sale_update:
            setattr(sale, field, sale_update[field])
    
    # Recalculate total amount if costs changed
    if any(field in sale_update for field in ["shipping_cost", "labour_cost", "other_cost"]):
        sale.total_amount = sale.subtotal + sale.tax_amount + sale.shipping_cost + sale.labour_cost + sale.other_cost - sale.discount_amount
    
    db.commit()
    db.refresh(sale)
    
    return get_sale(sale_id, db, current_user)

@router.get("/summary/payment-methods")
def get_sales_by_payment_method(
    branch_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get sales summary grouped by payment method"""
    
    query = db.query(Sale)
    
    if current_user.role == "salesman":
        query = query.filter(Sale.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(Sale.branch_id == branch_id)
    
    if start_date:
        query = query.filter(Sale.created_at >= start_date)
    if end_date:
        query = query.filter(Sale.created_at <= end_date)
    
    sales = query.all()
    
    summary = {}
    for sale in sales:
        method = sale.payment_method
        if method not in summary:
            summary[method] = {
                "count": 0,
                "total_amount": 0,
                "total_tax": 0,
                "total_shipping": 0,
                "total_labour": 0,
                "total_other": 0
            }
        summary[method]["count"] += 1
        summary[method]["total_amount"] += float(sale.total_amount)
        summary[method]["total_tax"] += float(sale.tax_amount)
        summary[method]["total_shipping"] += float(sale.shipping_cost)
        summary[method]["total_labour"] += float(sale.labour_cost)
        summary[method]["total_other"] += float(sale.other_cost)
    
    return summary

@router.get("/summary/status")
def get_sales_by_status(
    branch_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get sales summary grouped by status"""
    
    query = db.query(Sale)
    
    if current_user.role == "salesman":
        query = query.filter(Sale.branch_id == current_user.branch_id)
    elif branch_id:
        query = query.filter(Sale.branch_id == branch_id)
    
    if start_date:
        query = query.filter(Sale.created_at >= start_date)
    if end_date:
        query = query.filter(Sale.created_at <= end_date)
    
    sales = query.all()
    
    summary = {}
    for sale in sales:
        status = sale.status
        if status not in summary:
            summary[status] = {
                "count": 0,
                "total_amount": 0,
                "total_refund": 0
            }
        summary[status]["count"] += 1
        summary[status]["total_amount"] += float(sale.total_amount)
        summary[status]["total_refund"] += float(sale.refund_amount)
    
    return summary