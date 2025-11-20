"""Popular decks routes - fetch top decks from Moxfield and Archidekt."""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from aoa.models import PopularDecksResponse, PopularDecksInfoResponse
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
    limit: int = 5,
    commander: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch top decks from Moxfield using their API.
    
    Args:
        bracket: Commander bracket (optional, for filtering - note: Moxfield doesn't have bracket filtering)
        limit: Number of decks to return (default 5)
        commander: Commander name to filter by (optional)
        
    Returns:
        List of deck dictionaries with URL, views, has_primer, and other metadata
    """
    decks = []
    
    try:
        # Use search endpoint if commander is specified, otherwise use /all endpoint
        if commander:
            url = "https://api2.moxfield.com/v2/decks/search"
            params = {
                'pageNumber': 1,
                'pageSize': limit,
                'sortType': 'views',
                'sortDirection': 'Descending',
                'fmt': 'commander',
                'filter': f'mainCard={commander}'
            }
        else:
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
        
        logger.info(f"Fetched {len(decks)} decks from Moxfield API" + (f" for commander '{commander}'" if commander else ""))
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


@router.get("/api/v1/popular-decks", response_model=PopularDecksResponse)
async def get_all_popular_decks(
    limit_per_source: int = Query(
        5, 
        description="Number of decks to fetch from each source (default 5)",
        ge=1,
        le=20
    ),
    commander: Optional[str] = Query(
        None,
        description="Filter by commander name (e.g., 'Brudiclad' or 'Brudiclad, Telchor Engineer')"
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get top most-viewed Commander decks from Moxfield and Archidekt without bracket filtering.
    
    When a commander is specified, only Moxfield results are returned (10 decks total).
    Without a commander, returns decks from both sources (5 from each by default).
    
    Returns deck URLs with metadata including view count, primer status, and source information.
    - Commander name (for search context)
    
    Args:
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        commander: Optional commander name to filter results
        
    Returns:
        Dictionary containing decks with metadata including bracket info
    """
    logger.info(f"Fetching popular decks" + (f" for commander '{commander}'" if commander else " without bracket filter"))
    
    # If commander is specified, only use Moxfield (Archidekt doesn't support commander filtering)
    if commander:
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=None,
            limit=10,
            commander=commander
        )
        archidekt_decks = []
    else:
        # Fetch decks from both sources without filtering
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
    
    return PopularDecksResponse(
        success=True,
        data=all_decks,
        count=len(all_decks),
        source="moxfield+archidekt",
        description="Top most-viewed Commander decks from Moxfield and Archidekt",
        bracket=None,
        timestamp=datetime.utcnow().isoformat()
    )



@router.get("/api/v1/popular-decks/info", response_model=PopularDecksInfoResponse)
async def get_popular_decks_info(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get information about the popular decks endpoint.
    
    Returns supported brackets and usage examples.
    """
    return PopularDecksInfoResponse(
        description="Fetch top most-viewed Commander decks from Moxfield and Archidekt",
        supported_brackets=["exhibition", "core", "upgraded", "optimized", "cedh"],
        usage_examples={
            "/api/v1/popular-decks": "Get top 5 decks from each source (no bracket filter)",
            "/api/v1/popular-decks/upgraded": "Get top 5 decks from each source for Upgraded bracket",
            "/api/v1/popular-decks?limit_per_source=10": "Get top 10 decks from each source",
            "/api/v1/popular-decks?commander=Brudiclad": "Get top 10 Brudiclad decks from Moxfield"
        },
        timestamp=datetime.utcnow().isoformat()
    )


@router.get("/api/v1/popular-decks/{bracket}", response_model=PopularDecksResponse)
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
    commander: Optional[str] = Query(
        None,
        description="Filter by commander name (e.g., 'Brudiclad' or 'Brudiclad, Telchor Engineer')"
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get top most-viewed decks for a specific commander bracket from both Moxfield and Archidekt.
    
    When a commander is specified, only Moxfield results are returned (10 decks total).
    Without a commander, returns decks from both sources (5 from each by default).
    
    Returns deck URLs with metadata including view count, primer status, and source information.
    - Whether it includes a primer
    - Deck title
    - Source (moxfield or archidekt)
    - Bracket information
    - Commander name (for search context)
    
    Args:
        bracket: Commander bracket (exhibition, core, upgraded, optimized, cedh)
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        commander: Optional commander name to filter results
        
    Returns:
        Dictionary containing decks with metadata
    """
    # Validate bracket
    valid_brackets = ["exhibition", "core", "upgraded", "optimized", "cedh"]
    if bracket.lower() not in valid_brackets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bracket '{bracket}'. Must be one of: {', '.join(valid_brackets)}"
        )
    
    logger.info(f"Fetching popular decks for bracket: {bracket}" + (f" and commander '{commander}'" if commander else ""))
    
    # If commander is specified, only use Moxfield
    if commander:
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=bracket.lower(),
            limit=10,
            commander=commander
        )
        archidekt_decks = []
    else:
        # Fetch decks from both sources
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
    
    return PopularDecksResponse(
        success=True,
        data=all_decks,
        count=len(all_decks),
        source="moxfield+archidekt",
        description="Top most-viewed Commander decks from Moxfield and Archidekt",
        bracket=bracket.lower(),
        timestamp=datetime.utcnow().isoformat()
    )


