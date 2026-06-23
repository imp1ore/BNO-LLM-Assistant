"""
Request logging middleware
"""
import time
from fastapi import Request
from backend.utils.logging import get_logger

logger = get_logger(__name__)


async def logging_middleware(request: Request, call_next):
    """
    Log all HTTP requests with timing information
    """
    start_time = time.time()
    
    # Log request
    logger.info(f"{request.method} {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration = time.time() - start_time
    
    # Log response
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {duration:.3f}s"
    )
    
    return response

