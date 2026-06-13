# app/routes/settings.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Dict, Any, List, Optional
from app.database import get_db, engine, SessionLocal
from app.services import SettingsService
from app.utils.dependencies import require_admin, get_current_user, get_current_user_optional
from app.models import User, Branch, BankAccount
from app.config import settings as app_settings
from pydantic import BaseModel
import json
import os
import zipfile
import io
import tempfile
import shutil
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["Settings"])

class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]

class BankAccountCreate(BaseModel):
    bank_name: str
    branch_name: Optional[str] = None
    account_number: str
    account_name: str
    account_type: str = "checking"
    currency: str = "ETB"
    is_active: bool = True
    is_primary: bool = False
    account_category: str = "regular"  # "vat" or "regular"
    branch_id: int
    notes: Optional[str] = None

class BankAccountUpdate(BaseModel):
    bank_name: Optional[str] = None
    branch_name: Optional[str] = None
    account_number: Optional[str] = None
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    currency: Optional[str] = None
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None
    account_category: Optional[str] = None
    notes: Optional[str] = None

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

# ==================== BANK ACCOUNT MANAGEMENT (using BankAccount table) ====================

@router.get("/bank-accounts")
@router.get("/bank-accounts/")
def get_bank_accounts(
    account_category: Optional[str] = Query(None, description="Filter by category: vat or regular"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    branch_id: Optional[int] = Query(None, description="Filter by branch ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get all bank accounts from BankAccount table with optional filtering"""
    try:
        query = db.query(BankAccount)
        
        # Apply filters
        if account_category:
            query = query.filter(BankAccount.account_category == account_category)
        if is_active is not None:
            query = query.filter(BankAccount.is_active == is_active)
        if branch_id:
            query = query.filter(BankAccount.branch_id == branch_id)
        elif not current_user.is_admin() and current_user.branch_id:
            query = query.filter(BankAccount.branch_id == current_user.branch_id)
        
        bank_accounts = query.order_by(BankAccount.bank_name, BankAccount.account_number).all()
        
        # Convert to response format
        result = []
        for acc in bank_accounts:
            result.append({
                "id": acc.id,
                "bank_name": acc.bank_name,
                "branch_name": acc.branch_name,
                "account_number": acc.account_number,
                "account_name": acc.account_name,
                "account_type": acc.account_type,
                "currency": acc.currency,
                "is_active": acc.is_active,
                "is_primary": acc.is_primary,
                "account_category": getattr(acc, 'account_category', 'regular'),
                "branch_id": acc.branch_id,
                "notes": acc.notes,
                "created_at": acc.created_at.isoformat() if acc.created_at else None,
                "updated_at": acc.updated_at.isoformat() if acc.updated_at else None
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bank-accounts/{account_id}")
@router.get("/bank-accounts/{account_id}/")
def get_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get a single bank account by ID"""
    try:
        account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        return {
            "id": account.id,
            "bank_name": account.bank_name,
            "branch_name": account.branch_name,
            "account_number": account.account_number,
            "account_name": account.account_name,
            "account_type": account.account_type,
            "currency": account.currency,
            "is_active": account.is_active,
            "is_primary": account.is_primary,
            "account_category": getattr(account, 'account_category', 'regular'),
            "branch_id": account.branch_id,
            "notes": account.notes,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bank-accounts")
@router.post("/bank-accounts/")
def create_bank_account(
    account_data: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new bank account in BankAccount table"""
    try:
        # Check if branch exists
        branch = db.query(Branch).filter(Branch.id == account_data.branch_id).first()
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        
        # Check for duplicate account number in the same branch
        existing = db.query(BankAccount).filter(
            BankAccount.branch_id == account_data.branch_id,
            BankAccount.account_number == account_data.account_number
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Account number already exists for this branch")
        
        # Create new bank account
        new_account = BankAccount(
            bank_name=account_data.bank_name,
            branch_name=account_data.branch_name,
            account_number=account_data.account_number,
            account_name=account_data.account_name,
            account_type=account_data.account_type,
            currency=account_data.currency,
            is_active=account_data.is_active,
            is_primary=account_data.is_primary,
            account_category=account_data.account_category,
            branch_id=account_data.branch_id,
            notes=account_data.notes,
            created_by=current_user.id,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        db.add(new_account)
        db.commit()
        db.refresh(new_account)
        
        return {
            "id": new_account.id,
            "bank_name": new_account.bank_name,
            "branch_name": new_account.branch_name,
            "account_number": new_account.account_number,
            "account_name": new_account.account_name,
            "account_type": new_account.account_type,
            "currency": new_account.currency,
            "is_active": new_account.is_active,
            "is_primary": new_account.is_primary,
            "account_category": new_account.account_category,
            "branch_id": new_account.branch_id,
            "notes": new_account.notes,
            "created_at": new_account.created_at.isoformat() if new_account.created_at else None,
            "updated_at": new_account.updated_at.isoformat() if new_account.updated_at else None
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/bank-accounts/{account_id}")
@router.put("/bank-accounts/{account_id}/")
def update_bank_account(
    account_id: int,
    account_update: BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a bank account in BankAccount table"""
    try:
        account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        # Update fields
        update_data = account_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(account, field, value)
        
        account.updated_at = datetime.now()
        db.commit()
        db.refresh(account)
        
        return {
            "id": account.id,
            "bank_name": account.bank_name,
            "branch_name": account.branch_name,
            "account_number": account.account_number,
            "account_name": account.account_name,
            "account_type": account.account_type,
            "currency": account.currency,
            "is_active": account.is_active,
            "is_primary": account.is_primary,
            "account_category": getattr(account, 'account_category', 'regular'),
            "branch_id": account.branch_id,
            "notes": account.notes,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/bank-accounts/{account_id}")
@router.delete("/bank-accounts/{account_id}/")
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Soft delete a bank account (set is_active to false)"""
    try:
        account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        account.is_active = False
        account.updated_at = datetime.now()
        db.commit()
        
        return {"message": "Bank account deactivated successfully", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/bank-accounts/{account_id}/activate")
@router.patch("/bank-accounts/{account_id}/activate/")
def activate_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Activate a bank account"""
    try:
        account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        account.is_active = True
        account.updated_at = datetime.now()
        db.commit()
        
        return {"message": "Bank account activated successfully", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PUBLIC BANK ACCOUNTS ENDPOINT ====================
# FIXED: Now accessible without authentication (for POS system)

@router.get("/bank-accounts/public")
@router.get("/bank-accounts/public/")
def get_public_bank_accounts(
    account_category: Optional[str] = Query(None, description="Filter by category: vat or regular"),
    is_active: bool = Query(True, description="Filter by active status"),
    db: Session = Depends(get_db),
    # No authentication dependency - completely public
):
    """
    Get bank accounts for POS transactions.
    COMPLETELY PUBLIC - No authentication required.
    This endpoint is used by the POS system for bank transfer payments.
    """
    try:
        print(f"=== FETCHING PUBLIC BANK ACCOUNTS (NO AUTH REQUIRED) ===")
        
        # Start with active bank accounts
        query = db.query(BankAccount).filter(BankAccount.is_active == is_active)
        
        # Filter by category if provided
        if account_category:
            query = query.filter(BankAccount.account_category == account_category)
        
        bank_accounts = query.order_by(
            BankAccount.is_primary.desc(), 
            BankAccount.bank_name
        ).all()
        
        # Format for display (simplified for POS)
        formatted_accounts = []
        for acc in bank_accounts:
            formatted_accounts.append({
                "id": acc.id,
                "bank_name": acc.bank_name,
                "branch_name": acc.branch_name,
                "account_number": acc.account_number,
                "account_name": acc.account_name,
                "account_type": acc.account_type,
                "currency": acc.currency,
                "is_active": acc.is_active,
                "is_primary": acc.is_primary,
                "account_category": getattr(acc, 'account_category', 'regular')
            })
        
        print(f"Returning {len(formatted_accounts)} active bank accounts")
        return formatted_accounts
        
    except Exception as e:
        print(f"Error fetching public bank accounts: {str(e)}")
        import traceback
        traceback.print_exc()
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

# ==================== DATABASE DOWNLOAD (ZIP) ====================

@router.get("/database/download")
@router.get("/database/download/")
def download_database(
    current_user: User = Depends(require_admin)
):
    """
    Download the entire database as a ZIP file.
    Only accessible by admin users.
    """
    try:
        # Get database file path based on database type
        if app_settings.DATABASE_TYPE == "sqlite":
            db_path = os.path.join(app_settings.DB_DIR, app_settings.DB_FILENAME)
            
            if not os.path.exists(db_path):
                raise HTTPException(status_code=404, detail="Database file not found")
            
            # Create a ZIP file in memory
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                # Add the database file
                zip_file.write(db_path, arcname=app_settings.DB_FILENAME)
                
                # Add a metadata file with backup information
                metadata = {
                    "backup_date": datetime.now().isoformat(),
                    "database_type": app_settings.DATABASE_TYPE,
                    "database_file": app_settings.DB_FILENAME,
                    "app_version": app_settings.APP_VERSION,
                    "backup_by": current_user.email,
                    "file_size_bytes": os.path.getsize(db_path)
                }
                
                # Add metadata to zip
                zip_file.writestr("backup_info.json", json.dumps(metadata, indent=2))
            
            # Prepare the response
            zip_buffer.seek(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"database_backup_{app_settings.APP_NAME}_{timestamp}.zip"
            
            return Response(
                content=zip_buffer.getvalue(),
                media_type="application/zip",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}",
                    "Content-Length": str(len(zip_buffer.getvalue()))
                }
            )
        else:
            # For MySQL, we would need to dump the database
            raise HTTPException(status_code=501, detail="Download only supported for SQLite database")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database download error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download database: {str(e)}")

# ==================== DATABASE RESTORE ====================

@router.post("/database/restore")
@router.post("/database/restore/")
async def restore_database(
    file: bytes = None,
    current_user: User = Depends(require_admin)
):
    """
    Restore database from a ZIP file.
    Upload the ZIP file created by the download endpoint.
    """
    raise HTTPException(
        status_code=400, 
        detail="Use /database/restore/simple endpoint with multipart/form-data"
    )

# Simple restore endpoint using UploadFile
@router.post("/database/restore/simple")
async def restore_database_simple(
    backup_file: UploadFile = File(...),
    current_user: User = Depends(require_admin)
):
    """
    Simple database restore endpoint using UploadFile.
    Upload the ZIP file created by the download endpoint.
    """
    try:
        # Check file type
        if not backup_file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only ZIP files are accepted")
        
        # Read file content
        content = await backup_file.read()
        
        # Verify and extract ZIP
        try:
            zip_buffer = io.BytesIO(content)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                file_list = zip_file.namelist()
                
                # Find database file
                db_file_name = None
                for name in file_list:
                    if name.endswith('.db') or name == app_settings.DB_FILENAME:
                        db_file_name = name
                        break
                
                if not db_file_name:
                    raise HTTPException(
                        status_code=400, 
                        detail="ZIP file does not contain a valid database file"
                    )
                
                # Extract database content
                db_content = zip_file.read(db_file_name)
                
                # Extract metadata
                metadata = {}
                if "backup_info.json" in file_list:
                    metadata_content = zip_file.read("backup_info.json")
                    metadata = json.loads(metadata_content)
                
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")
        
        # Restore for SQLite
        if app_settings.DATABASE_TYPE == "sqlite":
            db_path = os.path.join(app_settings.DB_DIR, app_settings.DB_FILENAME)
            
            # Ensure directory exists
            os.makedirs(app_settings.DB_DIR, exist_ok=True)
            
            # Create backup of current database
            if os.path.exists(db_path):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f"{db_path}.pre_restore_{timestamp}"
                shutil.copy2(db_path, backup_path)
                logger.info(f"Pre-restore backup saved: {backup_path}")
            
            # Write new database
            with open(db_path, 'wb') as f:
                f.write(db_content)
            
            # Set permissions
            os.chmod(db_path, 0o666)
            
            return {
                "message": "Database restored successfully",
                "success": True,
                "filename": backup_file.filename,
                "backup_info": metadata,
                "restored_by": current_user.email,
                "restored_at": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=501, detail="Restore only supported for SQLite")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== DATABASE INFO ENDPOINT ====================

@router.get("/database/info")
@router.get("/database/info/")
def get_database_info(
    current_user: User = Depends(require_admin)
):
    """Get information about the current database"""
    try:
        if app_settings.DATABASE_TYPE == "sqlite":
            db_path = os.path.join(app_settings.DB_DIR, app_settings.DB_FILENAME)
            
            if os.path.exists(db_path):
                stat_info = os.stat(db_path)
                size_mb = stat_info.st_size / (1024 * 1024)
                
                # Get table counts
                from app.database import SessionLocal
                from sqlalchemy import text
                
                db_session = SessionLocal()
                try:
                    # Get table list and counts
                    result = db_session.execute(text("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                        ORDER BY name
                    """))
                    tables = result.fetchall()
                    
                    table_info = []
                    for table in tables:
                        count_result = db_session.execute(text(f"SELECT COUNT(*) FROM {table[0]}"))
                        count = count_result.scalar()
                        table_info.append({"name": table[0], "rows": count})
                    
                finally:
                    db_session.close()
                
                return {
                    "database_type": "SQLite",
                    "path": db_path,
                    "exists": True,
                    "size_mb": round(size_mb, 2),
                    "last_modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                    "tables": table_info
                }
            else:
                return {
                    "database_type": "SQLite",
                    "path": db_path,
                    "exists": False,
                    "size_mb": 0
                }
        else:
            return {
                "database_type": "MySQL",
                "info": "Use /api/settings/system/info for MySQL details"
            }
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