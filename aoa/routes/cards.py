"""Card-related API routes."""
from __future__ import annotations

import httpx
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.models import Card, CardSearchRequest, CardSearchResponse
from aoa.security import verify_api_key

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])
logger = logging.getLogger(__name__)


@router.post("/search", response_model=CardSearchResponse)
async def search_cards(request: CardSearchRequest, api_key: str = Depends(verify_api_key)) -> CardSearchResponse:
    """Search for MTG cards using Scryfall API."""
    try:
        async with httpx.AsyncClient() as client:
            # Build Scryfall search URL with query parameters
            scryfall_url = "https://api.scryfall.com/cards/search"
            params = {
                "q": request.query,
                "order": request.order or "name",
                "unique": request.unique or "cards",
                "include_extras": str(request.include_extras).lower() if request.include_extras is not None else "true",
                "include_multilingual": str(request.include_multilingual).lower() if request.include_multilingual is not None else "false",
                "include_foil": str(request.include_foil).lower() if request.include_foil is not None else "true"
            }
            
            if request.per_page:
                params["page_size"] = min(request.per_page, 100)  # Scryfall max is 100
            
            if request.page and request.page > 1:
                params["page"] = request.page
            
            # Log the query for debugging large result sets
            if request.per_page and request.per_page > 50:
                logger.info(f"Large page size requested: {request.per_page} for query: {request.query}")
            
            response = await client.get(scryfall_url, params=params)
            response.raise_for_status()
            
            scryfall_data = response.json()
            
            # Convert Scryfall format to our format
            cards = []
            for card_data in scryfall_data.get("data", []):
                try:
                    card = Card(**card_data)
                    cards.append(card)
                except Exception as e:
                    logger.warning(f"Failed to parse card {card_data.get('name', 'unknown')}: {e}")
                    continue
            
            return CardSearchResponse(
                object="list",
                total_cards=scryfall_data.get("total_cards", len(cards)),  # Use Scryfall's total if available
                data=cards
            )
    except httpx.HTTPStatusError as exc:
        logger.error("Scryfall API error: %s", exc)
        if exc.response.status_code == 429:
            detail = "Rate limit exceeded. Please try again later or use more specific queries with pagination."
        elif "too many results" in str(exc).lower():
            detail = "Query returns too many results. Use per_page and page parameters for pagination, or make your query more specific."
        else:
            detail = "Error communicating with card database"
        raise HTTPException(status_code=502, detail=detail)
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


@router.get("/random", response_model=Card)
async def get_random_card(api_key: str = Depends(verify_api_key)) -> Card:
    """Return a random card from Scryfall API."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.scryfall.com/cards/random")
            response.raise_for_status()
            
            card_data = response.json()
            return Card(**card_data)
    except httpx.HTTPStatusError as exc:
        logger.error("Scryfall API error: %s", exc)
        raise HTTPException(status_code=502, detail="Error communicating with card database")
    except Exception as exc:
        logger.error("Error fetching random card: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error fetching random card: {exc}")


@router.get("/{card_id}", response_model=Card)
async def get_card(card_id: str, api_key: str = Depends(verify_api_key)) -> Card:
    """Return a specific card by ID from Scryfall API."""
    try:
        async with httpx.AsyncClient() as client:
            # Scryfall supports both exact card IDs and "!" notation for exact card lookup
            # Try exact ID first, then try named lookup
            urls_to_try = [
                f"https://api.scryfall.com/cards/{card_id}",
                f"https://api.scryfall.com/cards/named?exact={card_id}"
            ]
            
            for url in urls_to_try:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        card_data = response.json()
                        return Card(**card_data)
                except httpx.HTTPStatusError:
                    continue
            
            # If neither URL worked, return 404
            raise HTTPException(status_code=404, detail="Card not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error fetching card %s: %s", card_id, exc)
        raise HTTPException(status_code=500, detail=f"Error fetching card: {exc}")

