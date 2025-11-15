"""
MTG Deckbuilding API with Rate Limiting, Caching, and Scryfall-Compliant Headers
FastAPI application with proper API etiquette and comprehensive compliance
"""

import os
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
from collections import defaultdict
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from hishel import Headers

from mightstone.services import scryfall
from config import settings


# Configure logging
logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# Scryfall-compliant headers
SCRYFALL_HEADERS = Headers({
    "User-Agent": "MtgDeckbuildingAPI/1.1.0 (https://github.com/Knack117/Archive-of-Argentum)",
    "Accept": "application/json;q=0.9,*/*;q=0.8"
})

# Global mightstone client with custom headers
client = scryfall.Scryfall()

# Configure client headers for Scryfall compliance
try:
    # Set custom headers on the underlying HTTP client
    if hasattr(client, 'client') and hasattr(client.client, 'headers'):
        # Update existing headers
        client.client.headers.update(SCRYFALL_HEADERS)
        logger.info("Configured Scryfall-compliant headers on mightstone client")
    else:
        logger.warning("Could not configure mightstone client headers")
except Exception as e:
    logger.error(f"Failed to configure mightstone headers: {e}")

# Security
security = HTTPBearer()

# Rate limiting storage (in production, use Redis)
rate_limit_store: Dict[str, List[datetime]] = defaultdict(list)

# Cache storage (in production, use Redis/Memcached)
cache_store: Dict[str, tuple] = {}

# Constants for rate limiting
MAX_REQUESTS_PER_SECOND = 10
MIN_DELAY_MS = 50  # 50ms minimum between requests
CACHE_TTL_SECONDS = 3600  # 1 hour cache


class RateLimiter:
    """Rate limiter for API requests"""
    
    def __init__(self, max_requests: int = MAX_REQUESTS_PER_SECOND, window_seconds: int = 1):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed for client"""
        now = datetime.now()
        
        # Clean old entries
        cutoff = now - timedelta(seconds=self.window_seconds)
        rate_limit_store[client_id] = [
            timestamp for timestamp in rate_limit_store[client_id]
            if timestamp > cutoff
        ]
        
        # Check if under limit
        if len(rate_limit_store[client_id]) >= self.max_requests:
            return False
            
        # Record this request
        rate_limit_store[client_id].append(now)
        return True

rate_limiter = RateLimiter()


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


def get_cache_key(query: str, limit: int) -> str:
    """Generate cache key for search query"""
    return f"search:{query}:{limit}"


def get_cached_response(cache_key: str) -> Optional[ApiResponse]:
    """Retrieve cached response"""
    if cache_key in cache_store:
        cached_data, timestamp = cache_store[cache_key]
        if datetime.now() - timestamp < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.info(f"Cache hit for {cache_key}")
            return cached_data
        else:
            # Remove expired cache
            del cache_store[cache_key]
    return None


def cache_response(cache_key: str, response: ApiResponse):
    """Cache response"""
    cache_store[cache_key] = (response, datetime.now())
    logger.info(f"Cached response for {cache_key}")


async def respect_rate_limit():
    """Add delay to respect Scryfall's rate limits"""
    # Add 50ms delay between requests (Scryfall recommends 50-100ms)
    await asyncio.sleep(0.05)


async def safe_mightstone_call(func, *args, **kwargs):
    """Make mightstone API call with rate limiting and error handling"""
    await respect_rate_limit()
    
    try:
        result = await func(*args, **kwargs)
        return result
    except HTTPException as e:
        if e.status_code == 429:  # Too Many Requests
            logger.warning("Scryfall rate limit exceeded - waiting longer")
            await asyncio.sleep(1.0)  # Wait 1 second
            result = await func(*args, **kwargs)
            return result
        else:
            raise
    except Exception as e:
        logger.error(f"Mightstone API error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scryfall API temporarily unavailable"
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting MTG API with mightstone, rate limiting, and Scryfall-compliant headers...")
    
    # Verify header configuration
    try:
        if hasattr(client, 'client') and hasattr(client.client, 'headers'):
            current_headers = client.client.headers
            logger.info(f"Current mightstone headers: {dict(current_headers)}")
            
            # Check if our headers are properly set
            user_agent = current_headers.get('user-agent', '')
            if 'MtgDeckbuildingAPI' in user_agent:
                logger.info("✅ Scryfall-compliant User-Agent configured")
            else:
                logger.warning("⚠️ User-Agent may not be Scryfall-compliant")
        else:
            logger.warning("⚠️ Could not access mightstone client headers")
            
        logger.info("Rate limiting and caching enabled")
    except Exception as e:
        logger.warning(f"Could not verify header configuration: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MTG API...")
    cache_store.clear()
    rate_limit_store.clear()


async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API key from Authorization header"""
    expected_key = settings.api_key
    
    if not expected_key:
        logger.warning("No API_KEY environment variable set!")
        if settings.environment == "development":
            return True
    
    if credentials.credentials != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


def get_client_identifier(request: Request) -> str:
    """Get unique identifier for rate limiting (IP + API key)"""
    # Combine IP address and API key for unique identification
    ip = request.client.host if request.client else "unknown"
    auth_header = request.headers.get("authorization", "")
    api_key = auth_header.replace("Bearer ", "") if auth_header else "anonymous"
    return f"{ip}:{api_key}"


# Create FastAPI app
app = FastAPI(
    title="MTG Deckbuilding API",
    description="Magic: The Gathering card search API with Scryfall rate limiting compliance",
    version="1.2.0",
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


@app.get("/", response_model=ApiResponse)
async def root():
    """Root endpoint with API information"""
    return ApiResponse(
        success=True,
        message="MTG Deckbuilding API v1.2.0 is running! Rate-limited, cached, and Scryfall-compliant.",
        data=None
    )


@app.get("/health", response_model=ApiResponse)
async def health_check():
    """Health check endpoint"""
    return ApiResponse(
        success=True,
        message="API is healthy"
    )


@app.get("/api/v1/status", response_model=ApiResponse)
async def api_status():
    """Get API status including rate limiting and header info"""
    total_cache_items = len(cache_store)
    total_rate_limited_clients = len(rate_limit_store)
    
    # Check header status
    header_status = "unknown"
    try:
        if hasattr(client, 'client') and hasattr(client.client, 'headers'):
            user_agent = client.client.headers.get('user-agent', '')
            if 'MtgDeckbuildingAPI' in user_agent:
                header_status = "compliant"
            else:
                header_status = "non-compliant"
        else:
            header_status = "unavailable"
    except:
        header_status = "error"
    
    return ApiResponse(
        success=True,
        message=f"Cache: {total_cache_items} items, Rate limits: {total_rate_limited_clients} clients, Headers: {header_status}",
        data=None
    )


@app.post("/api/v1/cards/search", response_model=ApiResponse)
async def search_cards(
    request: CardSearchRequest,
    http_request: Request,
    _: bool = Depends(verify_api_key)
):
    """
    Search for Magic: The Gathering cards with rate limiting, caching, and Scryfall compliance
    """
    try:
        # Rate limiting check
        client_id = get_client_identifier(http_request)
        if not rate_limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_SECOND} requests per second.",
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Limit": str(MAX_REQUESTS_PER_SECOND)
                }
            )
        
        # Check cache first
        cache_key = get_cache_key(request.query, request.limit)
        cached_response = get_cached_response(cache_key)
        if cached_response:
            return cached_response
        
        # Make rate-limited API call with proper headers
        cards = []
        async for card in client.search(request.query):
            # Respect rate limit between each card fetch
            await respect_rate_limit()
            cards.append(card)
            if len(cards) >= request.limit:
                break
        
        if not cards:
            response = ApiResponse(
                success=True,
                data_list=[],
                message="No cards found",
                count=0
            )
            # Cache empty results too
            cache_response(cache_key, response)
            return response
        
        # Convert to response format
        card_responses = [convert_scry_card_to_response(card) for card in cards]
        
        response = ApiResponse(
            success=True,
            data_list=card_responses,
            message=f"Found {len(card_responses)} cards",
            count=len(card_responses)
        )
        
        # Cache successful response
        cache_response(cache_key, response)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching cards: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching cards: {str(e)}"
        )


@app.get("/api/v1/cards/{card_id}", response_model=ApiResponse)
async def get_card_by_id(
    card_id: str,
    http_request: Request,
    _: bool = Depends(verify_api_key)
):
    """Get detailed information about a specific card with full compliance"""
    try:
        # Rate limiting check
        client_id = get_client_identifier(http_request)
        if not rate_limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_SECOND} requests per second.",
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Limit": str(MAX_REQUESTS_PER_SECOND)
                }
            )
        
        # Check cache
        cache_key = f"card:{card_id}"
        cached_response = get_cached_response(cache_key)
        if cached_response and cached_response.data:
            return cached_response
        
        # Make rate-limited API call with Scryfall-compliant headers
        card = await safe_mightstone_call(client.card, card_id)
        
        if not card:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Card not found"
            )
        
        card_response = convert_scry_card_to_response(card)
        
        response = ApiResponse(
            success=True,
            data=card_response,
            message="Card retrieved successfully"
        )
        
        # Cache the response
        cache_response(cache_key, response)
        
        return response
        
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
    http_request: Request,
    query: Optional[str] = None,
    _: bool = Depends(verify_api_key)
):
    """Get a random card with full compliance"""
    try:
        # Rate limiting check
        client_id = get_client_identifier(http_request)
        if not rate_limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_SECOND} requests per second.",
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Limit": str(MAX_REQUESTS_PER_SECOND)
                }
            )
        
        # Make rate-limited API call with Scryfall-compliant headers
        card = await safe_mightstone_call(client.random, query)
        
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
    http_request: Request,
    _: bool = Depends(verify_api_key)
):
    """Get autocomplete suggestions with full compliance"""
    try:
        if not q or len(q.strip()) < 2:
            return ApiResponse(
                success=True,
                data_list=[],
                message="Query must be at least 2 characters",
                count=0
            )
        
        # Rate limiting check
        client_id = get_client_identifier(http_request)
        if not rate_limiter.is_allowed(client_id):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_SECOND} requests per second.",
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Limit": str(MAX_REQUESTS_PER_SECOND)
                }
            )
        
        # Check cache
        cache_key = f"autocomplete:{q.strip()}"
        cached_response = get_cached_response(cache_key)
        if cached_response:
            return cached_response
        
        # Make rate-limited API call with Scryfall-compliant headers
        catalog = await safe_mightstone_call(client.autocomplete_async, q.strip())
        suggestions = catalog.data[:10]
        
        response = ApiResponse(
            success=True,
            data_list=[{"name": name} for name in suggestions],
            message=f"Found {len(suggestions)} suggestions",
            count=len(suggestions)
        )
        
        # Cache the response
        cache_response(cache_key, response)
        
        return response
        
    except HTTPException:
        raise
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
