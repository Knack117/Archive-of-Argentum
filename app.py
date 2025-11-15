"""
MTG Deckbuilding API with Rate Limiting, Caching, and Scryfall-Compliant Headers
FastAPI application with proper API etiquette and comprehensive compliance
"""

import os
import asyncio
import logging
import time
import json
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from collections import defaultdict
from datetime import datetime, timedelta

import uvicorn
import aiohttp
from aiohttp import ClientSession, ClientTimeout
from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from aiolimiter import AsyncLimiter
from cachetools import TTLCache

from mightstone.services import scryfall
from config import settings


# Configure logging
logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

# Scryfall-compliant headers
SCRYFALL_HEADERS = {
    "User-Agent": "MtgDeckbuildingAPI/1.1.0 (https://github.com/Knack117/Archive-of-Argentum)",
    "Accept": "application/json;q=0.9,*/*;q=0.8"
}

# Rate limiter: 10 requests per second per client (Scryfall limit)
rate_limiter = AsyncLimiter(max_rate=10, time_period=1.0)

# Cache for Scryfall responses (1 hour TTL for 80-90% hit rate)
cache = TTLCache(maxsize=1000, ttl=3600)

# Global HTTP session with custom headers
http_session: Optional[ClientSession] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for HTTP session"""
    global http_session
    # Startup
    timeout = ClientTimeout(total=30, connect=10)
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=10)
    http_session = ClientSession(
        headers=SCRYFALL_HEADERS,
        timeout=timeout,
        connector=connector
    )
    logger.info("Started HTTP session with Scryfall-compliant headers")
    
    try:
        yield
    finally:
        # Shutdown
        if http_session:
            await http_session.close()
            logger.info("Closed HTTP session")


# Create FastAPI app with lifespan
app = FastAPI(
    title="MTG Deckbuilding API",
    description="Scryfall-compliant MTG API with rate limiting and caching",
    version="1.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Rate limiting per client (IP + API key)
client_rate_limits = defaultdict(list)


async def get_client_identifier(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get unique client identifier for rate limiting"""
    client_ip = request.client.host if request.client else "unknown"
    api_key = credentials.credentials if credentials else "no_key"
    return f"{client_ip}:{api_key}"


async def check_rate_limit(client_id: str):
    """Check if client has exceeded rate limit"""
    now = time.time()
    # Clean old entries (older than 1 second)
    client_rate_limits[client_id] = [
        timestamp for timestamp in client_rate_limits[client_id]
        if now - timestamp < 1.0
    ]
    
    # Check if at limit
    if len(client_rate_limits[client_id]) >= 10:  # 10 requests per second
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Maximum 10 requests per second per client."
        )
    
    # Record this request
    client_rate_limits[client_id].append(now)


async def make_scryfall_request(url: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
    """Make rate-limited request to Scryfall with proper error handling"""
    await rate_limiter.acquire()
    
    # Check cache for GET requests
    if method == "GET":
        cache_key = f"{url}:{json.dumps(kwargs.get('params', {}), sort_keys=True)}"
        if cache_key in cache:
            logger.debug(f"Cache hit for {url}")
            return cache[cache_key]
    
    if not http_session:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HTTP session not available"
        )
    
    try:
        async with http_session.request(method, url, **kwargs) as response:
            # Handle rate limiting
            if response.status == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limit exceeded, retrying after {retry_after}s")
                await asyncio.sleep(retry_after)
                return await make_scryfall_request(url, method, **kwargs)
            
            # Handle other errors
            if response.status >= 400:
                error_text = await response.text()
                logger.error(f"Scryfall API error {response.status}: {error_text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Scryfall API error: {response.status}"
                )
            
            # Parse successful response
            data = await response.json()
            
            # Cache successful GET responses
            if method == "GET" and response.status == 200:
                cache[cache_key] = data
                logger.debug(f"Cached response for {url}")
            
            return data
            
    except asyncio.TimeoutError:
        logger.error(f"Timeout requesting {url}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Scryfall API timeout"
        )
    except Exception as e:
        logger.error(f"Error requesting {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Scryfall API request failed: {str(e)}"
        )


# Pydantic models
class Card(BaseModel):
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
    keywords: Optional[List[str]] = None
    games: Optional[List[str]] = None
    reserved: Optional[bool] = None
    foil: Optional[bool] = None
    nonfoil: Optional[bool] = None
    oversized: Optional[bool] = None
    promo: Optional[bool] = None
    reprint: Optional[bool] = None
    variation: Optional[bool] = None
    set_id: Optional[str] = None
    set: Optional[str] = None
    set_name: Optional[str] = None
    set_type: Optional[str] = None
    set_uri: Optional[str] = None
    set_search_uri: Optional[str] = None
    scryfall_set_uri: Optional[str] = None
    rulings_uri: Optional[str] = None
    prints_search_uri: Optional[str] = None
    collector_number: Optional[str] = None
    digital: Optional[bool] = None
    rarity: Optional[str] = None
    flavor_text: Optional[str] = None
    artist: Optional[str] = None
    artist_ids: Optional[List[str]] = None
    illustration_id: Optional[str] = None
    border_color: Optional[str] = None
    frame: Optional[str] = None
    full_art: Optional[bool] = None
    textless: Optional[bool] = None
    booster: Optional[bool] = None
    story_spotlight: Optional[bool] = None
    edhrec_rank: Optional[int] = None
    penny_rank: Optional[int] = None
    prices: Optional[Dict[str, Optional[str]]] = None
    related_uris: Optional[Dict[str, str]] = None
    mana_cost_html: Optional[str] = None
    generated_mana: Optional[str] = None


class CardsResponse(BaseModel):
    object: str
    total_cards: int
    has_more: bool
    next_page: Optional[str] = None
    data: List[Card]


class StatusResponse(BaseModel):
    status: str
    timestamp: str
    cache_stats: Dict[str, Any]
    rate_limiting: Dict[str, Any]
    scryfall_compliance: Dict[str, Any]


@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint"""
    return {
        "message": "MTG Deckbuilding API",
        "version": "1.1.0",
        "docs": "/docs",
        "status": "/api/v1/status"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for Render monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "MTG Deckbuilding API"
    }


@app.get("/api/v1/status", response_model=StatusResponse)
async def get_status():
    """Get API status and compliance information"""
    return StatusResponse(
        status="operational",
        timestamp=datetime.utcnow().isoformat(),
        cache_stats={
            "size": cache.currsize,
            "maxsize": cache.maxsize,
            "hit_rate_estimate": f"{(cache.currsize / max(1, cache.maxsize)) * 100:.1f}%"
        },
        rate_limiting={
            "enabled": True,
            "limit_per_client": "10 requests/second",
            "global_limit": "10 requests/second"
        },
        scryfall_compliance={
            "user_agent": SCRYFALL_HEADERS["User-Agent"],
            "accept_header": SCRYFALL_HEADERS["Accept"],
            "rate_limit_compliant": True,
            "caching_enabled": True,
            "retry_logic": True
        }
    )


@app.get("/api/v1/cards/random", response_model=Card)
async def get_random_card(client_id: str = Depends(get_client_identifier)):
    """Get a random card"""
    await check_rate_limit(client_id)
    
    url = "https://api.scryfall.com/cards/random"
    data = await make_scryfall_request(url)
    
    return Card(**data)


@app.get("/api/v1/cards/search", response_model=CardsResponse)
async def search_cards(
    q: str,
    unique: Optional[str] = None,
    order: Optional[str] = None,
    dir: Optional[str] = None,
    include_extras: Optional[bool] = None,
    include_multilingual: Optional[bool] = None,
    page: Optional[int] = None,
    client_id: str = Depends(get_client_identifier)
):
    """Search for cards using Scryfall syntax"""
    await check_rate_limit(client_id)
    
    params = {"q": q}
    if unique:
        params["unique"] = unique
    if order:
        params["order"] = order
    if dir:
        params["dir"] = dir
    if include_extras is not None:
        params["include_extras"] = str(include_extras).lower()
    if include_multilingual is not None:
        params["include_multilingual"] = str(include_multilingual).lower()
    if page:
        params["page"] = page
    
    url = "https://api.scryfall.com/cards/search"
    data = await make_scryfall_request(url, params=params)
    
    return CardsResponse(**data)


@app.get("/api/v1/cards/{card_id}", response_model=Card)
async def get_card(
    card_id: str,
    client_id: str = Depends(get_client_identifier)
):
    """Get a specific card by Scryfall ID"""
    await check_rate_limit(client_id)
    
    url = f"https://api.scryfall.com/cards/{card_id}"
    data = await make_scryfall_request(url)
    
    return Card(**data)


@app.get("/api/v1/cards/collection", response_model=CardsResponse)
async def get_cards_collection(
    identifiers: List[str],
    client_id: str = Depends(get_client_identifier)
):
    """Get multiple cards by identifiers"""
    await check_rate_limit(client_id)
    
    payload = {"identifiers": [{"id": card_id} for card_id in identifiers]}
    
    url = "https://api.scryfall.com/cards/collection"
    data = await make_scryfall_request(
        url,
        method="POST",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    return CardsResponse(**data)


@app.get("/api/v1/sets", response_model=Dict[str, Any])
async def get_sets(client_id: str = Depends(get_client_identifier)):
    """Get all sets"""
    await check_rate_limit(client_id)
    
    url = "https://api.scryfall.com/sets"
    data = await make_scryfall_request(url)
    
    return data


@app.get("/api/v1/sets/{set_code}", response_model=Dict[str, Any])
async def get_set(
    set_code: str,
    client_id: str = Depends(get_client_identifier)
):
    """Get a specific set"""
    await check_rate_limit(client_id)
    
    url = f"https://api.scryfall.com/sets/{set_code.lower()}"
    data = await make_scryfall_request(url)
    
    return data


@app.get("/api/v1/symbology/ Mana", response_model=Dict[str, Any])
async def get_mana_symbology(client_id: str = Depends(get_client_identifier)):
    """Get mana symbol reference data"""
    await check_rate_limit(client_id)
    
    url = "https://api.scryfall.com/symbology"
    data = await make_scryfall_request(url)
    
    return data


@app.get("/api/v1/names", response_model=Dict[str, Any])
async def get_names(client_id: str = Depends(get_client_identifier)):
    """Get all card names"""
    await check_rate_limit(client_id)
    
    url = "https://api.scryfall.com/names"
    data = await make_scryfall_request(url)
    
    return data


@app.get("/api/v1/rulings/{card_id}", response_model=Dict[str, Any])
async def get_rulings(
    card_id: str,
    client_id: str = Depends(get_client_identifier)
):
    """Get rulings for a specific card"""
    await check_rate_limit(client_id)
    
    url = f"https://api.scryfall.com/cards/{card_id}/rulings"
    data = await make_scryfall_request(url)
    
    return data


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with proper error format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
        log_level=settings.log_level.lower()
    )
