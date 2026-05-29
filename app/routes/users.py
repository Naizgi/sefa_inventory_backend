from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.services import AuthService
from app.models import User as UserModel
from app.schemas import User, UserCreate, UserUpdate, UserProfileUpdate
from app.utils.dependencies import require_admin, get_current_user

router = APIRouter(prefix="/api/users", tags=["Users"])

# POST - Create user (handle both with and without slash)
@router.post("", response_model=User, status_code=status.HTTP_201_CREATED)   # No slash
@router.post("/", response_model=User, status_code=status.HTTP_201_CREATED)  # With slash
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Create a new user (Admin only)"""
    existing_user = db.query(UserModel).filter(UserModel.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    db_user = UserModel(
        name=user.name,
        email=user.email,
        password_hash=AuthService.get_password_hash(user.password),
        role=user.role,
        branch_id=user.branch_id,
        active=user.active
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# GET - Get all users (handle both with and without slash)
@router.get("", response_model=List[User])   # No slash
@router.get("/", response_model=List[User])  # With slash
def get_users(
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Get all users (Admin only)"""
    users = db.query(UserModel).all()
    return users

# GET by ID - no change needed (always has slash)
@router.get("/{user_id}", response_model=User)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Get user details (Admin only)"""
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# PUT by ID - no change needed
@router.put("/{user_id}", response_model=User)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Update user (Admin only)"""
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_update.dict(exclude_unset=True)
    
    if "password" in update_data:
        update_data["password_hash"] = AuthService.get_password_hash(update_data.pop("password"))
    
    for key, value in update_data.items():
        setattr(user, key, value)
    
    db.commit()
    db.refresh(user)
    return user

# DELETE by ID - no change needed
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Delete user (Admin only)"""
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    db.delete(user)
    db.commit()
    return None

# ==================== CURRENT USER ENDPOINTS ====================

@router.get("/me", response_model=User)
def get_current_user_profile(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get current user profile (Any authenticated user)"""
    return current_user

@router.put("/me", response_model=User)
def update_current_user_profile(
    user_update: UserProfileUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update current user profile (Any authenticated user)"""
    update_data = user_update.dict(exclude_unset=True)
    
    for key, value in update_data.items():
        if value is not None:
            setattr(current_user, key, value)
    
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/me/change-password")
def change_password(
    password_data: dict,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Change current user password"""
    current_password = password_data.get("current_password")
    new_password = password_data.get("new_password")
    
    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Missing password fields")
    
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    
    if not AuthService.verify_password(current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    
    current_user.password_hash = AuthService.get_password_hash(new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}