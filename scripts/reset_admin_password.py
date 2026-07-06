"""
Recovery script: reset the admin account's password (use if you're locked out).

Replaces the old create_admin.py, which silently reset ANY existing admin
account's password back to the literal string "admin" every time it ran -
a real security risk if it was ever re-run on a live server by mistake. This
version:
  - Only touches the account named in ADMIN_USERNAME (.env), never a hardcoded
    "admin" username if you've configured something else.
  - Prompts for a new password (hidden input) instead of using a fixed default.
  - Enforces the same password policy (MIN_PASSWORD_LENGTH) as the app itself.
  - Creates the admin account if it doesn't exist yet; otherwise just resets
    its password without touching any other fields.

Usage:
    python scripts/reset_admin_password.py
"""
import sys
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backend.shared.database import SessionLocal, User, Base, engine
from backend.api_server.auth import get_password_hash, validate_password_strength


def reset_admin_password():
    admin_username = getattr(config, "ADMIN_USERNAME", "admin")

    Base.metadata.create_all(bind=engine)

    password = getpass.getpass(f"New password for '{admin_username}': ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm:
        print("[ERROR] Passwords did not match. No changes made.")
        sys.exit(1)

    error = validate_password_strength(password)
    if error:
        print(f"[ERROR] {error}")
        sys.exit(1)

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.username == admin_username).first()
        if admin_user:
            admin_user.hashed_password = get_password_hash(password)
            admin_user.is_admin = True
            db.commit()
            print(f"[OK] Password reset for existing admin account '{admin_username}'.")
        else:
            admin_user = User(
                username=admin_username,
                email=None,
                hashed_password=get_password_hash(password),
                is_admin=True,
                can_upload=True,
                full_name="Administrator",
            )
            db.add(admin_user)
            db.commit()
            print(f"[OK] Admin account '{admin_username}' did not exist - created it.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    reset_admin_password()
