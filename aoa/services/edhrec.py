"""Sophisticated EDHREC service - matching the approach from the other repository."""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote_plus

import httpx
from fastapi import HTTPException

from aoa.constants import EDHREC_BASE_URL
from aoa.models.themes import EdhrecError, ThemeCollection, ThemeContainer, ThemeItem, PageTheme
from aoa.utils.commander_identity import normalize_commander_name, get_commander_slug_candidates
from aoa.utils.edhrec_commander import (
    extract_build_id_from_html,
    extract_commander_tags_from_html,
    extract_commander_tags_from_json,
    extract_nextjs_payload,
    normalize_commander_tags,
    _camel_or_snake_to_title,
    _order_commander_headers,
)

logger = logging.getLogger(__name__)


class CommanderPageSnapshot:
    """In-memory representation of commander page metadata."""
    
    def __init__(self, url: str, html: str, tags: List[str], json_payload: Optional[Dict[str, Any]] = None):
        self.url = url
        self.html = html
        self.tags = tags
        self.json_payload = json_payload


async def fetch_commander_summary(name: str, budget: Optional[str] = None) -> Dict[str, Any]:
    """Fetch comprehensive commander summary using sophisticated EDHREC extraction."""
    try:
        display_name, slug, edhrec_url = normalize_commander_name(name)
        
        # Fetch commander page snapshot
        snapshot = await _fetch_commander_page_snapshot(slug)
        if not snapshot:
            raise EdhrecError("NOT_FOUND", f"Could not find commander data for '{display_name}'")
        
        # Extract synergy data using sophisticated Next.js approach
        page_data, snapshot = await _try_fetch_commander_synergy(slug, snapshot=snapshot)
        
        # Build PageTheme response
        tags = snapshot.tags if snapshot else []
        source_url = snapshot.url if snapshot else edhrec_url
        
        # Check if we have meaningful data
        if not _payload_has_collections(page_data):
            # Return fallback with error message
            fallback_page = PageTheme(
                header=f"{display_name} | EDHREC",
                description="",
                tags=tags,
                container=ThemeContainer(collections=[]),
                source_url=source_url,
                error=f"Synergy unavailable for {display_name}",
            )
            return fallback_page.dict()
        
        # Process the data into the expected format
        processed_data = _process_commander_data(page_data, display_name, tags, source_url)
        return processed_data
        
    except EdhrecError:
        raise
    except Exception as exc:
        logger.exception(f"Failed to fetch commander summary for '{name}': {exc}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


async def _fetch_commander_page_snapshot(slug: str) -> Optional[CommanderPageSnapshot]:
    """Fetch commander page snapshot with both HTML and JSON data."""
    commander_url = f"{EDHREC_BASE_URL}commanders/{slug}"
    
    try:
        # Fetch HTML
        html = await _fetch_text(commander_url)
    except HTTPException:
        logger.warning(f"Commander HTML fetch failed for slug '{slug}'")
        return None
    
    # Extract tags from HTML
    html_tags = extract_commander_tags_from_html(html)
    
    # Extract build ID for JSON
    build_id = extract_build_id_from_html(html)
    
    json_payload = None
    json_tags = []
    
    if build_id:
        json_url = f"{EDHREC_BASE_URL}_next/data/{build_id}/commanders/{slug}.json"
        try:
            json_payload = await _fetch_json(json_url)
            json_tags = extract_commander_tags_from_json(json_payload)
        except HTTPException:
            logger.warning(f"Commander JSON fetch failed for slug '{slug}'")
            json_payload = None
    else:
        logger.warning(f"No buildId discovered for commander slug '{slug}'")
    
    # Combine and normalize tags
    tags = normalize_commander_tags(html_tags + json_tags)
    
    return CommanderPageSnapshot(
        url=commander_url,
        html=html,
        tags=tags,
        json_payload=json_payload,
    )


async def _try_fetch_commander_synergy(
    slug: str, 
    snapshot: Optional[CommanderPageSnapshot] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[CommanderPageSnapshot]]:
    """Try to fetch commander synergy data using Next.js JSON extraction."""
    if snapshot is None:
        snapshot = await _fetch_commander_page_snapshot(slug)
    
    if snapshot is None:
        return None, None
    
    # Extract title and description from HTML
    header, description = _extract_title_description_from_head(snapshot.html)
    
    # Extract card buckets from JSON payload
    buckets = _extract_commander_buckets(snapshot.json_payload or {})
    ordered_headers = _order_commander_headers(list(buckets.keys()))
    
    # Build collections
    collections = []
    for header_name in ordered_headers:
        items = buckets.get(header_name, [])
        if items:
            collections.append(ThemeCollection(header=header_name, items=items))
    
    # Build PageTheme
    page = PageTheme(
        header=header or f"{slug.replace('-', ' ').title()} | EDHREC",
        description=description or "",
        tags=snapshot.tags,
        container=ThemeContainer(collections=collections),
        source_url=snapshot.url,
    )
    
    return page.dict(), snapshot


def _extract_title_description_from_head(html: str) -> Tuple[str, str]:
    """Extract title and description from HTML head."""
    import re
    title = ""
    desc = ""
    
    # Extract title
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = _snakecase(re.sub(r"<.*?>", "", title_match.group(1)))
    
    # Extract description
    desc_match = re.search(
        r'<meta\s+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html, re.IGNORECASE | re.DOTALL
    )
    if desc_match:
        desc = _snakecase(desc_match.group(1))
    
    return title or "Unknown", desc or ""


def _snakecase(s: str) -> str:
    """Convert string to snake case."""
    import re
    return re.sub(r"\s+", " ", s or "").strip()


def _extract_commander_buckets(data: Any) -> Dict[str, List[ThemeItem]]:
    """Extract commander card buckets from JSON payload."""
    buckets = {}
    visited_lists = set()
    
    def walk(node: Any, path: List[str]):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + [key])
            return
        
        if isinstance(node, list):
            node_id = id(node)
            if node_id in visited_lists:
                return
            visited_lists.add(node_id)
            
            # Extract card-like items
            items = []
            for element in node:
                item = _commander_item_from_entry(element)
                if item:
                    items.append(item)
            
            if items:
                key = path[-1] if path else "cards"
                header = _camel_or_snake_to_title(key)
                existing = buckets.setdefault(header, [])
                existing_names = {it.name for it in existing}
                for item in items:
                    if item.name not in existing_names:
                        existing.append(item)
                        existing_names.add(item.name)
            
            # Continue walking nested elements
            for element in node:
                walk(element, path)
    
    if isinstance(data, dict):
        # Handle Next.js pageProps structure
        page_props = data.get("pageProps")
        if isinstance(page_props, dict) and "data" in page_props:
            walk(page_props.get("data"), [])
        else:
            walk(data, [])
    else:
        walk(data, [])
    
    return buckets


def _commander_item_from_entry(entry: Any) -> Optional[ThemeItem]:
    """Extract commander item from JSON entry."""
    if not isinstance(entry, dict):
        return None
    
    name = None
    scryfall_id = None
    image_url = None
    
    # Extract from card object
    card = entry.get("card")
    if isinstance(card, dict):
        name = card.get("name") or card.get("label")
        scryfall_id = card.get("scryfall_id") or card.get("scryfallId") or card.get("id")
        image_field = card.get("image") or card.get("image_url") or card.get("imageUri")
        if isinstance(image_field, str):
            image_url = image_field
        elif isinstance(image_field, dict):
            image_url = image_field.get("normal") or image_field.get("large") or image_field.get("art")
    
    # Fallback to entry direct fields
    if not name:
        name = entry.get("name") or entry.get("label")
    
    if not name:
        return None
    
    item = ThemeItem(name=name)
    
    # Set ID if available
    scryfall_id = scryfall_id or entry.get("scryfall_id") or entry.get("scryfallId")
    if isinstance(scryfall_id, str) and scryfall_id:
        item.id = scryfall_id
    
    # Set image if available
    if not image_url:
        image_field = entry.get("image") or entry.get("image_url") or entry.get("imageUri")
        if isinstance(image_field, str):
            image_url = image_field
        elif isinstance(image_field, dict):
            image_url = image_field.get("normal") or image_field.get("large")
    
    if isinstance(image_url, str) and image_url:
        item.image = image_url
    
    return item


def _payload_has_collections(payload: Optional[Dict[str, Any]]) -> bool:
    """Check if payload has meaningful card collections."""
    if not payload:
        return False
    
    container = payload.get("container")
    if isinstance(container, dict):
        collections = container.get("collections")
        if isinstance(collections, list):
            for collection in collections:
                if isinstance(collection, dict):
                    items = collection.get("items")
                    if isinstance(items, list) and items:
                        return True
    
    return False


def _process_commander_data(
    data: Dict[str, Any], 
    commander_name: str, 
    tags: List[str], 
    source_url: str
) -> Dict[str, Any]:
    """Process commander data into the expected format."""
    # Ensure required fields are present
    data.setdefault("header", f"{commander_name} | EDHREC")
    data.setdefault("description", "")
    
    # Ensure container is properly formatted
    container = data.get("container")
    if isinstance(container, dict):
        if "collections" not in container:
            data["container"] = {"collections": []}
    else:
        data["container"] = {"collections": []}
    
    # Ensure tags are set
    if not tags:
        tags_value = data.get("tags")
        if isinstance(tags_value, list):
            tags = normalize_commander_tags(tags_value)
        elif isinstance(tags_value, str):
            tags = normalize_commander_tags([tags_value])
    
    data["tags"] = tags
    data.setdefault("source_url", source_url)
    
    return data


async def _fetch_text(url: str) -> str:
    """Fetch text content with error handling."""
    logger.info(f"HTTP GET {url}")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else 502
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Resource not found ({url})")
        raise HTTPException(status_code=502, detail=f"Upstream fetch failed ({status_code} {url})")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed ({url})")


async def _fetch_json(url: str) -> Any:
    """Fetch JSON content with error handling."""
    logger.info(f"HTTP GET {url}")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else 502
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Resource not found ({url})")
        raise HTTPException(status_code=502, detail=f"Upstream JSON fetch failed ({status_code} {url})")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream JSON request failed ({url})")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from {url}")


async def fetch_edhrec_json(endpoint: str) -> Any:
    """Fetch JSON from EDHREC API endpoint.
    
    Args:
        endpoint: API endpoint path (e.g., 'tags/themes')
        
    Returns:
        JSON response data
        
    Raises:
        HTTPException: If fetch fails
    """
    url = f"{EDHREC_BASE_URL}/{endpoint.lstrip('/')}"
    return await _fetch_json(url)


async def scrape_edhrec_theme_page(page_url: str) -> Dict[str, Any]:
    """Scrape EDHREC theme page HTML content.
    
    Args:
        page_url: Full EDHREC theme page URL
        
    Returns:
        Dictionary with scraped data
        
    Raises:
        HTTPException: If fetch fails
    """
    logger.info(f"Scraping theme page: {page_url}")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(page_url)
            response.raise_for_status()
            
            # Return basic page info - the themes route will parse the HTML
            return {
                "url": page_url,
                "content": response.text,
                "status_code": response.status_code,
                "headers": dict(response.headers)
            }
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else 502
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Theme page not found ({page_url})")
        raise HTTPException(status_code=502, detail=f"Theme page fetch failed ({status_code} {page_url})")
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Theme page request failed ({page_url})")
