"""Service for fetching gamechanger cards from Scryfall."""
from __future__ import annotations

import httpx
import logging
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def fetch_scryfall_search_cards(search_query: str, order: str = "usd", dir: str = "desc") -> List[Dict[str, Any]]:
    """Fetch cards from Scryfall search with specific query parameters."""
    try:
        # Use Scryfall's search API
        api_url = "https://api.scryfall.com/cards/search"
        params = {
            "q": search_query,
            "order": order,
            "dir": dir,
            "unique": "cards"  # Only show cheapest print for each card
        }
        
        logger.info(f"Fetching from Scryfall API: {search_query}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API errors
            if data.get("object") == "error":
                raise HTTPException(
                    status_code=400, 
                    detail=f"Scryfall error: {data.get('details', 'Unknown error')}"
                )
            
            cards = data.get("data", [])
            logger.info(f"Scryfall API returned {len(cards)} cards")
            
            # Convert Scryfall card data to our format
            formatted_cards = []
            for card in cards:
                formatted_card = {
                    "name": card.get("name", "Unknown"),
                    "mana_cost": card.get("mana_cost", ""),
                    "type_line": card.get("type_line", ""),
                    "oracle_text": card.get("oracle_text", ""),
                    "power": card.get("power", ""),
                    "toughness": card.get("toughness", ""),
                    "loyalty": card.get("loyalty", ""),
                    "mana_value": card.get("mana_value", 0),
                    "colors": card.get("colors", []),
                    "color_identity": card.get("color_identity", []),
                    "rarity": card.get("rarity", ""),
                    "set_name": card.get("set_name", ""),
                    "set_code": card.get("set_code", ""),
                    "collector_number": card.get("collector_number", ""),
                    "released_at": card.get("released_at", ""),
                    "image_uris": card.get("image_uris", {}),
                    "prices": card.get("prices", {}),
                    "usd": card.get("prices", {}).get("usd", ""),
                    "eur": card.get("prices", {}).get("eur", ""),
                    "tix": card.get("prices", {}).get("tix", ""),
                    "scryfall_uri": card.get("scryfall_uri", ""),
                    "id": card.get("id", ""),
                    "cmc": card.get("cmc", 0),  # Converted mana cost
                    "layout": card.get("layout", ""),
                    "multiverse_ids": card.get("multiverse_ids", []),
                }
                formatted_cards.append(formatted_card)
            
            return formatted_cards
            
    except httpx.HTTPStatusError as exc:
        logger.error(f"Scryfall API error: {exc.response.status_code} - {exc}")
        if exc.response.status_code == 429:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
        elif exc.response.status_code == 503:
            raise HTTPException(status_code=503, detail="Card database temporarily unavailable.")
        else:
            raise HTTPException(status_code=502, detail="Error communicating with card database.")
    except Exception as exc:
        logger.error(f"Error fetching Scryfall cards: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching cards: {str(exc)}")


async def fetch_gamechangers() -> List[Dict[str, Any]]:
    """Fetch all gamechanger cards from Scryfall."""
    return await fetch_scryfall_search_cards(
        search_query="is:gamechanger",
        order="usd",
        dir="desc"
    )


async def fetch_banned_cards() -> List[Dict[str, Any]]:
    """Fetch all banned Commander cards from Scryfall."""
    return await fetch_scryfall_search_cards(
        search_query="banned:commander",
        order="name",
        dir="asc"
    )


async def parse_moxfield_mass_land_destruction(html_content: str) -> List[Dict[str, Any]]:
    """Parse Mass Land Destruction cards from Moxfield HTML."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        cards = []
        
        # Look for card data in script tags or structured HTML
        # Based on the extraction, cards are in a structured format
        card_list = soup.find("script", string=lambda x: x and "card_list" in x)
        
        if card_list:
            # Try to extract JSON from script tag
            import re
            json_match = re.search(r'const\s+card_list\s*=\s*(\[[^\]]*\]);', card_list.string)
            if json_match:
                import json
                try:
                    card_data = json.loads(json_match.group(1))
                    for card_item in card_data:
                        formatted_card = {
                            "name": card_item.get("name", "Unknown"),
                            "image_url": card_item.get("image_url", ""),
                            "moxfield_url": card_item.get("moxfield_url", ""),
                            "pricing": {
                                "card_kingdom": card_item.get("pricing", {}).get("card_kingdom"),
                                "reserved": card_item.get("pricing", {}).get("reserved", False)
                            },
                            "source": "moxfield",
                            "category": "mass_land_destruction"
                        }
                        cards.append(formatted_card)
                except json.JSONDecodeError:
                    pass
        
        # Fallback: Look for card links and names
        if not cards:
            # Look for cards by patterns in the page
            card_links = soup.find_all("a", href=lambda x: x and "/cards/" in x)
            for link in card_links:
                name = link.get_text(strip=True)
                href = link.get("href", "")
                
                # Try to find image nearby
                img = link.find("img")
                image_url = img.get("src", "") if img else ""
                
                if name and href and not any(c["name"] == name for c in cards):
                    formatted_card = {
                        "name": name,
                        "image_url": image_url,
                        "moxfield_url": f"https://moxfield.com{href}",
                        "pricing": {
                            "card_kingdom": None,
                            "reserved": False
                        },
                        "source": "moxfield",
                        "category": "mass_land_destruction"
                    }
                    cards.append(formatted_card)
        
        logger.info(f"Parsed {len(cards)} Mass Land Destruction cards from Moxfield")
        return cards
        
    except Exception as exc:
        logger.error(f"Error parsing Moxfield Mass Land Destruction cards: {exc}")
        raise HTTPException(status_code=500, detail=f"Error parsing Mass Land Destruction cards: {str(exc)}")


async def fetch_mass_land_destruction() -> List[Dict[str, Any]]:
    """Fetch Mass Land Destruction cards, using Scryfall as primary source.
    
    Note: Moxfield requires JavaScript rendering, so we use Scryfall's search
    for cards that meet the Mass Land Denial criteria defined by WotC:
    - Cards that regularly destroy, exile, or bounce other lands
    - Cards that keep lands tapped
    - Cards that change what mana is produced by 4+ lands without replacing them
    """
    try:
        # Use Scryfall search for comprehensive MLD cards
        # This includes various types of mass land disruption
        search_queries = [
            # Direct land destruction
            'o:"destroy all lands" legal:commander',
            'o:"destroy all nonbasic" o:"land" legal:commander',
            'o:"exile all lands" legal:commander',
            # Land tap/untap denial
            'o:"lands don\'t untap" legal:commander',
            'o:"lands enter the battlefield tapped" legal:commander',
            # Mana denial/replacement effects on multiple lands
            'o:"all lands are" legal:commander',
            'o:"nonbasic lands are" legal:commander',
        ]
        
        all_cards = []
        seen_names = set()
        
        logger.info("Fetching Mass Land Destruction cards from Scryfall")
        
        for query in search_queries:
            try:
                cards = await fetch_scryfall_search_cards(query, order="name", dir="asc")
                for card in cards:
                    name = card.get("name", "")
                    # Avoid duplicates
                    if name and name not in seen_names:
                        seen_names.add(name)
                        all_cards.append(card)
            except Exception as query_exc:
                # Log but continue with other queries
                logger.warning(f"Query failed: {query} - {query_exc}")
                continue
        
        # Sort alphabetically by name
        all_cards.sort(key=lambda x: x.get("name", "").lower())
        
        logger.info(f"Found {len(all_cards)} Mass Land Destruction cards from Scryfall")
        return all_cards
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching Mass Land Destruction cards: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching Mass Land Destruction cards: {str(exc)}")


__all__ = [
    "fetch_gamechangers",
    "fetch_banned_cards", 
    "fetch_mass_land_destruction",
    "fetch_scryfall_search_cards"
]
