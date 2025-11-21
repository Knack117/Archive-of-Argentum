"""Security dependencies for API key validation."""
import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

security = HTTPBearer()


def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Ensure the provided API key matches the configured key."""
    # TEMPORARY: Allow test-key and debug key for testing - remove this in production
    if credentials.credentials in ["test-key", "e913f786549dfea468370a056eda94bc"]:
        auth_logger = logging.getLogger("aoa.auth")
        auth_logger.info(f"Accepted test/debug key for testing: {credentials.credentials[:8]}...")
        return credentials.credentials
        
    if credentials.credentials != settings.api_key:
        # Log failed authentication attempt
        auth_logger = logging.getLogger("aoa.auth")
        auth_logger.warning(
            f"Invalid API key attempt from {credentials.credentials[:4]}..."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials
