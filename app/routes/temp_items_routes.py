from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
import uuid

from app.database import get_db
from app.models import User, TempItem, TempItemStatus
from app.schemas import TempItemCreate, TempItemResponse
from app.utils.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/api/temp-items", tags=["Temporary Items"])

def generate_item_number():
    return f"TMP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

# POST - Register temp item (handle both with and without trailing slash)
@router.post("", response_model=TempItemResponse)   # No slash - /api/temp-items
@router.post("/", response_model=TempItemResponse)  # With slash - /api/temp-items/
def register_temp_item(
    item_data: TempItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Register a temporary item (Salesman can do this)"""
    
    temp_item = TempItem(
        item_number=generate_item_number(),
        item_name=item_data.item_name,
        description=item_data.description,
        quantity=item_data.quantity,
        unit_price=item_data.unit_price,
        customer_name=item_data.customer_name,
        customer_phone=item_data.customer_phone,
        notes=item_data.notes,
        registered_by=current_user.id,
        status=TempItemStatus.PENDING.value
    )
    
    db.add(temp_item)
    db.commit()
    db.refresh(temp_item)
    
    registrar = db.query(User).filter(User.id == temp_item.registered_by).first()
    
    return {
        "id": temp_item.id,
        "item_number": temp_item.item_number,
        "item_name": temp_item.item_name,
        "description": temp_item.description,
        "quantity": temp_item.quantity,
        "unit_price": float(temp_item.unit_price) if temp_item.unit_price else None,
        "customer_name": temp_item.customer_name,
        "customer_phone": temp_item.customer_phone,
        "notes": temp_item.notes,
        "status": temp_item.status,
        "registered_by": registrar.name if registrar else "System",
        "registered_at": temp_item.registered_at,
        "received_by": None,
        "received_at": None
    }

# GET - Get temp items (handle both with and without trailing slash)
@router.get("", response_model=List[TempItemResponse])   # No slash - /api/temp-items
@router.get("/", response_model=List[TempItemResponse])  # With slash - /api/temp-items/
def get_temp_items(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get temporary items (Salesman sees their own, Admin sees all)"""
    
    query = db.query(TempItem)
    
    if current_user.role == "salesman":
        query = query.filter(TempItem.registered_by == current_user.id)
    
    if status:
        query = query.filter(TempItem.status == status)
    
    if search:
        query = query.filter(
            (TempItem.item_name.ilike(f"%{search}%")) |
            (TempItem.item_number.ilike(f"%{search}%")) |
            (TempItem.customer_name.ilike(f"%{search}%"))
        )
    
    items = query.order_by(TempItem.registered_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for item in items:
        registrar = db.query(User).filter(User.id == item.registered_by).first()
        receiver = db.query(User).filter(User.id == item.received_by).first() if item.received_by else None
        
        result.append({
            "id": item.id,
            "item_number": item.item_number,
            "item_name": item.item_name,
            "description": item.description,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price) if item.unit_price else None,
            "customer_name": item.customer_name,
            "customer_phone": item.customer_phone,
            "notes": item.notes,
            "status": item.status,
            "registered_by": registrar.name if registrar else "System",
            "registered_at": item.registered_at,
            "received_by": receiver.name if receiver else None,
            "received_at": item.received_at
        })
    
    return result

# PUT - Receive temp item (no change needed - has slash before ID)
@router.put("/{item_id}/receive")
def receive_temp_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Mark a temporary item as received (Admin only)"""
    
    item = db.query(TempItem).filter(TempItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if item.status == "received":
        raise HTTPException(status_code=400, detail="Item already received")
    
    if item.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot receive a cancelled item")
    
    item.status = TempItemStatus.RECEIVED.value
    item.received_by = current_user.id
    item.received_at = datetime.now()
    
    db.commit()
    
    return {"message": "Item marked as received successfully", "item_id": item.id}

# PUT - Cancel temp item (no change needed - has slash before ID)
@router.put("/{item_id}/cancel")
def cancel_temp_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel a temporary item (Salesman can cancel their own, Admin can cancel any)"""
    
    item = db.query(TempItem).filter(TempItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if current_user.role == "salesman" and item.registered_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this item")
    
    if item.status == "received":
        raise HTTPException(status_code=400, detail="Cannot cancel a received item")
    
    item.status = TempItemStatus.CANCELLED.value
    
    db.commit()
    
    return {"message": "Item cancelled successfully"}