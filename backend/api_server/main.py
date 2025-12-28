"""
API Server - Main FastAPI application on port 9000
Handles authentication, documents, and chat
"""
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import httpx
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.shared.database import get_db, init_db, User, Chat, Message, Document
from backend.shared.document_processor import extract_text, split_text_into_chunks
from backend.shared.llm_providers import get_embedding
from backend.shared.vector_db import add_documents, init_vector_db
from backend.api_server.auth import verify_password, get_password_hash, create_access_token, decode_access_token
from backend.api_server.models import (
    MessageRequest,
    UserCreate, UserLogin, UserResponse, Token,
    ChatCreate, ChatResponse, MessageCreate, MessageResponse,
    DocumentUploadResponse, QueryRequest, QueryResponse, AdminUserCreate
)
import config

# Initialize database
init_db()
init_vector_db()

app = FastAPI(title="BNO LLM Assistant API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:9000", "http://localhost:9000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (frontend) - serve from root
frontend_path = Path(__file__).parent.parent.parent / "frontend"
if frontend_path.exists():
    # Serve CSS and JS files from root
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
    # Also serve individual files from root for easier access
    @app.get("/styles.css")
    async def get_styles():
        return FileResponse(str(frontend_path / "styles.css"))
    
    @app.get("/app.js")
    async def get_app_js():
        return FileResponse(str(frontend_path / "app.js"))


# ============================================================================
# Dependency: Get current user from token
# ============================================================================
async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    
    return user


# ============================================================================
# Authentication Routes
# ============================================================================
@app.post("/api/auth/register", response_model=UserResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    # Check if user exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    # Email is optional, no need to check for duplicates
    
    # Create user
    hashed_password = get_password_hash(user_data.password)
    user = User(
        username=user_data.username,
        email=user_data.email if user_data.email else None,  # Optional
        hashed_password=hashed_password
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@app.post("/api/auth/login")
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and get access token"""
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email if user.email else None,
                "is_admin": user.is_admin,
                "can_upload": getattr(user, 'can_upload', True),
                "full_name": getattr(user, 'full_name', user.username)
            }
    }


@app.get("/api/auth/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


# ============================================================================
# Chat Routes
# ============================================================================
@app.get("/api/chats", response_model=List[ChatResponse])
async def get_chats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all chats for current user with messages for title generation"""
    chats = db.query(Chat).filter(Chat.user_id == current_user.id).order_by(Chat.updated_at.desc()).all()
    
    # Include first message for each chat to generate titles if needed
    result = []
    for chat in chats:
        # Get first user message for title generation
        first_message = db.query(Message).filter(
            Message.chat_id == chat.id,
            Message.role == 'user'
        ).order_by(Message.created_at.asc()).first()
        
        chat_dict = {
            "id": chat.id,
            "title": chat.title,
            "created_at": chat.created_at.isoformat() if chat.created_at else None,
            "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
            "messages": [{"id": first_message.id, "role": first_message.role, "content": first_message.content, "created_at": first_message.created_at.isoformat() if first_message.created_at else None}] if first_message else []
        }
        result.append(chat_dict)
    
    return result


@app.post("/api/chats", response_model=ChatResponse)
async def create_chat(chat_data: ChatCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new chat"""
    chat = Chat(
        user_id=current_user.id,
        title=chat_data.title
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@app.get("/api/chats/{chat_id}", response_model=ChatResponse)
async def get_chat(chat_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a specific chat"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a chat - fully removes chat and all messages (cascade delete)"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    # Cascade delete will automatically remove all messages
    db.delete(chat)
    db.commit()
    
    # Verify deletion
    verify_chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if verify_chat:
        raise HTTPException(status_code=500, detail="Chat deletion failed")
    
    return {"message": "Chat deleted successfully"}


@app.post("/api/chats/bulk-delete")
async def bulk_delete_chats(chat_ids: List[int], current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete multiple chats"""
    chats = db.query(Chat).filter(Chat.id.in_(chat_ids), Chat.user_id == current_user.id).all()
    for chat in chats:
        db.delete(chat)
    db.commit()
    return {"message": f"Deleted {len(chats)} chats"}


# ============================================================================
# Chat Routes (matching frontend expectations)
# ============================================================================
@app.get("/api/chat/chats", response_model=List[ChatResponse])
async def get_chats_v2(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all chats for current user (v2 endpoint)"""
    chats = db.query(Chat).filter(Chat.user_id == current_user.id).order_by(Chat.updated_at.desc()).all()
    # Include messages in response
    result = []
    for chat in chats:
        messages = db.query(Message).filter(Message.chat_id == chat.id).order_by(Message.created_at.asc()).all()
        chat_dict = {
            "id": chat.id,
            "title": chat.title,
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in messages]
        }
        result.append(chat_dict)
    return result


@app.get("/api/chat/chats/{chat_id}")
async def get_chat_v2(chat_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get a specific chat with messages (v2 endpoint)"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at.asc()).all()
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at} for m in messages]
    }


@app.put("/api/chat/chats/{chat_id}")
async def update_chat(chat_id: int, chat_data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update chat (e.g., rename)"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    if "title" in chat_data:
        chat.title = chat_data["title"]
        db.commit()
        db.refresh(chat)
    
    return chat


@app.delete("/api/chat/chats/{chat_id}")
async def delete_chat_v2(chat_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a chat (v2 endpoint)"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return {"message": "Chat deleted"}


@app.post("/api/chat/bulk-delete-chats")
async def bulk_delete_chats_v2(request: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete multiple chats (v2 endpoint)"""
    chat_ids = request.get("chat_ids", [])
    chats = db.query(Chat).filter(Chat.id.in_(chat_ids), Chat.user_id == current_user.id).all()
    for chat in chats:
        db.delete(chat)
    db.commit()
    return {"message": f"Deleted {len(chats)} chats"}


@app.post("/api/chat/message")
async def send_message_v2(request: MessageRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a message in a chat (v2 endpoint)"""
    content = request.content
    chat_id = request.chat_id
    
    if not content:
        raise HTTPException(status_code=400, detail="Message content is required")
    
    # Get or create chat
    if chat_id:
        chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        # Create new chat
        chat = Chat(user_id=current_user.id, title=content[:50])
        db.add(chat)
        db.commit()
        db.refresh(chat)
    
    # Save user message
    user_message = Message(chat_id=chat.id, role="user", content=content)
    db.add(user_message)
    db.commit()
    
    # Call LLM server
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"http://{config.LLM_SERVER_HOST}:{config.LLM_SERVER_PORT}/query",
                json={"query": content}
            )
            response.raise_for_status()
            result = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calling LLM server: {str(e)}")
    
    # Save assistant message
    assistant_message = Message(chat_id=chat.id, role="assistant", content=result["response"])
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    
    # Update chat timestamp
    chat.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "chat_id": chat.id,
        "response": result["response"],  # Add response field for compatibility
        "assistant_reply": {
            "id": assistant_message.id,
            "role": "assistant",
            "content": result["response"],
            "created_at": assistant_message.created_at
        }
    }


@app.get("/api/chats/{chat_id}/messages", response_model=List[MessageResponse])
async def get_messages(chat_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get messages for a chat"""
    chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at.asc()).all()
    return messages


# ============================================================================
# Query/Question Routes
# ============================================================================
@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Process a query using RAG"""
    # Get or create chat
    if request.chat_id:
        chat = db.query(Chat).filter(Chat.id == request.chat_id, Chat.user_id == current_user.id).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        # Create new chat
        chat = Chat(user_id=current_user.id, title=request.query[:50])
        db.add(chat)
        db.commit()
        db.refresh(chat)
    
    # Save user message
    user_message = Message(chat_id=chat.id, role="user", content=request.query)
    db.add(user_message)
    db.commit()
    
    # Call LLM server
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"http://{config.LLM_SERVER_HOST}:{config.LLM_SERVER_PORT}/query",
                json={"query": request.query}
            )
            response.raise_for_status()
            result = response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calling LLM server: {str(e)}")
    
    # Save assistant message
    assistant_message = Message(chat_id=chat.id, role="assistant", content=result["response"])
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    
    # Update chat timestamp
    chat.updated_at = datetime.utcnow()
    db.commit()
    
    return QueryResponse(
        response=result["response"],
        chat_id=chat.id,
        message_id=assistant_message.id
    )


# ============================================================================
# Document Routes
# ============================================================================
@app.post("/api/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload and process a document"""
    # Check file type
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {file_ext} not allowed")
    
    # Check file size
    file_content = await file.read()
    file_size = len(file_content)
    if file_size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large. Max size: {config.MAX_FILE_SIZE_MB}MB")
    
    # Save file
    file_path = config.DOCUMENTS_DIR / f"{current_user.id}_{datetime.utcnow().timestamp()}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    # Create database record
    doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=str(file_path),
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        processed=False,
        title=title or file.filename
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # Process document in background (for now, synchronous)
    try:
        # Extract text
        text = extract_text(str(file_path), file_ext)
        
        if len(text) < 50:
            raise ValueError(f"Extracted very little text ({len(text)} characters). The document may be corrupted or image-based.")
        
        # Split into chunks
        chunks = split_text_into_chunks(text)
        
        if len(chunks) == 0:
            raise ValueError("No chunks created from document text.")
        
        # Generate embeddings
        print(f"[DEBUG] Generating {len(chunks)} embeddings for {file.filename}...")
        embeddings = []
        for i, chunk in enumerate(chunks, 1):
            try:
                embedding = get_embedding(chunk)
                embeddings.append(embedding)
            except Exception as e:
                raise Exception(f"Failed to generate embedding for chunk {i}/{len(chunks)}: {str(e)}")
        
        # Add to vector database
        metadata = [{"user_id": current_user.id, "document_id": doc.id}] * len(chunks)
        print(f"[DEBUG] Adding {len(chunks)} chunks to vector database...")
        add_documents(chunks, embeddings, metadata)
        print(f"[DEBUG] Added {len(chunks)} chunks to vector database")
        
        # Update chunk count
        doc.chunk_count = len(chunks)
        
        # Mark as processed
        doc.processed = True
        db.commit()
        
    except Exception as e:
        # Log full error for debugging
        import traceback
        error_msg = f"Error processing document {file.filename}: {str(e)}"
        print(f"[ERROR] {error_msg}")
        traceback.print_exc()
        
        # Update document to show it failed
        doc.processed = False
        doc.chunk_count = 0
        db.commit()
        
        # Return document but with error info - frontend can check processed status
        # Don't raise exception so upload appears successful, but document shows as unprocessed
    
    return doc


@app.get("/api/documents", response_model=List[DocumentUploadResponse])
async def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all documents (global/shared) - only accessible to users with upload permission"""
    # Only users with upload access can view documents
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to view documents")
    
    # Return all documents (global/shared) for users with upload access
    # CRITICAL: No user_id filter - all documents are shared globally across all users with upload access
    # This means ALL users with can_upload=True see the SAME documents
    documents = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    
    # Explicit debug logging to verify behavior
    print(f"[DOCUMENTS API] User '{current_user.username}' (id: {current_user.id}, can_upload: {current_user.can_upload}, is_admin: {current_user.is_admin})")
    print(f"[DOCUMENTS API] Query executed: db.query(Document).order_by(Document.uploaded_at.desc()).all()")
    print(f"[DOCUMENTS API] Total documents in database: {db.query(Document).count()}")
    print(f"[DOCUMENTS API] Returning {len(documents)} documents (GLOBAL/SHARED - no user_id filter)")
    for i, doc in enumerate(documents, 1):
        print(f"[DOCUMENTS API]   Document {i}: {doc.filename} (id: {doc.id}, user_id: {doc.user_id})")
    
    return documents


@app.get("/api/documents/stats")
async def get_document_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get document statistics - only accessible to users with upload permission"""
    # Only users with upload access can view document stats
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to view document statistics")
    
    # Get all documents (global/shared)
    documents = db.query(Document).all()
    
    # Calculate statistics
    total_documents = len(documents)
    total_chunks = sum(doc.chunk_count or 0 for doc in documents)
    total_size = sum(doc.file_size or 0 for doc in documents)
    
    return {
        "total_documents": total_documents,
        "total_chunks": total_chunks,
        "total_size": total_size
    }


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a document - fully removes file, database record, and all vector chunks"""
    from backend.shared.vector_db import delete_documents
    
    # Only users with upload access or admins can delete documents
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to delete documents")
    
    # Documents are global, so any user with upload access can delete any document
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 1. Delete all chunks from vector database (synchronized deletion)
    try:
        delete_documents(document_ids=[str(doc.id)], user_id=current_user.id)
        print(f"[DELETE] Removed {doc.chunk_count} chunks from vector database for document {doc.id}")
    except Exception as e:
        print(f"[WARNING] Error deleting chunks from vector DB: {e}")
        # Continue with deletion even if vector DB deletion fails
    
    # 2. Delete physical file
    if os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
            print(f"[DELETE] Removed file: {doc.file_path}")
        except Exception as e:
            print(f"[WARNING] Error deleting file: {e}")
    
    # 3. Delete from database (cascade will handle any related data)
    db.delete(doc)
    db.commit()
    
    # 4. Verify deletion
    verify_doc = db.query(Document).filter(Document.id == document_id).first()
    if verify_doc:
        raise HTTPException(status_code=500, detail="Document deletion failed - still exists in database")
    
    return {"message": "Document and all associated data deleted successfully"}


# ============================================================================
# Admin Routes
# ============================================================================
@app.get("/api/admin/users", response_model=List[UserResponse])
async def get_all_users(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all users (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = db.query(User).all()
    return users


@app.post("/api/admin/users", response_model=UserResponse)
async def create_user(user_data: AdminUserCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new user (admin only)"""
    try:
        if not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        from backend.api_server.auth import get_password_hash
        
        # Check if username already exists
        existing = db.query(User).filter(User.username == user_data.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Validate password length
        if len(user_data.password) < 3:
            raise HTTPException(status_code=400, detail="Password must be at least 3 characters")
        
        # Create user
        try:
            password_hash = get_password_hash(user_data.password)
        except Exception as e:
            print(f"Error hashing password: {e}")
            raise HTTPException(status_code=500, detail=f"Error processing password: {str(e)}")
        
        new_user = User(
            username=user_data.username,
            hashed_password=password_hash,
            full_name=user_data.full_name,
            can_upload=user_data.can_upload,
            is_admin=user_data.is_admin
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        return new_user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating user: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@app.put("/api/admin/users/{user_id}")
async def update_user(user_id: int, user_data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update user (admin only)"""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields
    if "can_upload" in user_data:
        user.can_upload = user_data["can_upload"]
    if "is_admin" in user_data:
        user.is_admin = user_data["is_admin"]
    if "full_name" in user_data:
        user.full_name = user_data["full_name"]
    
    db.commit()
    db.refresh(user)
    
    return {"message": "User updated successfully"}


# ============================================================================
# Root and Health
# ============================================================================
@app.get("/")
async def root():
    """Serve frontend"""
    frontend_index = frontend_path / "index.html"
    if frontend_index.exists():
        return FileResponse(str(frontend_index))
    return {"message": "BNO LLM Assistant API", "status": "running"}


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "service": "API Server"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.API_SERVER_HOST,
        port=config.API_SERVER_PORT,
        log_level="info"
    )

