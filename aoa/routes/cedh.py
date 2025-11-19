"""cEDH Deck Database routes - search and filter competitive EDH decklists."""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from aoa.security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cedh"], prefix="/api/v1/cedh")

# Database URL
CEDH_DATABASE_URL = "https://raw.githubusercontent.com/AverageDragon/cEDH-Decklist-Database/master/_data/database.json"

# Cache for database with TTL
_database_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: Optional[datetime] = None
CACHE_TTL_HOURS = 6  # Refresh every 6 hours


async def fetch_cedh_database(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Fetch the cEDH database from GitHub with caching.
    
    Args:
        force_refresh: Force refresh the cache even if still valid
        
    Returns:
        List of deck entries from the database
    """
    global _database_cache, _cache_timestamp
    
    # Check if cache is valid
    if not force_refresh and _database_cache is not None and _cache_timestamp is not None:
        if datetime.utcnow() - _cache_timestamp < timedelta(hours=CACHE_TTL_HOURS):
            logger.info("Returning cached cEDH database")
            return _database_cache
    
    # Fetch fresh data
    logger.info("Fetching fresh cEDH database from GitHub")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(CEDH_DATABASE_URL)
            response.raise_for_status()
            data = response.json()
            
            # Update cache
            _database_cache = data
            _cache_timestamp = datetime.utcnow()
            
            logger.info(f"Successfully fetched {len(data)} cEDH deck entries")
            return data
            
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch cEDH database: {e}")
        # Return cached data if available, even if stale
        if _database_cache is not None:
            logger.warning("Returning stale cached data due to fetch error")
            return _database_cache
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch cEDH database and no cached data available"
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching cEDH database: {e}")
        if _database_cache is not None:
            return _database_cache
        raise HTTPException(status_code=500, detail="Internal server error")


def filter_decks(
    decks: List[Dict[str, Any]],
    commander: Optional[str] = None,
    colors: Optional[str] = None,
    section: Optional[str] = None,
    primer_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    Filter deck entries based on search criteria.
    
    Args:
        decks: List of all deck entries
        commander: Commander name to search for (partial match, case-insensitive)
        colors: Color identity filter (e.g., "ub" for Blue/Black, "wubrg" for 5-color)
        section: Section filter (COMPETITIVE, DEPRECATED, BREW)
        primer_only: Only return decks with primers
        
    Returns:
        Filtered list of deck entries
    """
    filtered = decks
    
    # Filter by commander name
    if commander:
        commander_lower = commander.lower()
        filtered = [
            deck for deck in filtered
            if any(commander_lower in cmd.get("name", "").lower() for cmd in deck.get("commander", []))
        ]
    
    # Filter by color identity
    if colors:
        # Normalize color input (remove spaces, make lowercase, sort)
        color_set = set(colors.lower().replace(" ", ""))
        # Validate colors
        valid_colors = {"w", "u", "b", "r", "g"}
        if not color_set.issubset(valid_colors):
            invalid = color_set - valid_colors
            raise HTTPException(
                status_code=400,
                detail=f"Invalid color(s): {', '.join(invalid)}. Valid colors are: w, u, b, r, g"
            )
        
        filtered = [
            deck for deck in filtered
            if set(deck.get("colors", [])) == color_set
        ]
    
    # Filter by section
    if section:
        section_upper = section.upper()
        valid_sections = {"COMPETITIVE", "DEPRECATED", "BREW"}
        if section_upper not in valid_sections:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid section: {section}. Valid sections are: COMPETITIVE, DEPRECATED, BREW"
            )
        filtered = [
            deck for deck in filtered
            if deck.get("section", "").upper() == section_upper
        ]
    
    # Filter by primer availability
    if primer_only:
        filtered = [
            deck for deck in filtered
            if any(dl.get("primer", False) for dl in deck.get("decklists", []))
        ]
    
    return filtered


def format_deck_entry(deck: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format a deck entry for API response.
    
    Args:
        deck: Raw deck entry from database
        
    Returns:
        Formatted deck entry with clean structure
    """
    commanders = deck.get("commander", [])
    commander_names = [cmd.get("name", "Unknown") for cmd in commanders]
    
    decklists = deck.get("decklists", [])
    
    # Color identity mapping
    color_map = {"w": "White", "u": "Blue", "b": "Black", "r": "Red", "g": "Green"}
    colors = deck.get("colors", [])
    color_names = [color_map.get(c, c) for c in colors]
    
    return {
        "id": deck.get("id"),
        "title": deck.get("title"),
        "commanders": commander_names,
        "color_identity": "".join(colors).upper(),
        "colors": color_names,
        "description": deck.get("description"),
        "section": deck.get("section"),
        "recommended": deck.get("recommended", False),
        "updated": deck.get("updated"),
        "discord": deck.get("discord"),
        "decklists": [
            {
                "title": dl.get("title"),
                "url": dl.get("link"),
                "has_primer": dl.get("primer", False)
            }
            for dl in decklists
        ],
        "decklist_count": len(decklists),
        "has_primer": any(dl.get("primer", False) for dl in decklists)
    }


@router.get(
    "/search",
    summary="Search cEDH Database",
    description="""
    Search the competitive EDH decklist database with various filters.
    
    **Filter Options:**
    - `commander`: Search by commander name (partial match, case-insensitive)
    - `colors`: Exact color identity match (e.g., "ub" for Dimir, "wubrg" for 5-color)
    - `section`: Filter by competitive level (COMPETITIVE, DEPRECATED, BREW)
    - `primer_only`: Only return decks with primers available
    - `limit`: Maximum number of results to return (default: 20)
    
    **Examples:**
    - `/api/v1/cedh/search?commander=tymna` - Find all Tymna decks
    - `/api/v1/cedh/search?colors=ub&section=COMPETITIVE` - Competitive Dimir decks
    - `/api/v1/cedh/search?primer_only=true&limit=10` - Top 10 decks with primers
    """,
)
async def search_cedh_decks(
    commander: Optional[str] = Query(None, description="Commander name to search for"),
    colors: Optional[str] = Query(None, description="Color identity (e.g., 'ub', 'wubrg')"),
    section: Optional[str] = Query(None, description="Section filter: COMPETITIVE, DEPRECATED, or BREW"),
    primer_only: bool = Query(False, description="Only return decks with primers"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results"),
):
    """Search the cEDH database with filters."""
    # Fetch database
    database = await fetch_cedh_database()
    
    # Apply filters
    filtered = filter_decks(
        database,
        commander=commander,
        colors=colors,
        section=section,
        primer_only=primer_only
    )
    
    # Limit results
    filtered = filtered[:limit]
    
    # Format results
    results = [format_deck_entry(deck) for deck in filtered]
    
    return {
        "total_results": len(results),
        "filters_applied": {
            "commander": commander,
            "colors": colors,
            "section": section,
            "primer_only": primer_only
        },
        "decks": results
    }


@router.get(
    "/commanders",
    summary="List All Commanders",
    description="Get a list of all commanders in the cEDH database with deck counts.",
)
async def list_commanders():
    """List all commanders in the database with deck counts."""
    database = await fetch_cedh_database()
    
    commander_counts = {}
    for deck in database:
        commanders = deck.get("commander", [])
        for cmd in commanders:
            name = cmd.get("name", "Unknown")
            if name not in commander_counts:
                commander_counts[name] = {
                    "name": name,
                    "image_url": cmd.get("link"),
                    "deck_count": 0,
                    "color_identities": set()
                }
            commander_counts[name]["deck_count"] += 1
            # Track color identities for this commander
            colors = "".join(sorted(deck.get("colors", []))).upper()
            commander_counts[name]["color_identities"].add(colors)
    
    # Convert sets to lists and sort by deck count
    commanders = []
    for cmd_data in commander_counts.values():
        cmd_data["color_identities"] = sorted(list(cmd_data["color_identities"]))
        commanders.append(cmd_data)
    
    commanders.sort(key=lambda x: x["deck_count"], reverse=True)
    
    return {
        "total_commanders": len(commanders),
        "commanders": commanders
    }


@router.get(
    "/stats",
    summary="Database Statistics",
    description="Get statistics about the cEDH database including color distribution, section breakdown, and more.",
)
async def get_database_stats():
    """Get comprehensive statistics about the cEDH database."""
    database = await fetch_cedh_database()
    
    # Initialize counters
    section_counts = {}
    color_counts = {}
    primer_count = 0
    total_decklists = 0
    
    for deck in database:
        # Section counts
        section = deck.get("section", "UNKNOWN")
        section_counts[section] = section_counts.get(section, 0) + 1
        
        # Color identity counts
        colors = "".join(sorted(deck.get("colors", []))).upper()
        if not colors:
            colors = "Colorless"
        color_counts[colors] = color_counts.get(colors, 0) + 1
        
        # Primer counts
        if any(dl.get("primer", False) for dl in deck.get("decklists", [])):
            primer_count += 1
        
        # Total decklists
        total_decklists += len(deck.get("decklists", []))
    
    return {
        "total_deck_archetypes": len(database),
        "total_decklists": total_decklists,
        "section_breakdown": section_counts,
        "color_identity_distribution": color_counts,
        "decks_with_primers": primer_count,
        "cache_status": {
            "cached": _database_cache is not None,
            "last_updated": _cache_timestamp.isoformat() if _cache_timestamp else None,
            "cache_ttl_hours": CACHE_TTL_HOURS
        }
    }


@router.get(
    "/info",
    summary="API Information",
    description="Get information about the cEDH database API endpoints and usage.",
)
async def get_api_info():
    """Get API information and usage guide."""
    return {
        "name": "cEDH Deck Database API",
        "version": "1.0.0",
        "description": "Search and explore competitive EDH decklists from the community-maintained cEDH database",
        "database_source": CEDH_DATABASE_URL,
        "endpoints": {
            "/api/v1/cedh/search": {
                "method": "GET",
                "description": "Search decks with filters",
                "parameters": {
                    "commander": "Commander name (partial match)",
                    "colors": "Color identity (exact match, e.g., 'ub', 'wubrg')",
                    "section": "COMPETITIVE, DEPRECATED, or BREW",
                    "primer_only": "true/false - only decks with primers",
                    "limit": "Number of results (1-100, default: 20)"
                }
            },
            "/api/v1/cedh/commanders": {
                "method": "GET",
                "description": "List all commanders with deck counts"
            },
            "/api/v1/cedh/stats": {
                "method": "GET",
                "description": "Database statistics and breakdown"
            }
        },
        "color_codes": {
            "w": "White",
            "u": "Blue",
            "b": "Black",
            "r": "Red",
            "g": "Green"
        },
        "examples": [
            "/api/v1/cedh/search?commander=tymna",
            "/api/v1/cedh/search?colors=ub&section=COMPETITIVE",
            "/api/v1/cedh/search?primer_only=true&limit=10",
            "/api/v1/cedh/commanders",
            "/api/v1/cedh/stats"
        ]
    }
