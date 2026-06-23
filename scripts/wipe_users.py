"""
Maintenance script: wipe all user accounts EXCEPT the admin account.

Deletes every user whose username is not the configured admin username, along
with their chats and messages (cascade). Useful before/after go-live to clear
out test accounts and leave a clean slate with only the admin.

Usage:
    python scripts/wipe_users.py            # interactive (asks for confirmation)
    python scripts/wipe_users.py --yes      # non-interactive (no prompt)

The admin account is preserved. If it does not exist, it is created using
ADMIN_USERNAME / ADMIN_PASSWORD from your environment (.env).
"""
import sys
from pathlib import Path

# Add project root to path (parent of scripts directory)
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from backend.shared.database import SessionLocal, User, Base, engine
from backend.api_server.auth import get_password_hash


def wipe_users(assume_yes: bool = False):
    admin_username = getattr(config, "ADMIN_USERNAME", "admin")

    # Make sure tables exist (safe no-op if they do)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Ensure the admin account exists and stays
        admin_user = db.query(User).filter(User.username == admin_username).first()
        if not admin_user:
            admin_password = getattr(config, "ADMIN_PASSWORD", "admin")
            admin_user = User(
                username=admin_username,
                email=None,
                hashed_password=get_password_hash(admin_password),
                is_admin=True,
                can_upload=True,
                full_name="Administrator",
            )
            db.add(admin_user)
            db.commit()
            print(f"[OK] Admin account '{admin_username}' did not exist - created it.")

        # Everyone who is NOT the admin account
        others = db.query(User).filter(User.username != admin_username).all()

        if not others:
            print(f"[OK] No non-admin accounts to remove. Only '{admin_username}' remains.")
            return

        print(f"The following {len(others)} account(s) will be PERMANENTLY deleted")
        print("(along with their chats and messages):")
        for u in others:
            flags = []
            if u.is_admin:
                flags.append("admin")
            if getattr(u, "can_upload", False):
                flags.append("can_upload")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            print(f"   - {u.username}{suffix}")

        if not assume_yes:
            answer = input("\nType 'wipe' to confirm: ").strip().lower()
            if answer != "wipe":
                print("Aborted. No changes made.")
                return

        count = 0
        for u in others:
            db.delete(u)  # cascade removes chats/messages/documents owned by the user
            count += 1
        db.commit()
        print(f"[OK] Deleted {count} account(s). Only '{admin_username}' remains.")
        print("Note: vector-store chunks from deleted users' documents are not removed here;")
        print("      delete documents via the app UI if you also want to clear the index.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    assume_yes = "--yes" in sys.argv or "-y" in sys.argv
    wipe_users(assume_yes=assume_yes)
