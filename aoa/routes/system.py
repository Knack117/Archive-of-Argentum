"""System endpoints such as status and root."""
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

from aoa.constants import API_VERSION

router = APIRouter(tags=["system"])


@router.get("/api/v1/status", response_model=Dict[str, Any])
async def api_status() -> Dict[str, Any]:
    """API status endpoint."""
    return {
        "success": True,
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": API_VERSION,
    }


@router.get("/", response_model=Dict[str, Any])
async def root() -> Dict[str, Any]:
    """Root endpoint."""
    return {
        "success": True,
        "message": "MTG Deckbuilding API",
        "version": API_VERSION,
        "docs": "/docs",
        "status": "/api/v1/status",
    }


@router.get("/health", response_model=Dict[str, Any])
async def health_check() -> Dict[str, Any]:
    """Health check endpoint expected by hosting environments."""
    return {
        "success": True,
        "status": "healthy",
        "message": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "MTG Deckbuilding API",
    }
