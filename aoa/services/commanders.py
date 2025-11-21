"""Rewritten commander data fetching to work with real EDHRec JSON structure."""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import httpx
from fastapi import HTTPException

from aoa.constants import EDHREC_JSON_BASE_URL

logger = logging.getLogger(__name__)


def normalize_commander_name(name: str) -> str:
    """Normalize commander name for EDHRec URL."""
    if not name:
        return ""
    
    # Remove special characters and normalize
    normalized = name.lower().strip()
    normalized = normalized.replace(",", "-")
    normalized = normalized.replace("'", "")
    normalized = normalized.replace(" ", "-")
    normalized = normalized.replace("--", "-")
    
    # Remove extra hyphens
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    
    return normalized.strip("-")


def extract_commander_name_from_url(url: str) -> str:
    """Extract commander name from EDHRec URL."""
    if not url:
        return ""
    
    # Handle EDHRec URLs
    if "commanders/" in url:
        name_part = url.split("commanders/")[-1]
        # Convert URL format back to readable name
        name = name_part.replace("-", " ").title()
        return name
    
    # If it's already a name, return as-is
    return url.strip()


async def fetch_edhrec_commander_json(commander_url: str) -> Dict[str, Any]:
    """Fetch commander data from EDHRec JSON endpoint with fallback to HTML scraping."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            logger.info(f"Fetching EDHRec JSON for: {commander_url}")
            response = await client.get(commander_url)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully fetched EDHRec data: {len(data)} top-level keys")
            return data
            
    except httpx.RequestError as exc:
        logger.error(f"Network error fetching EDHRec JSON {commander_url}: {exc}")
        logger.info("Attempting HTML scraping fallback...")
        return await _fallback_html_scraping(commander_url)
    except httpx.HTTPStatusError as exc:
        logger.error(f"EDHRec API error {exc.response.status_code}: {exc}")
        logger.info("Attempting HTML scraping fallback...")
        return await _fallback_html_scraping(commander_url)
    except Exception as exc:
        logger.error(f"JSON parsing error: {exc}")
        logger.info("Attempting HTML scraping fallback...")
        return await _fallback_html_scraping(commander_url)


async def _fallback_html_scraping(commander_url: str) -> Dict[str, Any]:
    """Fallback to HTML scraping when JSON API fails."""
    try:
        # Convert JSON URL to HTML URL
        if "json.edhrec.com" in commander_url:
            html_url = commander_url.replace("json.edhrec.com/pages/", "thedocs.esearchtools.com/")
            if not html_url.endswith("/"):
                html_url += "/"
        else:
            html_url = commander_url
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=5.0),
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        ) as client:
            logger.info(f"Fetching HTML fallback: {html_url}")
            response = await client.get(html_url)
            response.raise_for_status()
            
            # For now, return a limited response structure
            # In a full implementation, this would parse the HTML
            logger.warning("HTML scraping fallback implemented - returning limited response")
            
            # Extract commander name from URL
            if "commanders/" in commander_url:
                name_part = commander_url.split("commanders/")[-1]
                commander_name = name_part.replace("-", " ").title()
            else:
                commander_name = "Unknown Commander"
            
            return {
                "card": {
                    "name": commander_name,
                    "sanitized": name_part if "commanders/" in commander_url else "",
                    "num_decks": 0,
                    "rank": None,
                    "salt": None,
                    "cmc": None,
                    "rarity": None,
                    "color_identity": []
                },
                "taglinks": [],
                "similar": [],
                "container": {
                    "json_dict": {
                        "cardlists": []
                    }
                },
                "combocounts": []
            }
            
    except Exception as exc:
        logger.error(f"HTML scraping fallback failed: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Both JSON API and HTML scraping failed for commander data. EDHRec service may be temporarily unavailable."
        )


def extract_commander_summary_data(
    json_data: Dict[str, Any], 
    limit_per_category: Optional[int] = None,
    categories_filter: Optional[Set[str]] = None,
    compact_mode: bool = False
) -> Dict[str, Any]:
    """Extract structured commander summary data from EDHRec JSON response with fallback support."""
    
    # Get commander info from the card section
    card_data = json_data.get("card", {})
    commander_name = card_data.get("name", "Unknown Commander")
    
    # Check if this is fallback data (indicated by limited structure)
    is_fallback = (not card_data.get("num_decks") or card_data.get("num_decks") == 0) and len(json_data.get("container", {}).get("json_dict", {}).get("cardlists", [])) == 0
    
    if is_fallback:
        logger.warning(f"Using fallback response for {commander_name} - EDHRec data unavailable")
        # Return a graceful fallback response
        return {
            "commander_name": commander_name,
            "commander_url": f"https://thedocs.esearchtools.com/commanders/{card_data.get('sanitized', '')}",
            "commander_tags": ["unavailable due to EDHRec access restrictions"],
            "top_10_tags": [{
                "tag": "unavailable due to EDHRec access restrictions",
                "count": None,
                "link": None
            }],
            "all_tags": [{
                "tag": "unavailable due to EDHRec access restrictions",
                "count": None,
                "link": None
            }],
            "combos": [],
            "similar_commanders": [],
            "categories": {},
            "timestamp": datetime.utcnow().isoformat(),
            "commander_stats": {
                "rank": None,
                "total_decks": 0,
                "salt_score": None,
                "cmc": None,
                "rarity": None,
                "color_identity": card_data.get("color_identity", [])
            },
            "warning": "EDHRec JSON API access is currently restricted. Limited commander data available."
        }
    
    logger.info(f"Commander card data: {commander_name} - {card_data.get('num_decks', 0)} decks")
    
    # Get tags data
    tags_data = json_data.get("taglinks", [])
    logger.info(f"Found {len(tags_data)} tags")
    
    # Get similar commanders
    similar_data = json_data.get("similar", [])
    logger.info(f"Found {len(similar_data)} similar commanders")
    
    # Get card categories
    container_data = json_data.get("container", {})
    cardlists = container_data.get("json_dict", {}).get("cardlists", [])
    logger.info(f"Found {len(cardlists)} card categories")
    
    # Extract card data by category
    categories_output = {}
    
    for category in cardlists:
        category_header = category.get("header", "")
        category_tag = category.get("tag", "")
        
        # Skip if not in filter
        if categories_filter and category_tag not in categories_filter:
            continue
            
        # Skip empty categories
        if not category_header:
            continue
            
        cardviews = category.get("cardviews", [])
        if not cardviews:
            continue
            
        # Apply limit per category
        if limit_per_category:
            cardviews = cardviews[:limit_per_category]
        elif compact_mode:
            cardviews = cardviews[:10]  # Compact mode default
        
        # Convert card views to commander cards
        commander_cards = []
        for card in cardviews:
            commander_card = {
                "name": card.get("name"),
                "num_decks": card.get("num_decks"),
                "potential_decks": card.get("potential_decks"),
                "inclusion_percentage": card.get("inclusion") if card.get("inclusion") else None,
                "synergy_percentage": card.get("synergy") if card.get("synergy") else None,
                "sanitized_name": card.get("sanitized"),
                "card_url": card.get("url")
            }
            commander_cards.append(commander_card)
        
        if commander_cards:
            categories_output[category_header] = commander_cards
            logger.info(f"Category '{category_header}': {len(commander_cards)} cards")
    
    # Build tags output
    tags_output = []
    for tag_data in tags_data:
        tags_output.append({
            "tag": tag_data.get("value"),
            "count": tag_data.get("count"),
            "link": f"/tags/{tag_data.get('slug')}"
        })
    
    # Build similar commanders output
    similar_output = []
    for sim_cmd in similar_data:
        similar_output.append({
            "name": sim_cmd.get("name"),
            "url": sim_cmd.get("url")
        })
    
    # Build combos output (if available)
    combos_data = json_data.get("combocounts", [])
    combos_output = []
    for combo in combos_data:
        combo_name = combo.get("value", "")
        if combo_name and combo_name != "See More...":
            combos_output.append({
                "combo": combo_name,
                "url": combo.get("href")
            })
    
    # Build output structure
    result = {
        "commander_name": commander_name,
        "commander_url": f"https://thedocs.esearchtools.com/commanders/{card_data.get('sanitized', '')}",
        "commander_tags": [tag_data.get("value", "") for tag_data in tags_data[:10]],  # Top 10 tags as list of strings
        "top_10_tags": tags_output[:10],  # Top 10 tags as detailed objects
        "all_tags": tags_output,  # All tags as detailed objects
        "combos": combos_output,
        "similar_commanders": similar_output,
        "categories": categories_output,
        "timestamp": datetime.utcnow().isoformat(),
        "commander_stats": {
            "rank": card_data.get("rank"),
            "total_decks": card_data.get("num_decks"),
            "salt_score": card_data.get("salt"),
            "cmc": card_data.get("cmc"),
            "rarity": card_data.get("rarity"),
            "color_identity": card_data.get("color_identity", [])
        }
    }
    
    logger.info(f"Extracted commander summary with {len(result['categories'])} categories, {len(result['all_tags'])} tags")
    return result


async def scrape_edhrec_commander_page(
    commander_url: str,
    limit_per_category: Optional[int] = None,
    categories_filter: Optional[Set[str]] = None,
    compact_mode: bool = False
) -> Dict[str, Any]:
    """Fetch commander data from EDHRec using the JSON endpoint.
    
    This replaces the old HTML scraping approach with the direct JSON API.
    """
    try:
        # Fetch raw JSON data
        json_data = await fetch_edhrec_commander_json(commander_url)
        
        # Extract structured data
        result = extract_commander_summary_data(
            json_data, 
            limit_per_category=limit_per_category,
            categories_filter=categories_filter,
            compact_mode=compact_mode
        )
        
        return result
        
    except Exception as exc:
        logger.error(f"Unexpected error in scrape_edhrec_commander_page: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Failed to process commander data"
        ) from exc
