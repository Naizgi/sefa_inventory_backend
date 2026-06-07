from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, date, timedelta
from typing import Optional, List
from decimal import Decimal
import random
import string

from app.database import get_db
from app.models import (
    User, Branch, Wallet, WalletTransaction, WalletTransactionType,
    WalletTransactionStatus, WalletSummary, Product, PurchaseOrder, Refund
)
from app.schemas import (
    WalletCreate, WalletUpdate, WalletResponse,
    WalletDeposit, WalletWithdrawal, WalletTransfer,
    WalletTransactionResponse, WalletSummaryResponse, WalletBalanceResponse
)
from app.utils.dependencies import get_current_user, require_admin, require_privileged

router = APIRouter(prefix="/api/wallet", tags=["Wallet Management"])


# ==================== HELPER FUNCTIONS ====================

def generate_transaction_number() -> str:
    """Generate unique transaction number"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_digits = ''.join(random.choices(string.digits, k=4))
    return f"TXN-{timestamp}-{random_digits}"


def process_wallet_transaction(
    db: Session,
    wallet_id: int,
    transaction_type: str,
    amount: Decimal,
    description: str,
    user_id: int = None,
    reference_type: str = None,
    reference_id: int = None
) -> WalletTransaction:
    """Process a wallet transaction and update balance"""
    
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if not wallet.is_active:
        raise HTTPException(status_code=400, detail="Wallet is inactive")
    
    # Calculate new balance
    balance_before = wallet.balance
    amount_decimal = Decimal(str(amount))
    
    # For withdrawal-type transactions, check sufficient funds
    if transaction_type in [WalletTransactionType.WITHDRAWAL.value, 
                            WalletTransactionType.PURCHASE.value,
                            WalletTransactionType.RESTOCK.value,
                            WalletTransactionType.REFUND.value]:
        if balance_before < amount_decimal:
            raise HTTPException(
                status_code=400, 
                detail=f"Insufficient funds in wallet. Available: {float(balance_before)}, Required: {float(amount_decimal)}"
            )
        balance_after = balance_before - amount_decimal
    else:
        # Deposit-type transactions
        balance_after = balance_before + amount_decimal
    
    # Create transaction record
    transaction = WalletTransaction(
        transaction_number=generate_transaction_number(),
        wallet_id=wallet_id,
        transaction_type=transaction_type,
        amount=amount_decimal,
        balance_before=balance_before,
        balance_after=balance_after,
        status=WalletTransactionStatus.COMPLETED.value,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=user_id
    )
    
    # Update wallet balance
    wallet.balance = balance_after
    wallet.updated_at = datetime.now()
    
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    
    return transaction


def get_or_create_wallet(db: Session, branch_id: int, wallet_type: str) -> Wallet:
    """Get or create wallet for a branch"""
    wallet = db.query(Wallet).filter(
        Wallet.branch_id == branch_id,
        Wallet.wallet_type == wallet_type
    ).first()
    
    if not wallet:
        wallet = Wallet(
            branch_id=branch_id,
            wallet_type=wallet_type,
            balance=0,
            currency="ETB",
            is_active=True
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    
    return wallet


def generate_wallet_summary(db: Session, branch_id: int, summary_date: date) -> WalletSummary:
    """Generate wallet summary for a specific date"""
    
    # Get wallets
    vat_wallet = get_or_create_wallet(db, branch_id, "vat")
    regular_wallet = get_or_create_wallet(db, branch_id, "regular")
    
    # Get start and end of day
    start_of_day = datetime.combine(summary_date, datetime.min.time())
    end_of_day = datetime.combine(summary_date, datetime.max.time())
    
    # Get transactions for the day
    vat_transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == vat_wallet.id,
        WalletTransaction.created_at >= start_of_day,
        WalletTransaction.created_at <= end_of_day
    ).all()
    
    regular_transactions = db.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == regular_wallet.id,
        WalletTransaction.created_at >= start_of_day,
        WalletTransaction.created_at <= end_of_day
    ).all()
    
    # Calculate totals for VAT wallet
    deposits_vat = sum(t.amount for t in vat_transactions if t.transaction_type == "deposit")
    withdrawals_vat = sum(t.amount for t in vat_transactions if t.transaction_type == "withdrawal")
    purchase_expenses_vat = sum(t.amount for t in vat_transactions if t.transaction_type == "purchase")
    restock_expenses_vat = sum(t.amount for t in vat_transactions if t.transaction_type == "restock")
    refunds_vat = sum(t.amount for t in vat_transactions if t.transaction_type == "refund")
    
    # Calculate totals for Regular wallet
    deposits_regular = sum(t.amount for t in regular_transactions if t.transaction_type == "deposit")
    withdrawals_regular = sum(t.amount for t in regular_transactions if t.transaction_type == "withdrawal")
    purchase_expenses_regular = sum(t.amount for t in regular_transactions if t.transaction_type == "purchase")
    restock_expenses_regular = sum(t.amount for t in regular_transactions if t.transaction_type == "restock")
    refunds_regular = sum(t.amount for t in regular_transactions if t.transaction_type == "refund")
    
    # Calculate opening balances (current balance minus today's changes)
    opening_balance_vat = vat_wallet.balance - (deposits_vat - withdrawals_vat - purchase_expenses_vat - restock_expenses_vat - refunds_vat)
    opening_balance_regular = regular_wallet.balance - (deposits_regular - withdrawals_regular - purchase_expenses_regular - restock_expenses_regular - refunds_regular)
    
    # Calculate totals
    total_income_vat = deposits_vat
    total_income_regular = deposits_regular
    total_expenses_vat = withdrawals_vat + purchase_expenses_vat + restock_expenses_vat + refunds_vat
    total_expenses_regular = withdrawals_regular + purchase_expenses_regular + restock_expenses_regular + refunds_regular
    
    net_profit_vat = total_income_vat - total_expenses_vat
    net_profit_regular = total_income_regular - total_expenses_regular
    total_profit = net_profit_vat + net_profit_regular
    
    # Create or update summary
    summary = db.query(WalletSummary).filter(
        WalletSummary.branch_id == branch_id,
        WalletSummary.summary_date == summary_date
    ).first()
    
    if summary:
        # Update existing summary
        summary.opening_balance_vat = opening_balance_vat
        summary.opening_balance_regular = opening_balance_regular
        summary.deposits_vat = deposits_vat
        summary.deposits_regular = deposits_regular
        summary.purchase_expenses_vat = purchase_expenses_vat
        summary.purchase_expenses_regular = purchase_expenses_regular
        summary.restock_expenses_vat = restock_expenses_vat
        summary.restock_expenses_regular = restock_expenses_regular
        summary.refunds_vat = refunds_vat
        summary.refunds_regular = refunds_regular
        summary.withdrawals_vat = withdrawals_vat
        summary.withdrawals_regular = withdrawals_regular
        summary.closing_balance_vat = vat_wallet.balance
        summary.closing_balance_regular = regular_wallet.balance
        summary.net_profit_vat = net_profit_vat
        summary.net_profit_regular = net_profit_regular
        summary.total_profit = total_profit
        summary.updated_at = datetime.now()
    else:
        # Create new summary
        summary = WalletSummary(
            branch_id=branch_id,
            summary_date=summary_date,
            opening_balance_vat=opening_balance_vat,
            opening_balance_regular=opening_balance_regular,
            deposits_vat=deposits_vat,
            deposits_regular=deposits_regular,
            purchase_expenses_vat=purchase_expenses_vat,
            purchase_expenses_regular=purchase_expenses_regular,
            restock_expenses_vat=restock_expenses_vat,
            restock_expenses_regular=restock_expenses_regular,
            refunds_vat=refunds_vat,
            refunds_regular=refunds_regular,
            withdrawals_vat=withdrawals_vat,
            withdrawals_regular=withdrawals_regular,
            closing_balance_vat=vat_wallet.balance,
            closing_balance_regular=regular_wallet.balance,
            net_profit_vat=net_profit_vat,
            net_profit_regular=net_profit_regular,
            total_profit=total_profit
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
    
    existing = db.query(Wallet).filter(
        Wallet.branch_id == wallet_data.branch_id,
        Wallet.wallet_type == wallet_data.wallet_type.value
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Wallet for {wallet_data.wallet_type.value} already exists for this branch"
        )
    
    wallet = Wallet(
        branch_id=wallet_data.branch_id,
        wallet_type=wallet_data.wallet_type.value,
        balance=Decimal(str(wallet_data.initial_balance)),
        currency=wallet_data.currency,
        is_active=True
    )
    
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    
    # If initial balance > 0, create initial deposit transaction
    if wallet_data.initial_balance > 0:
        process_wallet_transaction(
            db=db,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.DEPOSIT.value,
            amount=Decimal(str(wallet_data.initial_balance)),
            description="Initial wallet deposit",
            user_id=current_user.id
        )
    
    return WalletResponse(
        id=wallet.id,
        branch_id=wallet.branch_id,
        branch_name=branch.name,
        wallet_type=wallet.wallet_type,
        balance=float(wallet.balance),
        currency=wallet.currency,
        is_active=wallet.is_active,
        created_at=wallet.created_at,
        updated_at=wallet.updated_at
    )


@router.get("/balances", response_model=WalletBalanceResponse)
def get_wallet_balances(
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get wallet balances for a branch"""
    
    if current_user.role == "salesman":
        branch_id = current_user.branch_id
    elif not branch_id and current_user.is_admin():
        branch_id = current_user.branch_id or 1
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="Branch ID required")
    
    vat_wallet = get_or_create_wallet(db, branch_id, "vat")
    regular_wallet = get_or_create_wallet(db, branch_id, "regular")
    
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    
    return WalletBalanceResponse(
        vat_wallet=WalletResponse(
            id=vat_wallet.id,
            branch_id=vat_wallet.branch_id,
            branch_name=branch.name if branch else None,
            wallet_type=vat_wallet.wallet_type,
            balance=float(vat_wallet.balance),
            currency=vat_wallet.currency,
            is_active=vat_wallet.is_active,
            created_at=vat_wallet.created_at,
            updated_at=vat_wallet.updated_at
        ),
        regular_wallet=WalletResponse(
            id=regular_wallet.id,
            branch_id=regular_wallet.branch_id,
            branch_name=branch.name if branch else None,
            wallet_type=regular_wallet.wallet_type,
            balance=float(regular_wallet.balance),
            currency=regular_wallet.currency,
            is_active=regular_wallet.is_active,
            created_at=regular_wallet.created_at,
            updated_at=regular_wallet.updated_at
        ),
        total_balance=float(vat_wallet.balance + regular_wallet.balance)
    )


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
        reference_type=deposit_data.reference_type,
        reference_id=deposit_data.reference_id
    )
    
    return WalletTransactionResponse(
        id=transaction.id,
        transaction_number=transaction.transaction_number,
        wallet_id=transaction.wallet_id,
        transaction_type=transaction.transaction_type,
        amount=float(transaction.amount),
        balance_before=float(transaction.balance_before),
        balance_after=float(transaction.balance_after),
        status=transaction.status,
        description=transaction.description,
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
        reference_type=withdrawal_data.reference_type,
        reference_id=withdrawal_data.reference_id
    )
    
    return WalletTransactionResponse(
        id=transaction.id,
        transaction_number=transaction.transaction_number,
        wallet_id=transaction.wallet_id,
        transaction_type=transaction.transaction_type,
        amount=float(transaction.amount),
        balance_before=float(transaction.balance_before),
        balance_after=float(transaction.balance_after),
        status=transaction.status,
        description=transaction.description,
        created_at=transaction.created_at,
        created_by=current_user.name
    )


@router.post("/transfer", response_model=List[WalletTransactionResponse])
def transfer_between_wallets(
    transfer_data: WalletTransfer,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Transfer money between wallets (Admin only)"""
    
    from_wallet = db.query(Wallet).filter(Wallet.id == transfer_data.from_wallet_id).first()
    to_wallet = db.query(Wallet).filter(Wallet.id == transfer_data.to_wallet_id).first()
    
    if not from_wallet:
        raise HTTPException(status_code=404, detail="Source wallet not found")
    if not to_wallet:
        raise HTTPException(status_code=404, detail="Destination wallet not found")
    
    # Withdraw from source wallet
    withdraw_txn = process_wallet_transaction(
        db=db,
        wallet_id=transfer_data.from_wallet_id,
        transaction_type=WalletTransactionType.TRANSFER.value,
        amount=Decimal(str(transfer_data.amount)),
        description=f"Transfer to {to_wallet.wallet_type} wallet: {transfer_data.description or ''}",
        user_id=current_user.id
    )
    
    # Deposit to destination wallet
    deposit_txn = process_wallet_transaction(
        db=db,
        wallet_id=transfer_data.to_wallet_id,
        transaction_type=WalletTransactionType.TRANSFER.value,
        amount=Decimal(str(transfer_data.amount)),
        description=f"Transfer from {from_wallet.wallet_type} wallet: {transfer_data.description or ''}",
        user_id=current_user.id
    )
    
    return [
        WalletTransactionResponse(
            id=withdraw_txn.id,
            transaction_number=withdraw_txn.transaction_number,
            wallet_id=withdraw_txn.wallet_id,
            transaction_type=withdraw_txn.transaction_type,
            amount=float(withdraw_txn.amount),
            balance_before=float(withdraw_txn.balance_before),
            balance_after=float(withdraw_txn.balance_after),
            status=withdraw_txn.status,
            description=withdraw_txn.description,
            created_at=withdraw_txn.created_at,
            created_by=current_user.name
        ),
        WalletTransactionResponse(
            id=deposit_txn.id,
            transaction_number=deposit_txn.transaction_number,
            wallet_id=deposit_txn.wallet_id,
            transaction_type=deposit_txn.transaction_type,
            amount=float(deposit_txn.amount),
            balance_before=float(deposit_txn.balance_before),
            balance_after=float(deposit_txn.balance_after),
            status=deposit_txn.status,
            description=deposit_txn.description,
            created_at=deposit_txn.created_at,
            created_by=current_user.name
        )
    ]


@router.get("/transactions", response_model=List[WalletTransactionResponse])
def get_wallet_transactions(
    wallet_id: int,
    transaction_type: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get wallet transaction history"""
    
    # Verify wallet belongs to user's branch
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    
    if current_user.role == "salesman" and wallet.branch_id != current_user.branch_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    query = db.query(WalletTransaction).filter(WalletTransaction.wallet_id == wallet_id)
    
    if transaction_type:
        query = query.filter(WalletTransaction.transaction_type == transaction_type)
    if from_date:
        query = query.filter(WalletTransaction.created_at >= from_date)
    if to_date:
        query = query.filter(WalletTransaction.created_at <= to_date)
    
    transactions = query.order_by(WalletTransaction.created_at.desc()).limit(limit).all()
    
    result = []
    for txn in transactions:
        creator_name = txn.creator.name if txn.creator else None
        result.append(WalletTransactionResponse(
            id=txn.id,
            transaction_number=txn.transaction_number,
            wallet_id=txn.wallet_id,
            transaction_type=txn.transaction_type,
            amount=float(txn.amount),
            balance_before=float(txn.balance_before),
            balance_after=float(txn.balance_after),
            status=txn.status,
            description=txn.description,
            created_at=txn.created_at,
            created_by=creator_name
        ))
    
    return result


# ==================== WALLET TRANSACTIONS FOR BUSINESS OPERATIONS ====================

@router.post("/process-restock/{product_id}")
def process_restock_wallet_transaction(
    product_id: int,
    quantity: float = Query(..., gt=0),
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Process wallet transaction when restocking (Deduct from regular wallet)"""
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if not branch_id:
        branch_id = current_user.branch_id
    
    if not branch_id:
        raise HTTPException(status_code=400, detail="Branch ID required")
    
    # Calculate total cost
    total_cost = Decimal(str(quantity)) * product.cost
    
    # Use regular wallet for restocking
    wallet = get_or_create_wallet(db, branch_id, "regular")
    
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
    
    return {
        "message": "Restock processed successfully",
        "transaction": transaction.transaction_number,
        "amount_deducted": float(total_cost),
        "wallet_balance": float(wallet.balance)
    }


@router.post("/process-purchase/{purchase_order_id}")
def process_purchase_wallet_transaction(
    purchase_order_id: int,
    wallet_type: str = Query("regular", regex="^(regular|vat)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_privileged)
):
    """Process wallet transaction when a purchase is made (Deduct from wallet)"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    wallet = get_or_create_wallet(db, purchase_order.branch_id, wallet_type)
    
    transaction = process_wallet_transaction(
        db=db,
        wallet_id=wallet.id,
        transaction_type=WalletTransactionType.PURCHASE.value,
        amount=Decimal(str(purchase_order.total_amount)),
        description=f"Purchase Order #{purchase_order.order_number} - Supplier: {purchase_order.supplier}",
        user_id=current_user.id,
        reference_type="purchase",
        reference_id=purchase_order.id
    )
    
    return {
        "message": "Purchase processed successfully",
        "transaction": transaction.transaction_number,
        "amount_deducted": float(purchase_order.total_amount),
        "wallet_balance": float(wallet.balance)
    }


@router.post("/process-refund/{refund_id}")
def process_refund_wallet_transaction(
    refund_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Process wallet transaction when a refund is given (Deduct from wallet)"""
    
    refund = db.query(Refund).filter(Refund.id == refund_id).first()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund not found")
    
    # Use regular wallet for refunds
    wallet = get_or_create_wallet(db, refund.branch_id, "regular")
    
    transaction = process_wallet_transaction(
        db=db,
        wallet_id=wallet.id,
        transaction_type=WalletTransactionType.REFUND.value,
        amount=Decimal(str(refund.refund_amount)),
        description=f"Refund #{refund.refund_number} - Sale #{refund.original_sale_id}",
        user_id=current_user.id,
        reference_type="refund",
        reference_id=refund_id
    )
    
    return {
        "message": "Refund processed successfully",
        "transaction": transaction.transaction_number,
        "amount_deducted": float(refund.refund_amount),
        "wallet_balance": float(wallet.balance)
    }


# ==================== WALLET SUMMARY ENDPOINTS ====================

@router.get("/summary", response_model=WalletSummaryResponse)
def get_wallet_summary(
    branch_id: int,
    summary_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get wallet summary for a specific date"""
    
    if not summary_date:
        summary_date = date.today()
    
    # Check if branch exists
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Generate or retrieve summary
    summary = generate_wallet_summary(db, branch_id, summary_date)
    
    return WalletSummaryResponse(
        id=summary.id,
        branch_id=summary.branch_id,
        branch_name=branch.name,
        summary_date=summary.summary_date,
        opening_balance_vat=float(summary.opening_balance_vat),
        opening_balance_regular=float(summary.opening_balance_regular),
        deposits_vat=float(summary.deposits_vat),
        deposits_regular=float(summary.deposits_regular),
        total_income_vat=float(summary.deposits_vat),
        total_income_regular=float(summary.deposits_regular),
        purchase_expenses_vat=float(summary.purchase_expenses_vat),
        purchase_expenses_regular=float(summary.purchase_expenses_regular),
        restock_expenses_vat=float(summary.restock_expenses_vat),
        restock_expenses_regular=float(summary.restock_expenses_regular),
        refunds_vat=float(summary.refunds_vat),
        refunds_regular=float(summary.refunds_regular),
        withdrawals_vat=float(summary.withdrawals_vat),
        withdrawals_regular=float(summary.withdrawals_regular),
        total_expenses_vat=float(summary.purchase_expenses_vat + summary.restock_expenses_vat + summary.refunds_vat + summary.withdrawals_vat),
        total_expenses_regular=float(summary.purchase_expenses_regular + summary.restock_expenses_regular + summary.refunds_regular + summary.withdrawals_regular),
        closing_balance_vat=float(summary.closing_balance_vat),
        closing_balance_regular=float(summary.closing_balance_regular),
        net_profit_vat=float(summary.net_profit_vat),
        net_profit_regular=float(summary.net_profit_regular),
        total_profit=float(summary.total_profit),
        created_at=summary.created_at
    )


@router.get("/summary/range", response_model=List[WalletSummaryResponse])
def get_wallet_summary_range(
    branch_id: int,
    from_date: date,
    to_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get wallet summaries for a date range"""
    
    # Generate summaries for each date in range
    current_date = from_date
    summaries = []
    
    while current_date <= to_date:
        summary = generate_wallet_summary(db, branch_id, current_date)
        summaries.append(summary)
        current_date += timedelta(days=1)
    
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    
    result = []
    for summary in summaries:
        result.append(WalletSummaryResponse(
            id=summary.id,
            branch_id=summary.branch_id,
            branch_name=branch.name if branch else None,
            summary_date=summary.summary_date,
            opening_balance_vat=float(summary.opening_balance_vat),
            opening_balance_regular=float(summary.opening_balance_regular),
            deposits_vat=float(summary.deposits_vat),
            deposits_regular=float(summary.deposits_regular),
            total_income_vat=float(summary.deposits_vat),
            total_income_regular=float(summary.deposits_regular),
            purchase_expenses_vat=float(summary.purchase_expenses_vat),
            purchase_expenses_regular=float(summary.purchase_expenses_regular),
            restock_expenses_vat=float(summary.restock_expenses_vat),
            restock_expenses_regular=float(summary.restock_expenses_regular),
            refunds_vat=float(summary.refunds_vat),
            refunds_regular=float(summary.refunds_regular),
            withdrawals_vat=float(summary.withdrawals_vat),
            withdrawals_regular=float(summary.withdrawals_regular),
            total_expenses_vat=float(summary.purchase_expenses_vat + summary.restock_expenses_vat + summary.refunds_vat + summary.withdrawals_vat),
            total_expenses_regular=float(summary.purchase_expenses_regular + summary.restock_expenses_regular + summary.refunds_regular + summary.withdrawals_regular),
            closing_balance_vat=float(summary.closing_balance_vat),
            closing_balance_regular=float(summary.closing_balance_regular),
            net_profit_vat=float(summary.net_profit_vat),
            net_profit_regular=float(summary.net_profit_regular),
            total_profit=float(summary.total_profit),
            created_at=summary.created_at
        ))
    
    return result