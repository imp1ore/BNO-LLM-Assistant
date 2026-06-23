"""
Authentication utilities
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import config
import bcrypt

# Use direct bcrypt (more reliable, avoids passlib compatibility issues)
# This eliminates the bcrypt version reading error from passlib


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash using direct bcrypt"""
    try:
        # Ensure password is not too long (bcrypt limit is 72 bytes)
        password_bytes = plain_password.encode('utf-8')
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        print(f"Password verification error: {e}")
        return False


def validate_password_strength(password: str) -> Optional[str]:
    """Validate a password against the policy.

    Returns an error message string if invalid, or None if the password is OK.
    """
    if password is None or not isinstance(password, str):
        return "Password is required"
    min_len = getattr(config, "MIN_PASSWORD_LENGTH", 8)
    if len(password) < min_len:
        return f"Password must be at least {min_len} characters"
    if password.strip() == "":
        return "Password cannot be blank"
    return None


def get_password_hash(password: str) -> str:
    """Hash a password using direct bcrypt"""
    try:
        # Ensure password is not too long (bcrypt limit is 72 bytes)
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
        
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except Exception as e:
        print(f"Password hashing error: {e}")
        raise


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=config.JWT_EXPIRATION_HOURS)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

