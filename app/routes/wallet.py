# app/routes/wallet.py (or app/routers/wallet.py)
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, date, timedelta
from typing import Optional, List
from decimal import Decimal
import random
import string
import secrets

from app.database import get_db
from app.models import (
    User, Branch, Wallet, WalletTransaction, WalletTransactionType,
    WalletTransactionStatus, WalletTransactionMethod, WalletSummary,
    WalletType, WalletPurpose, Product, PurchaseOrder, Refund,
    BankAccount, BankTransaction
)
from app.schemas import (
    WalletCreate, WalletUpdate, WalletResponse,
    WalletDeposit, WalletWithdrawal, WalletTransfer,
    WalletTransactionResponse, WalletSummaryResponse,
    WalletBalanceResponse, BranchWalletSummaryResponse,
    BankAccountCreate, BankAccountUpdate, BankAccountResponse,
    BankTransactionCreate, BankTransactionResponse, BankTransactionReconcile,
    WalletPerformanceReport
)
from app.utils.dependencies import get_current_user, require_admin, require_privileged

router = APIRouter(prefix="/api/wallet", tags=["Wallet Management"])


# ==================== HELPER FUNCTIONS ====================

def generate_wallet_number(branch_id: int, wallet_type: str) -> str:
    """Generate unique wallet number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(4).upper()
    return f"W{wallet_type[:3].upper()}-{branch_id}-{timestamp}-{random_suffix}"


def generate_transaction_number() -> str:
    """Generate unique transaction number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = secrets.token_hex(3).upper()
    return f"TXN-{timestamp}-{random_suffix}"


def process_wallet_transaction(
    db: Session,
    wallet_id: int,
    transaction_type: str,
    amount: Decimal,
    description: str,
    user_id: int = None,
    transaction_method: str = WalletTransactionMethod.CASH.value,
    reference_type: str = None,
    reference_id: int = None,
    reference_number: str = None,
    bank_reference: str = None,
    from_wallet_id: int = None,
    to_wallet_id: int = None
) -> WalletTransaction:
    """Process a wallet transaction and update balance"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if not wallet.is_active:
        raise HTTPException(status_code=400, detail="Wallet is inactive")
    
    # Check daily limit if applicable
    if wallet.daily_limit and transaction_type in ["withdrawal", "purchase", "restock"]:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_total = db.query(func.sum(WalletTransaction.amount)).filter(
            WalletTransaction.wallet_id == wallet_id,
            WalletTransaction.transaction_type.in_(["withdrawal", "purchase", "restock"]),
            WalletTransaction.created_at >= today_start,
            WalletTransaction.status == WalletTransactionStatus.COMPLETED.value
        ).scalar() or Decimal('0')
        
        if daily_total + amount > Decimal(str(wallet.daily_limit)):
            raise HTTPException(
                status_code=400,
                detail=f"Daily limit exceeded. Limit: {wallet.daily_limit}, Used today: {float(daily_total)}"
            )
    
    # Check transaction limit if applicable
    if wallet.transaction_limit and amount > Decimal(str(wallet.transaction_limit)):
        raise HTTPException(
            status_code=400,
            detail=f"Transaction amount exceeds limit. Max per transaction: {wallet.transaction_limit}"
        )
    
    # Calculate new balance
    balance_before = wallet.balance
    amount_decimal = Decimal(str(amount))
    
    # Determine if this is a debit or credit transaction
    debit_transactions = [
        WalletTransactionType.WITHDRAWAL.value,
        WalletTransactionType.PURCHASE.value,
        WalletTransactionType.RESTOCK.value
    ]
    
    # Special handling for transfer transactions
    if transaction_type == WalletTransactionType.TRANSFER.value:
        # If this is a transfer FROM this wallet, it's a debit
        # If this is a transfer TO this wallet, it's a credit
        # We determine this by checking if this wallet is the source or destination
        if to_wallet_id == wallet_id:
            # This wallet is receiving money -> credit
            balance_after = balance_before + amount_decimal
        elif from_wallet_id == wallet_id:
            # This wallet is sending money -> debit
            if balance_before < amount_decimal:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Insufficient funds in wallet. Available: {float(balance_before)}, Required: {float(amount_decimal)}"
                )
            balance_after = balance_before - amount_decimal
        else:
            # Try to infer from context - if to_wallet_id is set but from_wallet_id is not,
            # this is likely a withdrawal transaction (sending money)
            if to_wallet_id is not None and from_wallet_id is None:
                # This wallet is sending money -> debit
                if balance_before < amount_decimal:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Insufficient funds in wallet. Available: {float(balance_before)}, Required: {float(amount_decimal)}"
                    )
                balance_after = balance_before - amount_decimal
            elif from_wallet_id is not None and to_wallet_id is None:
                # This wallet is receiving money -> credit
                balance_after = balance_before + amount_decimal
            else:
                raise HTTPException(status_code=400, detail="Invalid transfer transaction")
    elif transaction_type in debit_transactions:
        if balance_before < amount_decimal:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient funds in wallet. Available: {float(balance_before)}, Required: {float(amount_decimal)}"
            )
        balance_after = balance_before - amount_decimal
    else:
        # Credit transactions (deposit, refund, adjustment)
        balance_after = balance_before + amount_decimal
    
    # Check max balance if applicable (only for credit transactions)
    if wallet.max_balance and balance_after > Decimal(str(wallet.max_balance)):
        raise HTTPException(
            status_code=400,
            detail=f"Max balance would be exceeded. Limit: {wallet.max_balance}"
        )
    
    # Create transaction record
    transaction = WalletTransaction(
        transaction_number=generate_transaction_number(),
        wallet_id=wallet_id,
        transaction_type=transaction_type,
        transaction_method=transaction_method,
        amount=amount_decimal,
        balance_before=balance_before,
        balance_after=balance_after,
        status=WalletTransactionStatus.COMPLETED.value,
        approval_status="approved",
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        bank_reference=bank_reference,
        from_wallet_id=from_wallet_id,
        to_wallet_id=to_wallet_id,
        created_by=user_id
    )
    
    # Update wallet balance
    wallet.balance = balance_after
    wallet.updated_at = datetime.now()
    
    # If linked to bank account, update bank balance and create bank transaction
    if wallet.bank_account_id and transaction_type in ["deposit", "withdrawal"]:
        bank_account = db.query(BankAccount).filter(BankAccount.id == wallet.bank_account_id).first()
        if bank_account:
            if transaction_type == "deposit":
                bank_account.current_balance += amount_decimal
            else:
                bank_account.current_balance -= amount_decimal
            
            # Create bank transaction record
            bank_transaction = BankTransaction(
                bank_account_id=bank_account.id,
                transaction_date=datetime.now(),
                transaction_type="credit" if transaction_type == "deposit" else "debit",
                amount=amount_decimal,
                description=description,
                reference=transaction.transaction_number,
                wallet_transaction_id=transaction.id
            )
            db.add(bank_transaction)
    
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    
    # Check minimum balance alert
    if wallet.min_balance and balance_after < Decimal(str(wallet.min_balance)):
        # You can implement notification system here
        pass
    
    return transaction


def get_or_create_wallet(db: Session, branch_id: int, wallet_type: str, wallet_name: str = None) -> Wallet:
    """Get or create default wallet for a branch"""
    wallet = db.query(Wallet).filter(
        Wallet.branch_id == branch_id,
        Wallet.wallet_type == wallet_type
    ).first()
    
    if not wallet:
        wallet = Wallet(
            wallet_number=generate_wallet_number(branch_id, wallet_type),
            wallet_name=wallet_name or f"{wallet_type.title()} Wallet",
            branch_id=branch_id,
            wallet_type=wallet_type,
            wallet_purpose=WalletPurpose.OTHER.value,
            balance=0,
            currency="ETB",
            is_active=True,
            created_by=1
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    
    return wallet


def generate_wallet_summary(db: Session, wallet_id: int, summary_date: date) -> WalletSummary:
    """Generate wallet summary for a specific date"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    # Get start and end of day
    start_of_day = datetime.combine(summary_date, datetime.min.time())
    end_of_day = datetime.combine(summary_date, datetime.max.time())
    
    # Get transactions for the day
    transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet_id,
        WalletTransaction.created_at >= start_of_day,
        WalletTransaction.created_at <= end_of_day,
        WalletTransaction.status == WalletTransactionStatus.COMPLETED.value
    ).all()
    
    # Calculate totals
    total_deposits = Decimal('0')
    total_withdrawals = Decimal('0')
    total_transfers_in = Decimal('0')
    total_transfers_out = Decimal('0')
    total_purchases = Decimal('0')
    total_restocks = Decimal('0')
    total_refunds = Decimal('0')
    
    amounts = []
    for tx in transactions:
        amounts.append(tx.amount)
        if tx.transaction_type == "deposit":
            total_deposits += tx.amount
        elif tx.transaction_type == "withdrawal":
            total_withdrawals += tx.amount
        elif tx.transaction_type == "transfer":
            if tx.to_wallet_id == wallet_id:
                total_transfers_in += tx.amount
            else:
                total_transfers_out += tx.amount
        elif tx.transaction_type == "purchase":
            total_purchases += tx.amount
        elif tx.transaction_type == "restock":
            total_restocks += tx.amount
        elif tx.transaction_type == "refund":
            total_refunds += tx.amount
    
    # Calculate opening balance (current balance minus today's changes)
    total_income = total_deposits + total_transfers_in + total_refunds
    total_expenses = total_withdrawals + total_transfers_out + total_purchases + total_restocks
    opening_balance = wallet.balance - (total_income - total_expenses)
    
    # Calculate statistics
    transaction_count = len(transactions)
    average_amount = sum(amounts) / len(amounts) if amounts else Decimal('0')
    highest_amount = max(amounts) if amounts else Decimal('0')
    lowest_amount = min(amounts) if amounts else Decimal('0')
    
    # Create or update summary
    summary = db.query(WalletSummary).filter(
        WalletSummary.wallet_id == wallet_id,
        WalletSummary.summary_date == summary_date
    ).first()
    
    if summary:
        # Update existing summary
        summary.opening_balance = opening_balance
        summary.total_deposits = total_deposits
        summary.total_transfers_in = total_transfers_in
        summary.total_withdrawals = total_withdrawals
        summary.total_transfers_out = total_transfers_out
        summary.total_purchases = total_purchases
        summary.total_restocks = total_restocks
        summary.total_refunds = total_refunds
        summary.closing_balance = wallet.balance
        summary.transaction_count = transaction_count
        summary.average_transaction_amount = average_amount
        summary.highest_transaction = highest_amount
        summary.lowest_transaction = lowest_amount
        summary.updated_at = datetime.now()
    else:
        # Create new summary
        summary = WalletSummary(
            wallet_id=wallet_id,
            branch_id=wallet.branch_id,
            summary_date=summary_date,
            opening_balance=opening_balance,
            total_deposits=total_deposits,
            total_transfers_in=total_transfers_in,
            total_withdrawals=total_withdrawals,
            total_transfers_out=total_transfers_out,
            total_purchases=total_purchases,
            total_restocks=total_restocks,
            total_refunds=total_refunds,
            closing_balance=wallet.balance,
            transaction_count=transaction_count,
            average_transaction_amount=average_amount,
            highest_transaction=highest_amount,
            lowest_transaction=lowest_amount
        )
        db.add(summary)
    
    db.commit()
    db.refresh(summary)
    
    return summary


# ==================== WALLET CRUD ENDPOINTS ====================

@router.post("/create", response_model=WalletResponse)
def create_wallet(
    wallet_data: WalletCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new wallet for a branch (Admin only)"""
    
    branch = db.query(Branch).filter(Branch.id == wallet_data.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Check if wallet number already exists
    existing = db.query(Wallet).filter(
        Wallet.wallet_number == generate_wallet_number(wallet_data.branch_id, wallet_data.wallet_type.value)
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Wallet already exists for this branch")
    
    # Check bank account if provided
    if wallet_data.bank_account_id:
        bank_account = db.query(BankAccount).filter(
            BankAccount.id == wallet_data.bank_account_id,
            BankAccount.branch_id == wallet_data.branch_id
        ).first()
        if not bank_account:
            raise HTTPException(status_code=404, detail="Bank account not found or doesn't belong to branch")
    
    initial_balance = Decimal(str(wallet_data.initial_balance)) if wallet_data.initial_balance else Decimal('0')
    
    wallet = Wallet(
        wallet_number=generate_wallet_number(wallet_data.branch_id, wallet_data.wallet_type.value),
        wallet_name=wallet_data.wallet_name,
        branch_id=wallet_data.branch_id,
        wallet_type=wallet_data.wallet_type.value,
        wallet_purpose=wallet_data.wallet_purpose.value,
        balance=initial_balance,
        currency=wallet_data.currency,
        bank_account_id=wallet_data.bank_account_id,
        is_active=True,
        requires_approval=wallet_data.requires_approval,
        max_balance=Decimal(str(wallet_data.max_balance)) if wallet_data.max_balance else None,
        min_balance=Decimal(str(wallet_data.min_balance)) if wallet_data.min_balance else None,
        daily_limit=Decimal(str(wallet_data.daily_limit)) if wallet_data.daily_limit else None,
        transaction_limit=Decimal(str(wallet_data.transaction_limit)) if wallet_data.transaction_limit else None,
        description=wallet_data.description,
        created_by=current_user.id
    )
    
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    
    # Only create initial deposit transaction if initial_balance > 0
    if initial_balance > 0:
        process_wallet_transaction(
            db=db,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.DEPOSIT.value,
            amount=initial_balance,
            description="Initial wallet deposit",
            user_id=current_user.id,
            transaction_method=WalletTransactionMethod.BANK_TRANSFER.value
        )
        db.refresh(wallet)
    
    # Create initial summary
    generate_wallet_summary(db, wallet.id, date.today())
    
    return WalletResponse(
        id=wallet.id,
        wallet_number=wallet.wallet_number,
        wallet_name=wallet.wallet_name,
        branch_id=wallet.branch_id,
        branch_name=branch.name,
        wallet_type=wallet.wallet_type,
        wallet_purpose=wallet.wallet_purpose,
        balance=float(wallet.balance),
        currency=wallet.currency,
        bank_account_id=wallet.bank_account_id,
        is_active=wallet.is_active,
        requires_approval=wallet.requires_approval,
        max_balance=float(wallet.max_balance) if wallet.max_balance else None,
        min_balance=float(wallet.min_balance) if wallet.min_balance else None,
        daily_limit=float(wallet.daily_limit) if wallet.daily_limit else None,
        transaction_limit=float(wallet.transaction_limit) if wallet.transaction_limit else None,
        description=wallet.description,
        created_by=current_user.id,
        created_by_name=current_user.name,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at
    )


@router.get("/branch/{branch_id}", response_model=List[WalletResponse])
def get_branch_wallets(
    branch_id: int,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get all wallets for a branch"""
    
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    if current_user.role == "salesman" and current_user.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = db.query(Wallet).filter(Wallet.branch_id == branch_id)
    if not include_inactive:
        query = query.filter(Wallet.is_active == True)
    
    wallets = query.all()
    
    result = []
    for wallet in wallets:
        result.append(WalletResponse(
            id=wallet.id,
            wallet_number=wallet.wallet_number,
            wallet_name=wallet.wallet_name,
            branch_id=wallet.branch_id,
            branch_name=branch.name,
            wallet_type=wallet.wallet_type,
            wallet_purpose=wallet.wallet_purpose,
            balance=float(wallet.balance),
            currency=wallet.currency,
            bank_account_id=wallet.bank_account_id,
            is_active=wallet.is_active,
            requires_approval=wallet.requires_approval,
            max_balance=float(wallet.max_balance) if wallet.max_balance else None,
            min_balance=float(wallet.min_balance) if wallet.min_balance else None,
            daily_limit=float(wallet.daily_limit) if wallet.daily_limit else None,
            transaction_limit=float(wallet.transaction_limit) if wallet.transaction_limit else None,
            description=wallet.description,
            created_by=wallet.created_by,
            created_at=wallet.created_at,
            updated_at=wallet.updated_at
        ))
    
    return result


@router.get("/balances", response_model=BranchWalletSummaryResponse)
def get_wallet_balances(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all wallet balances for a branch"""
    
    if current_user.role == "salesman":
        branch_id = current_user.branch_id
    elif not branch_id and current_user.role == "admin":
        branch_id = current_user.branch_id or 1
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="Branch ID required")
    
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    wallets = db.query(Wallet).filter(
        Wallet.branch_id == branch_id,
        Wallet.is_active == True
    ).all()
    
    wallet_balances = []
    total_balance = Decimal('0')
    
    for wallet in wallets:
        wallet_balances.append(WalletBalanceResponse(
            wallet_id=wallet.id,
            wallet_name=wallet.wallet_name,
            wallet_type=wallet.wallet_type,
            balance=float(wallet.balance),
            currency=wallet.currency,
            bank_account_name=wallet.bank_account.account_name if wallet.bank_account else None
        ))
        total_balance += wallet.balance
    
    return BranchWalletSummaryResponse(
        branch_id=branch.id,
        branch_name=branch.name,
        wallets=wallet_balances,
        total_balance=float(total_balance)
    )


@router.put("/{wallet_id}", response_model=WalletResponse)
def update_wallet(
    wallet_id: int,
    wallet_update: WalletUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update wallet settings (Admin only)"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    update_data = wallet_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if field in ["max_balance", "min_balance", "daily_limit", "transaction_limit"] and value is not None:
                setattr(wallet, field, Decimal(str(value)))
            else:
                setattr(wallet, field, value)
    
    wallet.updated_at = datetime.now()
    db.commit()
    db.refresh(wallet)
    
    branch = db.query(Branch).filter(Branch.id == wallet.branch_id).first()
    
    return WalletResponse(
        id=wallet.id,
        wallet_number=wallet.wallet_number,
        wallet_name=wallet.wallet_name,
        branch_id=wallet.branch_id,
        branch_name=branch.name if branch else None,
        wallet_type=wallet.wallet_type,
        wallet_purpose=wallet.wallet_purpose,
        balance=float(wallet.balance),
        currency=wallet.currency,
        bank_account_id=wallet.bank_account_id,
        is_active=wallet.is_active,
        requires_approval=wallet.requires_approval,
        max_balance=float(wallet.max_balance) if wallet.max_balance else None,
        min_balance=float(wallet.min_balance) if wallet.min_balance else None,
        daily_limit=float(wallet.daily_limit) if wallet.daily_limit else None,
        transaction_limit=float(wallet.transaction_limit) if wallet.transaction_limit else None,
        description=wallet.description,
        created_by=wallet.created_by,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at
    )


# ==================== WALLET TRANSACTION ENDPOINTS ====================

@router.post("/deposit", response_model=WalletTransactionResponse)
def deposit_to_wallet(
    deposit_data: WalletDeposit,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Deposit money into a wallet (Admin only)"""
    
    wallet = db.query(Wallet).filter(Wallet.id == deposit_data.wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    transaction = process_wallet_transaction(
        db=db,
        wallet_id=deposit_data.wallet_id,
        transaction_type=WalletTransactionType.DEPOSIT.value,
        amount=Decimal(str(deposit_data.amount)),
        description=deposit_data.description or "Cash deposit",
        user_id=current_user.id,
        transaction_method=deposit_data.transaction_method.value,
        reference_type=deposit_data.reference_type,
        reference_id=deposit_data.reference_id,
        reference_number=deposit_data.reference_number,
        bank_reference=deposit_data.bank_reference
    )
    
    generate_wallet_summary(db, wallet.id, date.today())
    
    return WalletTransactionResponse(
        id=transaction.id,
        transaction_number=transaction.transaction_number,
        wallet_id=transaction.wallet_id,
        wallet_name=wallet.wallet_name,
        transaction_type=transaction.transaction_type,
        transaction_method=transaction.transaction_method,
        amount=float(transaction.amount),
        balance_before=float(transaction.balance_before),
        balance_after=float(transaction.balance_after),
        status=transaction.status,
        approval_status=transaction.approval_status,
        description=transaction.description,
        reference_type=transaction.reference_type,
        reference_id=transaction.reference_id,
        reference_number=transaction.reference_number,
        bank_reference=transaction.bank_reference,
        from_wallet_id=transaction.from_wallet_id,
        to_wallet_id=transaction.to_wallet_id,
        created_at=transaction.created_at,
        created_by=current_user.name
    )


@router.post("/withdraw", response_model=WalletTransactionResponse)
def withdraw_from_wallet(
    withdrawal_data: WalletWithdrawal,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Withdraw money from a wallet (Admin only)"""
    
    wallet = db.query(Wallet).filter(Wallet.id == withdrawal_data.wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    transaction = process_wallet_transaction(
        db=db,
        wallet_id=withdrawal_data.wallet_id,
        transaction_type=WalletTransactionType.WITHDRAWAL.value,
        amount=Decimal(str(withdrawal_data.amount)),
        description=withdrawal_data.description or "Cash withdrawal",
        user_id=current_user.id,
        transaction_method=withdrawal_data.transaction_method.value,
        reference_type=withdrawal_data.reference_type,
        reference_id=withdrawal_data.reference_id,
        reference_number=withdrawal_data.reference_number,
        bank_reference=withdrawal_data.bank_reference
    )
    
    generate_wallet_summary(db, wallet.id, date.today())
    
    return WalletTransactionResponse(
        id=transaction.id,
        transaction_number=transaction.transaction_number,
        wallet_id=transaction.wallet_id,
        wallet_name=wallet.wallet_name,
        transaction_type=transaction.transaction_type,
        transaction_method=transaction.transaction_method,
        amount=float(transaction.amount),
        balance_before=float(transaction.balance_before),
        balance_after=float(transaction.balance_after),
        status=transaction.status,
        approval_status=transaction.approval_status,
        description=transaction.description,
        reference_type=transaction.reference_type,
        reference_id=transaction.reference_id,
        reference_number=transaction.reference_number,
        bank_reference=transaction.bank_reference,
        from_wallet_id=transaction.from_wallet_id,
        to_wallet_id=transaction.to_wallet_id,
        created_at=transaction.created_at,
        created_by=current_user.name
    )


@router.post("/transfer", response_model=List[WalletTransactionResponse])
def transfer_between_wallets(
    transfer_data: WalletTransfer,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Transfer money between wallets (Admin only)
    FIXED: Now properly deducts from source and adds to destination
    """
    
    from_wallet = db.query(Wallet).filter(Wallet.id == transfer_data.from_wallet_id).first()
    to_wallet = db.query(Wallet).filter(Wallet.id == transfer_data.to_wallet_id).first()
    
    if not from_wallet:
        raise HTTPException(status_code=404, detail="Source wallet not found")
    if not to_wallet:
        raise HTTPException(status_code=404, detail="Destination wallet not found")
    
    amount = Decimal(str(transfer_data.amount))
    
    # Check if source wallet has sufficient funds
    if from_wallet.balance < amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient funds in source wallet '{from_wallet.wallet_name}'. "
                   f"Available: {float(from_wallet.balance)}, Required: {float(amount)}"
        )
    
    # FIXED: Process withdrawal from source wallet (DEBIT)
    # Set BOTH from_wallet_id and to_wallet_id to properly identify the transaction
    withdraw_txn = process_wallet_transaction(
        db=db,
        wallet_id=transfer_data.from_wallet_id,
        transaction_type=WalletTransactionType.TRANSFER.value,
        amount=amount,
        description=f"Transfer to {to_wallet.wallet_name}: {transfer_data.description or ''}",
        user_id=current_user.id,
        transaction_method=transfer_data.transaction_method.value,
        from_wallet_id=transfer_data.from_wallet_id,  # FIXED: Added this
        to_wallet_id=transfer_data.to_wallet_id
    )
    
    # Refresh to get updated balance
    db.refresh(from_wallet)
    
    # Process deposit to destination wallet (CREDIT)
    deposit_txn = process_wallet_transaction(
        db=db,
        wallet_id=transfer_data.to_wallet_id,
        transaction_type=WalletTransactionType.TRANSFER.value,
        amount=amount,
        description=f"Transfer from {from_wallet.wallet_name}: {transfer_data.description or ''}",
        user_id=current_user.id,
        transaction_method=transfer_data.transaction_method.value,
        from_wallet_id=transfer_data.from_wallet_id,
        to_wallet_id=transfer_data.to_wallet_id
    )
    
    # Generate summaries
    generate_wallet_summary(db, from_wallet.id, date.today())
    generate_wallet_summary(db, to_wallet.id, date.today())
    
    return [
        WalletTransactionResponse(
            id=withdraw_txn.id,
            transaction_number=withdraw_txn.transaction_number,
            wallet_id=withdraw_txn.wallet_id,
            wallet_name=from_wallet.wallet_name,
            transaction_type="transfer_out",
            transaction_method=withdraw_txn.transaction_method,
            amount=float(withdraw_txn.amount),
            balance_before=float(withdraw_txn.balance_before),
            balance_after=float(withdraw_txn.balance_after),
            status=withdraw_txn.status,
            approval_status=withdraw_txn.approval_status,
            description=withdraw_txn.description,
            from_wallet_id=withdraw_txn.from_wallet_id,
            to_wallet_id=withdraw_txn.to_wallet_id,
            created_at=withdraw_txn.created_at,
            created_by=current_user.name
        ),
        WalletTransactionResponse(
            id=deposit_txn.id,
            transaction_number=deposit_txn.transaction_number,
            wallet_id=deposit_txn.wallet_id,
            wallet_name=to_wallet.wallet_name,
            transaction_type="transfer_in",
            transaction_method=deposit_txn.transaction_method,
            amount=float(deposit_txn.amount),
            balance_before=float(deposit_txn.balance_before),
            balance_after=float(deposit_txn.balance_after),
            status=deposit_txn.status,
            approval_status=deposit_txn.approval_status,
            description=deposit_txn.description,
            from_wallet_id=deposit_txn.from_wallet_id,
            to_wallet_id=deposit_txn.to_wallet_id,
            created_at=deposit_txn.created_at,
            created_by=current_user.name
        )
    ]


@router.get("/transactions", response_model=List[WalletTransactionResponse])
def get_wallet_transactions(
    wallet_id: int,
    transaction_type: Optional[str] = None,
    transaction_method: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get wallet transaction history"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if current_user.role == "salesman" and wallet.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet_id)
    
    if transaction_type:
        query = query.filter(WalletTransaction.transaction_type == transaction_type)
    if transaction_method:
        query = query.filter(WalletTransaction.transaction_method == transaction_method)
    if from_date:
        query = query.filter(WalletTransaction.created_at >= from_date)
    if to_date:
        query = query.filter(WalletTransaction.created_at <= to_date)
    
    transactions = query.order_by(WalletTransaction.created_at.desc()).offset(offset).limit(limit).all()
    
    result = []
    for txn in transactions:
        display_type = txn.transaction_type
        if txn.transaction_type == "transfer":
            if txn.to_wallet_id == wallet_id:
                display_type = "transfer_in"
            else:
                display_type = "transfer_out"
        
        result.append(WalletTransactionResponse(
            id=txn.id,
            transaction_number=txn.transaction_number,
            wallet_id=txn.wallet_id,
            wallet_name=wallet.wallet_name,
            transaction_type=display_type,
            transaction_method=txn.transaction_method,
            amount=float(txn.amount),
            balance_before=float(txn.balance_before),
            balance_after=float(txn.balance_after),
            status=txn.status,
            approval_status=txn.approval_status,
            description=txn.description,
            reference_type=txn.reference_type,
            reference_id=txn.reference_id,
            reference_number=txn.reference_number,
            bank_reference=txn.bank_reference,
            from_wallet_id=txn.from_wallet_id,
            to_wallet_id=txn.to_wallet_id,
            created_at=txn.created_at,
            created_by=txn.creator.name if txn.creator else None,
            approved_by=txn.approver.name if txn.approver else None,
            approved_at=txn.approved_at
        ))
    
    return result


# ==================== WALLET SUMMARY ENDPOINTS ====================

@router.get("/summary/{wallet_id}", response_model=WalletSummaryResponse)
def get_wallet_summary(
    wallet_id: int,
    summary_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get wallet summary for a specific date"""
    
    if not summary_date:
        summary_date = date.today()
    
    summary = generate_wallet_summary(db, wallet_id, summary_date)
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    branch = db.query(Branch).filter(Branch.id == wallet.branch_id).first()
    
    return WalletSummaryResponse(
        id=summary.id,
        wallet_id=summary.wallet_id,
        wallet_name=wallet.wallet_name if wallet else None,
        branch_id=summary.branch_id,
        branch_name=branch.name if branch else None,
        summary_date=summary.summary_date,
        opening_balance=float(summary.opening_balance),
        total_deposits=float(summary.total_deposits),
        total_transfers_in=float(summary.total_transfers_in),
        total_income=float(summary.total_deposits + summary.total_transfers_in + summary.total_refunds),
        total_withdrawals=float(summary.total_withdrawals),
        total_transfers_out=float(summary.total_transfers_out),
        total_purchases=float(summary.total_purchases),
        total_restocks=float(summary.total_restocks),
        total_refunds=float(summary.total_refunds),
        total_expenses=float(summary.total_withdrawals + summary.total_transfers_out + 
                           summary.total_purchases + summary.total_restocks),
        closing_balance=float(summary.closing_balance),
        transaction_count=summary.transaction_count,
        average_transaction_amount=float(summary.average_transaction_amount) if summary.average_transaction_amount else 0,
        highest_transaction=float(summary.highest_transaction) if summary.highest_transaction else 0,
        lowest_transaction=float(summary.lowest_transaction) if summary.lowest_transaction else 0,
        is_reconciled=summary.is_reconciled,
        reconciled_at=summary.reconciled_at,
        created_at=summary.created_at,
        updated_at=summary.updated_at
    )


@router.get("/summary/range/{wallet_id}", response_model=List[WalletSummaryResponse])
def get_wallet_summary_range(
    wallet_id: int,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get wallet summaries for a date range"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    current_date = from_date
    summaries = []
    
    while current_date <= to_date:
        summary = generate_wallet_summary(db, wallet_id, current_date)
        summaries.append(summary)
        current_date += timedelta(days=1)
    
    branch = db.query(Branch).filter(Branch.id == wallet.branch_id).first()
    
    result = []
    for summary in summaries:
        result.append(WalletSummaryResponse(
            id=summary.id,
            wallet_id=summary.wallet_id,
            wallet_name=wallet.wallet_name,
            branch_id=summary.branch_id,
            branch_name=branch.name if branch else None,
            summary_date=summary.summary_date,
            opening_balance=float(summary.opening_balance),
            total_deposits=float(summary.total_deposits),
            total_transfers_in=float(summary.total_transfers_in),
            total_income=float(summary.total_deposits + summary.total_transfers_in + summary.total_refunds),
            total_withdrawals=float(summary.total_withdrawals),
            total_transfers_out=float(summary.total_transfers_out),
            total_purchases=float(summary.total_purchases),
            total_restocks=float(summary.total_restocks),
            total_refunds=float(summary.total_refunds),
            total_expenses=float(summary.total_withdrawals + summary.total_transfers_out + 
                               summary.total_purchases + summary.total_restocks),
            closing_balance=float(summary.closing_balance),
            transaction_count=summary.transaction_count,
            average_transaction_amount=float(summary.average_transaction_amount) if summary.average_transaction_amount else 0,
            highest_transaction=float(summary.highest_transaction) if summary.highest_transaction else 0,
            lowest_transaction=float(summary.lowest_transaction) if summary.lowest_transaction else 0,
            is_reconciled=summary.is_reconciled,
            reconciled_at=summary.reconciled_at,
            created_at=summary.created_at,
            updated_at=summary.updated_at
        ))
    
    return result


# ==================== BANK ACCOUNT ENDPOINTS ====================

@router.post("/bank-account/create", response_model=BankAccountResponse)
def create_bank_account(
    account_data: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new bank account for a branch (Admin only)"""
    
    branch = db.query(Branch).filter(Branch.id == account_data.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    existing = db.query(BankAccount).filter(
        BankAccount.branch_id == account_data.branch_id,
        BankAccount.account_number == account_data.account_number
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Bank account number already exists for this branch")
    
    bank_account = BankAccount(
        **account_data.dict(),
        current_balance=0,
        created_by=current_user.id
    )
    
    db.add(bank_account)
    db.commit()
    db.refresh(bank_account)
    
    return BankAccountResponse(
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
        created_by=current_user.id,
        created_at=bank_account.created_at,
        updated_at=bank_account.updated_at
    )


@router.get("/bank-accounts/{branch_id}", response_model=List[BankAccountResponse])
def get_branch_bank_accounts(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Get all bank accounts for a branch"""
    
    accounts = db.query(BankAccount).filter(
        BankAccount.branch_id == branch_id,
        BankAccount.is_active == True
    ).all()
    
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


# ==================== BUSINESS OPERATION ENDPOINTS ====================

@router.post("/process-restock/{product_id}")
def process_restock_wallet_transaction(
    product_id: int,
    quantity: float = Query(..., gt=0),
    branch_id: Optional[int] = None,
    wallet_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Process wallet transaction when restocking (Deduct from specified wallet)"""
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if not branch_id:
        branch_id = current_user.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="Branch ID required")
    
    total_cost = Decimal(str(quantity)) * product.cost
    
    if wallet_id:
        wallet = db.query(Wallet).filter(
            Wallet.id == wallet_id,
            Wallet.branch_id == branch_id,
            Wallet.is_active == True
        ).first()
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")
    else:
        wallet = get_or_create_wallet(db, branch_id, "regular", "Regular Operations Wallet")
    
    transaction = process_wallet_transaction(
        db=db,
        wallet_id=wallet.id,
        transaction_type=WalletTransactionType.RESTOCK.value,
        amount=total_cost,
        description=f"Restocked {quantity} units of {product.name} (SKU: {product.sku})",
        user_id=current_user.id,
        reference_type="restock",
        reference_id=product_id
    )
    
    generate_wallet_summary(db, wallet.id, date.today())
    
    return {
        "message": "Restock processed successfully",
        "transaction": transaction.transaction_number,
        "amount_deducted": float(total_cost),
        "wallet_id": wallet.id,
        "wallet_name": wallet.wallet_name,
        "wallet_balance": float(wallet.balance)
    }


# ==================== REPORTING ENDPOINTS ====================

@router.get("/performance-report", response_model=WalletPerformanceReport)
def get_wallet_performance_report(
    wallet_id: int,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get detailed wallet performance report"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    summaries = db.query(WalletSummary).filter(
        WalletSummary.wallet_id == wallet_id,
        WalletSummary.summary_date >= from_date,
        WalletSummary.summary_date <= to_date
    ).order_by(WalletSummary.summary_date).all()
    
    transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet_id,
        WalletTransaction.created_at >= from_date,
        WalletTransaction.created_at <= to_date,
        WalletTransaction.status == WalletTransactionStatus.COMPLETED.value
    ).order_by(WalletTransaction.created_at).all()
    
    opening_balance = summaries[0].opening_balance if summaries else wallet.balance
    closing_balance = summaries[-1].closing_balance if summaries else wallet.balance
    
    total_deposits = sum(s.total_deposits for s in summaries)
    total_withdrawals = sum(s.total_withdrawals for s in summaries)
    total_transfers_in = sum(s.total_transfers_in for s in summaries)
    total_transfers_out = sum(s.total_transfers_out for s in summaries)
    total_purchases = sum(s.total_purchases for s in summaries)
    total_restocks = sum(s.total_restocks for s in summaries)
    total_refunds = sum(s.total_refunds for s in summaries)
    
    daily_balances = [
        {
            "date": s.summary_date.isoformat(),
            "opening_balance": float(s.opening_balance),
            "closing_balance": float(s.closing_balance)
        }
        for s in summaries
    ]
    
    transaction_list = []
    for t in transactions[:100]:
        display_type = t.transaction_type
        if t.transaction_type == "transfer":
            if t.to_wallet_id == wallet_id:
                display_type = "transfer_in"
            else:
                display_type = "transfer_out"
        
        transaction_list.append(WalletTransactionResponse(
            id=t.id,
            transaction_number=t.transaction_number,
            wallet_id=t.wallet_id,
            wallet_name=wallet.wallet_name,
            transaction_type=display_type,
            transaction_method=t.transaction_method,
            amount=float(t.amount),
            balance_before=float(t.balance_before),
            balance_after=float(t.balance_after),
            status=t.status,
            approval_status=t.approval_status,
            description=t.description,
            created_at=t.created_at,
            created_by=t.creator.name if t.creator else None
        ))
    
    return WalletPerformanceReport(
        period_start=from_date,
        period_end=to_date,
        wallet_id=wallet.id,
        wallet_name=wallet.wallet_name,
        branch_id=wallet.branch_id,
        branch_name=wallet.branch.name if wallet.branch else None,
        opening_balance=float(opening_balance),
        closing_balance=float(closing_balance),
        net_change=float(closing_balance - opening_balance),
        total_deposits=float(total_deposits),
        total_withdrawals=float(total_withdrawals),
        total_transfers_in=float(total_transfers_in),
        total_transfers_out=float(total_transfers_out),
        total_purchases=float(total_purchases),
        total_restocks=float(total_restocks),
        total_refunds=float(total_refunds),
        transaction_count=len(transactions),
        average_transaction_size=float(sum(t.amount for t in transactions) / len(transactions)) if transactions else 0,
        largest_deposit=float(max((t.amount for t in transactions if t.transaction_type == "deposit"), default=0)),
        largest_withdrawal=float(max((t.amount for t in transactions if t.transaction_type == "withdrawal"), default=0)),
        daily_balances=daily_balances,
        transaction_history=transaction_list
    )


# ==================== WALLET DELETE ENDPOINT ====================

@router.delete("/{wallet_id}")
def delete_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a wallet and all related data (Admin only)"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    # Check if wallet has balance
    if wallet.balance > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete wallet with balance. Current balance: {float(wallet.balance)}. Please withdraw or transfer the balance first."
        )
    
    wallet_name = wallet.wallet_name
    wallet_number = wallet.wallet_number
    
    # Delete related records in order (respecting foreign keys)
    
    # 1. Delete wallet summaries
    db.query(WalletSummary).filter(
        WalletSummary.wallet_id == wallet_id
    ).delete()
    
    # 2. Delete wallet transactions (both sent and received)
    db.query(WalletTransaction).filter(
        (WalletTransaction.wallet_id == wallet_id) |
        (WalletTransaction.from_wallet_id == wallet_id) |
        (WalletTransaction.to_wallet_id == wallet_id)
    ).delete()
    
    # 3. Delete the wallet
    db.delete(wallet)
    db.commit()
    
    return {
        "success": True,
        "message": f"Wallet '{wallet_name}' ({wallet_number}) deleted successfully",
        "wallet_id": wallet_id
    }


# ==================== INFO ENDPOINT ====================

@router.get("/info")
def wallet_info(current_user: User = Depends(get_current_user)):
    """Get wallet system information"""
    return {
        "module": "Enhanced Wallet Management System",
        "version": "3.1.0",
        "description": "Multi-wallet system with bank account integration",
        "features": [
            "Multiple wallet types per branch (VAT, Regular, Petty Cash, Expense, Custom)",
            "Bank account integration with automatic reconciliation",
            "Real-time balance tracking with transaction history",
            "Transfer between wallets with proper debit/credit accounting",
            "Daily summaries with performance metrics",
            "Transaction limits and approval workflows",
            "Bank statement reconciliation",
            "Wallet performance reporting",
            "Daily, weekly, and monthly summaries",
            "Export capabilities for transactions and summaries"
        ],
        "wallet_types": [
            {"type": "vat", "description": "For VAT-tracked purchases and expenses"},
            {"type": "regular", "description": "For regular inventory operations"},
            {"type": "petty_cash", "description": "For small daily expenses"},
            {"type": "expense", "description": "For operating expenses"},
            {"type": "custom", "description": "Custom wallet for specific purposes"}
        ],
        "transaction_methods": [
            {"method": "cash", "description": "Cash transactions"},
            {"method": "bank_transfer", "description": "Bank transfer transactions"},
            {"method": "cheque", "description": "Cheque payments"},
            {"method": "card", "description": "Credit/Debit card transactions"},
            {"method": "mobile_money", "description": "Mobile money transactions"},
            {"method": "internal_transfer", "description": "Transfer between wallets"}
        ],
        "endpoints": {
            "wallet_management": [
                {"path": "/create", "method": "POST", "description": "Create new wallet (no auto transaction for 0 balance)"},
                {"path": "/branch/{branch_id}", "method": "GET", "description": "Get branch wallets"},
                {"path": "/balances", "method": "GET", "description": "Get wallet balances"},
                {"path": "/{wallet_id}", "method": "PUT", "description": "Update wallet settings"}
            ],
            "transactions": [
                {"path": "/deposit", "method": "POST", "description": "Deposit to wallet"},
                {"path": "/withdraw", "method": "POST", "description": "Withdraw from wallet"},
                {"path": "/transfer", "method": "POST", "description": "Transfer between wallets (debits source, credits destination)"},
                {"path": "/transactions", "method": "GET", "description": "Get transaction history"}
            ],
            "summaries": [
                {"path": "/summary/{wallet_id}", "method": "GET", "description": "Get daily summary"},
                {"path": "/summary/range/{wallet_id}", "method": "GET", "description": "Get summary range"}
            ],
            "bank_accounts": [
                {"path": "/bank-account/create", "method": "POST", "description": "Create bank account"},
                {"path": "/bank-accounts/{branch_id}", "method": "GET", "description": "Get branch bank accounts"}
            ],
            "reports": [
                {"path": "/performance-report", "method": "GET", "description": "Get performance report"}
            ],
            "delete": [
                {"path": "/{wallet_id}", "method": "DELETE", "description": "Delete wallet (only if balance is 0)"}
            ]
        }
    }