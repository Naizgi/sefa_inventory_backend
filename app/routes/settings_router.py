from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from app.database import get_db, engine, SessionLocal
from app.services import SettingsService
from app.utils.dependencies import require_admin, get_current_user
from app.models import User
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
    file: bytes = None,  # This will be handled differently - see below
    current_user: User = Depends(require_admin)
):
    """
    Restore database from a ZIP file.
    Upload the ZIP file created by the download endpoint.
    """
    raise HTTPException(
        status_code=400, 
        detail="Use /database/restore/upload endpoint with multipart/form-data"
    )

@router.post("/database/restore/upload")
async def restore_database_upload(
    request: Request,
    current_user: User = Depends(require_admin)
):
    """
    Restore database from a ZIP file upload.
    Upload the ZIP file created by the download endpoint.
    """
    try:
        # This requires python-multipart
        # pip install python-multipart
        
        form = await request.form()
        file = form.get("file")
        
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded")
        
        # Check file extension
        if not file.filename.endswith('.zip'):
            raise HTTPException(status_code=400, detail="Only ZIP files are accepted")
        
        # Read file content
        content = await file.read()
        
        # Verify it's a valid ZIP file
        try:
            zip_buffer = io.BytesIO(content)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                file_list = zip_file.namelist()
                
                # Find the database file in the ZIP
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
                
                # Extract database file content
                db_content = zip_file.read(db_file_name)
                
                # Read metadata if exists
                metadata = {}
                if "backup_info.json" in file_list:
                    metadata_content = zip_file.read("backup_info.json")
                    metadata = json.loads(metadata_content)
                
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")
        
        # For SQLite, we can restore directly
        if app_settings.DATABASE_TYPE == "sqlite":
            db_path = os.path.join(app_settings.DB_DIR, app_settings.DB_FILENAME)
            
            # Create backup of current database before restore
            if os.path.exists(db_path):
                backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(db_path, backup_path)
                logger.info(f"Created backup of current database: {backup_path}")
            
            # Write the new database file
            with open(db_path, 'wb') as f:
                f.write(db_content)
            
            # Ensure proper permissions
            os.chmod(db_path, 0o666)
            
            # Log the restore action
            logger.info(f"Database restored by {current_user.email} from file: {file.filename}")
            
            return {
                "message": "Database restored successfully",
                "success": True,
                "backup_metadata": metadata,
                "previous_backup_created": os.path.exists(backup_path) if 'backup_path' in locals() else False
            }
        else:
            raise HTTPException(status_code=501, detail="Restore only supported for SQLite database")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database restore error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restore database: {str(e)}")

# Alternative simpler version using FastAPI's UploadFile
from fastapi import UploadFile, File as FastAPIFile

@router.post("/database/restore/simple")
async def restore_database_simple(
    backup_file: UploadFile = FastAPIFile(...),
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