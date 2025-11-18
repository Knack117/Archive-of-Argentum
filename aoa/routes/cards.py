"""Fixed card search route with proper Scryfall API handling."""
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
    """Search for MTG cards using Scryfall API.
    
    NOTE: Scryfall returns up to 175 cards per page (fixed by Scryfall).
    The per_page parameter limits results client-side after fetching from Scryfall.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:  # Increased timeout for large responses
            # Build Scryfall search URL with query parameters
            scryfall_url = "https://api.scryfall.com/cards/search"
            params = {
                "q": request.query,
                "order": request.order or "name",
                "unique": request.unique or "cards",
            }
            
            # Only add page parameter if explicitly requesting a page > 1
            if request.page and request.page > 1:
                params["page"] = request.page
            
            # NOTE: Scryfall does not support page_size, include_extras, include_multilingual, 
            # or include_foil parameters in the /cards/search endpoint.
            # These can only be controlled via the query string itself.
            # Example: "include:extras" in query to include extras
            
            # Set a reasonable per_page default if not specified
            effective_per_page = request.per_page if request.per_page else 20
            
            # Warn about large requests
            if effective_per_page > 100:
                logger.warning(f"Large per_page requested ({effective_per_page}) for query: {request.query}")
            
            # Make the API call
            logger.info(f"Scryfall search: query='{request.query}', page={request.page or 1}")
            response = await client.get(scryfall_url, params=params)
            response.raise_for_status()
            
            scryfall_data = response.json()
            
            # Check if we got an error response from Scryfall
            if scryfall_data.get("object") == "error":
                error_msg = scryfall_data.get("details", "Unknown Scryfall error")
                logger.error(f"Scryfall error: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Card search error: {error_msg}")
            
            # Convert Scryfall format to our format with CLIENT-SIDE LIMITING
            cards = []
            scryfall_cards = scryfall_data.get("data", [])
            
            logger.info(f"Scryfall returned {len(scryfall_cards)} cards, limiting to {effective_per_page}")
            
            for card_data in scryfall_cards:
                # Stop if we've reached the requested limit (client-side pagination)
                if len(cards) >= effective_per_page:
                    logger.info(f"Reached per_page limit of {effective_per_page}, stopping parse")
                    break
                    
                try:
                    card = Card(**card_data)
                    cards.append(card)
                except Exception as e:
                    logger.warning(f"Failed to parse card {card_data.get('name', 'unknown')}: {e}")
                    continue
            
            # Log final statistics
            total_cards = scryfall_data.get("total_cards", len(cards))
            has_more = scryfall_data.get("has_more", False)
            logger.info(
                f"Search complete: returned {len(cards)}/{len(scryfall_cards)} cards, "
                f"total available: {total_cards}, has_more: {has_more}"
            )
            
            return CardSearchResponse(
                object="list",
                total_cards=total_cards,  # Use Scryfall's total count
                data=cards  # Limited by per_page
            )
            
    except httpx.HTTPStatusError as exc:
        logger.error(f"Scryfall API HTTP error: {exc.response.status_code} - {exc}")
        
        # Try to parse error response from Scryfall
        try:
            error_data = exc.response.json()
            if error_data.get("object") == "error":
                detail = f"Scryfall error: {error_data.get('details', 'Unknown error')}"
            else:
                detail = "Error communicating with card database"
        except:
            detail = "Error communicating with card database"
        
        if exc.response.status_code == 429:
            detail = "Rate limit exceeded. Please try again later or use more specific queries."
        elif exc.response.status_code == 503:
            detail = "Card database temporarily unavailable. Please try again in a moment."
            
        raise HTTPException(status_code=502, detail=detail)
        
    except httpx.TimeoutException:
        logger.error(f"Scryfall API timeout for query: {request.query}")
        raise HTTPException(
            status_code=504, 
            detail="Card search timed out. Try a more specific query or use pagination."
        )
        
    except Exception as exc:
        logger.error(f"Error searching cards: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=500, detail=f"Error searching cards: {str(exc)}")


@router.get("/autocomplete")
async def autocomplete_card_names(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Return card name suggestions using Scryfall autocomplete API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use Scryfall's autocomplete endpoint
            response = await client.get(
                "https://api.scryfall.com/cards/autocomplete",
                params={"q": q}
            )
            response.raise_for_status()
            
            # Scryfall returns {"object": "catalog", "data": ["card1", "card2", ...]}
            data = response.json()
            suggestions = data.get("data", [])
            
            return {"object": "list", "data": suggestions}
            
    except httpx.HTTPStatusError as exc:
        logger.error(f"Scryfall autocomplete error: {exc}")
        # Fallback to mock data if Scryfall fails
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
        logger.error(f"Error in autocomplete for '{q}': {exc}")
        raise HTTPException(status_code=500, detail=f"Error in autocomplete: {exc}")


@router.get("/random", response_model=Card)
async def get_random_card(api_key: str = Depends(verify_api_key)) -> Card:
    """Return a random card from Scryfall API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://api.scryfall.com/cards/random")
            response.raise_for_status()
            
            card_data = response.json()
            return Card(**card_data)
    except httpx.HTTPStatusError as exc:
        logger.error(f"Scryfall API error: {exc}")
        raise HTTPException(status_code=502, detail="Error communicating with card database")
    except Exception as exc:
        logger.error(f"Error fetching random card: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching random card: {exc}")


@router.get("/{card_id}", response_model=Card)
async def get_card(card_id: str, api_key: str = Depends(verify_api_key)) -> Card:
    """Return a specific card by ID from Scryfall API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        logger.error(f"Error fetching card {card_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching card: {exc}")
