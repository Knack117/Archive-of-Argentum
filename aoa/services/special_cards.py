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


async def extract_moxfield_mass_land_denial_names() -> List[str]:
    """Extract card names from Moxfield's official mass land denial list."""
    try:
        moxfield_url = "https://moxfield.com/commanderbrackets/masslanddenial"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(moxfield_url)
            response.raise_for_status()
            
            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Extract card names from the page
            # Moxfield displays card names in various formats, look for card links and text
            card_names = []
            
            # Try to find card names in the page structure
            # Method 1: Look for card links
            card_links = soup.find_all("a", href=lambda x: x and "/cards/" in x)
            for link in card_links:
                name = link.get_text(strip=True)
                if name and name not in card_names:
                    card_names.append(name)
            
            # Method 2: Look for specific card list containers
            if not card_names:
                # Try finding divs or spans with card names
                card_elements = soup.find_all(["div", "span"], class_=lambda x: x and "card" in x.lower())
                for elem in card_elements:
                    name = elem.get_text(strip=True)
                    if name and name not in card_names and len(name) > 2:
                        card_names.append(name)
            
            # Method 3: Parse from JSON data embedded in script tags
            if not card_names:
                scripts = soup.find_all("script")
                for script in scripts:
                    if script.string and "cards" in script.string.lower():
                        # Try to extract card names from JSON
                        import re
                        import json
                        # Look for card name patterns
                        matches = re.findall(r'"name"\s*:\s*"([^"]+)"', script.string)
                        card_names.extend([m for m in matches if m not in card_names])
            
            logger.info(f"Extracted {len(card_names)} card names from Moxfield")
            return card_names
            
    except Exception as exc:
        logger.error(f"Error extracting Moxfield mass land denial list: {exc}")
        # Return fallback list if extraction fails
        return []


async def fetch_mass_land_destruction() -> List[Dict[str, Any]]:
    """Fetch Mass Land Destruction cards from Moxfield's official list.
    
    This endpoint extracts the card list from Moxfield's commander brackets
    mass land denial page and fetches full card details from Scryfall.
    """
    try:
        # Hardcoded list from Moxfield (as of 2025-11-19)
        # This ensures consistent results even if web extraction fails
        moxfield_card_names = [
            "Acid Rain", "Apocalypse", "Armageddon", "Back to Basics", "Bearer of the Heavens",
            "Bend or Break", "Blood Moon", "Boil", "Boiling Seas", "Boom // Bust", "Break the Ice",
            "Burning of Xinye", "Cataclysm", "Catastrophe", "Choke", "Cleansing", "Contamination",
            "Conversion", "Curse of Marit Lage", "Death Cloud", "Decree of Annihilation",
            "Desolation Angel", "Destructive Force", "Devastating Dreams", "Devastation",
            "Dimensional Breach", "Disciple of Caelus Nin", "Epicenter", "Fall of the Thran",
            "Flashfires", "Gilt-Leaf Archdruid", "Glaciers", "Global Ruin", "Hall of Gemstone",
            "Harbinger of the Seas", "Hokori, Dust Drinker", "Impending Disaster", "Infernal Darkness",
            "Jokulhaups", "Keldon Firebombers", "Land Equilibrium", "Magus of the Balance",
            "Magus of the Moon", "Myojin of Infinite Rage", "Naked Singularity", "Natural Balance",
            "Obliterate", "Omen of Fire", "Raiding Party", "Ravages of War", "Razia's Purification",
            "Reality Twist", "Realm Razer", "Restore Balance", "Rising Waters", "Ritual of Subdual",
            "Ruination", "Soulscour", "Stasis", "Static Orb", "Storm Cauldron", "Sunder",
            "Sway of the Stars", "Tectonic Break", "Thoughts of Ruin", "Tsunami", "Wake of Destruction",
            "Wildfire", "Winter Moon", "Winter Orb", "Worldfire", "Worldpurge", "Worldslayer"
        ]
        
        logger.info(f"Fetching {len(moxfield_card_names)} Mass Land Denial cards from Scryfall")
        
        all_cards = []
        failed_cards = []
        
        # Fetch each card from Scryfall by exact name
        async with httpx.AsyncClient(timeout=60.0) as client:
            for card_name in moxfield_card_names:
                try:
                    # Use Scryfall's exact name search
                    response = await client.get(
                        "https://api.scryfall.com/cards/named",
                        params={"exact": card_name}
                    )
                    
                    if response.status_code == 200:
                        card_data = response.json()
                        formatted_card = {
                            "name": card_data.get("name", card_name),
                            "mana_cost": card_data.get("mana_cost", ""),
                            "type_line": card_data.get("type_line", ""),
                            "oracle_text": card_data.get("oracle_text", ""),
                            "mana_value": card_data.get("mana_value", 0),
                            "colors": card_data.get("colors", []),
                            "color_identity": card_data.get("color_identity", []),
                            "rarity": card_data.get("rarity", ""),
                            "set_name": card_data.get("set_name", ""),
                            "set_code": card_data.get("set_code", ""),
                            "image_uris": card_data.get("image_uris", {}),
                            "prices": card_data.get("prices", {}),
                            "scryfall_uri": card_data.get("scryfall_uri", ""),
                            "id": card_data.get("id", ""),
                        }
                        all_cards.append(formatted_card)
                    else:
                        failed_cards.append(card_name)
                        logger.warning(f"Card not found on Scryfall: {card_name}")
                        
                except Exception as card_exc:
                    failed_cards.append(card_name)
                    logger.warning(f"Error fetching card '{card_name}': {card_exc}")
                    continue
        
        # Sort alphabetically by name
        all_cards.sort(key=lambda x: x.get("name", "").lower())
        
        logger.info(f"Successfully fetched {len(all_cards)}/{len(moxfield_card_names)} Mass Land Denial cards")
        if failed_cards:
            logger.warning(f"Failed to fetch {len(failed_cards)} cards: {', '.join(failed_cards)}")
        
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
