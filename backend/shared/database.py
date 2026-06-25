"""
Database models and connection for user management and chat history
"""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import config

Base = declarative_base()

# Database connection
engine = create_engine(f"sqlite:///{config.DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class User(Base):
    """User model for authentication"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, nullable=True)  # Optional, no unique constraint needed
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    can_upload = Column(Boolean, default=True)  # Add can_upload field
    full_name = Column(String, nullable=True)  # Add full_name field
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")


class Chat(Base):
    """Chat conversation model"""
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    """Individual message in a chat"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    chat = relationship("Chat", back_populates="messages")


class Document(Base):
    """Uploaded document metadata"""
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)  # pdf, docx, pptx, txt
    file_size = Column(Integer, nullable=False)  # in bytes
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processed = Column(Boolean, default=False)  # Whether it's been indexed
    status = Column(String, default="processing")  # processing | indexed | failed
    error_message = Column(Text, nullable=True)  # Why indexing failed (if it did)
    title = Column(String, nullable=True)  # Add title field
    chunk_count = Column(Integer, default=0)  # Add chunk_count field
    
    # Relationships
    user = relationship("User", back_populates="documents")


def _run_lightweight_migrations():
    """Add columns that were introduced after the first release.

    SQLite's create_all() won't alter existing tables, so on an upgraded
    deployment we add any missing columns here. Safe to run on every startup.
    """
    from sqlalchemy import text
    wanted = {
        "status": "VARCHAR DEFAULT 'processing'",
        "error_message": "TEXT",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(documents)"))}
        for col, ddl in wanted.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {ddl}"))
                conn.commit()
                print(f"[migration] Added documents.{col}")
        # Backfill status from the older processed flag for existing rows
        if "status" not in existing:
            conn.execute(text(
                "UPDATE documents SET status = CASE WHEN processed = 1 THEN 'indexed' ELSE 'failed' END"
            ))
            conn.commit()


def init_db():
    """Initialize database tables and create default admin user"""
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()
    
    # Create default admin user if it doesn't exist
    db = SessionLocal()
    try:
        from backend.api_server.auth import get_password_hash
        
        admin_username = getattr(config, "ADMIN_USERNAME", "admin")
        admin_password = getattr(config, "ADMIN_PASSWORD", "admin")
        admin_user = db.query(User).filter(User.username == admin_username).first()
        if not admin_user:
            admin_user = User(
                username=admin_username,
                email=None,  # No email needed
                hashed_password=get_password_hash(admin_password),
                is_admin=True,
                can_upload=True,
                full_name="Administrator"
            )
            db.add(admin_user)
            db.commit()
            if admin_password == "admin":
                print(f"✓ Default admin user created (username: {admin_username}, password: admin) "
                      "- CHANGE THIS via ADMIN_PASSWORD in .env for production")
            else:
                print(f"✓ Admin user created (username: {admin_username})")
    except Exception as e:
        print(f"Error creating default admin user: {e}")
        db.rollback()
    finally:
        db.close()


def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
