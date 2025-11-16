"""Card-related API routes."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.models import Card, CardSearchRequest, CardSearchResponse
from aoa.security import verify_api_key

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger(__name__)


@router.post("/search", response_model=CardSearchResponse)
async def search_cards(request: CardSearchRequest, api_key: str = Depends(verify_api_key)) -> CardSearchResponse:
    """Search for MTG cards using a Scryfall-style query."""
    try:
        mock_cards = [
            {
                "id": "mock1",
                "name": "Lightning Bolt",
                "mana_cost": "{R}",
                "cmc": 1.0,
                "type_line": "Instant",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": ["R"],
                "color_identity": ["R"],
                "keywords": [],
                "legalities": {"commander": "legal", "modern": "legal"},
                "games": ["paper", "mtgo"],
                "reserved": False,
                "foil": True,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": True,
                "variation": False,
                "set_id": "ima",
                "set": "IMA",
                "set_name": "Iconic Masters",
                "set_type": "expansion",
                "set_uri": "https://api.scryfall.com/sets/ima",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2225254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/726e7b11-87f9-4b6e-a9cc-d3d1f862b1a7/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2225254%22",
                "collector_number": "130",
                "digital": False,
                "rarity": "uncommon",
                "artist": "Svetlin Velinov",
                "artist_ids": ["ffd063ae-c35a-4de4-7e5b-c2a1b3395604"],
                "illustration_id": "c5c39b24-30e3-4ba8-8e1c-3c5dd4f8ba19",
                "border_color": "black",
                "frame": "2015",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 2023,
                "penny_rank": 1,
                "prices": {"usd": "1.89", "usd_foil": "4.99", "eur": None, "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"},
            },
            {
                "id": "mock2",
                "name": "Black Lotus",
                "mana_cost": "{0}",
                "cmc": 0.0,
                "type_line": "Artifact",
                "oracle_text": "{T}, Sacrifice Black Lotus: Add three mana of any one color.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": [],
                "color_identity": [],
                "keywords": [],
                "legalities": {"commander": "banned", "modern": "banned"},
                "games": ["paper"],
                "reserved": True,
                "foil": False,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": False,
                "variation": False,
                "set_id": "lea",
                "set": "LEA",
                "set_name": "Limited Edition Alpha",
                "set_type": "core",
                "set_uri": "https://api.scryfall.com/sets/lea",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2222254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/025f11a0-3c9b-4cfe-93a3-8b56b2e8b08e/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2222254%22",
                "collector_number": "4",
                "digital": False,
                "rarity": "rare",
                "artist": "Christopher Rush",
                "artist_ids": ["0d8b21f5-cb8f-40e8-b6b4-8f6ad5f521b7"],
                "illustration_id": "c0afc45b-8bd4-4c08-a09e-2ddfcc7bf10f",
                "border_color": "white",
                "frame": "1993",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 9999,
                "penny_rank": None,
                "prices": {"usd": "8000.00", "usd_foil": None, "eur": "7200.00", "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=600"},
            },
        ]

        filtered_cards = [
            Card(**card) for card in mock_cards if request.query.lower() in card["name"].lower()
        ]
        return CardSearchResponse(object="list", total_cards=len(filtered_cards), data=filtered_cards)
    except Exception as exc:
        logger.error("Error searching cards: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error searching cards: {exc}")


@router.get("/autocomplete")
async def autocomplete_card_names(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Return mock card name suggestions for autocomplete."""
    try:
        mock_suggestions = [
            "Lightning Bolt",
            "Lightning Helix",
            "Lightning Greaves",
            "Lightning Axe",
            "Storm Lightning",
            "Forked Lightning",
            "Arc Lightning",
            "Static Lightning",
        ]
        suggestions = [name for name in mock_suggestions if q.lower() in name.lower()]
        return {"object": "list", "data": suggestions}
    except Exception as exc:
        logger.error("Error in autocomplete for '%s': %s", q, exc)
        raise HTTPException(status_code=500, detail=f"Error in autocomplete: {exc}")


@router.get("/{card_id}", response_model=Card)
async def get_card(card_id: str, api_key: str = Depends(verify_api_key)) -> Card:
    """Return a specific card by ID."""
    try:
        if card_id == "mock1":
            mock_card_data = {
                "id": "mock1",
                "name": "Lightning Bolt",
                "mana_cost": "{R}",
                "cmc": 1.0,
                "type_line": "Instant",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": ["R"],
                "color_identity": ["R"],
                "keywords": [],
                "legalities": {"commander": "legal", "modern": "legal"},
                "games": ["paper", "mtgo"],
                "reserved": False,
                "foil": True,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": True,
                "variation": False,
                "set_id": "ima",
                "set": "IMA",
                "set_name": "Iconic Masters",
                "set_type": "expansion",
                "set_uri": "https://api.scryfall.com/sets/ima",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2225254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/726e7b11-87f9-4b6e-a9cc-d3d1f862b1a7/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2225254%22",
                "collector_number": "130",
                "digital": False,
                "rarity": "uncommon",
                "artist": "Svetlin Velinov",
                "artist_ids": ["ffd063ae-c35a-4de4-7e5b-c2a1b3395604"],
                "illustration_id": "c5c39b24-30e3-4ba8-8e1c-3c5dd4f8ba19",
                "border_color": "black",
                "frame": "2015",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 2023,
                "penny_rank": 1,
                "prices": {"usd": "1.89", "usd_foil": "4.99", "eur": None, "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"},
            }
            return Card(**mock_card_data)
        raise HTTPException(status_code=404, detail="Card not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error fetching card %s: %s", card_id, exc)
        raise HTTPException(status_code=500, detail=f"Error fetching card: {exc}")


@router.get("/random", response_model=Card)
async def get_random_card(api_key: str = Depends(verify_api_key)) -> Card:
    """Return a mock random card."""
    try:
        mock_card_data = {
            "id": "random1",
            "name": "Time Walk",
            "mana_cost": "{2}{U}",
            "cmc": 3.0,
            "type_line": "Sorcery",
            "oracle_text": "Take an extra turn after this one.",
            "power": None,
            "toughness": None,
            "loyalty": None,
            "colors": ["U"],
            "color_identity": ["U"],
            "keywords": [],
            "legalities": {"commander": "banned", "modern": "banned"},
            "games": ["paper", "mtgo"],
            "reserved": True,
            "foil": False,
            "nonfoil": True,
            "oversized": False,
            "promo": False,
            "reprint": True,
            "variation": False,
            "set_id": "vma",
            "set": "VMA",
            "set_name": "Vintage Masters",
            "set_type": "masters",
            "set_uri": "https://api.scryfall.com/sets/vma",
            "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%22325254%22&include_extras=true&include_multilingual=false&include_foil=true",
            "rulings_uri": "https://api.scryfall.com/cards/a3e8f8a2-70e5-4c8c-b2bb-9e9d8e4e35f0/rulings",
            "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%22325254%22",
            "collector_number": "85",
            "digital": False,
            "rarity": "rare",
            "artist": "Jesper Ejsing",
            "artist_ids": ["a5c88e26-c5da-4e85-b797-b7f9a59fba7a"],
            "illustration_id": "b2dbe1b4-62c9-4b9e-aab4-985c4a4c4d5e",
            "border_color": "black",
            "frame": "2015",
            "full_art": False,
            "textless": False,
            "booster": True,
            "story_spotlight": False,
            "edhrec_rank": 500,
            "penny_rank": 10,
            "prices": {"usd": "2800.00", "usd_foil": None, "eur": "2200.00", "eur_foil": None},
            "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=2215"},
        }
        return Card(**mock_card_data)
    except Exception as exc:
        logger.error("Error fetching random card: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error fetching random card: {exc}")

