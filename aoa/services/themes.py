"""Utilities for performing live theme data extraction from EDHRec HTML pages."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

from aoa.constants import EDHREC_BASE_URL

logger = logging.getLogger(__name__)


async def scrape_edhrec_theme_page(theme_url: str) -> Dict[str, Any]:
    """Fetch theme data from EDHRec HTML pages using web scraping."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://edhrec.com/",
        }
        
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(theme_url, headers=headers)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        next_data = soup.find("script", id="__NEXT_DATA__", type="application/json")
        
        if not next_data or not next_data.string:
            raise HTTPException(
                status_code=404,
                detail=f"No data found on theme page: {theme_url}"
            )

        data = json.loads(next_data.string)
        return extract_theme_data_from_json(data)
        
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Theme page not found: {theme_url}"
            )
        else:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=f"Failed to fetch theme page: {theme_url}"
            )
    except httpx.RequestError as exc:
        logger.error("Network error fetching theme page %s: %s", theme_url, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to contact EDHRec for theme: {theme_url}"
        )
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in theme page %s: %s", theme_url, exc)
        raise HTTPException(
            status_code=500,
            detail="Invalid data format from EDHRec"
        )
    except Exception as exc:
        logger.error("Unexpected error fetching theme page %s: %s", theme_url, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract theme data: {exc}"
        )


def extract_theme_data_from_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract theme data from the Next.js payload."""
    try:
        # Navigate to the correct data structure
        page_props = payload.get("props", {}).get("pageProps", {})
        data = page_props.get("data", {})
        container = data.get("container", {})
        json_dict = container.get("json_dict", {})
        cardlists = json_dict.get("cardlists", [])
        
        # Extract header and description
        header = data.get("header", container.get("title", "Theme"))
        description = container.get("description", data.get("description", ""))
        
        # Extract color identity deck statistics from related_info
        deck_stats = {}
        related_info = data.get("related_info", [])
        for section in related_info:
            section_header = section.get("header", "")
            items = section.get("items", [])
            for item in items:
                color_identity = item.get("textLeft", "")
                count = item.get("count", 0)
                if color_identity and count:
                    deck_stats[color_identity] = count
        
        # Extract card collections
        collections = []
        for cardlist in cardlists:
            if not isinstance(cardlist, dict):
                continue
                
            list_header = cardlist.get("header") or cardlist.get("tag", "Cards")
            cardviews = cardlist.get("cardviews", [])
            
            items = []
            for card_data in cardviews:
                if not isinstance(card_data, dict):
                    continue
                    
                card_name = card_data.get("name", "Unknown")
                inclusion = card_data.get("inclusion", 0)
                synergy = card_data.get("synergy", 0)
                label = card_data.get("label", "")
                num_decks = card_data.get("num_decks", inclusion)
                potential_decks = card_data.get("potential_decks", 0)
                
                # Calculate inclusion percentage
                inclusion_percentage = 0
                if potential_decks > 0:
                    inclusion_percentage = (inclusion / potential_decks) * 100
                
                items.append({
                    "card_name": card_name,
                    "inclusion": inclusion,
                    "inclusion_percentage": f"{inclusion_percentage:.1f}%",
                    "synergy": synergy,
                    "synergy_percentage": f"{synergy * 100:.0f}%" if synergy else "0%",
                    "num_decks": num_decks,
                    "potential_decks": potential_decks,
                    "label": label
                })
            
            if items:
                collections.append({
                    "header": list_header,
                    "items": items
                })

        return {
            "header": header,
            "description": description,
            "deck_statistics": deck_stats,
            "collections": collections,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
    except Exception as exc:
        logger.error("Error extracting theme data from JSON: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse theme data: {str(exc)}"
        )


def build_theme_url(theme_slug: str) -> str:
    """Build the EDHRec URL for a theme (legacy function)."""
    sanitized = theme_slug.strip().lower().replace(" ", "-")
    return f"{EDHREC_BASE_URL}tags/{sanitized}"


def build_theme_url_with_colors(theme_slug: str, color_identity: Optional[str] = None) -> str:
    """Build EDHRec URL with correct theme-color pattern."""
    sanitized = theme_slug.strip().lower().replace(" ", "-")
    
    if color_identity:
        # Use correct pattern: theme-color, not color-theme
        normalized_color = color_identity.lower().replace(" ", "-")
        return f"{EDHREC_BASE_URL}tags/{sanitized}-{normalized_color}"
    else:
        return f"{EDHREC_BASE_URL}tags/{sanitized}"


async def scrape_edhrec_theme_by_slug(theme_slug: str, color_identity: Optional[str] = None) -> Dict[str, Any]:
    """Scrape theme data by theme slug with optional color identity."""
    theme_url = build_theme_url_with_colors(theme_slug, color_identity)
    return await scrape_edhrec_theme_page(theme_url)


__all__ = [
    "scrape_edhrec_theme_page",
    "scrape_edhrec_theme_by_slug", 
    "build_theme_url",
    "build_theme_url_with_colors",
    "extract_theme_data_from_json",
]
