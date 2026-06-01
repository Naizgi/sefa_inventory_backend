from fastapi import HTTPException, Depends
from app.models import User, DamagedGoods, DamagedGoodsStatus, PurchaseOrder
from app.utils.dependencies import get_current_user

def require_privileged(user: User = Depends(get_current_user)):
    """Require user to have privileged access (admin or privileged_sales)"""
    if not user.is_privileged():
        raise HTTPException(
            status_code=403,
            detail="Privileged access required for this operation"
        )
    return user

def require_loan_creation_privilege(user: User = Depends(get_current_user)):
    """Require user to have loan creation privileges"""
    if not user.can_create_loans():
        raise HTTPException(
            status_code=403,
            detail="Loan creation requires privileged access. Please contact an administrator."
        )
    return user

def require_loan_approval_privilege(user: User = Depends(get_current_user)):
    """Require user to have loan approval privileges (admin only)"""
    if not user.can_approve_loans():
        raise HTTPException(
            status_code=403,
            detail="Loan approval requires administrator access"
        )
    return user

def require_refund_privilege(user: User = Depends(get_current_user)):
    """Require user to have refund processing privileges"""
    if not user.can_process_refunds():
        raise HTTPException(
            status_code=403,
            detail="Refund processing requires privileged access"
        )
    return user

def require_admin(user: User = Depends(get_current_user)):
    """Require admin access"""
    if not user.is_admin():
        raise HTTPException(
            status_code=403,
            detail="Administrator access required"
        )
    return user

# ==================== PURCHASE PERMISSION DEPENDENCIES ====================

def require_purchase_management(user: User = Depends(get_current_user)):
    """
    Require user to have purchase management privileges (admin or privileged_sales)
    """
    if not user.can_manage_purchases():
        raise HTTPException(
            status_code=403,
            detail="Purchase management requires privileged access (admin or privileged sales)"
        )
    return user

def require_create_purchase_order(user: User = Depends(get_current_user)):
    """
    Require user to have purchase order creation privileges
    """
    if not user.can_create_purchase_orders():
        raise HTTPException(
            status_code=403,
            detail="Creating purchase orders requires privileged access"
        )
    return user

def require_receive_purchase_order(user: User = Depends(get_current_user)):
    """
    Require user to have purchase order receiving privileges
    """
    if not user.can_receive_purchase_orders():
        raise HTTPException(
            status_code=403,
            detail="Receiving purchase orders requires privileged access"
        )
    return user

def require_manage_suppliers(user: User = Depends(get_current_user)):
    """
    Require user to have supplier management privileges
    """
    if not user.can_manage_suppliers():
        raise HTTPException(
            status_code=403,
            detail="Supplier management requires privileged access"
        )
    return user

def can_access_purchase_order(user: User, purchase_order: PurchaseOrder) -> bool:
    """
    Helper function to check if user can access a specific purchase order
    Privileged users (admin and privileged_sales) can access all purchase orders
    """
    return user.is_privileged()

def can_update_purchase_order(user: User, purchase_order: PurchaseOrder) -> bool:
    """
    Helper function to check if user can update a specific purchase order
    Only admin and privileged_sales can update purchase orders
    """
    if not user.is_privileged():
        return False
    
    # Additional logic could be added here (e.g., only pending orders can be edited)
    # For now, privileged users can update any purchase order
    
    # Optional: Restrict updates to only pending orders
    # from app.models import PurchaseStatus
    # if purchase_order.status != PurchaseStatus.PENDING.value:
    #     return False
    
    return True

# ==================== DAMAGED GOODS PERMISSION DEPENDENCIES ====================

def require_report_damaged_goods(user: User = Depends(get_current_user)):
    """
    Allow any active user (admin, privileged_sales, salesman) to report damaged goods
    This lets front-line staff flag issues immediately
    """
    if not user.can_report_damaged_goods():
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to report damaged goods"
        )
    return user

def require_approve_damaged_goods(user: User = Depends(get_current_user)):
    """
    Require privileged access (admin or privileged_sales) to approve damaged goods reports
    Regular salesmen cannot approve - requires supervisor approval
    """
    if not user.can_approve_damaged_goods():
        raise HTTPException(
            status_code=403,
            detail="Approving damaged goods requires privileged access (admin or privileged sales)"
        )
    return user

def require_process_damaged_goods(user: User = Depends(get_current_user)):
    """
    Require privileged access to process damaged goods (adjust inventory)
    """
    if not user.can_process_damaged_goods():
        raise HTTPException(
            status_code=403,
            detail="Processing damaged goods requires privileged access (admin or privileged sales)"
        )
    return user

def require_view_damaged_goods_report(user: User = Depends(get_current_user)):
    """
    Allow viewing damaged goods reports:
    - Admin/privileged: can view all reports
    - Regular salesmen: can only view their own reports
    Note: This is a base dependency - actual report filtering should be done in the endpoint
    """
    if not user.active:
        raise HTTPException(
            status_code=403,
            detail="Inactive user cannot access damaged goods reports"
        )
    # All active users can view at least their own reports
    return user

# ==================== HELPER FUNCTIONS FOR ROUTE-LEVEL CHECKING ====================

def can_access_damaged_goods_report(user: User, damaged_report: DamagedGoods) -> bool:
    """
    Helper function to check if user can access a specific damaged goods report
    Use this inside route handlers after fetching the report
    """
    return user.can_view_damaged_goods_report(damaged_report)

def can_update_damaged_goods_status(user: User, damaged_report: DamagedGoods) -> bool:
    """
    Helper function to check if user can update the status of a damaged goods report
    """
    return user.can_update_damaged_goods_status(damaged_report.status)

# ==================== EXAMPLE ROUTE IMPLEMENTATIONS ====================

"""
Example of how to use these dependencies in your routes:

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import DamagedGoods, PurchaseOrder

# ==================== PURCHASE ROUTES ====================

router = APIRouter(prefix="/purchases", tags=["purchases"])

@router.post("/orders")
def create_purchase_order(
    order_data: PurchaseOrderCreate,
    user: User = Depends(require_create_purchase_order),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Create a new purchase order - privileged access only'''
    # Implementation here
    pass

@router.get("/orders")
def get_purchase_orders(
    user: User = Depends(require_purchase_management),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Get all purchase orders - privileged access only'''
    query = db.query(PurchaseOrder)
    
    # Optional: Filter by branch if needed
    if not user.is_admin():
        query = query.filter(PurchaseOrder.branch_id == user.branch_id)
    
    orders = query.all()
    return orders

@router.get("/orders/{order_id}")
def get_purchase_order(
    order_id: int,
    user: User = Depends(require_purchase_management),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Get specific purchase order with access control'''
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    # Check if user has access to this order
    if not can_access_purchase_order(user, order):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view this purchase order"
        )
    
    return order

@router.put("/orders/{order_id}/receive")
def receive_purchase_order(
    order_id: int,
    receive_data: PurchaseOrderReceive,
    user: User = Depends(require_receive_purchase_order),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Receive a purchase order and update stock - privileged access only'''
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    # Update stock for each item
    for item in order.items:
        # Update stock logic here
        pass
    
    order.status = PurchaseStatus.COMPLETED.value
    order.actual_delivery_date = func.now()
    
    db.commit()
    return {"message": "Purchase order received successfully"}

@router.put("/orders/{order_id}")
def update_purchase_order(
    order_id: int,
    order_data: PurchaseOrderUpdate,
    user: User = Depends(require_purchase_management),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Update purchase order - privileged access only'''
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if not can_update_purchase_order(user, order):
        raise HTTPException(
            status_code=403,
            detail="Cannot update this purchase order"
        )
    
    # Update logic here
    db.commit()
    return {"message": "Purchase order updated successfully"}

# ==================== SUPPLIER ROUTES ====================

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

@router.post("/")
def create_supplier(
    supplier_data: SupplierCreate,
    user: User = Depends(require_manage_suppliers),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Create a new supplier - privileged access only'''
    # Implementation here
    pass

@router.get("/")
def get_suppliers(
    user: User = Depends(require_manage_suppliers),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Get all suppliers - privileged access only'''
    suppliers = db.query(Supplier).all()
    return suppliers

@router.put("/{supplier_id}")
def update_supplier(
    supplier_id: int,
    supplier_data: SupplierUpdate,
    user: User = Depends(require_manage_suppliers),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Update supplier - privileged access only'''
    # Implementation here
    pass

# ==================== DAMAGED GOODS ROUTES ====================

router = APIRouter(prefix="/damaged-goods", tags=["damaged-goods"])

@router.post("/report")
def report_damaged_goods(
    report_data: DamagedGoodsCreate,
    user: User = Depends(require_report_damaged_goods),  # All active users can report
    db: Session = Depends(get_db)
):
    '''Report damaged goods - available to all active users'''
    # Implementation here
    pass

@router.put("/{report_id}/approve")
def approve_damaged_goods(
    report_id: int,
    user: User = Depends(require_approve_damaged_goods),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Approve damaged goods report - privileged access only'''
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Check if report is in correct status
    if report.status != DamagedGoodsStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Only pending reports can be approved")
    
    # Update report
    report.status = DamagedGoodsStatus.APPROVED.value
    report.approved_by = user.id
    report.approved_at = func.now()
    
    db.commit()
    return {"message": "Report approved successfully"}

@router.put("/{report_id}/process")
def process_damaged_goods(
    report_id: int,
    user: User = Depends(require_process_damaged_goods),  # Privileged only
    db: Session = Depends(get_db)
):
    '''Process damaged goods (adjust inventory) - privileged access only'''
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Check if report is in correct status
    if report.status != DamagedGoodsStatus.APPROVED.value:
        raise HTTPException(status_code=400, detail="Only approved reports can be processed")
    
    # Update report
    report.status = DamagedGoodsStatus.PROCESSED.value
    report.processed_by = user.id
    report.processed_at = func.now()
    
    # Adjust inventory here (reduce stock)
    stock = db.query(Stock).filter(
        Stock.branch_id == report.branch_id,
        Stock.product_id == report.product_id
    ).first()
    
    if stock:
        stock.quantity -= report.quantity
        # Update quantity_with_vat and quantity_without_vat as needed
    
    db.commit()
    return {"message": "Damaged goods processed successfully"}

@router.get("/")
def get_damaged_goods_reports(
    user: User = Depends(require_view_damaged_goods_report),  # All active users can view
    db: Session = Depends(get_db)
):
    '''Get damaged goods reports with role-based filtering'''
    query = db.query(DamagedGoods)
    
    # Filter based on user role
    if not user.is_privileged():
        # Regular salesmen can only see their own reports
        query = query.filter(DamagedGoods.reported_by == user.id)
    
    reports = query.all()
    return reports

@router.get("/{report_id}")
def get_damaged_goods_report(
    report_id: int,
    user: User = Depends(require_view_damaged_goods_report),
    db: Session = Depends(get_db)
):
    '''Get specific damaged goods report with access control'''
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Check if user has access to this specific report
    if not can_access_damaged_goods_report(user, report):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view this report"
        )
    
    return report

@router.delete("/{report_id}")
def cancel_damaged_goods_report(
    report_id: int,
    user: User = Depends(require_approve_damaged_goods),  # Only privileged can cancel
    db: Session = Depends(get_db)
):
    '''Cancel a damaged goods report - privileged access only'''
    report = db.query(DamagedGoods).filter(DamagedGoods.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    # Only pending reports can be cancelled
    if report.status != DamagedGoodsStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Only pending reports can be cancelled")
    
    report.status = DamagedGoodsStatus.REJECTED.value
    report.approved_by = user.id
    report.approved_at = func.now()
    
    db.commit()
    return {"message": "Report cancelled/rejected successfully"}
"""