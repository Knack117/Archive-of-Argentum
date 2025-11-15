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

from mightstone.models import ScryCard
from mightstone.client import AsyncClient
from config import settings


# Configure logging
logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# Global mightstone client
client = AsyncClient()

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
    await client.initialize()
    logger.info("Mightstone client initialized successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MTG API...")
    await client.close()


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


def convert_scry_card_to_response(card: ScryCard) -> CardResponse:
    """Convert mightstone ScryCard to our API response format"""
    return CardResponse(
        id=card.id,
        name=card.name,
        mana_cost=card.mana_cost,
        cmc=card.cmc,
        type_line=card.type_line,
        oracle_text=card.oracle_text,
        power=card.power,
        toughness=card.toughness,
        loyalty=card.loyalty,
        colors=card.colors,
        color_identity=card.color_identity,
        set_name=card.set_name,
        set_code=card.set_code,
        rarity=card.rarity,
        image_uris=card.image_uris,
        scryfall_uri=card.scryfall_uri
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
        # Create search parameters for mightstone
        search_params = SearchParameters(
            name=f"!{request.query}" if request.query else "",  # Exact name match
            order=request.order,
            unique=request.unique,
            include_extras=False
        )
        
        # Search using mightstone's Scryfall service
        cards = await client.search(
            ScryCard,
            query=request.query,
            limit=request.limit,
            order=request.order,
            unique=request.unique
        )
        
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
        suggestions = await client.autocomplete(q.strip())
        
        return ApiResponse(
            success=True,
            data_list=[{"name": name} for name in suggestions[:10]],  # Limit to 10 suggestions
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