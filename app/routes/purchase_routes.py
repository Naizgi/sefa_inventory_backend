from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, date, timedelta
from decimal import Decimal
import uuid

from app.database import get_db
from app.models import (
    User, 
    Purchase as PurchaseModel, 
    PurchaseOrder, 
    PurchaseOrderItem, 
    PurchaseItem as PurchaseItemModel, 
    Product, 
    Stock, 
    StockMovement,
    BankAccount
)
from app.schemas import (
    PurchaseCreate, 
    Purchase as PurchaseSchema, 
    PurchaseOrderCreate, 
    PurchaseOrderResponse, 
    PurchaseOrderUpdate, 
    ReceivePurchaseOrder
)
from app.utils.dependencies import require_admin

# Import wallet functions
from app.routes.wallet import get_or_create_wallet, process_wallet_transaction
from app.models import WalletTransactionType

router = APIRouter(prefix="/api/purchases", tags=["Purchases"])

# Fixed VAT rate (can be changed via settings in the future)
DEFAULT_VAT_RATE = Decimal('15.00')

def generate_order_number():
    return f"PO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

def generate_transaction_number():
    """Generate a unique transaction number for wallet transactions"""
    return f"WT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

def calculate_purchase_totals(
    subtotal: Decimal, 
    vat_rate: Optional[Decimal] = None, 
    tax_amount: Decimal = Decimal('0'),
    shipping_cost: Decimal = Decimal('0'), 
    labour_cost: Decimal = Decimal('0'),
    other_cost: Decimal = Decimal('0')
) -> dict:
    """
    Calculate purchase order totals including VAT, shipping, labour, and other costs.
    """
    vat_amount = Decimal('0')
    actual_vat_rate = Decimal('0')
    
    if vat_rate is not None and vat_rate > 0:
        # Calculate VAT from rate
        actual_vat_rate = vat_rate
        vat_amount = subtotal * (vat_rate / Decimal('100'))
    elif tax_amount > 0:
        # Use provided tax amount
        vat_amount = tax_amount
        if subtotal > 0:
            actual_vat_rate = (tax_amount / subtotal) * Decimal('100')
    
    # Total = subtotal + VAT + shipping + labour + other
    total_amount = subtotal + vat_amount + shipping_cost + labour_cost + other_cost
    
    return {
        'subtotal': subtotal,
        'vat_rate': actual_vat_rate,
        'vat_amount': vat_amount,
        'total_amount': total_amount
    }

# ==================== MULTI-WALLET PROCESSING FUNCTION ====================
def process_multiple_wallet_allocations(
    db: Session,
    wallet_allocations: List[dict],
    branch_id: int,
    user_id: int,
    reference_type: str,
    reference_id: int,
    description_prefix: str = ""
) -> dict:
    """
    Process multiple wallet allocations for a purchase.
    Each allocation should have 'wallet_id' and 'amount'.
    Creates a separate transaction record for EACH wallet.
    Returns summary of processed allocations.
    """
    from app.models import Wallet, WalletTransaction
    
    results = []
    total_processed = Decimal('0')
    errors = []
    
    if not wallet_allocations:
        return {
            'success': False,
            'error': 'No wallet allocations provided',
            'results': []
        }
    
    print(f"📊 Processing {len(wallet_allocations)} wallet allocations...")
    
    for idx, allocation in enumerate(wallet_allocations):
        # Handle both dict and object formats
        if isinstance(allocation, dict):
            wallet_id = allocation.get('wallet_id')
            amount = allocation.get('amount')
        else:
            wallet_id = getattr(allocation, 'wallet_id', None)
            amount = getattr(allocation, 'amount', 0)
        
        print(f"   [{idx+1}] Wallet ID: {wallet_id}, Amount: {amount}")
        
        if not wallet_id:
            errors.append({'wallet_id': None, 'error': 'Wallet ID is required'})
            continue
            
        if not amount or amount <= 0:
            errors.append({'wallet_id': wallet_id, 'error': 'Amount must be greater than 0'})
            continue
            
        # Convert to Decimal
        amount = Decimal(str(amount))
        
        # Get wallet
        wallet = db.query(Wallet).filter(
            Wallet.id == wallet_id,
            Wallet.branch_id == branch_id,
            Wallet.is_active == True
        ).first()
        
        if not wallet:
            errors.append({
                'wallet_id': wallet_id,
                'error': f'Wallet not found or inactive'
            })
            continue
        
        # Check sufficient balance
        if wallet.balance < amount:
            errors.append({
                'wallet_id': wallet_id,
                'wallet_name': wallet.wallet_name,
                'error': f'Insufficient balance. Available: {float(wallet.balance)}, Required: {float(amount)}',
                'balance': float(wallet.balance),
                'required': float(amount)
            })
            continue
        
        # Save old balance before deduction
        old_balance = wallet.balance
        
        # Deduct from wallet
        wallet.balance -= amount
        
        # Generate unique transaction number for THIS wallet
        transaction_number = generate_transaction_number()
        
        # Create transaction record for THIS wallet
        description = f"{description_prefix} - {wallet.wallet_name}" if description_prefix else f"Payment from {wallet.wallet_name}"
        
        transaction = WalletTransaction(
            transaction_number=transaction_number,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.PURCHASE.value,
            transaction_method='wallet_payment',
            amount=amount,
            from_wallet_id=None,
            to_wallet_id=None,
            balance_before=old_balance,
            balance_after=wallet.balance,
            status='completed',
            approval_status='approved',
            approved_by=None,
            approved_at=None,
            reference_type=reference_type,
            reference_id=reference_id,
            reference_number=None,
            bank_transaction_id=None,
            bank_reference=None,
            bank_account_id=None,
            description=description,
            attachments=None,
            notes=None,
            created_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=None
        )
        db.add(transaction)
        
        # Flush to get the transaction ID
        db.flush()
        
        total_processed += amount
        
        # Store result for this wallet
        results.append({
            'wallet_id': wallet_id,
            'wallet_name': wallet.wallet_name,
            'amount': float(amount),
            'old_balance': float(old_balance),
            'new_balance': float(wallet.balance),
            'transaction_id': transaction.id,
            'transaction_number': transaction_number,
            'success': True
        })
        
        print(f"✅ Wallet deducted: {wallet.wallet_name} - Amount: {float(amount)} - Transaction: {transaction_number}")
    
    # Commit all transactions
    db.commit()
    
    # Check if any errors occurred
    if errors:
        return {
            'success': len(results) > 0,
            'partial_success': len(results) > 0,
            'total_processed': float(total_processed),
            'results': results,
            'errors': errors
        }
    
    print(f"✅ All {len(results)} wallet allocations processed successfully!")
    return {
        'success': True,
        'total_processed': float(total_processed),
        'results': results,
        'errors': []
    }

# ==================== LEGACY PURCHASE ROUTES ====================

@router.post("", response_model=PurchaseSchema, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=PurchaseSchema, status_code=status.HTTP_201_CREATED)
def create_purchase(
    purchase_data: PurchaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new purchase (legacy) with VAT tracking and wallet deduction"""
    
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    total_amount = Decimal('0')
    subtotal = Decimal('0')
    
    # Get VAT status from request (default to False if not specified)
    has_vat = getattr(purchase_data, 'with_vat', False)
    
    # Get additional costs
    shipping_cost = Decimal(str(purchase_data.shipping_cost)) if hasattr(purchase_data, 'shipping_cost') else Decimal('0')
    labour_cost = Decimal(str(purchase_data.labour_cost)) if hasattr(purchase_data, 'labour_cost') else Decimal('0')
    labour_cost_description = getattr(purchase_data, 'labour_cost_description', None)
    other_cost = Decimal(str(purchase_data.other_cost)) if hasattr(purchase_data, 'other_cost') else Decimal('0')
    other_cost_description = getattr(purchase_data, 'other_cost_description', None)
    
    # Create purchase
    purchase = PurchaseModel(
        branch_id=branch_id,
        supplier_name=purchase_data.supplier_name,
        subtotal=0,
        vat_amount=0,
        shipping_cost=shipping_cost,
        labour_cost=labour_cost,
        labour_cost_description=labour_cost_description,
        other_cost=other_cost,
        other_cost_description=other_cost_description,
        total_amount=0,
    )
    db.add(purchase)
    db.flush()
    
    # Add items and calculate total
    for item_data in purchase_data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
        
        # Convert to Decimal to handle fractions
        quantity = Decimal(str(item_data.quantity))
        unit_cost = Decimal(str(item_data.unit_cost))
        item_total = quantity * unit_cost
        subtotal += item_total
        
        purchase_item = PurchaseItemModel(
            purchase_id=purchase.id,
            product_id=item_data.product_id,
            quantity=quantity,
            unit_cost=unit_cost
        )
        db.add(purchase_item)
        
        # Update stock with VAT tracking
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == item_data.product_id
        ).first()
        
        if stock:
            stock.quantity += quantity
            # Update VAT-specific quantities
            if has_vat:
                stock.quantity_with_vat = (stock.quantity_with_vat or Decimal('0')) + quantity
            else:
                stock.quantity_without_vat = (stock.quantity_without_vat or Decimal('0')) + quantity
        else:
            stock = Stock(
                branch_id=branch_id,
                product_id=item_data.product_id,
                quantity=quantity,
                quantity_with_vat=quantity if has_vat else Decimal('0'),
                quantity_without_vat=quantity if not has_vat else Decimal('0'),
                reorder_level=0
            )
            db.add(stock)
        
        # Record stock movement with VAT info
        vat_status = "with VAT" if has_vat else "without VAT"
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=item_data.product_id,
            user_id=current_user.id,
            change_qty=quantity,
            movement_type="purchase",
            reference_id=purchase.id,
            notes=f"Purchase from {purchase_data.supplier_name} - {vat_status}"
        )
        if hasattr(stock_movement, 'with_vat'):
            stock_movement.with_vat = has_vat
        db.add(stock_movement)
    
    # Calculate VAT
    vat_rate = Decimal(str(getattr(purchase_data, 'vat_rate', 15)))
    vat_amount = subtotal * (vat_rate / Decimal('100'))
    purchase.vat_amount = vat_amount
    
    # Update purchase with calculated values
    purchase.subtotal = subtotal
    purchase.total_amount = subtotal + vat_amount + shipping_cost + labour_cost + other_cost
    
    db.commit()
    db.refresh(purchase)
    
    # ==================== DEDUCT FROM WALLET ====================
    try:
        # Determine which wallet to use (regular wallet for purchases)
        wallet = get_or_create_wallet(db, branch_id, "regular")
        
        # Process wallet transaction (deduct amount)
        transaction = process_wallet_transaction(
            db=db,
            wallet_id=wallet.id,
            transaction_type=WalletTransactionType.PURCHASE.value,
            amount=purchase.total_amount,
            description=f"Purchase from {purchase_data.supplier_name} - #{purchase.id}",
            user_id=current_user.id,
            reference_type="purchase",
            reference_id=purchase.id
        )
        print(f"✅ Wallet deducted: {transaction.transaction_number} - Amount: {purchase.total_amount}")
    except Exception as wallet_error:
        print(f"⚠️ Wallet deduction failed: {wallet_error}")
        # Don't fail the purchase if wallet deduction fails, just log it
    
    return PurchaseSchema.model_validate(purchase)

@router.get("", response_model=List[PurchaseSchema])
@router.get("/", response_model=List[PurchaseSchema])
def get_purchases(
    supplier: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get all purchases"""
    query = db.query(PurchaseModel)
    
    if supplier:
        query = query.filter(PurchaseModel.supplier_name.ilike(f"%{supplier}%"))
    if from_date:
        start_date = datetime.combine(from_date, datetime.min.time())
        query = query.filter(PurchaseModel.created_at >= start_date)
    if to_date:
        end_date = datetime.combine(to_date, datetime.max.time())
        query = query.filter(PurchaseModel.created_at <= end_date)
    
    purchases = query.order_by(PurchaseModel.created_at.desc()).offset(skip).limit(limit).all()
    return [PurchaseSchema.model_validate(p) for p in purchases]

# ==================== PURCHASE ORDER ROUTES ====================

@router.post("/orders", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
@router.post("/orders/", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(
    purchase_data: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new purchase order with VAT, shipping, labour, other costs, and multi-wallet payment"""
    
    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    # Calculate subtotal from items (supporting decimal quantities)
    subtotal = Decimal('0')
    for item in purchase_data.items:
        quantity = Decimal(str(item.quantity_ordered))
        cost = Decimal(str(item.unit_cost))
        item_total = quantity * cost
        subtotal += item_total
    
    # Get VAT parameters
    vat_rate = None
    tax_amount = Decimal('0')
    
    # Check for vat_rate in request
    if hasattr(purchase_data, 'vat_rate') and purchase_data.vat_rate is not None:
        vat_rate = Decimal(str(purchase_data.vat_rate))
    # Check for tax_amount in request (legacy)
    elif hasattr(purchase_data, 'tax_amount') and purchase_data.tax_amount > 0:
        tax_amount = Decimal(str(purchase_data.tax_amount))
    
    # Get all costs
    shipping_cost = Decimal(str(purchase_data.shipping_cost)) if hasattr(purchase_data, 'shipping_cost') else Decimal('0')
    labour_cost = Decimal(str(purchase_data.labour_cost)) if hasattr(purchase_data, 'labour_cost') else Decimal('0')
    labour_cost_description = getattr(purchase_data, 'labour_cost_description', None)
    other_cost = Decimal(str(purchase_data.other_cost)) if hasattr(purchase_data, 'other_cost') else Decimal('0')
    other_cost_description = getattr(purchase_data, 'other_cost_description', None)
    
    # Calculate totals with VAT and all costs
    totals = calculate_purchase_totals(subtotal, vat_rate, tax_amount, shipping_cost, labour_cost, other_cost)
    
    # Check if using wallet payment
    use_wallet_payment = getattr(purchase_data, 'use_wallet_payment', False)
    
    # ============ IMPORTANT: Get wallet_allocations from request ============
    wallet_allocations = []
    
    # Try to get wallet_allocations from the request data
    if hasattr(purchase_data, 'wallet_allocations') and purchase_data.wallet_allocations:
        for alloc in purchase_data.wallet_allocations:
            if hasattr(alloc, 'dict'):
                # If it's a Pydantic model
                wallet_allocations.append(alloc.dict())
            elif isinstance(alloc, dict):
                # If it's already a dict
                wallet_allocations.append(alloc)
            else:
                # Try to access as object attributes
                wallet_allocations.append({
                    'wallet_id': getattr(alloc, 'wallet_id', None),
                    'amount': getattr(alloc, 'amount', 0)
                })
    
    # Also check if wallet_id is provided (backward compatibility)
    wallet_id = getattr(purchase_data, 'wallet_id', None)
    
    print(f"📊 Received wallet_allocations: {wallet_allocations}")
    print(f"📊 Received wallet_id: {wallet_id}")
    print(f"📊 use_wallet_payment: {use_wallet_payment}")
    
    # ==================== VALIDATE WALLET ALLOCATIONS ====================
    total_allocated = Decimal('0')
    
    if use_wallet_payment:
        # If using old single wallet_id, convert to wallet_allocations
        if wallet_id and not wallet_allocations:
            wallet_allocations = [{'wallet_id': wallet_id, 'amount': float(totals['total_amount'])}]
            print(f"📊 Converted single wallet to allocation: {wallet_allocations}")
        
        # Validate wallet allocations
        if not wallet_allocations:
            raise HTTPException(
                status_code=400, 
                detail="Wallet payment selected but no wallet allocations provided"
            )
        
        # Process allocations for validation only (don't deduct yet)
        from app.models import Wallet
        total_allocated = Decimal('0')
        
        for allocation in wallet_allocations:
            # Handle both dict and object
            if isinstance(allocation, dict):
                alloc_wallet_id = allocation.get('wallet_id')
                amount = allocation.get('amount')
            else:
                alloc_wallet_id = getattr(allocation, 'wallet_id', None)
                amount = getattr(allocation, 'amount', 0)
            
            if not alloc_wallet_id:
                raise HTTPException(status_code=400, detail="Wallet ID is required for each allocation")
            
            if not amount or amount <= 0:
                raise HTTPException(status_code=400, detail="Amount must be greater than 0 for each allocation")
            
            amount = Decimal(str(amount))
            total_allocated += amount
            
            # Check if wallet exists and has sufficient balance
            wallet = db.query(Wallet).filter(
                Wallet.id == alloc_wallet_id,
                Wallet.branch_id == current_user.branch_id,
                Wallet.is_active == True
            ).first()
            
            if not wallet:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Wallet {alloc_wallet_id} not found or inactive"
                )
            
            if wallet.balance < amount:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Insufficient balance in wallet '{wallet.wallet_name}'. "
                           f"Available: {float(wallet.balance)}, Required: {float(amount)}"
                )
        
        # Check if total allocated matches total amount
        if abs(total_allocated - totals['total_amount']) > Decimal('0.01'):
            raise HTTPException(
                status_code=400, 
                detail=f"Total allocated ({float(total_allocated)}) does not match total amount ({float(totals['total_amount'])})"
            )
    
    # Get bank account info if not using wallet payment
    bank_account_name = None
    bank_name = None
    if not use_wallet_payment and hasattr(purchase_data, 'bank_account_id') and purchase_data.bank_account_id:
        bank_account = db.query(BankAccount).filter(
            BankAccount.id == purchase_data.bank_account_id,
            BankAccount.branch_id == current_user.branch_id,
            BankAccount.is_active == True
        ).first()
        if not bank_account:
            raise HTTPException(status_code=404, detail="Bank account not found or inactive")
        bank_account_name = bank_account.account_name
        bank_name = bank_account.bank_name
    
    # Create purchase order with all costs and payment fields
    purchase_order = PurchaseOrder(
        order_number=generate_order_number(),
        branch_id=current_user.branch_id,
        supplier=purchase_data.supplier,
        expected_delivery_date=purchase_data.expected_delivery_date,
        subtotal=totals['subtotal'],
        vat_rate=totals['vat_rate'],
        vat_amount=totals['vat_amount'],
        tax_amount=totals['vat_amount'],
        shipping_cost=shipping_cost,
        labour_cost=labour_cost,
        labour_cost_description=labour_cost_description,
        other_cost=other_cost,
        other_cost_description=other_cost_description,
        total_amount=totals['total_amount'],
        notes=purchase_data.notes,
        created_by=current_user.id,
        status='pending',
        # Payment fields
        bank_account_id=purchase_data.bank_account_id if not use_wallet_payment else None,
        payment_reference=getattr(purchase_data, 'payment_reference', None),
        payment_date=datetime.combine(purchase_data.payment_date, datetime.min.time()) if hasattr(purchase_data, 'payment_date') and purchase_data.payment_date else None,
        # Wallet payment tracking
        use_wallet_payment=use_wallet_payment,
        wallet_id=None  # We'll store the first wallet ID for backward compatibility
    )
    
    db.add(purchase_order)
    db.flush()
    
    # Add items (supporting decimal quantities)
    for item_data in purchase_data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
        
        quantity = Decimal(str(item_data.quantity_ordered))
        cost = Decimal(str(item_data.unit_cost))
        
        purchase_item = PurchaseOrderItem(
            purchase_order_id=purchase_order.id,
            product_id=item_data.product_id,
            quantity_ordered=quantity,
            unit_cost=cost,
            total_cost=quantity * cost,
            notes=item_data.notes
        )
        db.add(purchase_item)
    
    db.commit()
    db.refresh(purchase_order)
    
    # ==================== DEDUCT FROM MULTIPLE WALLETS ====================
    wallet_transactions = []
    if use_wallet_payment and wallet_allocations:
        try:
            print(f"📊 Starting wallet deduction for {len(wallet_allocations)} wallets...")
            
            # Process all wallet allocations - creates separate transaction for EACH wallet
            result = process_multiple_wallet_allocations(
                db=db,
                wallet_allocations=wallet_allocations,
                branch_id=current_user.branch_id,
                user_id=current_user.id,
                reference_type="purchase_order",
                reference_id=purchase_order.id,
                description_prefix=f"Purchase Order: {purchase_order.order_number} - Supplier: {purchase_data.supplier}"
            )
            
            if result['success']:
                wallet_transactions = result['results']
                # Store the first wallet ID for backward compatibility
                if wallet_transactions:
                    purchase_order.wallet_id = wallet_transactions[0]['wallet_id']
                    purchase_order.wallet_transaction_id = wallet_transactions[0].get('transaction_id')
                
                # Log all successful transactions
                print(f"\n✅ Multi-wallet deduction completed for PO #{purchase_order.order_number}")
                print(f"   Total wallets: {len(wallet_transactions)}")
                for txn in wallet_transactions:
                    print(f"   💳 {txn['wallet_name']}: {txn['amount']} (Transaction: {txn['transaction_number']})")
                
                db.commit()
            else:
                # If no success and there are errors, raise exception
                error_messages = [e.get('error', 'Unknown error') for e in result.get('errors', [])]
                raise HTTPException(
                    status_code=400, 
                    detail=f"Wallet deduction failed: {'; '.join(error_messages)}"
                )
                
        except HTTPException:
            raise
        except Exception as wallet_error:
            print(f"⚠️ Wallet deduction failed for PO #{purchase_order.order_number}: {wallet_error}")
            import traceback
            traceback.print_exc()
            # Re-raise to prevent order creation if wallet deduction fails
            raise HTTPException(status_code=400, detail=f"Wallet deduction failed: {str(wallet_error)}")
    
    creator = db.query(User).filter(User.id == purchase_order.created_by).first()
    creator_name = creator.name if creator else "System"
    
    items_response = []
    for item in purchase_order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items_response.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.name if product else None,
            "quantity_ordered": float(item.quantity_ordered),
            "unit_cost": float(item.unit_cost),
            "notes": item.notes,
            "quantity_received": float(item.quantity_received),
            "total_cost": float(item.total_cost),
            "received_at": item.received_at
        })
    
    return {
        "id": purchase_order.id,
        "order_number": purchase_order.order_number,
        "branch_id": purchase_order.branch_id,
        "supplier": purchase_order.supplier,
        "expected_delivery_date": purchase_order.expected_delivery_date,
        "order_date": purchase_order.order_date,
        "actual_delivery_date": purchase_order.actual_delivery_date,
        "status": purchase_order.status,
        "subtotal": float(purchase_order.subtotal),
        "vat_rate": float(purchase_order.vat_rate) if purchase_order.vat_rate else 0,
        "vat_amount": float(purchase_order.vat_amount) if purchase_order.vat_amount else 0,
        "tax_amount": float(purchase_order.tax_amount),
        "shipping_cost": float(purchase_order.shipping_cost),
        "labour_cost": float(purchase_order.labour_cost),
        "labour_cost_description": purchase_order.labour_cost_description,
        "other_cost": float(purchase_order.other_cost),
        "other_cost_description": purchase_order.other_cost_description,
        "total_amount": float(purchase_order.total_amount),
        "notes": purchase_order.notes,
        "created_by": creator_name,
        "created_at": purchase_order.created_at,
        "updated_at": purchase_order.updated_at,
        "items": items_response,
        "bank_account_id": purchase_order.bank_account_id,
        "bank_account_name": bank_account_name,
        "bank_name": bank_name,
        "payment_reference": purchase_order.payment_reference,
        "payment_date": purchase_order.payment_date,
        "use_wallet_payment": purchase_order.use_wallet_payment,
        "wallet_id": purchase_order.wallet_id,
        "wallet_transactions": wallet_transactions,
        "wallet_transaction_id": purchase_order.wallet_transaction_id
    }

@router.get("/orders", response_model=List[PurchaseOrderResponse])
@router.get("/orders/", response_model=List[PurchaseOrderResponse])
def get_purchase_orders(
    supplier: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get all purchase orders with VAT, costs, and payment information"""
    
    try:
        query = db.query(PurchaseOrder)
        
        if supplier:
            query = query.filter(PurchaseOrder.supplier.ilike(f"%{supplier}%"))
        if status:
            query = query.filter(PurchaseOrder.status == status)
        if from_date:
            start_date = datetime.combine(from_date, datetime.min.time())
            query = query.filter(PurchaseOrder.order_date >= start_date)
        if to_date:
            end_date = datetime.combine(to_date, datetime.max.time())
            query = query.filter(PurchaseOrder.order_date <= end_date)
        
        orders = query.order_by(PurchaseOrder.order_date.desc()).offset(skip).limit(limit).all()
        
        result = []
        for order in orders:
            creator = db.query(User).filter(User.id == order.created_by).first()
            creator_name = creator.name if creator else "System"
            
            # Get bank account info if exists
            bank_account_name = None
            bank_name = None
            if not order.use_wallet_payment and order.bank_account_id:
                bank_account = db.query(BankAccount).filter(BankAccount.id == order.bank_account_id).first()
                if bank_account:
                    bank_account_name = bank_account.account_name
                    bank_name = bank_account.bank_name
            
            # Get wallet info if using wallet payment
            wallet_name = None
            if order.use_wallet_payment and order.wallet_id:
                from app.models import Wallet
                wallet = db.query(Wallet).filter(Wallet.id == order.wallet_id).first()
                if wallet:
                    wallet_name = wallet.wallet_name
            
            # Get all wallet transactions for this order
            wallet_transactions = []
            if order.use_wallet_payment:
                from app.models import WalletTransaction
                transactions = db.query(WalletTransaction).filter(
                    WalletTransaction.reference_type == "purchase_order",
                    WalletTransaction.reference_id == order.id
                ).all()
                for txn in transactions:
                    wallet = db.query(Wallet).filter(Wallet.id == txn.wallet_id).first()
                    wallet_transactions.append({
                        "wallet_id": txn.wallet_id,
                        "wallet_name": wallet.wallet_name if wallet else "Unknown",
                        "amount": float(txn.amount),
                        "balance_before": float(txn.balance_before) if hasattr(txn, 'balance_before') else None,
                        "balance_after": float(txn.balance_after),
                        "transaction_number": txn.transaction_number if hasattr(txn, 'transaction_number') else None,
                        "created_at": txn.created_at.isoformat() if hasattr(txn, 'created_at') and txn.created_at else None
                    })
            
            items_response = []
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                items_response.append({
                    "id": item.id,
                    "product_id": item.product_id,
                    "product_name": product.name if product else None,
                    "quantity_ordered": float(item.quantity_ordered),
                    "unit_cost": float(item.unit_cost),
                    "notes": item.notes,
                    "quantity_received": float(item.quantity_received),
                    "total_cost": float(item.total_cost),
                    "received_at": item.received_at
                })
            
            result.append({
                "id": order.id,
                "order_number": order.order_number,
                "branch_id": order.branch_id,
                "supplier": order.supplier,
                "expected_delivery_date": order.expected_delivery_date,
                "order_date": order.order_date,
                "actual_delivery_date": order.actual_delivery_date,
                "status": order.status,
                "subtotal": float(order.subtotal),
                "vat_rate": float(order.vat_rate) if order.vat_rate else 0,
                "vat_amount": float(order.vat_amount) if order.vat_amount else 0,
                "tax_amount": float(order.tax_amount),
                "shipping_cost": float(order.shipping_cost),
                "labour_cost": float(order.labour_cost),
                "labour_cost_description": order.labour_cost_description,
                "other_cost": float(order.other_cost),
                "other_cost_description": order.other_cost_description,
                "total_amount": float(order.total_amount),
                "notes": order.notes,
                "created_by": creator_name,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "items": items_response,
                "bank_account_id": order.bank_account_id,
                "bank_account_name": bank_account_name,
                "bank_name": bank_name,
                "payment_reference": order.payment_reference,
                "payment_date": order.payment_date,
                "use_wallet_payment": order.use_wallet_payment,
                "wallet_id": order.wallet_id,
                "wallet_name": wallet_name,
                "wallet_transactions": wallet_transactions,
                "wallet_transaction_id": order.wallet_transaction_id
            })
        
        return result
        
    except Exception as e:
        print(f"Error in get_purchase_orders: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching purchase orders: {str(e)}")

@router.get("/orders/{order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get purchase order by ID with VAT, costs, and payment information"""
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    creator = db.query(User).filter(User.id == order.created_by).first()
    creator_name = creator.name if creator else "System"
    
    # Get bank account info if exists
    bank_account_name = None
    bank_name = None
    if not order.use_wallet_payment and order.bank_account_id:
        bank_account = db.query(BankAccount).filter(BankAccount.id == order.bank_account_id).first()
        if bank_account:
            bank_account_name = bank_account.account_name
            bank_name = bank_account.bank_name
    
    # Get wallet info if using wallet payment
    wallet_name = None
    wallet_transactions = []
    if order.use_wallet_payment:
        from app.models import Wallet, WalletTransaction
        if order.wallet_id:
            wallet = db.query(Wallet).filter(Wallet.id == order.wallet_id).first()
            if wallet:
                wallet_name = wallet.wallet_name
        
        # Get all wallet transactions for this order
        transactions = db.query(WalletTransaction).filter(
            WalletTransaction.reference_type == "purchase_order",
            WalletTransaction.reference_id == order.id
        ).all()
        for txn in transactions:
            wallet = db.query(Wallet).filter(Wallet.id == txn.wallet_id).first()
            wallet_transactions.append({
                "wallet_id": txn.wallet_id,
                "wallet_name": wallet.wallet_name if wallet else "Unknown",
                "amount": float(txn.amount),
                "balance_before": float(txn.balance_before) if hasattr(txn, 'balance_before') else None,
                "balance_after": float(txn.balance_after),
                "transaction_number": txn.transaction_number if hasattr(txn, 'transaction_number') else None,
                "created_at": txn.created_at.isoformat() if hasattr(txn, 'created_at') and txn.created_at else None
            })
    
    items_response = []
    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items_response.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.name if product else None,
            "quantity_ordered": float(item.quantity_ordered),
            "unit_cost": float(item.unit_cost),
            "notes": item.notes,
            "quantity_received": float(item.quantity_received),
            "total_cost": float(item.total_cost),
            "received_at": item.received_at
        })
    
    return {
        "id": order.id,
        "order_number": order.order_number,
        "branch_id": order.branch_id,
        "supplier": order.supplier,
        "expected_delivery_date": order.expected_delivery_date,
        "order_date": order.order_date,
        "actual_delivery_date": order.actual_delivery_date,
        "status": order.status,
        "subtotal": float(order.subtotal),
        "vat_rate": float(order.vat_rate) if order.vat_rate else 0,
        "vat_amount": float(order.vat_amount) if order.vat_amount else 0,
        "tax_amount": float(order.tax_amount),
        "shipping_cost": float(order.shipping_cost),
        "labour_cost": float(order.labour_cost),
        "labour_cost_description": order.labour_cost_description,
        "other_cost": float(order.other_cost),
        "other_cost_description": order.other_cost_description,
        "total_amount": float(order.total_amount),
        "notes": order.notes,
        "created_by": creator_name,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "items": items_response,
        "bank_account_id": order.bank_account_id,
        "bank_account_name": bank_account_name,
        "bank_name": bank_name,
        "payment_reference": order.payment_reference,
        "payment_date": order.payment_date,
        "use_wallet_payment": order.use_wallet_payment,
        "wallet_id": order.wallet_id,
        "wallet_name": wallet_name,
        "wallet_transactions": wallet_transactions,
        "wallet_transaction_id": order.wallet_transaction_id
    }

@router.post("/orders/{order_id}/receive")
def receive_purchase_order(
    order_id: int,
    receive_data: ReceivePurchaseOrder,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Receive items from purchase order and update inventory with VAT tracking"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if purchase_order.status == "completed":
        raise HTTPException(status_code=400, detail="Purchase order already completed")
    
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    received_items = []
    
    # Determine if this purchase has VAT
    has_vat = purchase_order.vat_rate and purchase_order.vat_rate > 0
    
    # Calculate total cost of received items
    total_received_cost = Decimal('0')
    
    for receive_item in receive_data.items:
        purchase_item = db.query(PurchaseOrderItem).filter(
            PurchaseOrderItem.purchase_order_id == order_id,
            PurchaseOrderItem.product_id == receive_item.product_id
        ).first()
        
        if not purchase_item:
            raise HTTPException(
                status_code=404, 
                detail=f"Product ID {receive_item.product_id} not found in purchase order"
            )
        
        quantity_received = Decimal(str(receive_item.quantity_received))
        new_received = purchase_item.quantity_received + quantity_received
        
        if new_received > purchase_item.quantity_ordered:
            remaining = purchase_item.quantity_ordered - purchase_item.quantity_received
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot receive {quantity_received} units. Only {remaining} units remaining."
            )
        
        purchase_item.quantity_received = new_received
        purchase_item.received_at = datetime.now()
        
        # Calculate cost for this item
        item_cost = quantity_received * purchase_item.unit_cost
        total_received_cost += item_cost
        
        product = db.query(Product).filter(Product.id == purchase_item.product_id).first()
        
        # Get existing stock
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == purchase_item.product_id
        ).first()
        
        if stock:
            # Update stock quantities
            stock.quantity += quantity_received
            
            # Update VAT-specific quantities based on purchase order's VAT status
            if has_vat:
                stock.quantity_with_vat = (stock.quantity_with_vat or Decimal('0')) + quantity_received
            else:
                stock.quantity_without_vat = (stock.quantity_without_vat or Decimal('0')) + quantity_received
                
        else:
            # Create new stock record
            stock = Stock(
                branch_id=branch_id,
                product_id=purchase_item.product_id,
                quantity=quantity_received,
                quantity_with_vat=quantity_received if has_vat else Decimal('0'),
                quantity_without_vat=quantity_received if not has_vat else Decimal('0'),
                reorder_level=0
            )
            db.add(stock)
        
        # Record stock movement with VAT info
        vat_status = "with VAT" if has_vat else "without VAT"
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=purchase_item.product_id,
            user_id=current_user.id,
            change_qty=quantity_received,
            movement_type="purchase",
            reference_id=purchase_order.id,
            notes=f"Received from PO: {purchase_order.order_number} - {vat_status}"
        )
        if hasattr(stock_movement, 'with_vat'):
            stock_movement.with_vat = has_vat
        db.add(stock_movement)
        
        received_items.append({
            "product_id": purchase_item.product_id,
            "product_name": product.name if product else "Unknown",
            "quantity_received": float(quantity_received),
            "unit_cost": float(purchase_item.unit_cost),
            "total_cost": float(item_cost),
            "branch_id": branch_id,
            "with_vat": has_vat
        })
    
    all_items_received = all(
        item.quantity_received >= item.quantity_ordered 
        for item in purchase_order.items
    )
    
    purchase_order.status = "completed" if all_items_received else "partially_received"
    purchase_order.actual_delivery_date = datetime.combine(receive_data.actual_delivery_date, datetime.min.time())
    purchase_order.updated_at = datetime.now()
    
    db.commit()
    
    return {
        "success": True,
        "message": "Purchase order received successfully",
        "status": purchase_order.status,
        "order_number": purchase_order.order_number,
        "branch_id": branch_id,
        "has_vat": has_vat,
        "received_items": received_items,
        "total_items_received": len(received_items),
        "total_amount": float(total_received_cost)
    }

@router.put("/orders/{order_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(
    order_id: int,
    update_data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update purchase order status and costs"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if update_data.status:
        purchase_order.status = update_data.status
    if update_data.actual_delivery_date:
        purchase_order.actual_delivery_date = datetime.combine(update_data.actual_delivery_date, datetime.min.time())
    if update_data.notes:
        purchase_order.notes = update_data.notes
    
    # Update costs if provided
    if update_data.shipping_cost is not None:
        purchase_order.shipping_cost = Decimal(str(update_data.shipping_cost))
    if update_data.labour_cost is not None:
        purchase_order.labour_cost = Decimal(str(update_data.labour_cost))
    if update_data.labour_cost_description is not None:
        purchase_order.labour_cost_description = update_data.labour_cost_description
    if update_data.other_cost is not None:
        purchase_order.other_cost = Decimal(str(update_data.other_cost))
    if update_data.other_cost_description is not None:
        purchase_order.other_cost_description = update_data.other_cost_description
    
    if update_data.bank_account_id is not None:
        purchase_order.bank_account_id = update_data.bank_account_id
    if update_data.payment_reference is not None:
        purchase_order.payment_reference = update_data.payment_reference
    if update_data.payment_date is not None:
        purchase_order.payment_date = datetime.combine(update_data.payment_date, datetime.min.time())
    
    purchase_order.updated_at = datetime.now()
    db.commit()
    db.refresh(purchase_order)
    
    creator = db.query(User).filter(User.id == purchase_order.created_by).first()
    creator_name = creator.name if creator else "System"
    
    # Get bank account info if exists
    bank_account_name = None
    bank_name = None
    if not purchase_order.use_wallet_payment and purchase_order.bank_account_id:
        bank_account = db.query(BankAccount).filter(BankAccount.id == purchase_order.bank_account_id).first()
        if bank_account:
            bank_account_name = bank_account.account_name
            bank_name = bank_account.bank_name
    
    # Get wallet info if using wallet payment
    wallet_name = None
    wallet_transactions = []
    if purchase_order.use_wallet_payment:
        from app.models import Wallet, WalletTransaction
        if purchase_order.wallet_id:
            wallet = db.query(Wallet).filter(Wallet.id == purchase_order.wallet_id).first()
            if wallet:
                wallet_name = wallet.wallet_name
        
        # Get all wallet transactions for this order
        transactions = db.query(WalletTransaction).filter(
            WalletTransaction.reference_type == "purchase_order",
            WalletTransaction.reference_id == purchase_order.id
        ).all()
        for txn in transactions:
            wallet = db.query(Wallet).filter(Wallet.id == txn.wallet_id).first()
            wallet_transactions.append({
                "wallet_id": txn.wallet_id,
                "wallet_name": wallet.wallet_name if wallet else "Unknown",
                "amount": float(txn.amount),
                "balance_before": float(txn.balance_before) if hasattr(txn, 'balance_before') else None,
                "balance_after": float(txn.balance_after),
                "transaction_number": txn.transaction_number if hasattr(txn, 'transaction_number') else None,
                "created_at": txn.created_at.isoformat() if hasattr(txn, 'created_at') and txn.created_at else None
            })
    
    items_response = []
    for item in purchase_order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items_response.append({
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.name if product else None,
            "quantity_ordered": float(item.quantity_ordered),
            "unit_cost": float(item.unit_cost),
            "notes": item.notes,
            "quantity_received": float(item.quantity_received),
            "total_cost": float(item.total_cost),
            "received_at": item.received_at
        })
    
    return {
        "id": purchase_order.id,
        "order_number": purchase_order.order_number,
        "branch_id": purchase_order.branch_id,
        "supplier": purchase_order.supplier,
        "expected_delivery_date": purchase_order.expected_delivery_date,
        "order_date": purchase_order.order_date,
        "actual_delivery_date": purchase_order.actual_delivery_date,
        "status": purchase_order.status,
        "subtotal": float(purchase_order.subtotal),
        "vat_rate": float(purchase_order.vat_rate) if purchase_order.vat_rate else 0,
        "vat_amount": float(purchase_order.vat_amount) if purchase_order.vat_amount else 0,
        "tax_amount": float(purchase_order.tax_amount),
        "shipping_cost": float(purchase_order.shipping_cost),
        "labour_cost": float(purchase_order.labour_cost),
        "labour_cost_description": purchase_order.labour_cost_description,
        "other_cost": float(purchase_order.other_cost),
        "other_cost_description": purchase_order.other_cost_description,
        "total_amount": float(purchase_order.total_amount),
        "notes": purchase_order.notes,
        "created_by": creator_name,
        "created_at": purchase_order.created_at,
        "updated_at": purchase_order.updated_at,
        "items": items_response,
        "bank_account_id": purchase_order.bank_account_id,
        "bank_account_name": bank_account_name,
        "bank_name": bank_name,
        "payment_reference": purchase_order.payment_reference,
        "payment_date": purchase_order.payment_date,
        "use_wallet_payment": purchase_order.use_wallet_payment,
        "wallet_id": purchase_order.wallet_id,
        "wallet_name": wallet_name,
        "wallet_transactions": wallet_transactions,
        "wallet_transaction_id": purchase_order.wallet_transaction_id
    }

@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_purchase_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a purchase order (Admin only)"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if purchase_order.status != "pending":
        raise HTTPException(status_code=400, detail="Cannot delete non-pending purchase orders")
    
    db.delete(purchase_order)
    db.commit()
    
    return None

# ==================== REPORTS ROUTE ====================

@router.get("/reports")
@router.get("/reports/")
def get_purchase_report(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get purchase report with VAT, shipping, labour, other costs, and payment information"""
    
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=30)
    
    start_date = datetime.combine(from_date, datetime.min.time())
    end_date = datetime.combine(to_date, datetime.max.time())
    
    purchase_orders = db.query(PurchaseOrder).filter(
        PurchaseOrder.order_date.between(start_date, end_date)
    ).all()
    
    purchases = db.query(PurchaseModel).filter(
        PurchaseModel.created_at.between(start_date, end_date)
    ).all()
    
    total_purchase_cost = sum(po.total_amount for po in purchase_orders)
    total_vat_amount = sum(po.vat_amount for po in purchase_orders if po.vat_amount)
    total_shipping_cost = sum(po.shipping_cost for po in purchase_orders)
    total_labour_cost = sum(po.labour_cost for po in purchase_orders)
    total_other_cost = sum(po.other_cost for po in purchase_orders)
    total_legacy_cost = sum(p.total_amount for p in purchases)
    
    # Payment method summary
    wallet_payment_total = sum(po.total_amount for po in purchase_orders if po.use_wallet_payment)
    bank_payment_total = sum(po.total_amount for po in purchase_orders if not po.use_wallet_payment and po.bank_account_id)
    cash_payment_total = sum(po.total_amount for po in purchase_orders if not po.use_wallet_payment and not po.bank_account_id)
    
    # Bank account summary (only for non-wallet payments)
    bank_account_summary = {}
    for po in purchase_orders:
        if not po.use_wallet_payment and po.bank_account_id:
            bank_account = db.query(BankAccount).filter(BankAccount.id == po.bank_account_id).first()
            if bank_account:
                key = f"{bank_account.bank_name} - {bank_account.account_number}"
                if key not in bank_account_summary:
                    bank_account_summary[key] = {
                        "bank_name": bank_account.bank_name,
                        "account_number": bank_account.account_number,
                        "account_name": bank_account.account_name,
                        "total_amount": 0,
                        "order_count": 0
                    }
                bank_account_summary[key]["total_amount"] += float(po.total_amount)
                bank_account_summary[key]["order_count"] += 1
    
    supplier_totals = {}
    for po in purchase_orders:
        supplier_totals[po.supplier] = supplier_totals.get(po.supplier, 0) + po.total_amount
    for p in purchases:
        if p.supplier_name:
            supplier_totals[p.supplier_name] = supplier_totals.get(p.supplier_name, 0) + p.total_amount
    
    top_items = db.query(
        PurchaseOrderItem.product_id,
        Product.name,
        func.sum(PurchaseOrderItem.quantity_received).label('total_quantity'),
        func.sum(PurchaseOrderItem.total_cost).label('total_cost')
    ).join(
        Product, PurchaseOrderItem.product_id == Product.id
    ).join(
        PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id
    ).filter(
        PurchaseOrder.order_date.between(start_date, end_date),
        PurchaseOrder.status == 'completed'
    ).group_by(
        PurchaseOrderItem.product_id, Product.name
    ).order_by(
        func.sum(PurchaseOrderItem.total_cost).desc()
    ).limit(10).all()
    
    return {
        "date_range": {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat()
        },
        "summary": {
            "total_purchase_orders": len(purchase_orders),
            "total_purchase_cost": float(total_purchase_cost),
            "total_vat_amount": float(total_vat_amount),
            "total_shipping_cost": float(total_shipping_cost),
            "total_labour_cost": float(total_labour_cost),
            "total_other_cost": float(total_other_cost),
            "total_legacy_purchases": len(purchases),
            "total_legacy_cost": float(total_legacy_cost),
            "total_all_purchases": float(total_purchase_cost + total_legacy_cost),
            "average_order_value": float(total_purchase_cost / len(purchase_orders)) if purchase_orders else 0,
            "average_shipping_cost": float(total_shipping_cost / len(purchase_orders)) if purchase_orders else 0,
            "average_labour_cost": float(total_labour_cost / len(purchase_orders)) if purchase_orders else 0,
            "average_other_cost": float(total_other_cost / len(purchase_orders)) if purchase_orders else 0
        },
        "payment_summary": {
            "wallet_payments": float(wallet_payment_total),
            "bank_payments": float(bank_payment_total),
            "cash_payments": float(cash_payment_total),
            "wallet_order_count": sum(1 for po in purchase_orders if po.use_wallet_payment),
            "bank_order_count": sum(1 for po in purchase_orders if not po.use_wallet_payment and po.bank_account_id),
            "cash_order_count": sum(1 for po in purchase_orders if not po.use_wallet_payment and not po.bank_account_id)
        },
        "bank_account_summary": [
            {
                "bank_name": data["bank_name"],
                "account_number": data["account_number"],
                "account_name": data["account_name"],
                "total_amount": data["total_amount"],
                "order_count": data["order_count"]
            }
            for data in bank_account_summary.values()
        ],
        "supplier_breakdown": [
            {"supplier": supplier, "total_amount": float(amount)}
            for supplier, amount in sorted(supplier_totals.items(), key=lambda x: x[1], reverse=True)
        ],
        "top_items": [
            {
                "product_id": item.product_id,
                "product_name": item.name,
                "quantity": float(item.total_quantity),
                "total_cost": float(item.total_cost),
                "average_cost": float(item.total_cost / item.total_quantity) if item.total_quantity > 0 else 0
            }
            for item in top_items
        ],
        "purchase_orders": [
            {
                "order_number": po.order_number,
                "supplier": po.supplier,
                "order_date": po.order_date.isoformat(),
                "total_amount": float(po.total_amount),
                "vat_amount": float(po.vat_amount) if po.vat_amount else 0,
                "vat_rate": float(po.vat_rate) if po.vat_rate else 0,
                "shipping_cost": float(po.shipping_cost),
                "labour_cost": float(po.labour_cost),
                "other_cost": float(po.other_cost),
                "status": po.status,
                "items_count": len(po.items),
                "payment_method": "Wallet" if po.use_wallet_payment else ("Bank" if po.bank_account_id else "Cash"),
                "payment_reference": po.payment_reference
            }
            for po in purchase_orders[:20]
        ]
    }