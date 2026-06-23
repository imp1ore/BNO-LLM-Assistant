"""
Error handling middleware for consistent error responses
"""
from fastapi import Request, status
from fastapi.responses import JSONResponse
from backend.utils.exceptions import (
    BNOException,
    ValidationError,
    NotFoundError,
    AuthenticationError,
    AuthorizationError
)
from backend.utils.logging import get_logger

logger = get_logger(__name__)


async def error_handler_middleware(request: Request, call_next):
    """
    Global error handler middleware
    
    Catches exceptions and returns consistent error responses
    """
    try:
        response = await call_next(request)
        return response
    except NotFoundError as e:
        logger.warning(f"Not found: {e.message}")
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": e.message, "error_code": e.error_code or "NOT_FOUND"}
        )
    except ValidationError as e:
        logger.warning(f"Validation error: {e.message}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": e.message, "error_code": e.error_code or "VALIDATION_ERROR"}
        )
    except AuthenticationError as e:
        logger.warning(f"Authentication error: {e.message}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": e.message, "error_code": e.error_code or "AUTHENTICATION_ERROR"}
        )
    except AuthorizationError as e:
        logger.warning(f"Authorization error: {e.message}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": e.message, "error_code": e.error_code or "AUTHORIZATION_ERROR"}
        )
    except BNOException as e:
        logger.error(f"BNO error: {e.message}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": e.message, "error_code": e.error_code or "INTERNAL_ERROR"}
        )
    except Exception as e:
        logger.exception(f"Unexpected error: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "An unexpected error occurred", "error_code": "INTERNAL_ERROR"}
        )

