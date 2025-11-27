"""Commander summary and average deck endpoints - sophisticated Next.js approach."""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.models import AverageDeckResponse
from aoa.models.themes import EdhrecError, HealthResponse, PageTheme
from pydantic import BaseModel, Field
from aoa.services.edhrec import fetch_commander_summary, fetch_edhrec_json
from aoa.security import verify_api_key
from aoa.services.themes import scrape_edhrec_theme_page
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
    """EDHRec average deck response with theme filtering support."""
    commander_name: str
    commander_url: Optional[str] = None
    average_deck_data: Dict[str, Any] = Field(default_factory=dict)
    deck_statistics: Dict[str, Any] = Field(default_factory=dict)
    theme_filter: Optional[Dict[str, Any]] = None
    source: str = "edhrec"
    timestamp: str


@router.get("/commanders/{commander_name}/average-deck", response_model=EDHRecAverageDeckResponse)
async def get_average_deck(
    commander_name: str,
    theme_slug: Optional[str] = Query(None, description="Optional theme slug to filter average deck (e.g., 'voltron', 'blue-storm')"),
    api_key: str = Depends(verify_api_key),
    cache = Depends(get_tag_cache),
) -> AverageDeckResponse:
    """Fetch EDHRec average deck data for a commander with optional theme filtering.
    
    Returns the statistical average deck composition based on EDHRec data.
    Supports optional theme-slug filtering to focus on specific deck archetypes.
    
    Examples:
    - /api/v1/commanders/the-ur-dragon/average-deck
    - /api/v1/commanders/jhoira/average-deck?theme=storm
    - /api/v1/commanders/sol-ring/average-deck?theme=blue-control
    """
    logger.info(f"Average deck requested for commander: '{commander_name}', theme: '{theme_slug}'")
    
    try:
        # Get the commander summary data from EDHRec
        commander_data = await fetch_commander_summary(commander_name)
        
        # Extract commander information
        commander_header = commander_data.get("header", "")
        # Parse commander name from header (format: "commander-name | EDHREC")
        if " | " in commander_header:
            commander_name = commander_header.split(" | ")[0].replace("-", " ").title()
        else:
            commander_name = commander_header.replace("-", " ").title()
        
        commander_url = commander_data.get("source_url", "")
        
        # Initialize deck statistics and average deck data
        deck_statistics = {}
        average_deck_data = {}
        theme_filter_data = None
        
        # If theme_slug provided, validate it
        if theme_slug:
            try:
                validated_theme = await validate_theme_slug(theme_slug, cache)
                if validated_theme:
                    logger.info(f"Theme validated: '{theme_slug}' -> theme: {validated_theme}")
                    theme_filter_data = {
                        "theme_slug": theme_slug,
                        "validated": True,
                        "theme_info": validated_theme
                    }
                else:
                    logger.warning(f"Invalid theme slug: '{theme_slug}'")
                    theme_filter_data = {
                        "theme_slug": theme_slug,
                        "validated": False,
                        "error": "Theme slug not found in EDHRec catalog"
                    }
            except Exception as theme_error:
                logger.warning(f"Theme validation failed for '{theme_slug}': {theme_error}")
                theme_filter_data = {
                    "theme_slug": theme_slug,
                    "validated": False,
                    "error": str(theme_error)
                }
        
        # Extract available statistics from commander data
        container_data = commander_data.get("container", {})
        if container_data:
            # Extract collections (this is what EDHRec uses instead of "sections")
            collections = container_data.get("collections", [])
            categories = {}
            
            for collection in collections:
                collection_name = collection.get("header", "Unknown Collection")
                items = collection.get("items", [])
                if items:
                    categories[collection_name] = {
                        "count": len(items),
                        "sample_items": items[:5]  # Limit to first 5 items for response
                    }
            
            average_deck_data["collections"] = categories
            
            # Calculate some basic statistics
            deck_statistics.update({
                "total_collections": len(collections),
                "total_cards_listed": sum(len(collection.get("items", [])) for collection in collections),
                "data_source": "edhrec_commander_summary",
                "theme_applied": theme_slug is not None,
                "last_updated": container_data.get("last_updated", "")
            })
        
        # Build the response
        response = EDHRecAverageDeckResponse(
            commander_name=commander_name,
            commander_url=commander_url,
            average_deck_data=average_deck_data,
            deck_statistics=deck_statistics,
            theme_filter=theme_filter_data,
            timestamp=datetime.now().isoformat() + "Z"
        )
        
        logger.info(f"Average deck successfully processed for: '{commander_name}'")
        return response
        
    except EdhrecError as exc:
        # Convert EdhrecError to appropriate HTTP response
        if exc.code == "NOT_FOUND":
            logger.warning(f"Commander not found in EDHREC: '{commander_name}'")
            raise HTTPException(status_code=404, detail=exc.message)
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
