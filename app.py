"""
MTG Deckbuilding API using mightstone library
FastAPI application for Magic: The Gathering card search and deckbuilding
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mightstone.services import scryfall
from config import settings


# Configure logging
logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# Global mightstone client
client = scryfall.Scryfall()

# Security
security = HTTPBearer()


# Pydantic models for API responses
class CardSearchRequest(BaseModel):
    query: str = Field(..., description="Search query for cards")
    limit: int = Field(default=20, description="Number of cards to return")
    order: str = Field(default="name", description="Sort order")
    unique: str = Field(default="cards", description="Unique card strategy")


class CardResponse(BaseModel):
    id: str
    name: str
    mana_cost: Optional[str] = None
    cmc: Optional[float] = None
    type_line: Optional[str] = None
    oracle_text: Optional[str] = None
    power: Optional[str] = None
    toughness: Optional[str] = None
    loyalty: Optional[str] = None
    colors: Optional[List[str]] = None
    color_identity: Optional[List[str]] = None
    set_name: Optional[str] = None
    set_code: Optional[str] = None
    rarity: Optional[str] = None
    image_uris: Optional[dict] = None
    scryfall_uri: Optional[str] = None


class ApiResponse(BaseModel):
    success: bool
    data: Optional[CardResponse] = None
    data_list: Optional[List[CardResponse]] = None
    message: Optional[str] = None
    count: Optional[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting MTG API with mightstone...")
    # The new Scryfall client doesn't need explicit initialization
    logger.info("Mightstone client ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MTG API...")


# API Key authentication dependency
async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify API key from Authorization header
    Expected format: "Bearer YOUR_API_KEY"
    """
    expected_key = settings.api_key
    
    if not expected_key:
        logger.warning("No API_KEY environment variable set!")
        # In development, allow requests without verification
        if settings.environment == "development":
            return True
    
    if credentials.credentials != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


# Create FastAPI app
app = FastAPI(
    title="MTG Deckbuilding API",
    description="Magic: The Gathering card search and deckbuilding API using mightstone",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def convert_scry_card_to_response(card: scryfall.Card) -> CardResponse:
    """Convert mightstone Card to our API response format"""
    # Convert colors list to strings for JSON serialization
    colors_list = None
    if card.colors:
        colors_list = [str(color) for color in card.colors]
    
    color_identity_list = None
    if hasattr(card, 'color_identity') and card.color_identity:
        color_identity_list = [str(color) for color in card.color_identity]
    
    # Convert image_uris to dict
    image_uris_dict = None
    if card.image_uris:
        # Convert image_uris object to dict
        image_uris_dict = {}
        for key, value in card.image_uris.__dict__.items():
            image_uris_dict[key] = str(value)
    
    return CardResponse(
        id=str(card.id),  # Convert UUID to string
        name=card.name,
        mana_cost=str(card.mana_cost) if card.mana_cost else None,
        cmc=card.cmc,
        type_line=card.type_line,
        oracle_text=card.oracle_text,
        power=str(card.power) if card.power else None,
        toughness=str(card.toughness) if card.toughness else None,
        loyalty=str(card.loyalty) if card.loyalty else None,
        colors=colors_list,
        color_identity=color_identity_list,
        set_name=card.set_name,
        set_code=card.set_code,
        rarity=card.rarity,
        image_uris=image_uris_dict,
        scryfall_uri=None  # This field might not be available in the new API
    )


@app.get("/", response_model=ApiResponse)
async def root():
    """Root endpoint with API information"""
    return ApiResponse(
        success=True,
        message="MTG Deckbuilding API is running!",
        data=None
    )


@app.get("/health", response_model=ApiResponse)
async def health_check():
    """Health check endpoint"""
    return ApiResponse(
        success=True,
        message="API is healthy"
    )


@app.post("/api/v1/cards/search", response_model=ApiResponse)
async def search_cards(
    request: CardSearchRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Search for Magic: The Gathering cards using mightstone's Scryfall integration
    """
    try:
        # Search using mightstone's Scryfall service
        # The search method returns an async generator, so we need to collect cards
        cards = []
        async for card in client.search(request.query):
            cards.append(card)
            if len(cards) >= request.limit:
                break
        
        if not cards:
            return ApiResponse(
                success=True,
                data_list=[],
                message="No cards found",
                count=0
            )
        
        # Convert to response format
        card_responses = [convert_scry_card_to_response(card) for card in cards]
        
        return ApiResponse(
            success=True,
            data_list=card_responses,
            message=f"Found {len(card_responses)} cards",
            count=len(card_responses)
        )
        
    except Exception as e:
        logger.error(f"Error searching cards: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching cards: {str(e)}"
        )


@app.get("/api/v1/cards/{card_id}", response_model=ApiResponse)
async def get_card_by_id(
    card_id: str,
    _: bool = Depends(verify_api_key)
):
    """
    Get detailed information about a specific card by Scryfall ID
    """
    try:
        card = await client.card(card_id)
        
        if not card:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Card not found"
            )
        
        card_response = convert_scry_card_to_response(card)
        
        return ApiResponse(
            success=True,
            data=card_response,
            message="Card retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting card {card_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving card: {str(e)}"
        )


@app.get("/api/v1/cards/random", response_model=ApiResponse)
async def get_random_card(
    query: Optional[str] = None,
    _: bool = Depends(verify_api_key)
):
    """
    Get a random Magic: The Gathering card
    Optional query parameter to filter random cards
    """
    try:
        # Get random card using mightstone
        card = await client.random(query)
        
        if not card:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No random card found"
            )
        
        card_response = convert_scry_card_to_response(card)
        
        return ApiResponse(
            success=True,
            data=card_response,
            message="Random card retrieved successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting random card: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving random card: {str(e)}"
        )


@app.get("/api/v1/cards/autocomplete", response_model=ApiResponse)
async def autocomplete_card_name(
    q: str,
    _: bool = Depends(verify_api_key)
):
    """
    Get autocomplete suggestions for card names
    Query parameter: q (query string)
    """
    try:
        if not q or len(q.strip()) < 2:
            return ApiResponse(
                success=True,
                data_list=[],
                message="Query must be at least 2 characters",
                count=0
            )
        
        # Use mightstone's autocomplete functionality
        catalog = await client.autocomplete_async(q.strip())
        suggestions = catalog.data[:10]  # Limit to 10 suggestions
        
        return ApiResponse(
            success=True,
            data_list=[{"name": name} for name in suggestions],  # Limit to 10 suggestions
            message=f"Found {len(suggestions)} suggestions",
            count=len(suggestions)
        )
        
    except Exception as e:
        logger.error(f"Error in autocomplete for '{q}': {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in autocomplete: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("ENVIRONMENT") == "development"
    )
