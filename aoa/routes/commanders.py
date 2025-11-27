"""Commander summary and average deck endpoints - sophisticated Next.js approach."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from pydantic import BaseModel, Field

from aoa.models.themes import EdhrecError, PageTheme
from aoa.services.edhrec import fetch_commander_summary
from aoa.security import verify_api_key
from aoa.services.tag_cache import get_tag_cache, validate_theme_slug

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
    logger.info(f"Commander summary requested: '{name}'")
    
    try:
        payload = await fetch_commander_summary(name)
        logger.info(f"Commander summary successfully fetched for: '{name}'")
    except EdhrecError as exc:
        # Convert EdhrecError to appropriate HTTP response
        if exc.code == "NOT_FOUND":
            logger.warning(f"Commander not found in EDHREC: '{name}'")
            raise HTTPException(status_code=404, detail=exc.message)
        else:
            logger.warning(f"EDHREC error for '{name}': {exc.to_dict()}")
            raise HTTPException(status_code=400, detail=exc.to_dict())
    except HTTPException:
        # Re-raise HTTP exceptions (404, 400, etc.) without additional logging
        raise
    except Exception as exc:
        logger.exception(f"Commander summary fetch failed for '{name}'")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    
    # Ensure the response matches PageTheme model
    return PageTheme.parse_obj(payload)


class EDHRecAverageDeckResponse(BaseModel):
    """EDHRec average deck response with bracket and theme filtering support."""
    commander_name: str
    commander_url: Optional[str] = None
    average_deck_data: Dict[str, Any] = Field(default_factory=dict)
    deck_statistics: Dict[str, Any] = Field(default_factory=dict)
    bracket_filter: Optional[Dict[str, Any]] = None
    theme_filter: Optional[Dict[str, Any]] = None
    source: str = "edhrec"
    timestamp: str


@router.get("/commanders/{commander_name}/average-deck", response_model=EDHRecAverageDeckResponse)
@router.get("/commanders/{commander_name}/average-deck/{bracket}", response_model=EDHRecAverageDeckResponse)
async def get_average_deck(
    commander_name: str,
    bracket: Optional[str] = None,
    theme_slug: Optional[str] = Query(None, description="Optional theme slug to filter average deck (e.g., 'voltron', 'blue-storm')"),
    api_key: str = Depends(verify_api_key),
    cache = Depends(get_tag_cache),
) -> EDHRecAverageDeckResponse:
    """Fetch EDHRec average deck data for a commander with optional bracket and theme filtering.
    
    Returns the statistical average deck composition based on EDHRec data.
    Supports optional bracket filtering for different power levels:
    - exhibition: Casual/beginner level
    - core: Standard power level
    - upgraded: Enhanced builds
    - optimized: Highly tuned decks
    - cedh: Competitive EDH level
    
    Also supports optional theme-slug filtering to focus on specific deck archetypes.
    
    Examples:
    - /api/v1/commanders/the-ur-dragon/average-deck
    - /api/v1/commanders/the-ur-dragon/average-deck/optimized
    - /api/v1/commanders/jhoira/average-deck?theme=storm
    - /api/v1/commanders/jhoira/average-deck/core?theme=storm
    - /api/v1/commanders/sol-ring/average-deck/cedh
    """
    logger.info(f"Average deck requested for commander: '{commander_name}', bracket: '{bracket}', theme: '{theme_slug}'")
    
    # Validate bracket if provided
    valid_brackets = ["exhibition", "core", "upgraded", "optimized", "cedh"]
    if bracket and bracket not in valid_brackets:
        logger.warning(f"Invalid bracket specified: '{bracket}'. Valid options: {valid_brackets}")
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid bracket '{bracket}'. Valid brackets: {', '.join(valid_brackets)}"
        )
    
    try:
        # Validate theme_slug if provided
        theme_filter_data = None
        if theme_slug:
            try:
                validated_result = await validate_theme_slug(theme_slug, cache)
                if validated_result and validated_result.get("validated", False):
                    logger.info(f"Theme validated: '{theme_slug}' -> {validated_result}")
                    theme_filter_data = validated_result
                else:
                    logger.warning(f"Theme not found in cache: '{theme_slug}'")
                    theme_filter_data = validated_result or {
                        "theme_slug": theme_slug,
                        "validated": False,
                        "error": "Theme validation failed"
                    }
            except Exception as theme_error:
                logger.warning(f"Theme validation failed for '{theme_slug}': {theme_error}")
                theme_filter_data = {
                    "theme_slug": theme_slug,
                    "validated": False,
                    "error": str(theme_error)
                }
        
        # Fetch average deck data using the correct EDHREC average-decks endpoint
        from aoa.services.edhrec import fetch_average_deck_data
        average_deck_data = await fetch_average_deck_data(commander_name, bracket, theme_slug)
        
        logger.info(f"Average deck successfully processed for: '{commander_name}'")
        return EDHRecAverageDeckResponse(**average_deck_data)
        
    except EdhrecError as exc:
        # Convert EdhrecError to appropriate HTTP response
        if exc.code == "NOT_FOUND":
            logger.warning(f"Commander not found in EDHREC average decks: '{commander_name}'")
            raise HTTPException(status_code=404, detail=exc.message)
        elif exc.code == "PARSE_ERROR":
            logger.warning(f"Failed to parse average deck data for '{commander_name}': {exc.message}")
            raise HTTPException(status_code=400, detail=exc.message)
        else:
            logger.warning(f"EDHREC error for '{commander_name}': {exc.to_dict()}")
            raise HTTPException(status_code=400, detail=exc.to_dict())
    except HTTPException:
        # Re-raise HTTP exceptions (404, 400, etc.) without additional logging
        raise
    except Exception as exc:
        logger.exception(f"Average deck fetch failed for '{commander_name}'")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Legacy endpoints kept for backward compatibility but marked as deprecated
@router.get("/average_deck/summary", deprecated=True)
async def get_average_deck_summary(*args, **kwargs):
    """Deprecated endpoint - use /commanders/summary instead."""
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been deprecated. Use /api/v1/commanders/summary instead."
    )
