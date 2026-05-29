from fastapi import HTTPException, Depends
from app.models import User
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