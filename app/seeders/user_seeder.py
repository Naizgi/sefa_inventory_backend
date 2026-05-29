# app/seeders/user_seeder.py
from sqlalchemy.orm import Session
from app.models import User, Branch
from app.services import AuthService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed_users(db: Session):
    """Seed users into the database"""
    
    # Check if users already exist
    existing_users = db.query(User).count()
    if existing_users > 0:
        logger.info(f"Users already exist ({existing_users} users). Skipping seeding.")
        return
    
    # Get branches
    branches = db.query(Branch).all()
    logger.info(f"Found {len(branches)} branches")
    
    users = []
    
    # Create admin user
    try:
        admin_password = "admin123"
        admin_password_hash = AuthService.get_password_hash(admin_password)
        
        admin_user = User(
            name="System Administrator",
            email="admin@example.com",
            password_hash=admin_password_hash,
            role="admin",
            branch_id=None,
            active=True
        )
        users.append(admin_user)
        logger.info("✅ Created admin user")
        
    except Exception as e:
        logger.error(f"❌ Failed to create admin user: {e}")
        return
    
    # Create salesman user
    try:
        salesman_password = "sales123"
        salesman_password_hash = AuthService.get_password_hash(salesman_password)
        
        if branches:
            salesman = User(
                name="Sales Representative",
                email="sales@example.com",
                password_hash=salesman_password_hash,
                role="salesman",
                branch_id=branches[0].id,
                active=True
            )
        else:
            salesman = User(
                name="Sales Representative",
                email="sales@example.com",
                password_hash=salesman_password_hash,
                role="salesman",
                branch_id=None,
                active=True
            )
        users.append(salesman)
        logger.info("✅ Created salesman user")
        
    except Exception as e:
        logger.error(f"❌ Failed to create salesman: {e}")
    
    # Add all users to database
    try:
        db.add_all(users)
        db.commit()
        
        logger.info("=" * 60)
        logger.info(f"✅ Successfully created {len(users)} users")
        logger.info("=" * 60)
        logger.info("📋 LOGIN CREDENTIALS:")
        logger.info("-" * 40)
        
        for user in users:
            if user.role == 'admin':
                logger.info(f"👑 ADMIN:")
                logger.info(f"   Email: {user.email}")
                logger.info(f"   Password: admin123")
                logger.info(f"   Role: {user.role}")
            elif user.role == 'salesman':
                logger.info(f"👤 SALESMAN:")
                logger.info(f"   Email: {user.email}")
                logger.info(f"   Password: sales123")
                logger.info(f"   Role: {user.role}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Failed to commit users: {e}")
        db.rollback()