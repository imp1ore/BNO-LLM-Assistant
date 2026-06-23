"""
Script to create default admin user
Can be run even if server is running (will just add user if doesn't exist)
"""
import sys
from pathlib import Path
# Add project root to path (parent of scripts directory)
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.shared.database import SessionLocal, User, Base, engine
from backend.api_server.auth import get_password_hash

def create_admin():
    """Create default admin user"""
    print("Creating admin user...")
    
    # Try to create tables if they don't exist (won't affect existing ones)
    try:
        Base.metadata.create_all(bind=engine)
        print("[OK] Database tables checked/created")
    except Exception as e:
        print(f"[WARNING] {e}")
        print("Continuing anyway...")
    
    # Create admin user
    db = SessionLocal()
    try:
        # Check if admin user exists
        admin_user = db.query(User).filter(User.username == "admin").first()
        
        if admin_user:
            print("[OK] Admin user already exists")
            print(f"  Username: {admin_user.username}")
            print(f"  Is Admin: {admin_user.is_admin}")
            print(f"  Can Upload: {getattr(admin_user, 'can_upload', 'N/A')}")
            
            # Update password to "admin" if needed
            try:
                admin_user.hashed_password = get_password_hash("admin")
                admin_user.is_admin = True
                if hasattr(admin_user, 'can_upload'):
                    admin_user.can_upload = True
                if hasattr(admin_user, 'full_name'):
                    if not admin_user.full_name:
                        admin_user.full_name = "Administrator"
                db.commit()
                print("[OK] Admin password reset to 'admin'")
            except Exception as e:
                print(f"[WARNING] Could not update all fields: {e}")
                db.rollback()
                # Try just password
                admin_user.hashed_password = get_password_hash("admin")
                admin_user.is_admin = True
                db.commit()
                print("[OK] Admin password reset to 'admin' (basic update only)")
        else:
            # Create new admin user
            try:
                admin_user = User(
                    username="admin",
                    email=None,  # No email needed
                    hashed_password=get_password_hash("admin"),
                    is_admin=True,
                    can_upload=True,
                    full_name="Administrator"
                )
                db.add(admin_user)
                db.commit()
                print("[OK] Default admin user created!")
                print("  Username: admin")
                print("  Password: admin")
            except Exception as e:
                # If can_upload or full_name columns don't exist, try without them
                print(f"[WARNING] Error with new fields: {e}")
                print("Trying with basic fields...")
                db.rollback()
                admin_user = User(
                    username="admin",
                    email=None,  # No email needed
                    hashed_password=get_password_hash("admin"),
                    is_admin=True
                )
                db.add(admin_user)
                db.commit()
                print("[OK] Admin user created (basic fields only)")
                print("  Username: admin")
                print("  Password: admin")
                print("  Note: Some fields may be missing - restart server to update schema")
                
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()
