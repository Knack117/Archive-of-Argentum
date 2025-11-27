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


async def get_commander_name_from_url(deck_url: str, client: httpx.AsyncClient) -> str:
    """Attempt to extract commander name from Moxfield deck page."""
    try:
        # Parse deck ID from URL
        if '/decks/' not in deck_url:
            return "Unknown"
        
        deck_id = deck_url.split('/decks/')[-1]
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = await client.get(deck_url, headers=headers, timeout=10.0)
        if response.status_code != 200:
            return "Unknown"
        
        # Try to find commander in the page title or meta tags
        title_match = response.text.split('<title>')[1].split('</title>')[0] if '<title>' in response.text else ""
        
        # Look for "Commander:" pattern in title
        if ' - ' in title_match:
            parts = title_match.split(' - ')
            if len(parts) > 1:
                # Often format is "Deck Name - Commander Name"
                commander_part = parts[-1].strip()
                if commander_part and not commander_part.lower().startswith('moxfield'):
                    return commander_part
        
        return "Unknown"
    except Exception:
        return "Unknown"


async def scrape_moxfield_popular_decks(
    bracket: Optional[str] = None,
    limit: int = 5,
    commander: Optional[str] = None,
    min_views: int = 100
) -> List[Dict[str, Any]]:
    """
    Fetch top decks from Moxfield using their API with improved data extraction.
    
    Args:
        bracket: Commander bracket (optional, for client-side filtering)
        limit: Number of decks to return (default 5)
        commander: Commander name to filter by (optional)
        min_views: Minimum view count for quality filtering (default 100)
        
    Returns:
        List of deck dictionaries with URL, views, has_primer, and other metadata
    """
    decks = []
    
    # Bracket mapping for filtering
    BRACKET_NUMBERS = {
        "exhibition": 1,
        "core": 2,
        "upgraded": 3,
        "optimized": 4,
        "cedh": 5
    }
    target_bracket = BRACKET_NUMBERS.get(bracket.lower()) if bracket else None
    
    try:
        # Use search endpoint if commander is specified, otherwise use /all endpoint
        if commander:
            url = "https://api2.moxfield.com/v2/decks/search"
            params = {
                'pageNumber': 1,
                'pageSize': min(limit * 3, 50),  # Get more results for better filtering
                'sortType': 'views',
                'sortDirection': 'Descending',
                'fmt': 'commander',
                'filter': f'mainCard={commander}'
            }
        else:
            url = "https://api2.moxfield.com/v2/decks/all"
            params = {
                'pageNumber': 1,
                'pageSize': min(limit * 4, 100),  # Get more results for filtering
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
            
            # Filter and process decks
            filtered_decks = []
            for deck_info in deck_data:
                # Skip if no URL
                deck_url = deck_info.get('publicUrl', '')
                if not deck_url:
                    continue
                
                # Filter by view count
                view_count = deck_info.get('viewCount', 0)
                if view_count < min_views:
                    continue
                
                # Filter by bracket if specified
                if target_bracket is not None:
                    deck_bracket = deck_info.get('bracket', 0)
                    # Try multiple bracket fields for better compatibility
                    user_bracket = deck_info.get('userBracket', 0)
                    auto_bracket = deck_info.get('autoBracket', 0)
                    
                    # Match any bracket field that matches target
                    if deck_bracket != target_bracket and user_bracket != target_bracket and auto_bracket != target_bracket:
                        continue
                
                # Extract colors
                color_identity = deck_info.get('colorIdentity', [])
                colors_str = "".join(sorted(color_identity)) if color_identity else "Colorless"
                
                # Extract key metadata
                deck_bracket = deck_info.get('bracket', 0)
                has_primer = deck_info.get('hasPrimer', False)
                like_count = deck_info.get('likeCount', 0)
                comment_count = deck_info.get('commentCount', 0)
                
                filtered_decks.append({
                    'url': deck_url,
                    'title': deck_info.get('name', 'Unknown Deck'),
                    'views': view_count,
                    'has_primer': has_primer,
                    'bracket': deck_bracket,
                    'bracket_name': {
                        1: "Exhibition", 2: "Core", 3: "Upgraded", 
                        4: "Optimized", 5: "cEDH"
                    }.get(deck_bracket, f"Level {deck_bracket}"),
                    'source': 'moxfield',
                    'format': 'Commander',
                    'author': deck_info.get('createdByUser', {}).get('userName', 'Unknown'),
                    'author_display': deck_info.get('createdByUser', {}).get('displayName', 'Unknown'),
                    'last_updated': deck_info.get('lastUpdatedAtUtc', ''),
                    'created_at': deck_info.get('createdAtUtc', ''),
                    'colors': colors_str,
                    'color_percentages': deck_info.get('colorPercentages', {}),
                    'likes': like_count,
                    'comments': comment_count,
                    'card_count': deck_info.get('mainboardCount', 0),
                    'quality_score': (view_count * 0.7) + (like_count * 5) + (comment_count * 2) + (50 if has_primer else 0)
                })
            
            # Sort by quality score and take top results
            filtered_decks.sort(key=lambda x: x['quality_score'], reverse=True)
            decks = filtered_decks[:limit]
        
        # Add commander identification (optional, slows down response)
        if not commander and decks and limit <= 10:  # Only for small requests
            try:
                for deck in decks[:5]:  # Limit commander extraction to avoid slowdowns
                    commander_name = await get_commander_name_from_url(deck['url'], client)
                    if commander_name != "Unknown":
                        deck['commander'] = commander_name
            except Exception as e:
                logger.warning(f"Could not extract commander names: {e}")
        
        logger.info(f"Fetched {len(decks)} high-quality decks from Moxfield" + 
                   (f" for commander '{commander}'" if commander else "") + 
                   (f" bracket {bracket}" if bracket else ""))
        return decks
        
    except Exception as exc:
        logger.error(f"Error fetching from Moxfield API: {exc}")
        return []


async def get_archidekt_deck_details(deck_url: str, client: httpx.AsyncClient, min_views: int = 50) -> Dict[str, Any]:
    """Get detailed information about an Archidekt deck."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        response = await client.get(deck_url, headers=headers, timeout=15.0)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract deck title from page
        title_element = soup.find('h1') or soup.find('h2') or soup.find('title')
        deck_title = title_element.get_text(strip=True) if title_element else "Unknown Deck"
        
        # Clean up title (remove site name suffix)
        if ' - ' in deck_title and 'Archidekt' in deck_title:
            deck_title = deck_title.split(' - ')[0]
        
        # Extract commander name (look for "Commander:" pattern)
        commander = "Unknown"
        commander_patterns = [
            r'Commander[:\s]+([A-Za-z0-9\s,\.]+)',
            r'Deck for[:\s]+([A-Za-z0-9\s,\.]+)',
            r'Built with[:\s]+([A-Za-z0-9\s,\.]+)'
        ]
        
        page_text = soup.get_text()
        for pattern in commander_patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                commander = match.group(1).strip()
                # Clean up common suffixes
                commander = re.sub(r'\s*\([^)]*\).*$', '', commander).strip()
                if len(commander) > 50:  # Skip if too long (probably not a commander name)
                    commander = "Unknown"
                break
        
        # Extract colors
        colors = []
        color_patterns = [
            {'white': ['W', 'white', 'azorius', 'boros', 'selesnya', 'orzhov', 'bant', 'esper', 'naya']},
            {'blue': ['U', 'blue', 'azorius', 'dimir', 'izzet', 'simic', 'bant', 'esper', 'grixis', 'temur']},
            {'black': ['B', 'black', 'dimir', 'orzhov', 'golgari', 'rakdos', 'esper', 'grixis', 'jund']},
            {'red': ['R', 'red', 'boros', 'izzet', 'gruul', 'rakdos', 'grixis', 'naya', 'jund', 'temur']},
            {'green': ['G', 'green', 'selesnya', 'golgari', 'gruul', 'simic', 'bant', 'naya', 'jund', 'temur']}
        ]
        
        # Check if color identity is mentioned in the title or commander
        title_and_commander = f"{deck_title} {commander}".lower()
        for color_group in color_patterns:
            color_name = list(color_group.keys())[0]
            if any(pattern in title_and_commander for pattern in color_group[color_name]):
                colors.append(color_name)
        
        colors_str = "".join([c[0].upper() for c in sorted(colors)])
        
        # Extract additional metadata from meta tags
        description = ""
        meta_desc = soup.find('meta', {'name': 'description'})
        if meta_desc:
            description = meta_desc.get('content', '')[:200]  # Limit description length
        
        return {
            'title': deck_title,
            'commander': commander,
            'colors': colors_str,
            'description': description,
            'quality_score': 1  # Base score for decks with details
        }
        
    except Exception as e:
        logger.warning(f"Could not get details for {deck_url}: {e}")
        return None


async def scrape_archidekt_popular_decks(
    bracket: Optional[str] = None,
    limit: int = 5,
    min_views: int = 50
) -> List[Dict[str, Any]]:
    """
    Scrape top decks from Archidekt search page with improved data extraction.
    
    Args:
        bracket: Commander bracket name (e.g., 'upgraded', 'core', 'cedh')
        limit: Number of decks to return (default 5)
        min_views: Minimum view count for quality filtering (default 50)
        
    Returns:
        List of deck dictionaries with URL, views, has_primer, and other metadata
    """
    decks = []
    
    # Bracket mapping for filtering
    BRACKET_NUMBERS = {
        "exhibition": 1,
        "core": 2,
        "upgraded": 3,
        "optimized": 4,
        "cedh": 5
    }
    target_bracket = BRACKET_NUMBERS.get(bracket.lower()) if bracket else None
    
    try:
        # Build query parameters
        params = {
            'orderBy': 'views',
            'orderDir': 'desc',
            'formats': '3',  # Commander format
        }
        
        # Note: Archidekt doesn't support API-level bracket filtering via URL params
        # We'll handle bracket filtering in the scraping logic instead
        # (Removing ineffective URL parameter approach)
        
        url = "https://archidekt.com/search/decks"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all deck links - improved selector
            # Look for deck links in various possible containers
            deck_links = soup.find_all('a', href=re.compile(r'^/decks/\d+'))
            
            # Also try to find deck containers with more context
            deck_candidates = []
            for link in deck_links:
                # Get more context around the link
                parent = link.parent
                while parent and parent.name != 'div':
                    parent = parent.parent
                
                if parent:
                    deck_candidates.append({
                        'link': link,
                        'container': parent
                    })
            
            # Process candidates
            for candidate in deck_candidates:
                if len(decks) >= limit * 2:  # Get extra for filtering
                    break
                
                link = candidate['link']
                container = candidate['container']
                
                # Get deck URL
                deck_path = link.get('href', '')
                if not deck_path:
                    continue
                    
                deck_url = f"https://archidekt.com{deck_path}"
                
                # Avoid duplicates
                if any(d['url'] == deck_url for d in decks):
                    continue
                
                # Extract better title - look for the main title element
                deck_title = link.get_text(strip=True)
                
                # If title is too generic, try to find better title in container
                if len(deck_title) < 10 or 'views' in deck_title.lower():
                    # Look for better title in the container
                    title_candidates = container.find_all(['h1', 'h2', 'h3', 'h4', 'strong'])
                    for title_candidate in title_candidates:
                        candidate_text = title_candidate.get_text(strip=True)
                        if len(candidate_text) > len(deck_title) and len(candidate_text) > 10:
                            deck_title = candidate_text
                            break
                
                # Clean up title - remove view count and other noise
                deck_title = re.sub(r'\d+\s*views?', '', deck_title, flags=re.IGNORECASE).strip()
                deck_title = re.sub(r'^\d+\s+cards?', '', deck_title, flags=re.IGNORECASE).strip()
                
                if len(deck_title) < 5:  # Skip if title is too short
                    deck_title = "Commander Deck"
                
                # Extract metadata from container
                views = 0
                has_primer = False
                bracket_info = None
                container_text = container.get_text() if container else ""
                
                # Extract view count
                view_match = re.search(r'(\d+)\s+views?', container_text, re.IGNORECASE)
                if view_match:
                    views = int(view_match.group(1))
                
                # Skip low-view decks for quality
                if views < min_views:
                    continue
                
                # Check for primer
                has_primer = 'primer' in container_text.lower()
                
                # Extract bracket info with multiple patterns for better reliability
                bracket_info = None
                bracket_level = 0
                
                # Try multiple regex patterns for bracket extraction
                bracket_patterns = [
                    r'Bracket:\s+([^(]+)\s*\((\d+)\)',  # Standard format
                    r'bracket[:\s]+([^(]+)\s*\((\d+)\)',  # lowercase variant
                    r'EDH.*?(\d+).*?bracket',  # EDH bracket mention
                    r'bracket.*?(\d+)',  # Simple bracket number
                    r'level\s+(\d+)',  # Level format
                ]
                
                for pattern in bracket_patterns:
                    bracket_match = re.search(pattern, container_text, re.IGNORECASE)
                    if bracket_match:
                        try:
                            if len(bracket_match.groups()) >= 2:
                                bracket_name = bracket_match.group(1).strip()
                                bracket_level = int(bracket_match.group(2))
                            else:
                                bracket_level = int(bracket_match.group(1))
                                bracket_name = f"Level {bracket_level}"
                            
                            if 1 <= bracket_level <= 5:  # Valid bracket range
                                bracket_info = {
                                    'name': bracket_name,
                                    'level': bracket_level
                                }
                                break
                        except (ValueError, IndexError):
                            continue
                
                # Filter by bracket if specified
                if target_bracket is not None:
                    if bracket_info is None:
                        # If no bracket info found but bracket filter requested, 
                        # still include the deck (better than filtering everything out)
                        logger.warning(f"No bracket info found for filtered request, including deck anyway: {deck_url}")
                    elif bracket_level != target_bracket:
                        continue  # Skip if bracket doesn't match
                
                # Calculate quality score
                quality_score = views + (100 if has_primer else 0) + (20 if bracket_info else 0)
                
                decks.append({
                    'url': deck_url,
                    'title': deck_title,
                    'views': views,
                    'has_primer': has_primer,
                    'bracket': bracket_info,
                    'bracket_level': bracket_info['level'] if bracket_info else 0,
                    'bracket_name': bracket_info['name'] if bracket_info else 'Unknown',
                    'source': 'archidekt',
                    'format': 'Commander',
                    'quality_score': quality_score
                })
            
            # Sort by quality score and take top results
            decks.sort(key=lambda x: x['quality_score'], reverse=True)
            decks = decks[:limit]
            
            # Get additional details for top decks (optional)
            if decks and limit <= 10:
                try:
                    for deck in decks[:5]:  # Limit to avoid slowdowns
                        details = await get_archidekt_deck_details(deck['url'], client)
                        if details:
                            deck.update({
                                'commander': details['commander'],
                                'colors': details['colors'],
                                'description': details['description']
                            })
                except Exception as e:
                    logger.warning(f"Could not get deck details: {e}")
        
        logger.info(f"Scraped {len(decks)} high-quality decks from Archidekt" + 
                   (f" bracket {bracket}" if bracket else ""))
        return decks
        
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
    min_views: int = Query(
        100,
        description="Minimum view count for quality filtering (default 100)",
        ge=10,
        le=1000
    ),
    include_details: bool = Query(
        True,
        description="Include additional deck details like commander names (may slow response)"
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get top quality Commander decks from Moxfield and Archidekt with improved filtering and metadata.
    
    When a commander is specified, only Moxfield results are returned (10 decks total).
    Without a commander, returns decks from both sources with quality filtering applied.
    
    Features:
    - Minimum view count filtering for quality
    - Bracket-aware data where available
    - Enhanced metadata including commander names, colors, and quality scores
    - Automatic deduplication and ranking
    
    Args:
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        commander: Optional commander name to filter results (Moxfield only)
        min_views: Minimum view count for quality filtering (default 100, max 1000)
        include_details: Include additional deck details (may slow response)
        
    Returns:
        Dictionary containing high-quality decks with enhanced metadata
    """
    logger.info(f"Fetching popular decks" + 
               (f" for commander '{commander}'" if commander else "") +
               f" with min_views={min_views}")
    
    # If commander is specified, only use Moxfield
    if commander:
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=None,
            limit=10,
            commander=commander,
            min_views=min_views
        )
        archidekt_decks = []
        total_sources = "moxfield"
    else:
        # Fetch from both sources with quality filtering
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=None,
            limit=limit_per_source,
            min_views=min_views
        )
        
        archidekt_decks = await scrape_archidekt_popular_decks(
            bracket=None,
            limit=limit_per_source,
            min_views=max(50, min_views // 2)  # Lower threshold for Archidekt
        )
        total_sources = "moxfield+archidekt"
    
    # Combine and rank results by quality score
    all_decks = moxfield_decks + archidekt_decks
    
    # Remove duplicates (same deck URL)
    seen_urls = set()
    unique_decks = []
    for deck in all_decks:
        deck_url = deck.get('url', '')
        if deck_url and deck_url not in seen_urls:
            seen_urls.add(deck_url)
            unique_decks.append(deck)
    
    # Sort by quality score (higher is better)
    unique_decks.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    
    # Take the best results (limit total for performance)
    final_decks = unique_decks[:min(limit_per_source * 2, 20)]
    
    # Generate statistics
    total_views = sum(deck.get('views', 0) for deck in final_decks)
    avg_views = total_views / len(final_decks) if final_decks else 0
    primer_count = sum(1 for deck in final_decks if deck.get('has_primer', False))
    
    # Count by source
    source_counts = {'moxfield': 0, 'archidekt': 0}
    for deck in final_decks:
        source = deck.get('source', 'unknown')
        if source in source_counts:
            source_counts[source] += 1
    
    # Count by bracket
    bracket_distribution = {}
    for deck in final_decks:
        bracket = deck.get('bracket')
        if isinstance(bracket, dict):
            bracket_name = bracket.get('name', 'Unknown')
        elif isinstance(bracket, int):
            bracket_names = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}
            bracket_name = bracket_names.get(bracket, f"Level {bracket}")
        else:
            bracket_name = "Unknown"
        
        bracket_distribution[bracket_name] = bracket_distribution.get(bracket_name, 0) + 1
    
    # Add summary statistics
    response_data = final_decks.copy()
    for deck in response_data:
        # Ensure quality score is included
        if 'quality_score' not in deck:
            deck['quality_score'] = deck.get('views', 0)
    
    return PopularDecksResponse(
        success=True,
        data=response_data,
        count=len(response_data),
        source=total_sources,
        description=f"High-quality Commander decks from {total_sources.replace('+', ' and ')} with minimum {min_views} views",
        bracket=None,
        timestamp=datetime.utcnow().isoformat(),
        stats={
            "total_views": total_views,
            "average_views": round(avg_views, 1),
            "primer_count": primer_count,
            "source_distribution": source_counts,
            "bracket_distribution": bracket_distribution,
            "quality_threshold": min_views
        }
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
    min_views: int = Query(
        100,
        description="Minimum view count for quality filtering (default 100)",
        ge=10,
        le=1000
    ),
    include_details: bool = Query(
        True,
        description="Include additional deck details like commander names (may slow response)"
    ),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get top quality decks for a specific commander bracket from both Moxfield and Archidekt.
    
    When a commander is specified, only Moxfield results are returned (10 decks total).
    Without a commander, returns decks from both sources with bracket-specific filtering.
    
    Features:
    - Bracket-specific filtering (actual filtering, not just metadata)
    - Quality filtering by minimum view count
    - Enhanced metadata with commander names, colors, and quality scores
    - Automatic deduplication and ranking
    
    Args:
        bracket: Commander bracket (exhibition, core, upgraded, optimized, cedh)
        limit_per_source: Number of decks to fetch from each source (default 5, max 20)
        commander: Optional commander name to filter results (Moxfield only)
        min_views: Minimum view count for quality filtering (default 100, max 1000)
        include_details: Include additional deck details (may slow response)
        
    Returns:
        Dictionary containing high-quality bracket-specific decks with enhanced metadata
    """
    # Validate bracket
    valid_brackets = ["exhibition", "core", "upgraded", "optimized", "cedh"]
    if bracket.lower() not in valid_brackets:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bracket '{bracket}'. Must be one of: {', '.join(valid_brackets)}"
        )
    
    logger.info(f"Fetching popular decks for bracket: {bracket}" + 
               (f" and commander '{commander}'" if commander else "") +
               f" with min_views={min_views} (filtering_enabled={bracket is not None})")
    
    # If commander is specified, only use Moxfield
    if commander:
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=bracket.lower(),
            limit=10,
            commander=commander,
            min_views=min_views
        )
        archidekt_decks = []
        total_sources = "moxfield"
    else:
        # Fetch from both sources with bracket filtering
        moxfield_decks = await scrape_moxfield_popular_decks(
            bracket=bracket.lower(),
            limit=limit_per_source,
            min_views=min_views
        )
        
        archidekt_decks = await scrape_archidekt_popular_decks(
            bracket=bracket.lower(),
            limit=limit_per_source,
            min_views=max(50, min_views // 2)  # Lower threshold for Archidekt
        )
        total_sources = "moxfield+archidekt"
    
    # Combine and rank results by quality score
    all_decks = moxfield_decks + archidekt_decks
    
    # Remove duplicates (same deck URL)
    seen_urls = set()
    unique_decks = []
    for deck in all_decks:
        deck_url = deck.get('url', '')
        if deck_url and deck_url not in seen_urls:
            seen_urls.add(deck_url)
            unique_decks.append(deck)
    
    # Sort by quality score (higher is better)
    unique_decks.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
    
    # Take the best results (limit total for performance)
    final_decks = unique_decks[:min(limit_per_source * 2, 20)]
    
    # Generate statistics
    total_views = sum(deck.get('views', 0) for deck in final_decks)
    avg_views = total_views / len(final_decks) if final_decks else 0
    primer_count = sum(1 for deck in final_decks if deck.get('has_primer', False))
    
    # Count by source
    source_counts = {'moxfield': 0, 'archidekt': 0}
    for deck in final_decks:
        source = deck.get('source', 'unknown')
        if source in source_counts:
            source_counts[source] += 1
    
    # Verify bracket filtering worked and provide detailed breakdown
    bracket_verification = {}
    all_brackets_found = {}
    
    for deck in final_decks:
        bracket_info = deck.get('bracket')
        if isinstance(bracket_info, dict):
            level = bracket_info.get('level', 0)
            name = bracket_info.get('name', 'Unknown')
        elif isinstance(bracket_info, int):
            level = bracket_info
            name = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}.get(level, f"Level {level}")
        else:
            level = 0
            name = 'No bracket info'
        
        # Count all brackets found
        if level in [1, 2, 3, 4, 5]:
            level_name = {1: "Exhibition", 2: "Core", 3: "Upgraded", 4: "Optimized", 5: "cEDH"}.get(level, f"Level {level}")
            all_brackets_found[level_name] = all_brackets_found.get(level_name, 0) + 1
            
            # Count only matching brackets for verification
            target_bracket_name = bracket.lower().title()
            if level_name == target_bracket_name:
                bracket_verification[target_bracket_name] = bracket_verification.get(target_bracket_name, 0) + 1
    
    # Log filtering results for debugging
    if bracket:
        logger.info(f"Bracket filtering results - Target: {bracket}, Found brackets: {all_brackets_found}, Verified matches: {bracket_verification}")
    else:
        logger.info(f"No bracket filter applied. All brackets found: {all_brackets_found}")
    
    # Add summary statistics
    response_data = final_decks.copy()
    for deck in response_data:
        # Ensure quality score is included
        if 'quality_score' not in deck:
            deck['quality_score'] = deck.get('views', 0)
    
    return PopularDecksResponse(
        success=True,
        data=response_data,
        count=len(response_data),
        source=total_sources,
        description=f"High-quality {bracket.title()} bracket Commander decks from {total_sources.replace('+', ' and ')} with minimum {min_views} views",
        bracket=bracket.lower(),
        timestamp=datetime.utcnow().isoformat(),
        stats={
            "total_views": total_views,
            "average_views": round(avg_views, 1),
            "primer_count": primer_count,
            "source_distribution": source_counts,
            "bracket_verification": bracket_verification,
            "all_brackets_found": all_brackets_found if bracket else None,
            "quality_threshold": min_views,
            "filtering_applied": bracket is not None,
            "target_bracket": bracket.lower() if bracket else None
        }
    )


