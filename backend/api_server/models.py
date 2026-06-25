"""
Pydantic models for API requests/responses
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class UserCreate(BaseModel):
    """User registration model"""
    username: str
    email: Optional[str] = None  # Optional - no email feature yet
    password: str


class UserLogin(BaseModel):
    """User login model"""
    username: str
    password: str


class UserResponse(BaseModel):
    """User response model"""
    id: int
    username: str
    email: Optional[str] = None  # Optional - no email feature yet
    is_admin: bool
    can_upload: Optional[bool] = True  # Optional field
    full_name: Optional[str] = None  # Optional field
    created_at: datetime
    
    class Config:
        from_attributes = True


class Token(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str = "bearer"


class ChatCreate(BaseModel):
    """Create chat model"""
    title: str


class ChatResponse(BaseModel):
    """Chat response model"""
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    """Create message model"""
    content: str


class MessageResponse(BaseModel):
    """Message response model"""
    id: int
    role: str
    content: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DocumentUploadResponse(BaseModel):
    """Document upload response"""
    id: int
    filename: str
    file_type: str
    file_size: int
    uploaded_at: datetime
    processed: bool
    status: Optional[str] = "processing"
    error_message: Optional[str] = None
    chunk_count: Optional[int] = 0
    title: Optional[str] = None
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class QueryRequest(BaseModel):
    """Query request model"""
    query: str
    chat_id: Optional[int] = None


class MessageRequest(BaseModel):
    """Message request model"""
    content: str
    chat_id: Optional[int] = None


class AdminUserCreate(BaseModel):
    """Admin user creation model"""
    username: str
    password: str
    full_name: Optional[str] = None
    can_upload: bool = False
    is_admin: bool = False


class ChangePasswordRequest(BaseModel):
    """Self-service password change"""
    old_password: str
    new_password: str


class ResetPasswordRequest(BaseModel):
    """Admin password reset for another user"""
    new_password: str


class QueryResponse(BaseModel):
    """Query response model"""
    response: str
    chat_id: int
    message_id: int

