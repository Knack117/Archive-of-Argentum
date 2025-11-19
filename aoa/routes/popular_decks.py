"""Popular decks routes - fetch top decks from Moxfield and Archidekt."""
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from aoa.security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["popular-decks"])


# Bracket mapping for Archidekt
ARCHIDEKT_BRACKET_MAP = {
    "exhibition": "1",
    "core": "2", 
    "upgraded": "3",
    "optimized": "4",
    "cedh": "5"
}


async def scrape_moxfield_popular_decks(
    bracket: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Fetch top decks from Moxfield using their API.
    
    Args:
        bracket: Commander bracket (optional, for filtering - note: Moxfield doesn't have bracket filtering)
        limit: Number of decks to return (default 5)
        
    Returns:
        List of deck dictionaries with URL, views, has_primer, and other metadata
    """
    decks = []
    
    try:
        # Use Moxfield's public API to get decks
        url = "https://api2.moxfield.com/v2/decks/all"
        params = {
            'pageNumber': 1,
            'pageSize': limit * 2,  # Get extra in case we need to filter
            'sortType': 'views',
            'sortDirection': 'Descending',
            'fmt': 'commander'
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            deck_data = data.get('data', [])
            
            for deck_info in deck_data:
                if len(decks) >= limit:
                    break
                
                deck_url = deck_info.get('publicUrl', '')
                if not deck_url:
                    continue
                
                # Extract bracket information if available
                bracket_info = None
                # Moxfield API may include bracket info in various fields
                # Check for bracket in deck metadata
                if 'bracket' in deck_info:
                    bracket_info = deck_info.get('bracket')
                elif 'edhrecBracket' in deck_info:
                    bracket_info = deck_info.get('edhrecBracket')
                
                decks.append({
                    'url': deck_url,
                    'title': deck_info.get('name', 'Unknown'),
                    'views': deck_info.get('viewCount', 0),
                    'has_primer': deck_info.get('hasPrimer', False),
                    'bracket': bracket_info,
                    'source': 'moxfield',
                    'format': 'Commander',
                    'author': deck_info.get('createdByUser', {}).get('userName', 'Unknown'),
                    'last_updated': deck_info.get('lastUpdatedAtUtc', '')
                })
        
        logger.info(f"Fetched {len(decks)} decks from Moxfield API")
        return decks[:limit]
        
    except Exception as exc:
        logger.error(f"Error fetching from Moxfield API: {exc}")
        return []


async def scrape_archidekt_popular_decks(
    bracket: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Scrape top decks from Archidekt search page.
    
    Args:
        bracket: Commander bracket name (e.g., 'upgraded', 'core', 'cedh')
        limit: Number of decks to return (default 5)
        
    Returns:
        List of deck dictionaries with URL, views, has_primer, and other metadata
    """
    decks = []
    
    try:
        # Build query parameters
        params = {
            'orderBy': 'views',
            'orderDir': 'desc',
            'formats': '3',  # Commander format
        }
        
        # Add bracket filter if specified
        if bracket and bracket.lower() in ARCHIDEKT_BRACKET_MAP:
            bracket_num = ARCHIDEKT_BRACKET_MAP[bracket.lower()]
            params['edh_bracket'] = bracket_num
        
        url = "https://archidekt.com/search/decks"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all deck links
            # Archidekt uses links with pattern /decks/[deck-id]
            deck_links = soup.find_all('a', href=re.compile(r'^/decks/\d+'))
            
            for link in deck_links:
                if len(decks) >= limit:
                    break
                    
                # Get deck URL
                deck_path = link.get('href', '')
                if not deck_path:
                    continue
                    
                deck_url = f"https://archidekt.com{deck_path}"
                
                # Avoid duplicates
                if any(d['url'] == deck_url for d in decks):
                    continue
                
                # Get deck title
                deck_text = link.get_text(strip=True)
                
                # Find the parent container to get metadata
                parent = link.parent
                while parent and parent.name != 'div':
                    parent = parent.parent
                
                # Extract views
                views = 0
                has_primer = False
                bracket_info = None
                
                if parent:
                    parent_text = parent.get_text()
                    
                    # Extract view count (e.g., "123 views")
                    view_match = re.search(r'(\d+)\s+views?', parent_text)
                    if view_match:
                        views = int(view_match.group(1))
                    
                    # Check for primer
                    has_primer = 'primer' in parent_text.lower()
                    
                    # Extract bracket info (e.g., "Bracket: Upgraded (3)")
                    bracket_match = re.search(r'Bracket:\s+([^(]+)\s*\((\d+)\)', parent_text)
                    if bracket_match:
                        bracket_info = {
                            'name': bracket_match.group(1).strip(),
                            'level': int(bracket_match.group(2))
                        }
                
                decks.append({
                    'url': deck_url,
                    'title': deck_text,
                    'views': views,
                    'has_primer': has_primer,
                    'bracket': bracket_info,
                    'source': 'archidekt',
                    'format': 'Commander'
                })
        
        # Sort by views descending
        decks.sort(key=lambda x: x['views'], reverse=True)
        
        logger.info(f"Scraped {len(decks)} decks from Archidekt")
        return decks[:limit]
        
    except Exception as exc:
        logger.error(f"Error scraping Archidekt: {exc}")
        return []


@router.get("/api/v1/popular-decks")
async def get_all_popular_decks(
    limit_per_source: int = Query(
        5, 
        description="Number of decks to fetch from each source (default 5)",
        ge=1,
        le=20
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the top most viewed decks from both Moxfield and Archidekt without bracket filtering.
    
    Returns 10 deck URLs total (5 from Moxfield, 5 from Archidekt) with metadata including:
    - Deck URL
    - View count
    - Whether it includes a primer
    - Deck title
    - Source (moxfield or archidekt)
    - Bracket information (when available)
    
    Args:
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        
    Returns:
        Dictionary containing decks from both sources with metadata including bracket info
    """
    logger.info(f"Fetching popular decks without bracket filter")
    
    # Fetch decks from both sources without bracket filtering
    moxfield_decks = await scrape_moxfield_popular_decks(
        bracket=None,
        limit=limit_per_source
    )
    
    archidekt_decks = await scrape_archidekt_popular_decks(
        bracket=None,
        limit=limit_per_source
    )
    
    # Combine results
    all_decks = moxfield_decks + archidekt_decks
    
    # Count decks by bracket
    bracket_distribution = {}
    for deck in all_decks:
        if deck.get('bracket'):
            # Handle different bracket formats
            if isinstance(deck['bracket'], dict):
                bracket_name = deck['bracket'].get('name', 'Unknown')
            else:
                bracket_name = str(deck['bracket'])
            
            bracket_distribution[bracket_name] = bracket_distribution.get(bracket_name, 0) + 1
    
    return {
        "bracket_filter": None,
        "total_decks": len(all_decks),
        "moxfield": {
            "count": len(moxfield_decks),
            "decks": moxfield_decks
        },
        "archidekt": {
            "count": len(archidekt_decks),
            "decks": archidekt_decks
        },
        "all_decks": all_decks,
        "summary": {
            "total_with_primer": sum(1 for d in all_decks if d.get('has_primer', False)),
            "average_views": sum(d.get('views', 0) for d in all_decks) / len(all_decks) if all_decks else 0,
            "bracket_distribution": bracket_distribution,
            "decks_with_bracket_info": sum(1 for d in all_decks if d.get('bracket') is not None)
        }
    }



@router.get("/api/v1/popular-decks/info")
async def get_popular_decks_info(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get information about the popular decks endpoint.
    
    Returns supported brackets and usage examples.
    """
    return {
        "description": "Fetch top most-viewed Commander decks from Moxfield and Archidekt",
        "endpoints": [
            {
                "path": "/api/v1/popular-decks",
                "description": "Get popular decks without bracket filtering (includes bracket info for each deck)"
            },
            {
                "path": "/api/v1/popular-decks/{bracket}",
                "description": "Get popular decks filtered by specific bracket"
            }
        ],
        "supported_brackets": [
            "exhibition",
            "core",
            "upgraded",
            "optimized",
            "cedh"
        ],
        "default_limit_per_source": 5,
        "max_limit_per_source": 20,
        "total_decks_returned": "10 (5 from each source by default)",
        "example_usage": [
            {
                "url": "/api/v1/popular-decks",
                "description": "Get top 5 decks from each source (no bracket filter, shows bracket info for each deck)"
            },
            {
                "url": "/api/v1/popular-decks/upgraded",
                "description": "Get top 5 decks from each source for Upgraded bracket"
            },
            {
                "url": "/api/v1/popular-decks?limit_per_source=10",
                "description": "Get top 10 decks from each source (no bracket filter)"
            }
        ],
        "deck_metadata_included": [
            "url",
            "title",
            "views",
            "has_primer",
            "source",
            "format",
            "bracket (included when available, always present for Archidekt decks)",
            "author (Moxfield only)",
            "last_updated (Moxfield only)"
        ]
    }


@router.get("/api/v1/popular-decks/{bracket}")
async def get_popular_decks(
    bracket: str = Path(
        ..., 
        description="Commander bracket: exhibition, core, upgraded, optimized, or cedh"
    ),
    limit_per_source: int = Query(
        5, 
        description="Number of decks to fetch from each source (default 5)",
        ge=1,
        le=20
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the top most viewed decks for a given commander bracket from both Moxfield and Archidekt.
    
    Returns 10 deck URLs total (5 from Moxfield, 5 from Archidekt) with metadata including:
    - Deck URL
    - View count
    - Whether it includes a primer
    - Deck title
    - Source (moxfield or archidekt)
    
    Args:
        bracket: Commander bracket (exhibition, core, upgraded, optimized, cedh)
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        
    Returns:
        Dictionary containing decks from both sources with metadata
    """
    # Validate bracket
    valid_brackets = ["exhibition", "core", "upgraded", "optimized", "cedh"]
    if bracket.lower() not in valid_brackets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bracket '{bracket}'. Must be one of: {', '.join(valid_brackets)}"
        )
    
    logger.info(f"Fetching popular decks for bracket: {bracket}")
    
    # Fetch decks from both sources concurrently
    moxfield_decks = await scrape_moxfield_popular_decks(
        bracket=bracket.lower(),
        limit=limit_per_source
    )
    
    archidekt_decks = await scrape_archidekt_popular_decks(
        bracket=bracket.lower(),
        limit=limit_per_source
    )
    
    # Combine results
    all_decks = moxfield_decks + archidekt_decks
    
    # Count decks by bracket (for verification when filtering is applied)
    bracket_distribution = {}
    for deck in all_decks:
        if deck.get('bracket'):
            # Handle different bracket formats
            if isinstance(deck['bracket'], dict):
                bracket_name = deck['bracket'].get('name', 'Unknown')
            else:
                bracket_name = str(deck['bracket'])
            
            bracket_distribution[bracket_name] = bracket_distribution.get(bracket_name, 0) + 1
    
    return {
        "bracket_filter": bracket.lower(),
        "total_decks": len(all_decks),
        "moxfield": {
            "count": len(moxfield_decks),
            "decks": moxfield_decks
        },
        "archidekt": {
            "count": len(archidekt_decks),
            "decks": archidekt_decks
        },
        "all_decks": all_decks,
        "summary": {
            "total_with_primer": sum(1 for d in all_decks if d.get('has_primer', False)),
            "average_views": sum(d.get('views', 0) for d in all_decks) / len(all_decks) if all_decks else 0,
            "bracket_distribution": bracket_distribution,
            "decks_with_bracket_info": sum(1 for d in all_decks if d.get('bracket') is not None)
        }
    }


