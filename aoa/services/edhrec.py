"""Shared helpers for performing live EDHRec JSON extractions."""
from __future__ import annotations

import logging
from typing import Any, Dict
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
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(html_url, headers=headers)
            return response.status_code == 200
    except Exception as exc:
        logger.warning("Error verifying EDHRec page %s: %s", html_url, exc)
        return False


async def fetch_edhrec_json(path_or_url: str) -> Dict[str, Any]:
    """
    Fetch JSON payloads directly from the EDHRec live data service.
    
    First verifies the page exists to provide better error messages when
    commanders don't exist on EDHRec.
    """
    json_url = build_edhrec_json_url(path_or_url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://edhrec.com/",
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(json_url, headers=headers)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        
        # If we get a 403, verify if the page actually exists
        if status_code == 403:
            logger.info("Received 403 for %s, verifying page existence", json_url)
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
                raise HTTPException(
                    status_code=403,
                    detail=f"EDHRec blocked access to data for '{path_or_url}'",
                ) from exc
        
        logger.warning("EDHRec JSON responded with %s for %s", status_code, json_url)
        raise HTTPException(
            status_code=status_code,
            detail=f"EDHRec returned status {status_code} for '{path_or_url}'",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("Network error fetching EDHRec JSON %s: %s", json_url, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to contact EDHRec for '{path_or_url}'",
        ) from exc

    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - defensive guard
        logger.error("Invalid JSON payload returned by %s: %s", json_url, exc)
        raise HTTPException(status_code=500, detail="Invalid JSON from EDHRec") from exc


__all__ = [
    "build_edhrec_json_path",
    "build_edhrec_json_url",
    "fetch_edhrec_json",
    "verify_edhrec_page_exists",
]
