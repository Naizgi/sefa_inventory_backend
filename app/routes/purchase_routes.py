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
    StockMovement
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

router = APIRouter(prefix="/api/purchases", tags=["Purchases"])

def generate_order_number():
    return f"PO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

# ==================== LEGACY PURCHASE ROUTES ====================

@router.post("", response_model=PurchaseSchema, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=PurchaseSchema, status_code=status.HTTP_201_CREATED)
def create_purchase(
    purchase_data: PurchaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new purchase (legacy)"""
    
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    total_amount = Decimal('0')
    
    # Create purchase
    purchase = PurchaseModel(
        branch_id=branch_id,
        supplier_name=purchase_data.supplier_name,
        total_amount=0,
    )
    db.add(purchase)
    db.flush()
    
    # Add items and calculate total
    for item_data in purchase_data.items:
        product = db.query(Product).filter(Product.id == item_data.product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item_data.product_id} not found")
        
        item_total = item_data.quantity * item_data.unit_cost
        total_amount += item_total
        
        purchase_item = PurchaseItemModel(
            purchase_id=purchase.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
            unit_cost=item_data.unit_cost
        )
        db.add(purchase_item)
        
        # Update stock
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == item_data.product_id
        ).first()
        
        if stock:
            stock.quantity += item_data.quantity
        else:
            stock = Stock(
                branch_id=branch_id,
                product_id=item_data.product_id,
                quantity=item_data.quantity,
                reorder_level=0
            )
            db.add(stock)
        
        # Record stock movement
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=item_data.product_id,
            user_id=current_user.id,
            change_qty=item_data.quantity,
            movement_type="purchase",
            reference_id=purchase.id,
            notes=f"Purchase from {purchase_data.supplier_name}"
        )
        db.add(stock_movement)
    
    purchase.total_amount = total_amount
    db.commit()
    db.refresh(purchase)
    
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
    """Create a new purchase order"""
    
    if not current_user.branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    # Calculate totals
    subtotal = Decimal('0')
    for item in purchase_data.items:
        quantity = Decimal(str(item.quantity_ordered))
        cost = Decimal(str(item.unit_cost))
        item_total = quantity * cost
        subtotal += item_total
    
    tax = Decimal(str(purchase_data.tax_amount))
    shipping = Decimal(str(purchase_data.shipping_cost))
    discount = Decimal(str(purchase_data.discount_amount))
    total_amount = subtotal + tax + shipping - discount
    
    # Create purchase order
    purchase_order = PurchaseOrder(
        order_number=generate_order_number(),
        branch_id=current_user.branch_id,
        supplier=purchase_data.supplier,
        expected_delivery_date=purchase_data.expected_delivery_date,
        subtotal=subtotal,
        tax_amount=tax,
        shipping_cost=shipping,
        discount_amount=discount,
        total_amount=total_amount,
        notes=purchase_data.notes,
        created_by=current_user.id,
        status='pending'
    )
    
    db.add(purchase_order)
    db.flush()
    
    # Add items
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
        "tax_amount": float(purchase_order.tax_amount),
        "shipping_cost": float(purchase_order.shipping_cost),
        "discount_amount": float(purchase_order.discount_amount),
        "total_amount": float(purchase_order.total_amount),
        "notes": purchase_order.notes,
        "created_by": creator_name,
        "created_at": purchase_order.created_at,
        "updated_at": purchase_order.updated_at,
        "items": items_response
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
    """Get all purchase orders"""
    
    try:
        # Build query
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
        
        # Execute query
        orders = query.order_by(PurchaseOrder.order_date.desc()).offset(skip).limit(limit).all()
        
        # Build response without lazy loading issues
        result = []
        for order in orders:
            # Get creator name
            creator = db.query(User).filter(User.id == order.created_by).first()
            creator_name = creator.name if creator else "System"
            
            # Build items response
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
                "tax_amount": float(order.tax_amount),
                "shipping_cost": float(order.shipping_cost),
                "discount_amount": float(order.discount_amount),
                "total_amount": float(order.total_amount),
                "notes": order.notes,
                "created_by": creator_name,
                "created_at": order.created_at,
                "updated_at": order.updated_at,
                "items": items_response
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
    """Get purchase order by ID"""
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    creator = db.query(User).filter(User.id == order.created_by).first()
    creator_name = creator.name if creator else "System"
    
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
        "tax_amount": float(order.tax_amount),
        "shipping_cost": float(order.shipping_cost),
        "discount_amount": float(order.discount_amount),
        "total_amount": float(order.total_amount),
        "notes": order.notes,
        "created_by": creator_name,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "items": items_response
    }

@router.post("/orders/{order_id}/receive")
def receive_purchase_order(
    order_id: int,
    receive_data: ReceivePurchaseOrder,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Receive items from purchase order and update inventory"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if purchase_order.status == "completed":
        raise HTTPException(status_code=400, detail="Purchase order already completed")
    
    branch_id = current_user.branch_id
    if not branch_id:
        raise HTTPException(status_code=400, detail="User not assigned to a branch")
    
    received_items = []
    
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
        
        product = db.query(Product).filter(Product.id == purchase_item.product_id).first()
        
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == purchase_item.product_id
        ).first()
        
        if stock:
            stock.quantity += quantity_received
        else:
            stock = Stock(
                branch_id=branch_id,
                product_id=purchase_item.product_id,
                quantity=quantity_received,
                reorder_level=0
            )
            db.add(stock)
        
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=purchase_item.product_id,
            user_id=current_user.id,
            change_qty=quantity_received,
            movement_type="purchase",
            reference_id=purchase_order.id,
            notes=f"Received from PO: {purchase_order.order_number}"
        )
        db.add(stock_movement)
        
        received_items.append({
            "product_id": purchase_item.product_id,
            "product_name": product.name if product else "Unknown",
            "quantity_received": float(quantity_received),
            "unit_cost": float(purchase_item.unit_cost),
            "total_cost": float(purchase_item.unit_cost * quantity_received),
            "branch_id": branch_id
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
        "received_items": received_items,
        "total_items_received": len(received_items)
    }

@router.put("/orders/{order_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(
    order_id: int,
    update_data: PurchaseOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update purchase order status"""
    
    purchase_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not purchase_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if update_data.status:
        purchase_order.status = update_data.status
    if update_data.actual_delivery_date:
        purchase_order.actual_delivery_date = datetime.combine(update_data.actual_delivery_date, datetime.min.time())
    if update_data.notes:
        purchase_order.notes = update_data.notes
    
    purchase_order.updated_at = datetime.now()
    db.commit()
    db.refresh(purchase_order)
    
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
        "tax_amount": float(purchase_order.tax_amount),
        "shipping_cost": float(purchase_order.shipping_cost),
        "discount_amount": float(purchase_order.discount_amount),
        "total_amount": float(purchase_order.total_amount),
        "notes": purchase_order.notes,
        "created_by": creator_name,
        "created_at": purchase_order.created_at,
        "updated_at": purchase_order.updated_at,
        "items": items_response
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
    """Get purchase report"""
    
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
    total_legacy_cost = sum(p.total_amount for p in purchases)
    
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
            "total_legacy_purchases": len(purchases),
            "total_legacy_cost": float(total_legacy_cost),
            "total_all_purchases": float(total_purchase_cost + total_legacy_cost),
            "average_order_value": float(total_purchase_cost / len(purchase_orders)) if purchase_orders else 0
        },
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
                "status": po.status,
                "items_count": len(po.items)
            }
            for po in purchase_orders[:20]
        ]
    }