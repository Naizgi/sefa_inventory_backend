from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.database import get_db
from app.services import AlertService
from app.schemas import AlertResponse
from app.utils.dependencies import require_admin, get_current_user

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

# Handle BOTH with and without trailing slash
@router.get("")  # No trailing slash
@router.get("/")  # With trailing slash
def get_alerts(
    resolved: bool = Query(False),
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get alerts (Both Admin and Sales can access)
    
    - Admin: Can view alerts for all branches or filter by branch_id
    - Sales: Can only view alerts for their assigned branch
    """
    # Apply branch filtering for sales role
    if current_user.role == "salesman":
        # Sales can only see their own branch
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        
        # If sales tries to specify a different branch, restrict to their own
        if branch_id and branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to view alerts for other branches")
        
        # Force filter to user's branch
        branch_id = current_user.branch_id
    
    alerts = AlertService.get_alerts(db, resolved, branch_id)
    return alerts

@router.post("/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Resolve an alert (Both Admin and Sales can resolve alerts for their branch)"""
    
    # First get the alert to check permissions
    alert = AlertService.get_alert_by_id(db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Check permissions
    if current_user.role == "salesman":
        # Sales can only resolve alerts for their own branch
        if not current_user.branch_id:
            raise HTTPException(status_code=400, detail="User not assigned to a branch")
        
        if alert.branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Not authorized to resolve alerts for other branches")
    
    # Resolve the alert
    alert = AlertService.resolve_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    return {"message": "Alert resolved successfully"}

@router.post("/check-low-stock")
def check_low_stock_manual(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Manually trigger low stock check and create alerts
    
    - Admin: Can check low stock for all branches
    - Sales: Can only check low stock for their assigned branch
    """
    try:
        # For sales role, only check their branch
        if current_user.role == "salesman":
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            
            # Check low stock only for salesperson's branch
            alerts_created = AlertService.check_low_stock_for_branch(db, current_user.branch_id)
            resolved_count = AlertService.auto_resolve_alerts_for_branch(db, current_user.branch_id)
        else:
            # Admin can check all branches
            alerts_created = AlertService.check_low_stock_and_create_alerts(db)
            resolved_count = AlertService.auto_resolve_alerts(db)
        
        return {
            "message": "Low stock check completed",
            "alerts_created": alerts_created,
            "alerts_resolved": resolved_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/low-stock-summary")
def get_low_stock_summary(
    branch_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get summary of all low stock items
    
    - Admin: Can view summary for all branches or filter by branch_id
    - Sales: Can only view summary for their assigned branch
    """
    try:
        # Apply branch filtering for sales role
        if current_user.role == "salesman":
            # Sales can only see their own branch
            if not current_user.branch_id:
                raise HTTPException(status_code=400, detail="User not assigned to a branch")
            
            # If sales tries to specify a different branch, restrict to their own
            if branch_id and branch_id != current_user.branch_id:
                raise HTTPException(status_code=403, detail="Not authorized to view summary for other branches")
            
            # Force filter to user's branch
            branch_id = current_user.branch_id
        
        summary = AlertService.get_low_stock_summary(db, branch_id)
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))