from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from app.database import get_db
from app.services import SettingsService
from app.utils.dependencies import require_admin, get_current_user
from app.models import User
from pydantic import BaseModel
import json

router = APIRouter(prefix="/api/settings", tags=["Settings"])

class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]

# ==================== GENERAL SETTINGS ====================

@router.get("/general")
@router.get("/general/")
def get_general_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get general system settings"""
    try:
        settings = SettingsService.get_category_settings(db, "general")
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/general")
@router.put("/general/")
def update_general_settings(
    data: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update general system settings"""
    try:
        SettingsService.set_multiple_settings(db, "general", data.settings, current_user.id)
        return {"message": "General settings updated successfully", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== NOTIFICATION SETTINGS ====================

@router.get("/notifications")
@router.get("/notifications/")
def get_notification_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get notification settings"""
    try:
        settings = SettingsService.get_category_settings(db, "notification")
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/notifications")
@router.put("/notifications/")
def update_notification_settings(
    data: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update notification settings"""
    try:
        SettingsService.set_multiple_settings(db, "notification", data.settings, current_user.id)
        return {"message": "Notification settings updated successfully", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== BACKUP SETTINGS ====================

@router.get("/backup")
@router.get("/backup/")
def get_backup_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get backup settings"""
    try:
        settings = SettingsService.get_category_settings(db, "backup")
        return settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/backup")
@router.put("/backup/")
def update_backup_settings(
    data: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update backup settings"""
    try:
        SettingsService.set_multiple_settings(db, "backup", data.settings, current_user.id)
        return {"message": "Backup settings updated successfully", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== BACKUP MANAGEMENT ====================

@router.post("/backup/create")
@router.post("/backup/create/")
def create_backup(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a manual database backup"""
    try:
        backup = SettingsService.create_backup(db, current_user.id)
        return backup
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/backups")
@router.get("/backups/")
def get_backups(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get recent backups list"""
    try:
        backups = SettingsService.get_backups(db, limit)
        return backups
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/backups/{backup_id}")
def delete_backup(
    backup_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a backup file"""
    try:
        success = SettingsService.delete_backup(db, backup_id, current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Backup not found")
        return {"message": "Backup deleted successfully", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== CACHE MANAGEMENT ====================

@router.post("/cache/clear")
@router.post("/cache/clear/")
def clear_cache(
    current_user: User = Depends(require_admin)
):
    """Clear application cache"""
    try:
        result = SettingsService.clear_cache()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== SYSTEM INFORMATION ====================

@router.get("/system/info")
@router.get("/system/info/")
def get_system_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get system information and statistics"""
    try:
        info = SettingsService.get_system_info(db)
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== DATA MANAGEMENT ====================

@router.post("/system/reset")
@router.post("/system/reset/")
def reset_system_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Reset all system data (DANGER: This will delete all transactional data)"""
    try:
        result = SettingsService.reset_system_data(db, current_user.id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/system/export")
@router.post("/system/export/")
def export_all_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Export all system data as JSON"""
    try:
        data = SettingsService.export_all_data(db)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PUBLIC BANK ACCOUNTS ENDPOINT ====================

@router.get("/bank-accounts/public")
@router.get("/bank-accounts/public/")
def get_public_bank_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Allow both admin and salesman
):
    """Get bank accounts for POS transactions (accessible by all authenticated users)"""
    try:
        print("=== FETCHING BANK ACCOUNTS ===")
        # Get bank accounts from general settings
        settings = SettingsService.get_category_settings(db, "general")
        print(f"Settings retrieved: {settings.keys() if settings else 'None'}")
        
        bank_accounts = []
        if settings.get("bank_accounts"):
            print(f"Found bank_accounts in settings: {type(settings['bank_accounts'])}")
            if isinstance(settings["bank_accounts"], list):
                bank_accounts = settings["bank_accounts"]
                print(f"Bank accounts as list: {len(bank_accounts)} accounts")
            elif isinstance(settings["bank_accounts"], str):
                try:
                    bank_accounts = json.loads(settings["bank_accounts"])
                    print(f"Bank accounts parsed from string: {len(bank_accounts)} accounts")
                except json.JSONDecodeError as e:
                    print(f"Failed to parse bank_accounts JSON: {e}")
                    bank_accounts = []
        else:
            print("No bank_accounts found in settings")
        
        # Return only active bank accounts
        active_accounts = [acc for acc in bank_accounts if acc.get("is_active", True)]
        print(f"Returning {len(active_accounts)} active bank accounts")
        
        return active_accounts
    except Exception as e:
        print(f"Error fetching public bank accounts: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))