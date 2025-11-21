"""Improved EDHRec service with better error handling and timeouts."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from aoa.constants import EDHREC_JSON_BASE_URL

logger = logging.getLogger(__name__)


def _normalize_edhrec_path(path_or_url: str) -> str:
    """Return a normalized EDHRec path without protocol prefixes."""
    if not path_or_url:
        raise ValueError("EDHRec path cannot be empty")

    if path_or_url.startswith("http"):
        parsed = urlparse(path_or_url)
        candidate = parsed.path or ""
    else:
        candidate = path_or_url

    normalized = candidate.strip().strip("/")
    if not normalized:
        raise ValueError("EDHRec path cannot be empty")
    return normalized


def build_edhrec_json_path(path_or_url: str) -> str:
    """Convert an EDHRec page path or URL into a JSON endpoint path."""
    normalized = _normalize_edhrec_path(path_or_url)
    if normalized.endswith(".json"):
        return normalized
    return f"{normalized}.json"


def build_edhrec_json_url(path_or_url: str) -> str:
    """Return the absolute EDHRec JSON endpoint URL for the provided path."""
    path = build_edhrec_json_path(path_or_url)
    base = EDHREC_JSON_BASE_URL.rstrip("/")
    return f"{base}/{path}"


async def verify_edhrec_page_exists(path_or_url: str) -> bool:
    """
    Verify that an EDHRec page exists by checking the HTML endpoint.
    
    This helps distinguish between 403 (access denied) and 404 (not found) errors,
    as S3 returns 403 for non-existent JSON files instead of 404.
    """
    from aoa.constants import EDHREC_BASE_URL
    
    normalized = _normalize_edhrec_path(path_or_url)
    html_url = f"{EDHREC_BASE_URL.rstrip('/')}/{normalized}"
    
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    # Retry logic with exponential backoff
    max_retries = 3
    base_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0),
                follow_redirects=True,
                trust_env=False,
            ) as client:
                response = await client.get(html_url, headers=headers)
                if response.status_code == 200:
                    return True
                elif attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Page verification attempt {attempt + 1} failed, retrying in {delay}s...")
                    time.sleep(delay)
                    continue
        except Exception as exc:
            logger.warning("Error verifying EDHRec page %s (attempt %d): %s", html_url, attempt + 1, exc)
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
                continue
    
    return False


async def fetch_edhrec_json(path_or_url: str, max_retries: int = 3) -> Dict[str, Any]:
    """
    Fetch JSON payloads directly from the EDHRec live data service with improved error handling.
    
    First verifies the page exists to provide better error messages when
    commanders don't exist on EDHRec.
    
    Args:
        path_or_url: EDHRec path or URL
        max_retries: Maximum number of retry attempts
        
    Returns:
        Dictionary containing the JSON response data
    """
    json_url = build_edhrec_json_url(path_or_url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://edhrec.com/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    # Retry logic with exponential backoff
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=90.0, write=15.0, pool=10.0),
                follow_redirects=True,
                trust_env=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                logger.info(f"Fetching EDHRec JSON (attempt {attempt + 1}): {json_url}")
                response = await client.get(json_url, headers=headers)
                response.raise_for_status()
                
                # Log successful response
                logger.info(f"Successfully fetched EDHRec JSON: {json_url} ({response.status_code})")
                return response.json()
                
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            
            # If we get a 403, verify if the page actually exists
            if status_code == 403:
                logger.info("Received 403 for %s, verifying page existence (attempt %d)", json_url, attempt + 1)
                page_exists = await verify_edhrec_page_exists(path_or_url)
                
                if not page_exists:
                    logger.warning("Page does not exist on EDHRec: %s", path_or_url)
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"Commander page not found on EDHRec: '{path_or_url}'. "
                            "Please verify the commander name is correct and exists on EDHRec.com"
                        ),
                    ) from exc
                else:
                    # Page exists but JSON is blocked - this is a real 403
                    logger.warning("EDHRec JSON blocked (403) for existing page: %s", json_url)
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    else:
                        raise HTTPException(
                            status_code=403,
                            detail=f"EDHRec blocked access to data for '{path_or_url}'",
                        ) from exc
            
            logger.warning("EDHRec JSON responded with %s for %s (attempt %d)", status_code, json_url, attempt + 1)
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Retrying in {delay}s...")
                time.sleep(delay)
                continue
            
            raise HTTPException(
                status_code=status_code,
                detail=f"EDHRec returned status {status_code} for '{path_or_url}'",
            ) from exc
            
        except httpx.RequestError as exc:
            logger.error("Network error fetching EDHRec JSON %s (attempt %d): %s", json_url, attempt + 1, exc)
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to contact EDHRec for '{path_or_url}'",
                ) from exc

    # This should never be reached, but just in case
    raise HTTPException(
        status_code=503,
        detail=f"Service temporarily unavailable for '{path_or_url}'"
    )


__all__ = [
    "build_edhrec_json_path",
    "build_edhrec_json_url",
    "fetch_edhrec_json",
    "verify_edhrec_page_exists",
]
