"""
API Server - Main FastAPI application on port 9000
Handles authentication, documents, and chat
"""
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Header, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import json
import threading
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.shared.database import get_db, init_db, User, Chat, Message, Document, SessionLocal
from backend.shared.document_processor import extract_text, split_text_into_chunks, extract_images_from_document
from backend.shared.llm_providers import get_embedding, get_embeddings_batch, describe_image, _clean_response as clean_llm_response
from backend.shared.vector_db import add_documents, init_vector_db
from backend.api_server.auth import (
    verify_password, get_password_hash, create_access_token, decode_access_token,
    validate_password_strength,
)
from backend.api_server.models import (
    MessageRequest,
    UserCreate, UserLogin, UserResponse, Token,
    ChatCreate, ChatResponse, MessageCreate, MessageResponse,
    DocumentUploadResponse, QueryRequest, QueryResponse, AdminUserCreate,
    ChangePasswordRequest, ResetPasswordRequest,
)
from backend.middleware.error_handler import error_handler_middleware
from backend.middleware.logging_middleware import logging_middleware
from backend.utils.logging import setup_logging
import config

# Setup logging
logger = setup_logging()

# Initialize database and RAG (same process = upload and query share ChromaDB, no sync issues)
init_db()
init_vector_db()
from backend.llm_server.rag_engine import RAGEngine
_rag_engine = RAGEngine()

app = FastAPI(title="BNO LLM Assistant API", version="1.0.0")

# Add middleware (order matters - error handler should be last)
app.middleware("http")(logging_middleware)
app.middleware("http")(error_handler_middleware)

# CORS middleware
# The frontend is served from the same origin as the API, so CORS normally isn't
# needed. These defaults cover local dev; set CORS_ORIGINS in .env (comma-separated)
# if you ever serve the UI from a different host than the API.
_cors_origins = os.getenv("CORS_ORIGINS", "http://127.0.0.1:9000,http://localhost:9000")
allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
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
    # no-cache (not no-store) so browsers always revalidate with the server
    # before using a cached copy - deploys take effect on next reload instead
    # of silently running stale JS/CSS until someone hard-refreshes.
    _no_cache_headers = {"Cache-Control": "no-cache, must-revalidate"}

    @app.get("/styles.css")
    async def get_styles():
        return FileResponse(str(frontend_path / "styles.css"), headers=_no_cache_headers)

    @app.get("/app.js")
    async def get_app_js():
        return FileResponse(str(frontend_path / "app.js"), headers=_no_cache_headers)


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
    """Register a new user (disabled by default in production).

    Open self-registration is gated behind config.ALLOW_REGISTRATION. In a
    corporate deployment accounts are created by an admin instead.
    """
    if not getattr(config, "ALLOW_REGISTRATION", False):
        raise HTTPException(
            status_code=403,
            detail="Self-registration is disabled. Please contact an administrator for an account.",
        )

    # Enforce password policy
    pw_error = validate_password_strength(user_data.password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)

    # Check if user exists
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    # Email is optional, no need to check for duplicates
    
    # Create user - self-registered users get NO upload/admin privileges by default
    hashed_password = get_password_hash(user_data.password)
    user = User(
        username=user_data.username,
        email=user_data.email if user_data.email else None,  # Optional
        hashed_password=hashed_password,
        can_upload=False,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


# Simple in-memory login throttle (single-process app). Maps client IP -> list of
# recent failed-attempt timestamps. Good enough for brute-force slowdown; for a
# multi-instance deployment, move this to a shared store (e.g. Redis).
import time as _time
_login_attempts = {}


def _client_ip(request: Request) -> str:
    """Best-effort client IP, honoring X-Forwarded-For when behind a reverse proxy."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_login_rate_limit(ip: str):
    window = config.LOGIN_WINDOW_MINUTES * 60
    now = _time.time()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < window]
    _login_attempts[ip] = attempts
    if len(attempts) >= config.LOGIN_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in {config.LOGIN_WINDOW_MINUTES} minutes.",
        )


def _record_login_failure(ip: str):
    _login_attempts.setdefault(ip, []).append(_time.time())


@app.post("/api/auth/login")
async def login(credentials: UserLogin, request: Request, db: Session = Depends(get_db)):
    """Login and get access token"""
    ip = _client_ip(request)
    _check_login_rate_limit(ip)
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        _record_login_failure(ip)
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # Successful login clears the failure counter for this IP
    _login_attempts.pop(ip, None)
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


@app.post("/api/auth/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Allow the logged-in user to change their own password."""
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    pw_error = validate_password_strength(payload.new_password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)

    if verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="New password must be different from the current password")

    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


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

    # Run RAG in-process so we see the same ChromaDB as uploads (no cross-process sync issues)
    try:
        result = await asyncio.to_thread(_rag_engine.query, content)
        llm_response = (result.get("response") or "").strip()
    except Exception as e:
        import traceback
        error_detail = f"Error running RAG: {str(e)}"
        logger.exception(error_detail)
        raise HTTPException(status_code=500, detail=error_detail)
    if not llm_response:
        llm_response = "I apologize, but I didn't receive a response. Please try again."
    
    # Save assistant message
    assistant_message = Message(chat_id=chat.id, role="assistant", content=llm_response)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    
    # Update chat timestamp
    chat.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "chat_id": chat.id,
        "response": llm_response,  # Add response field for compatibility
        "assistant_reply": {
            "id": assistant_message.id,
            "role": "assistant",
            "content": llm_response,
            "created_at": assistant_message.created_at
        }
    }


@app.post("/api/chat/message/stream")
async def send_message_stream(request: MessageRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send a message and stream the answer back as it's generated (Server-Sent
    Events style: newline-delimited "data: {json}\\n\\n" frames).

    Streaming makes long CPU-bound generations feel much faster - the first
    words show up in a few seconds instead of waiting for the entire answer.
    """
    content = request.content
    chat_id = request.chat_id

    if not content:
        raise HTTPException(status_code=400, detail="Message content is required")

    if chat_id:
        chat = db.query(Chat).filter(Chat.id == chat_id, Chat.user_id == current_user.id).first()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        chat = Chat(user_id=current_user.id, title=content[:50])
        db.add(chat)
        db.commit()
        db.refresh(chat)

    user_message = Message(chat_id=chat.id, role="user", content=content)
    db.add(user_message)
    db.commit()

    chat_id_final = chat.id

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL_END = object()

        def producer():
            try:
                for piece in _rag_engine.query_stream(content):
                    loop.call_soon_threadsafe(queue.put_nowait, piece)
            except Exception as e:
                logger.exception(f"Error during streamed RAG generation: {e}")
                loop.call_soon_threadsafe(queue.put_nowait, {"__error__": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL_END)

        threading.Thread(target=producer, daemon=True).start()

        raw_text = ""
        errored = False
        while True:
            item = await queue.get()
            if item is SENTINEL_END:
                break
            if isinstance(item, dict) and "__error__" in item:
                errored = True
                yield _sse({"type": "error", "detail": "Something went wrong generating the response. Please try again."})
                continue
            raw_text += item
            yield _sse({"type": "chunk", "text": item})

        if errored:
            return

        final_response = clean_llm_response(raw_text) or raw_text.strip()
        if not final_response:
            final_response = "I apologize, but I didn't receive a response. Please try again."

        # New DB session: the request-scoped one may be tied to a different
        # thread/loop context by the time this generator finishes streaming.
        stream_db = SessionLocal()
        try:
            assistant_message = Message(chat_id=chat_id_final, role="assistant", content=final_response)
            stream_db.add(assistant_message)
            stream_db.commit()
            stream_db.refresh(assistant_message)

            chat_row = stream_db.query(Chat).filter(Chat.id == chat_id_final).first()
            if chat_row:
                chat_row.updated_at = datetime.utcnow()
                stream_db.commit()

            yield _sse({
                "type": "done",
                "chat_id": chat_id_final,
                "response": final_response,
                "message_id": assistant_message.id,
            })
        finally:
            stream_db.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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

    # Run RAG in-process so we see the same ChromaDB as uploads (no cross-process sync issues)
    try:
        result = await asyncio.to_thread(_rag_engine.query, request.query)
        rag_response = (result.get("response") or "").strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running RAG: {str(e)}")

    # Save assistant message
    assistant_message = Message(chat_id=chat.id, role="assistant", content=rag_response)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    
    # Update chat timestamp
    chat.updated_at = datetime.utcnow()
    db.commit()
    
    return QueryResponse(
        response=rag_response,
        chat_id=chat.id,
        message_id=assistant_message.id
    )


# ============================================================================
# Document Routes
# ============================================================================
def process_document_job(doc_id: int):
    """Index an uploaded document: extract -> chunk -> embed (batched) -> store.

    Runs in a background thread with its own DB session so the upload request can
    return immediately. Marks the document processed=True on success, or leaves it
    processed=False (chunk_count=0) on failure so the UI shows it didn't index.
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            print(f"[INDEX] Document {doc_id} not found; skipping")
            return

        try:
            size_mb = (os.path.getsize(doc.file_path) / (1024 * 1024))
        except OSError:
            size_mb = 0.0
        print(f"[INDEX] doc {doc_id}: START '{doc.filename}' ({doc.file_type}, {size_mb:.1f} MB)", flush=True)

        image_exts = {ext.lstrip('.') for ext in config.IMAGE_EXTENSIONS}
        if doc.file_type.lower() in image_exts:
            # Standalone image upload (not embedded in a document) - the image
            # IS the content, so it can only be indexed via vision description.
            if not (config.ENABLE_VISION_EXTRACTION and config.OPENAI_CONFIG.get("api_key")):
                raise ValueError(
                    "This is an image file, which can only be indexed with vision "
                    "extraction enabled (ENABLE_VISION_EXTRACTION=true and a valid "
                    "OPENAI_API_KEY in .env). Enable that, or embed this image inside "
                    "a PDF/Word/PowerPoint document and upload that instead."
                )
            with open(doc.file_path, "rb") as f:
                image_bytes = f.read()
            description = describe_image(image_bytes, doc.file_type)
            if not description or not description.strip():
                raise ValueError(
                    "Vision description of this image came back empty - it may be "
                    "corrupted, unreadable, or the OpenAI call failed."
                )
            chunks = [description.strip()]
        else:
            print(f"[INDEX] doc {doc_id}: extracting text...", flush=True)
            text = extract_text(doc.file_path, f".{doc.file_type}")
            chunks = split_text_into_chunks(text) if text else []
            print(f"[INDEX] doc {doc_id}: extracted {len(text)} chars -> {len(chunks)} text chunk(s)", flush=True)

            # Optional: describe embedded images/diagrams via OpenAI vision so their
            # content becomes searchable too. Fully opt-in (config.ENABLE_VISION_EXTRACTION),
            # covers PDF/PPTX/DOCX (not yet legacy .doc/.ppt/.xls), and never fails the
            # whole indexing job - a bad/uncallable image is just skipped. Deliberately
            # runs BEFORE the "too little text" check below: image-heavy slide decks/
            # design docs often have very little raw text and rely entirely on vision
            # to become searchable at all.
            if config.ENABLE_VISION_EXTRACTION and config.OPENAI_CONFIG.get("api_key"):
                try:
                    images = extract_images_from_document(doc.file_path, doc.file_type)
                    print(f"[VISION] doc {doc_id}: found {len(images)} candidate image(s) to describe")
                    if images:
                        # Describe images concurrently (network-bound OpenAI calls) instead
                        # of one-at-a-time - cuts wall-clock time a lot on figure-heavy docs.
                        # Small pool size so one document upload doesn't hog OpenAI rate limits.
                        from concurrent.futures import ThreadPoolExecutor
                        max_workers = min(5, len(images))
                        with ThreadPoolExecutor(max_workers=max_workers) as pool:
                            described = list(pool.map(
                                lambda item: (item[0], describe_image(item[1], item[2])),
                                images,
                            ))
                        # Preserve document order (page 1's image before page 2's, etc.)
                        # even though calls completed out of order.
                        for location_label, description in described:
                            if description and description.strip():
                                chunks.append(f"[Image on {location_label}]: {description.strip()}")
                except Exception as e:
                    # Vision extraction is a bonus, not a requirement - log and move on.
                    print(f"[VISION] doc {doc_id}: image description step failed, continuing without it: {e}")

            if len(text) < 50 and not chunks:
                raise ValueError(
                    f"Extracted very little text ({len(text)} chars) and no usable "
                    "images. The document may be empty, corrupted, or image-based "
                    "(needs OCR)."
                )
            if not chunks:
                raise ValueError("No chunks created from document text.")

        # Embed in batches (far faster than one request per chunk)
        batch_size = getattr(config, "EMBED_BATCH_SIZE", 32)
        embeddings = []
        total = len(chunks)
        for start in range(0, total, batch_size):
            batch = chunks[start:start + batch_size]
            embeddings.extend(get_embeddings_batch(batch))
            print(f"[INDEX] doc {doc_id}: embedded {min(start + batch_size, total)}/{total} chunks", flush=True)

        metadata = [
            {"user_id": doc.user_id, "document_id": str(doc.id), "filename": doc.filename}
        ] * len(chunks)
        add_documents(chunks, embeddings, metadata)

        doc.chunk_count = len(chunks)
        doc.processed = True
        doc.status = "indexed"
        doc.error_message = None
        db.commit()
        print(f"[INDEX] Document {doc_id} ({doc.filename}) indexed: {len(chunks)} chunks")
    except Exception as e:
        import traceback
        print(f"[INDEX][ERROR] Document {doc_id} failed: {e}")
        traceback.print_exc()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.processed = False
                doc.chunk_count = 0
                doc.status = "failed"
                doc.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@app.post("/api/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload and process a document"""
    # Permission: only users who can upload (or admins) may add documents
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="You do not have permission to upload documents")

    # Check file type
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {file_ext} not allowed")

    # Stream the upload straight to disk in 1MB chunks, enforcing the size limit
    # as we go. This keeps memory flat (~1MB) even for a 100MB upload instead of
    # loading the whole file into RAM.
    max_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
    file_path = config.DOCUMENTS_DIR / f"{current_user.id}_{datetime.utcnow().timestamp()}_{file.filename}"
    file_size = 0
    CHUNK_BYTES = 1024 * 1024
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > max_bytes:
                    f.close()
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max size: {config.MAX_FILE_SIZE_MB}MB",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    if file_size == 0:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Check for existing documents with the same filename and delete their chunks first
    # This prevents duplication when re-uploading the same file; also remove old DB rows and files
    from backend.shared.vector_db import delete_documents
    existing_docs = db.query(Document).filter(Document.filename == file.filename).all()
    if existing_docs:
        print(f"[DEBUG] Found {len(existing_docs)} existing document(s) with filename '{file.filename}', cleaning up old chunks and DB rows...")
        for existing_doc in existing_docs:
            try:
                delete_documents(document_ids=[str(existing_doc.id)])
                print(f"[DEBUG] Deleted chunks for existing document ID {existing_doc.id}")
            except Exception as e:
                print(f"[DEBUG] Error deleting chunks for document {existing_doc.id}: {e}")
            # Remove old file from disk if it still exists
            old_path = existing_doc.file_path
            if old_path and os.path.exists(old_path):
                try:
                    os.remove(old_path)
                    print(f"[DEBUG] Removed old file: {old_path}")
                except Exception as e:
                    print(f"[DEBUG] Error removing old file {old_path}: {e}")
            # Remove old document row so we don't have duplicate/orphan entries
            db.delete(existing_doc)
        db.commit()

    # Create database record (status starts as 'processing' until the bg job finishes)
    doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_path=str(file_path),
        file_type=file_ext.lstrip('.'),
        file_size=file_size,
        processed=False,
        status="processing",
        title=title or file.filename
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Index the document in the BACKGROUND so the request returns immediately.
    # This avoids client/proxy timeouts and keeps the server responsive even for
    # large files. The document shows as "Processing" until indexing finishes.
    background_tasks.add_task(process_document_job, doc.id)
    print(f"[DEBUG] Document {doc.id} ({file.filename}) queued for background indexing")

    return doc


@app.get("/api/documents", response_model=List[DocumentUploadResponse])
async def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all documents (global/shared) - only accessible to users with upload permission"""
    # Only users with upload access can view documents
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to view documents")
    
    # Return all documents (global/shared) for users with upload access
    # No user_id filter - all documents are shared globally
    # This means ALL users with can_upload=True see the SAME documents
    documents = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    
    # Verify documents actually exist in vector DB and sync status
    from backend.shared.vector_db import get_vector_db_status
    
    try:
        vector_db_status = get_vector_db_status()
        actual_chunks_in_vector_db = vector_db_status.get("total_chunks", 0)
        
        # Calculate expected chunks from SQL database
        expected_chunks = sum(doc.chunk_count or 0 for doc in documents if doc.processed)
        
        # If there's a mismatch, update document status
        if actual_chunks_in_vector_db != expected_chunks:
            logger.warning(f"Vector DB mismatch: SQL shows {expected_chunks} chunks, but vector DB has {actual_chunks_in_vector_db} chunks")
            
            # If vector DB is empty but documents show as processed, mark them as unprocessed
            if actual_chunks_in_vector_db == 0 and expected_chunks > 0:
                logger.warning("Vector DB is empty but documents show as processed. Updating status...")
                for doc in documents:
                    if doc.processed:
                        doc.processed = False
                        doc.chunk_count = 0
                        doc.status = "failed"
                        doc.error_message = "Vector store is empty; document needs re-indexing."
                db.commit()
                logger.info("Updated document status: marked all as unprocessed")
    
    except Exception as e:
        logger.error(f"Error verifying vector DB status: {e}")
        # Continue anyway - don't fail the request
    
    # Re-query documents after potential update (to get fresh data)
    documents = db.query(Document).order_by(Document.uploaded_at.desc()).all()
    
    return documents


@app.get("/api/documents/stats")
async def get_document_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get document statistics - only accessible to users with upload permission"""
    # Only users with upload access can view document stats
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to view document statistics")
    
    # Get all documents (global/shared)
    documents = db.query(Document).all()
    
    # Calculate statistics from SQL database
    total_documents = len(documents)
    total_chunks_sql = sum(doc.chunk_count or 0 for doc in documents)
    total_size = sum(doc.file_size or 0 for doc in documents)
    
    # Also get actual chunk count from vector DB
    actual_chunks_in_vector_db = None
    try:
        from backend.shared.vector_db import get_vector_db_status
        vector_db_status = get_vector_db_status()
        actual_chunks_in_vector_db = vector_db_status.get("total_chunks", 0)
    except Exception as e:
        logger.error(f"Error getting vector DB chunk count: {e}")
    
    return {
        "total_documents": total_documents,
        "total_chunks": total_chunks_sql,
        "total_chunks_in_vector_db": actual_chunks_in_vector_db,  # Actual count from vector DB
        "total_size": total_size,
        "vector_db_synced": actual_chunks_in_vector_db == total_chunks_sql if actual_chunks_in_vector_db is not None else None
    }


@app.post("/api/documents/{document_id}/reindex", response_model=DocumentUploadResponse)
async def reindex_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run indexing for a document (e.g. after a failure). The source file must
    still exist on disk. Clears any stale chunks first, then re-indexes in the background."""
    if not current_user.can_upload and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Upload access required to re-index documents")

    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=400, detail="Original file is no longer on disk; please re-upload it")

    # Clear any existing chunks so a retry doesn't duplicate them
    try:
        from backend.shared.vector_db import delete_documents
        delete_documents(document_ids=[str(doc.id)])
    except Exception as e:
        print(f"[REINDEX] Could not clear old chunks for {doc.id}: {e}")

    doc.processed = False
    doc.chunk_count = 0
    doc.status = "processing"
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(process_document_job, doc.id)
    print(f"[REINDEX] Document {doc.id} ({doc.filename}) queued for re-indexing")
    return doc


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
    
    # Store document ID and file path before deletion
    doc_id = doc.id
    file_path = doc.file_path
    chunk_count = doc.chunk_count or 0
    
    # Delete all chunks from vector database first
    try:
        from backend.shared.vector_db import delete_documents
        delete_documents(document_ids=[str(doc_id)])
        print(f"[DELETE] Removed chunks from vector database for document {doc_id}")
    except Exception as e:
        import traceback
        print(f"[ERROR] Failed to delete chunks from vector DB: {e}")
        traceback.print_exc()
        # Don't continue if vector DB deletion fails
        raise HTTPException(status_code=500, detail=f"Failed to delete document chunks from vector database: {str(e)}")
    
    # 2. Delete physical file
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"[DELETE] ✓ Removed file: {file_path}")
        except Exception as e:
            print(f"[WARNING] Error deleting file {file_path}: {e}")
            # Continue even if file deletion fails (file might already be deleted)
    
    # 3. Delete from database (cascade will handle any related data)
    db.delete(doc)
    db.commit()
    
    # 4. Verify database deletion
    verify_doc = db.query(Document).filter(Document.id == doc_id).first()
    if verify_doc:
        raise HTTPException(status_code=500, detail="Document deletion failed - still exists in database")
    
    print(f"[DELETE] ✓ Document {doc_id} completely removed from database, vector DB, and filesystem")
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
        
        # Validate password against policy
        pw_error = validate_password_strength(user_data.password)
        if pw_error:
            raise HTTPException(status_code=400, detail=pw_error)
        
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


@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    payload: ResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset another user's password (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    pw_error = validate_password_strength(payload.new_password)
    if pw_error:
        raise HTTPException(status_code=400, detail=pw_error)

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": f"Password reset for user '{user.username}'"}


@app.delete("/api/admin/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a user (admin only) with safety guards."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Guard: don't let an admin delete their own account
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    # Guard: never delete the last remaining admin
    if user.is_admin:
        admin_count = db.query(User).filter(User.is_admin == True).count()  # noqa: E712
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last remaining admin account")

    username = user.username
    db.delete(user)
    db.commit()
    return {"message": f"User '{username}' deleted successfully"}


# ============================================================================
# Root and Health
# ============================================================================
@app.get("/")
async def root():
    """Serve frontend"""
    frontend_index = frontend_path / "index.html"
    if frontend_index.exists():
        return FileResponse(str(frontend_index), headers={"Cache-Control": "no-cache, must-revalidate"})
    return {"message": "BNO LLM Assistant API", "status": "running"}


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "service": "API Server"}


@app.get("/api/config")
async def public_config():
    """Public client config (upload limits / allowed types) so the UI stays in sync."""
    return {
        "max_file_size_mb": config.MAX_FILE_SIZE_MB,
        "allowed_extensions": sorted(config.ALLOWED_EXTENSIONS),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.API_SERVER_HOST,
        port=config.API_SERVER_PORT,
        log_level="info"
    )

