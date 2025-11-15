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
from typing import List, Optional, Dict, Any, Tuple, Union, Set
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote, urljoin, quote_plus

import uvicorn
import aiohttp
import httpx
from aiohttp import ClientSession, ClientTimeout
from fastapi import FastAPI, HTTPException, Depends, status, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
# from aiolimiter import AsyncLimiter  # REMOVED - No longer rate limiting EDHRec requests
from cachetools import TTLCache

# from mightstone.services import scryfall  # REMOVED - unused import
from config import settings
from bs4 import BeautifulSoup
import re


EDHREC_BASE_URL = "https://edhrec.com/"
EDHREC_ALLOWED_HOSTS = {"edhrec.com", "www.edhrec.com"}
THEME_INDEX_CACHE_TTL_SECONDS = 6 * 3600  # Refresh the theme catalog every 6 hours


_theme_catalog_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "slugs": set(),
}
_theme_catalog_lock = asyncio.Lock()

# EDHRec helper functions (adapted from user's working implementation)
def extract_build_id_from_html(html: str) -> Optional[str]:
    """Return the Next.js buildId from EDHREC commander HTML (if present)."""
    if not html:
        return None
    build_id_pattern = r'"buildId"\s*:\s*"([^"]+)"'
    match = re.search(build_id_pattern, html)
    if match:
        return match.group(1)
    return None

def normalize_commander_tags(values: list) -> List[str]:
    """Clean and deduplicate commander tags while preserving order."""
    seen = set()
    result = []
    
    for raw in values:
        cleaned = raw.strip() if isinstance(raw, str) else ""
        if not cleaned:
            continue
        if len(cleaned) > 64:
            continue
        if not re.search(r"[A-Za-z]", cleaned):
            continue
            
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    
    return result

def extract_commander_name_from_url(url: str) -> str:
    """Extract commander name from an EDHREC commander URL."""
    try:
        parsed = urlparse(url)
        path = parsed.path or ""
        path = path.split("?")[0].split("#")[0]
        if path.startswith("/"):
            path = path[1:]

        if path.startswith("commanders/"):
            slug = path.split("commanders/", 1)[1]
        else:
            slug = path.split("/")[-1]

        slug = slug.strip("/")
        slug = slug.replace("-", " ").replace("_", " ")
        return " ".join(word.capitalize() for word in slug.split()) or "unknown"
    except Exception:
        return "unknown"

def normalize_commander_name(name: str) -> str:
    """
    Normalize a commander name into a slug suitable for EDHRec URLs.
    """
    slug = name.strip().lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug or "unknown"

def _clean_text(value: str) -> str:
    """Clean HTML text content"""
    from html import unescape
    cleaned = unescape(value or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()

def _gather_section_card_names(source: Any) -> List[str]:
    """Extract card names from JSON source"""
    names = []
    visited = set()
    
    def collect(node):
        node_id = id(node)
        if node_id in visited:
            return
        visited.add(node_id)
        
        if isinstance(node, dict):
            name_value = None
            # Try different possible name fields
            for key in ("name", "cardName", "label", "title"):
                raw = node.get(key)
                if isinstance(raw, str) and raw.strip():
                    name_value = _clean_text(raw)
                    break
            
            if not name_value and isinstance(node.get("names"), list):
                parts = [_clean_text(part) for part in node["names"] if isinstance(part, str)]
                parts = [part for part in parts if part]
                if parts:
                    name_value = " // ".join(parts)
            
            if name_value:
                names.append(name_value)
                
            # Continue traversing
            for child_key, child_value in node.items():
                if child_key in {"name", "cardName", "label", "title", "names"}:
                    continue
                if isinstance(child_value, (dict, list, tuple, set)):
                    collect(child_value)
                    
        elif isinstance(node, (list, tuple, set)):
            str_entries = [_clean_text(entry) for entry in node if isinstance(entry, str) and _clean_text(entry)]
            if str_entries and len(str_entries) == len(node):
                names.extend(str_entries)
            else:
                for entry in node:
                    if isinstance(entry, (dict, list, tuple, set)):
                        collect(entry)
    
    collect(source)
    
    # Deduplicate while preserving order
    deduped = []
    seen = set()
    for name in names:
        cleaned = _clean_text(name)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    
    return deduped

# ... other helper functions and original code remain unchanged ...

class ThemeItem(BaseModel):
    name: str
    id: Optional[str] = None
    image: Optional[str] = None

class ThemeCollection(BaseModel):
    header: str
    items: List[ThemeItem] = Field(default_factory=list)

class ThemeContainer(BaseModel):
    collections: List[ThemeCollection] = Field(default_factory=list)

class PageTheme(BaseModel):
    header: str
    description: str
    tags: List[str] = Field(default_factory=list)
    container: ThemeContainer
    source_url: Optional[str] = None
    error: Optional[str] = None

# ------------------------------------------------
# Create FastAPI application instance BEFORE routes
# ------------------------------------------------

app = FastAPI(
    title="MTG Deckbuilding API",
    description="Scryfall-compliant MTG API with rate limiting and caching",
    version="1.1.0"
)

# Optionally configure CORS (uses settings.allowed_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# other Pydantic models like Card, ThemeCard, ThemeResponse, etc. remain unchanged...

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint"""
    return {
        "message": "MTG Deckbuilding API",
        "version": "1.1.0",
        "docs": "/docs",
        "status": "/api/v1/status"
    }

# status, card search, help, etc. endpoints remain unchanged...

# ----------------------------------------------
# New simplified endpoints (replacing old ones)
# ----------------------------------------------

@app.get("/api/v1/commander/summary", response_model=PageTheme)
async def get_commander_summary(name: str) -> PageTheme:
    """
    Fetches commander data for the given commander name and returns a simplified
    PageTheme.  This implementation does not perform any response-size
    trimming or rate limiting; it normalizes the commander name to an EDHRec
    slug, fetches the commander page via the existing scrape helper, and maps
    categories into a list of ThemeCollections containing only card names.

    :param name: Name of the commander (e.g. "Atraxa, Praetors' Voice")
    :return: PageTheme with header, description, tags, container, and source_url.
    """
    # Normalize name to slug and construct EDHRec URL
    slug = normalize_commander_name(name)
    commander_url = f"{EDHREC_BASE_URL}commanders/{slug}"
    # Fetch commander data using existing helper
    try:
        commander_data = await scrape_edhrec_commander_page(commander_url)
    except HTTPException as exc:
        # propagate any HTTP exceptions such as 404
        raise exc

    # Build collections: each category becomes a ThemeCollection
    collections: List[ThemeCollection] = []
    for key, section in commander_data.get("categories", {}).items():
        if not isinstance(section, dict):
            continue
        header = section.get("category_name") or key
        cards = section.get("cards") or []
        items: List[ThemeItem] = []
        for card in cards:
            if isinstance(card, dict):
                card_name = card.get("name")
                if card_name:
                    items.append(ThemeItem(name=card_name))
        if items:
            collections.append(ThemeCollection(header=header, items=items))

    # Tags from commander_data
    tags = commander_data.get("commander_tags", [])

    header = commander_data.get("commander_name") or name
    description = ""
    source_url = commander_data.get("commander_url")

    return PageTheme(
        header=header,
        description=description,
        tags=tags,
        container=ThemeContainer(collections=collections),
        source_url=source_url,
    )

@app.get("/api/v1/themes/{theme_slug}", response_model=PageTheme)
async def get_theme(theme_slug: str) -> PageTheme:
    """
    Fetch EDHRec theme or tag data via a lightweight mechanism.
    A slug may be a simple theme (e.g. "spellslinger") or include a colour
    prefix (e.g. "temur-spellslinger").  If a colour is detected, the
    prefix is interpreted as the colour identity, and the suffix as the theme.
    Colour names are resolved via COLOR_SLUG_MAP; if no colour is detected,
    the slug is treated as a base theme with no colour restriction.
    """
    sanitized = theme_slug.strip().lower()
    # Try to split on the first hyphen: colour-prefix and theme
    parts = sanitized.split("-", 1)
    color_prefix = None
    theme_name = sanitized
    if len(parts) == 2:
        possible_color, possible_theme = parts
        if possible_color in COLOR_SLUG_MAP:
            color_prefix = possible_color
            theme_name = possible_theme

    # If a colour prefix is detected, call fetch_theme_tag with identity
    if color_prefix:
        return await fetch_theme_tag(theme_name, color_prefix)
    # otherwise fetch the base theme (no colour identity)
    return await fetch_theme_tag(theme_name, None)

# ----------------------------------------------
# Exception handlers and server main remain unchanged...
# ----------------------------------------------


# --------------------------------------------------------------------
# Health endpoint for Render/hosting environment
# --------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """
    Health check endpoint expected by Render. Returns a simple OK
    response to indicate the service is running.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "MTG Deckbuilding API"
    }

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
