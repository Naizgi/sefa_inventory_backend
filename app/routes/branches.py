from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from app.database import get_db
from app.services import BranchService
from app.schemas import Branch, BranchCreate, BranchUpdate
from app.utils.dependencies import require_admin
from app.models import User, Stock, Sale, Branch as BranchModel

router = APIRouter(prefix="/api/branches", tags=["Branches"])

# POST - Create branch (handle both with and without trailing slash)
@router.post("", response_model=Branch, status_code=status.HTTP_201_CREATED)   # No slash - /api/branches
@router.post("/", response_model=Branch, status_code=status.HTTP_201_CREATED)  # With slash - /api/branches/
def create_branch(
    branch: BranchCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Create a new branch (Admin only)"""
    return BranchService.create_branch(db, branch)

# GET - Get all branches (handle both with and without trailing slash)
@router.get("", response_model=List[Branch])   # No slash - /api/branches
@router.get("/", response_model=List[Branch])  # With slash - /api/branches/
def get_branches(
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Get all branches"""
    return BranchService.get_branches(db)

# GET by ID - no change needed (always has slash before ID)
@router.get("/{branch_id}", response_model=Branch)
def get_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Get branch details"""
    branch = BranchService.get_branch(db, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return branch

# PUT by ID - no change needed
@router.put("/{branch_id}", response_model=Branch)
def update_branch(
    branch_id: int,
    branch: BranchUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Update branch (Admin only)"""
    updated_branch = BranchService.update_branch(db, branch_id, branch)
    if not updated_branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    return updated_branch

# DELETE by ID - no change needed
@router.delete("/{branch_id}")
def delete_branch(
    branch_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Delete a branch (Admin only)"""
    branch = BranchService.get_branch(db, branch_id)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Check if branch has users
    users = db.query(User).filter(User.branch_id == branch_id).first()
    if users:
        raise HTTPException(status_code=400, detail="Cannot delete branch with assigned users")
    
    db.delete(branch)
    db.commit()
    return {"message": "Branch deleted successfully"}

# GET stats - no slash needed (different path)
@router.get("/stats")
def get_branch_stats(
    db: Session = Depends(get_db),
    current_user = Depends(require_admin)
):
    """Get overall branch statistics"""
    
    try:
        # Get total branches
        total_branches = db.query(BranchModel).count()
        
        # Get total staff (users assigned to branches)
        total_staff = db.query(User).filter(User.branch_id.isnot(None)).count()
        
        # Get total stock across all branches
        total_stock_result = db.query(func.sum(Stock.quantity)).scalar()
        total_stock = float(total_stock_result) if total_stock_result else 0
        
        # Get total revenue from sales (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        total_revenue_result = db.query(func.sum(Sale.total_amount)).filter(
            Sale.created_at >= thirty_days_ago
        ).scalar()
        total_revenue = float(total_revenue_result) if total_revenue_result else 0
        
        return {
            "total_branches": total_branches,
            "total_staff": total_staff,
            "total_stock": total_stock,
            "total_revenue": total_revenue
        }
        
    except Exception as e:
        print(f"Error in get_branch_stats: {str(e)}")
        # Return default values on error
        return {
            "total_branches": db.query(BranchModel).count(),
            "total_staff": 0,
            "total_stock": 0,
            "total_revenue": 0
        }