from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal

from app.database import get_db
from app.models import User, Stock, Product, Branch, StockMovement
from app.schemas import StockResponse
from app.utils.dependencies import get_current_user

router = APIRouter(prefix="/api/stock", tags=["Stock"])

# GET by branch ID
@router.get("/{branch_id}")
def get_branch_stock(
    branch_id: int,
    low_stock: bool = Query(False),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get stock for a specific branch"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        if current_user.role == "salesman" and current_user.branch_id != branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this branch")
        
        stocks = db.query(Stock).filter(Stock.branch_id == branch_id).all()
        
        result = []
        for stock in stocks:
            product = db.query(Product).filter(Product.id == stock.product_id).first()
            if not product:
                continue
            
            if stock.quantity <= 0:
                status = "out_of_stock"
            elif stock.quantity <= stock.reorder_level:
                status = "low"
            else:
                status = "normal"
            
            if low_stock and status != "low":
                continue
            
            result.append({
                "product_id": product.id,
                "product_name": product.name,
                "product_sku": product.sku,
                "quantity": float(stock.quantity),
                "reorder_level": float(stock.reorder_level),
                "status": status
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_branch_stock: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# GET - Get my branch stock
@router.get("", response_model=List[StockResponse])
@router.get("/", response_model=List[StockResponse])
def get_my_branch_stock(
    low_stock: bool = Query(False),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get stock for the current user's branch"""
    
    try:
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        
        stocks = db.query(Stock).filter(Stock.branch_id == current_user.branch_id).all()
        
        result = []
        for stock in stocks:
            product = db.query(Product).filter(Product.id == stock.product_id).first()
            if not product:
                continue
            
            if stock.quantity <= 0:
                status = "out_of_stock"
            elif stock.quantity <= stock.reorder_level:
                status = "low"
            else:
                status = "normal"
            
            if low_stock and status != "low":
                continue
            
            result.append({
                "product_id": product.id,
                "product_name": product.name,
                "product_sku": product.sku,
                "quantity": float(stock.quantity),
                "reorder_level": float(stock.reorder_level),
                "status": status
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_my_branch_stock: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# POST - Add stock
@router.post("/{branch_id}/{product_id}/add")
@router.post("/{branch_id}/{product_id}/add/")
def add_stock(
    branch_id: int,
    product_id: int,
    quantity: float = Query(..., gt=0),
    notes: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Add stock to a branch"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        if current_user.role == "salesman":
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            if current_user.branch_id != branch_id:
                raise HTTPException(status_code=403, detail="Not authorized to add stock to this branch")
        
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == product_id
        ).first()
        
        if stock:
            old_quantity = float(stock.quantity)
            new_quantity = float(stock.quantity) + quantity
            stock.quantity = Decimal(str(new_quantity))
        else:
            old_quantity = 0
            new_quantity = quantity
            stock = Stock(
                branch_id=branch_id,
                product_id=product_id,
                quantity=Decimal(str(quantity)),
                reorder_level=10
            )
            db.add(stock)
        
        # Record stock movement (without new_quantity and reason)
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=product_id,
            user_id=current_user.id,
            change_qty=Decimal(str(quantity)),
            movement_type="add",
            notes=notes or f"Stock added by {current_user.name} (Role: {current_user.role})"
        )
        db.add(stock_movement)
        
        db.commit()
        db.refresh(stock)
        
        return {
            "success": True,
            "message": f"Added {quantity} units of {product.name}",
            "product_id": product_id,
            "product_name": product.name,
            "branch_id": branch_id,
            "branch_name": branch.name,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity,
            "added_by": current_user.name,
            "role": current_user.role
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"ERROR in add_stock: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to add stock: {str(e)}")


# PUT - Adjust stock
@router.put("/{branch_id}/{product_id}")
def adjust_stock(
    branch_id: int,
    product_id: int,
    quantity: float = Query(..., ge=0),
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Adjust stock to a specific quantity"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        if current_user.role == "salesman":
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            if current_user.branch_id != branch_id:
                raise HTTPException(status_code=403, detail="Not authorized to adjust stock for this branch")
        
        stock = db.query(Stock).filter(
            Stock.branch_id == branch_id,
            Stock.product_id == product_id
        ).first()
        
        if not stock:
            raise HTTPException(status_code=404, detail="Stock record not found")
        
        old_quantity = float(stock.quantity)
        quantity_change = quantity - old_quantity
        
        stock.quantity = Decimal(str(quantity))
        new_quantity = float(stock.quantity)
        
        # Build notes with reason if provided
        notes_text = f"Stock adjusted by {current_user.name} (Role: {current_user.role})"
        if reason:
            notes_text = f"Reason: {reason} | {notes_text}"
        
        # Record stock movement (without new_quantity and reason)
        stock_movement = StockMovement(
            branch_id=branch_id,
            product_id=product_id,
            user_id=current_user.id,
            change_qty=Decimal(str(quantity_change)),
            movement_type="adjustment",
            notes=notes_text
        )
        db.add(stock_movement)
        
        db.commit()
        db.refresh(stock)
        
        return {
            "success": True,
            "message": f"Adjusted {product.name} stock to {quantity} units",
            "product_id": product_id,
            "product_name": product.name,
            "branch_id": branch_id,
            "branch_name": branch.name,
            "old_quantity": old_quantity,
            "new_quantity": new_quantity,
            "change": quantity_change,
            "reason": reason,
            "adjusted_by": current_user.name,
            "role": current_user.role
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error in adjust_stock: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# POST - Initialize branch stock
@router.post("/initialize/{branch_id}")
@router.post("/initialize/{branch_id}/")
def initialize_branch_stock(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Initialize stock for all products in a branch"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        if current_user.role == "salesman":
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            if current_user.branch_id != branch_id:
                raise HTTPException(status_code=403, detail="Not authorized to initialize stock for this branch")
        
        products = db.query(Product).filter(Product.active == True).all()
        
        created_count = 0
        skipped_count = 0
        
        for product in products:
            existing = db.query(Stock).filter(
                Stock.branch_id == branch_id,
                Stock.product_id == product.id
            ).first()
            
            if not existing:
                stock = Stock(
                    branch_id=branch_id,
                    product_id=product.id,
                    quantity=0,
                    reorder_level=10
                )
                db.add(stock)
                created_count += 1
            else:
                skipped_count += 1
        
        db.commit()
        
        return {
            "message": f"Initialized stock for {created_count} products in branch {branch.name}",
            "branch_id": branch_id,
            "branch_name": branch.name,
            "products_initialized": created_count,
            "products_already_existing": skipped_count,
            "initialized_by": current_user.name,
            "role": current_user.role
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"Error in initialize_branch_stock: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# GET - Stock history for a product
@router.get("/{branch_id}/history/{product_id}")
def get_stock_history(
    branch_id: int,
    product_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get stock movement history for a specific product in a branch"""
    
    try:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        if current_user.role == "salesman":
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            if current_user.branch_id != branch_id:
                raise HTTPException(status_code=403, detail="Not authorized to view history for this branch")
        
        # Get stock movements
        movements = db.query(StockMovement).filter(
            StockMovement.branch_id == branch_id,
            StockMovement.product_id == product_id
        ).order_by(StockMovement.created_at.desc()).limit(limit).all()
        
        result = []
        for movement in movements:
            # Get user name
            user_name = None
            if movement.user_id:
                user = db.query(User).filter(User.id == movement.user_id).first()
                if user:
                    user_name = user.name
            
            # Determine movement type for frontend
            movement_type_display = movement.movement_type
            if movement_type_display in ["add", "purchase"]:
                movement_type_display = "add"
            elif movement_type_display == "adjustment":
                movement_type_display = "adjust"
            
            # Try to extract reason from notes if present
            reason = None
            if movement.notes and "Reason:" in movement.notes:
                import re
                match = re.search(r'Reason:\s*(.*?)\s*\|', movement.notes)
                if match:
                    reason = match.group(1).strip()
            
            result.append({
                "id": movement.id,
                "branch_id": movement.branch_id,
                "product_id": movement.product_id,
                "user_id": movement.user_id,
                "user_name": user_name,
                "quantity_change": float(movement.change_qty),
                "type": movement_type_display,
                "reason": reason,
                "notes": movement.notes,
                "created_at": movement.created_at.isoformat() if movement.created_at else None
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_stock_history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))