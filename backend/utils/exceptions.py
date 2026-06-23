"""
Custom exception classes for the BNO LLM Assistant
"""
from typing import Optional


class BNOException(Exception):
    """Base exception for BNO LLM Assistant"""
    
    def __init__(self, message: str, error_code: Optional[str] = None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class ValidationError(BNOException):
    """Raised when validation fails"""
    pass


class NotFoundError(BNOException):
    """Raised when a resource is not found"""
    pass


class AuthenticationError(BNOException):
    """Raised when authentication fails"""
    pass


class AuthorizationError(BNOException):
    """Raised when authorization fails"""
    pass


class DocumentProcessingError(BNOException):
    """Raised when document processing fails"""
    pass


class LLMProviderError(BNOException):
    """Raised when LLM provider operations fail"""
    pass


class VectorDBError(BNOException):
    """Raised when vector database operations fail"""
    pass

