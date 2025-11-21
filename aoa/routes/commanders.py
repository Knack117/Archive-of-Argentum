"""Commander summary and average deck endpoints - sophisticated Next.js approach."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.models.themes import EdhrecError, HealthResponse, PageTheme
from aoa.services.edhrec import fetch_commander_summary
from aoa.security import verify_api_key

router = APIRouter(prefix="/api/v1", tags=["commanders"])
logger = logging.getLogger(__name__)


@router.get("/commanders/summary", response_model=PageTheme)
async def get_commander_summary(
    name: str = Query(..., description="Commander name (raw string, partners, MDFCs supported)"),
    api_key: str = Depends(verify_api_key),
) -> PageTheme:
    """Fetch EDHREC commander summary using sophisticated Next.js data extraction.
    
    This endpoint uses the same approach as the Knack117 repository, extracting
    build IDs from EDHREC pages and fetching structured Next.js JSON data.
    Returns a PageTheme with organized card collections and tags.
    """
    try:
        payload = await fetch_commander_summary(name)
    except EdhrecError as exc:
        # Convert EdhrecError to appropriate HTTP response
        if exc.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=exc.message)
        else:
            raise HTTPException(status_code=400, detail=exc.to_dict())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Commander summary fetch failed for '{name}'")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    
    # Ensure the response matches PageTheme model
    return PageTheme.parse_obj(payload)


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="ok")


# Legacy endpoints kept for backward compatibility but marked as deprecated
@router.get("/average_deck/summary", deprecated=True)
async def get_average_deck_summary(*args, **kwargs):
    """Deprecated endpoint - use /commanders/summary instead."""
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been deprecated. Use /api/v1/commanders/summary instead."
    )
