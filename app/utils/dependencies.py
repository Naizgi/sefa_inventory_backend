# app/utils/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models import User
from app.config import settings
import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)
security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    """
    Get current user from JWT token.
    Raises 401 if token is invalid or user not found.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        print("🔍 PAYLOAD:", payload)

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        user = db.query(User).filter(User.id == user_id).first()

        print("👤 USER:", user)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        return user

    except Exception as e:
        print("❌ AUTH ERROR:", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )


def get_current_user_optional(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme)
) -> Optional[User]:
    """
    Get current user from JWT token if present.
    Returns None if token is invalid or not provided.
    Does NOT raise exceptions for missing/invalid tokens.
    This is useful for endpoints that want to optionally identify the user.
    """
    if token is None:
        return None
    
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        
        user_id = payload.get("user_id")
        if not user_id:
            return None
        
        user = db.query(User).filter(User.id == user_id).first()
        return user
        
    except Exception:
        # If token is invalid, just return None
        return None


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user"""
    if not current_user.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    return current_user


# ==================== ROLE-BASED AUTHORIZATION DEPENDENCIES ====================

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to require admin role"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


def require_privileged(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access (admin or privileged_sales)"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privileged access required"
        )
    return current_user


def require_salesman(current_user: User = Depends(get_current_user)) -> User:
    """Require salesman access (including privileged_sales)"""
    if current_user.role not in ["admin", "salesman", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sales access required"
        )
    return current_user


def require_loan_creation_privilege(current_user: User = Depends(get_current_user)) -> User:
    """Require loan creation privileges (admin or privileged_sales)"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Loan creation requires privileged access"
        )
    return current_user


def require_loan_approval_privilege(current_user: User = Depends(get_current_user)) -> User:
    """Require loan approval privileges (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Loan approval requires administrator access"
        )
    return current_user


def require_refund_privilege(current_user: User = Depends(get_current_user)) -> User:
    """Require refund processing privileges (admin or privileged_sales)"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Refund processing requires privileged access"
        )
    return current_user


def require_report_damaged_goods(current_user: User = Depends(get_current_user)) -> User:
    """Allow any active user to report damaged goods"""
    if not current_user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user cannot report damaged goods"
        )
    if current_user.role not in ["admin", "privileged_sales", "salesman"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to report damaged goods"
        )
    return current_user


def require_approve_damaged_goods(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access to approve damaged goods"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approving damaged goods requires privileged access"
        )
    return current_user


def require_process_damaged_goods(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access to process damaged goods"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Processing damaged goods requires privileged access"
        )
    return current_user


def require_purchase_management(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access for purchase management"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purchase management requires privileged access"
        )
    return current_user


def require_create_purchase_order(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access to create purchase orders"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creating purchase orders requires privileged access"
        )
    return current_user


def require_receive_purchase_order(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access to receive purchase orders"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Receiving purchase orders requires privileged access"
        )
    return current_user


def require_manage_suppliers(current_user: User = Depends(get_current_user)) -> User:
    """Require privileged access to manage suppliers"""
    if current_user.role not in ["admin", "privileged_sales"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supplier management requires privileged access"
        )
    return current_user


# ==================== ADDITIONAL HELPER FUNCTIONS ====================

def get_current_branch_id(
    current_user: User = Depends(get_current_user)
) -> int:
    """
    Get the current user's branch ID.
    Useful for filtering data by branch.
    """
    if current_user.is_admin():
        # Admin might not have a branch, return 0
        return 0
    return current_user.branch_id or 0


def require_branch_access(
    branch_id: int,
    current_user: User = Depends(get_current_user)
) -> bool:
    """
    Check if current user has access to the specified branch.
    Admin has access to all branches.
    """
    if current_user.is_admin():
        return True
    return current_user.branch_id == branch_id