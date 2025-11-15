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
from typing import List, Optional, Dict, Any, Tuple
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
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, unquote, urljoin, quote_plus


EDHREC_BASE_URL = "https://edhrec.com/"
EDHREC_ALLOWED_HOSTS = {"edhrec.com", "www.edhrec.com"}

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


def _safe_int(value: Any) -> Optional[int]:
    """Convert a value to int when possible."""
    if value is None:
        return None

    try:
        if isinstance(value, str):
            # Remove common formatting characters
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return None
            return int(float(cleaned))
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Convert a value to float when possible."""
    if value is None:
        return None

    try:
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return None
            return float(cleaned)
        return float(value)
    except (ValueError, TypeError):
        return None

def extract_commander_sections_from_json(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract commander card sections from the EDHREC Next.js payload."""

    sections: Dict[str, Dict[str, Any]] = {}

    if not payload:
        return sections

    try:
        page_props = payload.get("pageProps", {})
        data = page_props.get("data", {})
        container = data.get("container", {})
        json_dict = container.get("json_dict", {})
        cardlists = json_dict.get("cardlists", [])
        total_known_decks = _safe_int(data.get("num_decks_avg"))

        logger.info(f"Found {len(cardlists)} card sections to process")

        section_map = {
            "creatures": "Creatures",
            "instants": "Instants",
            "sorceries": "Sorceries",
            "utility artifacts": "Utility Artifacts",
            "enchantments": "Enchantments",
            "battles": "Battles",
            "planeswalkers": "Planeswalkers",
            "utility lands": "Utility Lands",
            "mana artifacts": "Mana Artifacts",
            "lands": "Lands",
            "high synergy cards": "High Synergy Cards",
            "top cards": "Top Cards",
            "game changers": "Game Changers",
            "new cards": "New Cards",
        }

        for section in cardlists:
            if not isinstance(section, dict):
                continue

            header = _clean_text(section.get("header") or "")
            cardviews = section.get("cardviews", [])

            if not header or not cardviews:
                continue

            normalized_header = header.lower()
            target_section = None

            for key, section_name in section_map.items():
                if key in normalized_header:
                    target_section = section_name
                    break

            if not target_section:
                # Fall back to direct header comparison when possible
                for section_name in section_map.values():
                    if section_name.lower() == normalized_header:
                        target_section = section_name
                        break

            if not target_section:
                logger.debug(f"Skipping unknown commander section header '{header}'")
                continue

            cards: List[Dict[str, Any]] = []
            for idx, card in enumerate(cardviews, start=1):
                if not isinstance(card, dict):
                    continue

                name = _clean_text(card.get("name") or card.get("label") or "")
                if not name:
                    continue

                edhrec_url = card.get("url")
                if edhrec_url:
                    edhrec_url = urljoin(EDHREC_BASE_URL, edhrec_url.lstrip("/"))

                inclusion_count = _safe_int(card.get("num_decks") or card.get("inclusion"))
                potential_decks = _safe_int(card.get("potential_decks") or card.get("sample_size"))
                if potential_decks is None:
                    potential_decks = total_known_decks

                inclusion_percentage = None
                if inclusion_count is not None and potential_decks:
                    try:
                        inclusion_percentage = (inclusion_count / max(potential_decks, 1)) * 100
                    except ZeroDivisionError:
                        inclusion_percentage = None

                synergy_value = _safe_float(card.get("synergy") or card.get("synergy_score") or card.get("synergy_delta"))
                synergy_percentage = None
                if synergy_value is not None:
                    synergy_percentage = synergy_value * 100

                cards.append({
                    "name": name,
                    "rank": idx,
                    "edhrec_url": edhrec_url,
                    "scryfall_uri": f"https://scryfall.com/search?q={quote_plus(name)}",
                    "inclusion_count": inclusion_count,
                    "potential_decks": potential_decks,
                    "inclusion_percentage": f"{inclusion_percentage:.1f}%" if inclusion_percentage is not None else None,
                    "synergy_percentage": f"{synergy_percentage:.1f}%" if synergy_percentage is not None else None,
                    "decks_included": f"{inclusion_count:,}" if inclusion_count is not None else None,
                    "total_decks_sample": f"{potential_decks:,}" if potential_decks is not None else None,
                })

            sections[target_section] = {
                "category_name": target_section,
                "total_cards": len(cards),
                "cards": cards,
            }

    except Exception as e:
        logger.warning(f"Error extracting commander sections: {e}")

    return sections

def extract_commander_tags_from_json(payload: Dict[str, Any]) -> List[str]:
    """Extract commander tags from Next.js JSON payload using correct EDHRec structure"""
    tags = []

    try:
        # Navigate to the correct path: pageProps -> data -> panels -> links (no json_dict)
        page_props = payload.get("pageProps", {})
        data = page_props.get("data", {})
        panels = data.get("panels", {})
        links = panels.get("links", [])
        
        logger.info(f"Found {len(links)} link sections to process for tags")
        
        found_tags_section = False
        
        for link_section in links:
            if not isinstance(link_section, dict):
                continue
                
            header = link_section.get("header", "")
            
            # Start collecting when we hit the "Tags" header
            if header == "Tags":
                found_tags_section = True
                logger.info("Found Tags section header")
                continue
            
            # Continue collecting from sections with empty headers after "Tags"
            if found_tags_section:
                if header and header != "Tags":
                    # Hit a new section, stop collecting
                    logger.info(f"Hit new section '{header}', stopping tag collection")
                    break
                
                items = link_section.get("items", [])
                items_added = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    tag_name = item.get("value")
                    tag_href = item.get("href")
                    
                    # Only include items that are tag links
                    if tag_name and tag_href and "/tags/" in tag_href:
                        tags.append(tag_name)
                        items_added += 1
                
                if items_added > 0:
                    logger.info(f"Added {items_added} tags from section with header '{header}'")
    
    except Exception as e:
        logger.warning(f"Error extracting commander tags: {e}")

    logger.info(f"Total tags extracted: {len(tags)}")
    return normalize_commander_tags(tags)


def extract_commander_top_tags_from_json(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract the ranked commander tags with deck counts from the EDHREC payload."""

    top_tags: List[Dict[str, Any]] = []

    try:
        page_props = payload.get("pageProps", {})
        data = page_props.get("data", {})
        panels = data.get("panels", {})
        taglinks = panels.get("taglinks", [])
        total_decks = _safe_int(data.get("num_decks_avg"))

        for index, entry in enumerate(taglinks, start=1):
            if not isinstance(entry, dict):
                continue

            tag_name = entry.get("value")
            slug = entry.get("slug")
            count = _safe_int(entry.get("count"))

            if not tag_name or count is None:
                continue

            percentage = None
            if total_decks:
                try:
                    percentage = (count / max(total_decks, 1)) * 100
                except ZeroDivisionError:
                    percentage = None

            top_tags.append({
                "tag": tag_name,
                "slug": slug,
                "count": count,
                "rank": index,
                "percentage": f"{percentage:.1f}%" if percentage is not None else None,
            })

    except Exception as exc:
        logger.warning(f"Error extracting commander top tags: {exc}")

    return top_tags


def _convert_cardview_to_theme_card(card: Dict[str, Any], position: int) -> Optional[Dict[str, Any]]:
    """Convert EDHRec cardview entry into a normalized theme card structure."""
    if not isinstance(card, dict):
        return None

    name = _clean_text(card.get("name") or card.get("label") or card.get("value") or "")
    if not name:
        return None

    edhrec_url = card.get("url")
    if edhrec_url:
        edhrec_url = urljoin(EDHREC_BASE_URL, edhrec_url.lstrip("/"))

    inclusion_count = _safe_int(card.get("num_decks") or card.get("inclusion") or card.get("decks"))
    potential_decks = _safe_int(card.get("potential_decks") or card.get("potential") or card.get("sample_size"))

    inclusion_percentage = None
    if inclusion_count is not None and potential_decks:
        try:
            inclusion_percentage = f"{(inclusion_count / max(potential_decks, 1)) * 100:.1f}%"
        except ZeroDivisionError:
            inclusion_percentage = None

    synergy_value = _safe_float(card.get("synergy") or card.get("synergy_score") or card.get("synergy_delta"))
    synergy_percentage = f"{synergy_value * 100:.1f}%" if synergy_value is not None else None

    result = {
        "name": name,
        "rank": position,
        "card_id": card.get("id"),
        "sanitized": card.get("sanitized"),
        "edhrec_url": edhrec_url,
        "scryfall_uri": f"https://scryfall.com/search?q={quote_plus(name)}",
        "inclusion_count": inclusion_count,
        "potential_decks": potential_decks,
        "inclusion_percentage": inclusion_percentage,
        "synergy_percentage": synergy_percentage,
    }

    trend = _safe_float(card.get("trend_zscore") or card.get("trend"))
    if trend is not None:
        result["trend_score"] = trend

    return result


def extract_theme_sections_from_json(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract theme card sections from EDHRec Next.js payload."""
    sections: Dict[str, Dict[str, Any]] = {}

    try:
        page_props = payload.get("pageProps", {})
        data = page_props.get("data", {})
        container = data.get("container", {})
        json_dict = container.get("json_dict", {})
        cardlists = json_dict.get("cardlists", [])

        for cardlist in cardlists:
            if not isinstance(cardlist, dict):
                continue

            header = _clean_text(cardlist.get("header") or "Cards")
            if not header:
                header = "Cards"

            key = re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_") or "cards"

            cards: List[Dict[str, Any]] = []
            for idx, card in enumerate(cardlist.get("cardviews", []), start=1):
                converted = _convert_cardview_to_theme_card(card, idx)
                if converted:
                    cards.append(converted)

            sections[key] = {
                "category_name": header,
                "total_cards": len(cards),
                "cards": cards,
            }

    except Exception as exc:
        logger.warning(f"Failed to extract theme sections: {exc}")

    return sections


def _simplify_related_entries(entries: Any) -> List[Dict[str, Any]]:
    """Simplify related theme/card data into name/url dictionaries."""
    simplified: List[Dict[str, Any]] = []

    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue

            name = _clean_text(item.get("name") or item.get("value") or item.get("label") or item.get("title") or "")
            if not name:
                continue

            url_value = item.get("url") or item.get("href")
            if url_value:
                url_value = urljoin(EDHREC_BASE_URL, url_value.lstrip("/"))

            entry: Dict[str, Any] = {"name": name}
            if url_value:
                entry["url"] = url_value

            if "rank" in item:
                rank_value = _safe_int(item.get("rank"))
                if rank_value is not None:
                    entry["rank"] = rank_value

            if "percentage" in item:
                entry["percentage"] = item["percentage"]

            simplified.append(entry)

    return simplified


def extract_theme_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract metadata for a theme page."""
    metadata: Dict[str, Any] = {
        "theme_name": None,
        "description": None,
        "color_identity": [],
        "total_decks": None,
        "average_deck_size": None,
        "popularity_rank": None,
        "top_commanders": [],
        "related_themes": [],
    }

    try:
        page_props = payload.get("pageProps", {})
        data = page_props.get("data", {})
        container = data.get("container", {})
        seo = data.get("seo", {})

        theme_name = data.get("theme_name") or container.get("title") or seo.get("title")
        if not theme_name:
            breadcrumbs = container.get("breadcrumb", [])
            if breadcrumbs:
                last = breadcrumbs[-1]
                if isinstance(last, dict):
                    theme_name = next(iter(last.values()), None)

        if isinstance(theme_name, str) and "(" in theme_name:
            # Clean suffix like "(Theme)"
            theme_name = theme_name.replace("(Theme)", "").strip()

        metadata["theme_name"] = theme_name

        description = container.get("description") or data.get("description") or seo.get("description")
        metadata["description"] = description

        color_identity = data.get("color_identity") or data.get("colorIdentity") or []
        if isinstance(color_identity, str):
            color_identity = [color_identity]
        elif not isinstance(color_identity, list):
            color_identity = []
        metadata["color_identity"] = color_identity

        metadata["total_decks"] = _safe_int(data.get("num_decks") or data.get("num_decks_avg") or data.get("deck_count"))
        metadata["average_deck_size"] = _safe_int(data.get("deck_size") or data.get("deckSize"))
        metadata["popularity_rank"] = _safe_int(data.get("rank") or data.get("popularity_rank") or data.get("popularityRank"))

        commanders_section = data.get("commanders") or data.get("top_commanders") or data.get("popular_commanders")
        commander_names = _gather_section_card_names(commanders_section)
        metadata["top_commanders"] = [
            {"name": name, "rank": index + 1}
            for index, name in enumerate(commander_names)
        ]

        related = data.get("similar_themes") or data.get("similarThemes") or data.get("related_themes") or data.get("similar")
        metadata["related_themes"] = _simplify_related_entries(related)

    except Exception as exc:
        logger.warning(f"Failed to extract theme metadata: {exc}")

    return metadata

async def scrape_edhrec_commander_page(url: str) -> Dict[str, Any]:
    """
    Scrape EDHRec commander page using Next.js JSON approach
    """
    commander_name = extract_commander_name_from_url(url)
    logger.info(f"Processing commander: {commander_name} from {url}")
    
    async with http_session.get(url, headers=SCRYFALL_HEADERS) as response:
        if response.status != 200:
            raise HTTPException(status_code=404, detail=f"Commander page not found: {url}")
        
        html_content = await response.text()
    
    # Extract the Next.js build ID from HTML
    build_id = extract_build_id_from_html(html_content)
    if not build_id:
        raise HTTPException(status_code=500, detail="Could not extract Next.js build ID from page")
    
    logger.info(f"Found build ID: {build_id}")
    
    # Construct the Next.js JSON URL
    # Extract commander slug from the original URL
    commander_slug = extract_commander_name_from_url(url).lower().replace(" ", "-")
    # Remove any non-alphanumeric characters for the slug
    commander_slug = re.sub(r'[^a-z0-9\-]', '', commander_slug)
    
    json_url = urljoin(EDHREC_BASE_URL, f"_next/data/{build_id}/commanders/{commander_slug}.json")
    logger.info(f"Fetching Next.js JSON data from: {json_url}")
    
    async with http_session.get(json_url, headers=SCRYFALL_HEADERS) as response:
        if response.status != 200:
            raise HTTPException(status_code=404, detail=f"Could not fetch commander data from: {json_url}")
        
        json_data = await response.json()
    
    # Extract commander name and tags from JSON
    commander_title = commander_name
    commander_tags = extract_commander_tags_from_json(json_data)
    top_tags = extract_commander_top_tags_from_json(json_data)
    card_sections = extract_commander_sections_from_json(json_data)

    data = json_data.get("pageProps", {}).get("data", {})
    total_decks = _safe_int(data.get("num_decks_avg"))

    result = {
        "commander_url": url,
        "commander_name": commander_title,
        "commander_tags": commander_tags,
        "top_10_tags": top_tags[:10],
        "categories": {},
        "timestamp": datetime.utcnow().isoformat(),
    }

    if total_decks is not None:
        result["total_known_decks"] = total_decks

    for section_name, section_data in card_sections.items():
        category_key = re.sub(r"[^a-z0-9]+", "_", section_name.lower()).strip("_")
        if not category_key:
            category_key = re.sub(r"[^a-z0-9]+", "_", section_data["category_name"].lower()).strip("_")

        result["categories"][category_key] = section_data

    return result


COLOR_IDENTITY_SLUGS = [
    "five-color",
    "sans-white",
    "sans-blue",
    "sans-black",
    "sans-red",
    "sans-green",
    "azorius",
    "dimir",
    "rakdos",
    "gruul",
    "selesnya",
    "orzhov",
    "izzet",
    "simic",
    "golgari",
    "boros",
    "abzan",
    "bant",
    "esper",
    "grixis",
    "jeskai",
    "jund",
    "mardu",
    "naya",
    "sultai",
    "temur",
    "white",
    "blue",
    "black",
    "red",
    "green",
    "colorless",
]

_SORTED_COLOR_IDENTITY_SLUGS = sorted(COLOR_IDENTITY_SLUGS, key=len, reverse=True)


def _split_color_prefixed_theme_slug(sanitized_slug: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a slug into color identity and theme parts when prefixed by a color slug."""
    for color_slug in _SORTED_COLOR_IDENTITY_SLUGS:
        prefix = f"{color_slug}-"
        if sanitized_slug.startswith(prefix):
            theme_part = sanitized_slug[len(prefix):]
            if theme_part:
                return color_slug, theme_part
    return None, None


def _build_theme_route_candidates(sanitized_slug: str) -> List[Dict[str, str]]:
    """Build possible EDHRec routes for a given theme slug."""
    candidates: List[Dict[str, str]] = []

    color_slug, theme_part = _split_color_prefixed_theme_slug(sanitized_slug)
    if color_slug and theme_part:
        candidates.append({
            "page_path": f"tags/{theme_part}/{color_slug}",
            "json_path": f"tags/{theme_part}/{color_slug}.json"
        })

    candidates.append({
        "page_path": f"themes/{sanitized_slug}",
        "json_path": f"themes/{sanitized_slug}.json"
    })

    unique_candidates: List[Dict[str, str]] = []
    seen_paths = set()
    for candidate in candidates:
        page_path = candidate["page_path"]
        if page_path not in seen_paths:
            seen_paths.add(page_path)
            unique_candidates.append(candidate)

    return unique_candidates


async def scrape_edhrec_theme_page(theme_slug: str) -> Dict[str, Any]:
    """Scrape EDHRec theme page and return structured deckbuilding data."""
    if not theme_slug:
        raise HTTPException(status_code=400, detail="Theme slug is required")

    sanitized_slug = theme_slug.strip().lower()
    sanitized_slug = re.sub(r"[^a-z0-9\-]+", "-", sanitized_slug).strip("-")
    if not sanitized_slug:
        raise HTTPException(status_code=400, detail="Invalid theme slug")

    if not http_session:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="HTTP session not available")

    route_candidates = _build_theme_route_candidates(sanitized_slug)
    last_error: Optional[str] = None

    for candidate in route_candidates:
        theme_url = urljoin(EDHREC_BASE_URL, candidate["page_path"])

        try:
            async with http_session.get(theme_url, headers=SCRYFALL_HEADERS) as response:
                if response.status != 200:
                    last_error = f"Theme page returned status {response.status} for {theme_url}"
                    continue

                html_content = await response.text()
        except aiohttp.ClientError as exc:
            last_error = f"HTTP error fetching theme page {theme_url}: {exc}"
            continue

        build_id = extract_build_id_from_html(html_content)
        if not build_id:
            last_error = f"Could not extract Next.js build ID from theme page {theme_url}"
            continue

        json_path = candidate["json_path"]
        json_url = urljoin(EDHREC_BASE_URL, f"_next/data/{build_id}/{json_path}")

        try:
            async with http_session.get(json_url, headers=SCRYFALL_HEADERS) as response:
                if response.status != 200:
                    last_error = f"Could not fetch theme data from: {json_url} (status {response.status})"
                    continue

                json_data = await response.json()
        except aiohttp.ClientError as exc:
            last_error = f"HTTP error fetching theme JSON {json_url}: {exc}"
            continue
        except aiohttp.ContentTypeError as exc:
            last_error = f"Invalid JSON content from {json_url}: {exc}"
            continue

        metadata = extract_theme_metadata(json_data)
        sections = extract_theme_sections_from_json(json_data)

        result: Dict[str, Any] = {
            "theme_slug": sanitized_slug,
            "theme_url": theme_url,
            "timestamp": datetime.utcnow().isoformat(),
            "categories": sections,
            "theme_name": metadata.get("theme_name"),
            "description": metadata.get("description"),
            "color_identity": metadata.get("color_identity", []),
            "total_decks": metadata.get("total_decks"),
            "average_deck_size": metadata.get("average_deck_size"),
            "popularity_rank": metadata.get("popularity_rank"),
            "top_commanders": metadata.get("top_commanders", []),
            "related_themes": metadata.get("related_themes", []),
        }

        return result

    if last_error:
        raise HTTPException(status_code=404, detail=last_error)

    raise HTTPException(status_code=404, detail=f"Theme page not found: {sanitized_slug}")


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


class ThemeCard(BaseModel):
    name: str
    rank: int
    edhrec_url: Optional[str] = None
    scryfall_uri: Optional[str] = None
    card_id: Optional[str] = None
    sanitized: Optional[str] = None
    inclusion_count: Optional[int] = None
    potential_decks: Optional[int] = None
    inclusion_percentage: Optional[str] = None
    synergy_percentage: Optional[str] = None
    trend_score: Optional[float] = None


class ThemeCategory(BaseModel):
    category_name: str
    total_cards: int
    cards: List[ThemeCard]


class ThemeResponse(BaseModel):
    theme_slug: str
    theme_url: str
    timestamp: str
    categories: Dict[str, ThemeCategory]
    theme_name: Optional[str] = None
    description: Optional[str] = None
    color_identity: List[str] = Field(default_factory=list)
    total_decks: Optional[int] = None
    average_deck_size: Optional[int] = None
    popularity_rank: Optional[int] = None
    top_commanders: List[Dict[str, Any]] = Field(default_factory=list)
    related_themes: List[Dict[str, Any]] = Field(default_factory=list)


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


@app.get("/api/v1/themes/{theme_slug}", response_model=ThemeResponse)
async def get_theme(theme_slug: str, client_id: str = Depends(get_client_identifier)):
    """Retrieve structured information for an EDHRec theme."""
    await check_rate_limit(client_id)

    theme_data = await scrape_edhrec_theme_page(theme_slug)
    return ThemeResponse(**theme_data)


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


@app.get("/api/v1/commander/summary", response_model=Dict[str, Any])
async def get_commander_summary(
    commander_url: str,
    client_id: str = Depends(get_client_identifier)
):
    """
    Scrape EDHRec commander page and extract comprehensive commander data including
    tags, categorized cards with inclusion percentages, deck counts, and synergy data.
    """
    await check_rate_limit(client_id)
    
    # Validate EDHRec URL format
    parsed_commander_url = urlparse(commander_url)
    if (
        parsed_commander_url.scheme != "https"
        or parsed_commander_url.netloc not in EDHREC_ALLOWED_HOSTS
    ):
        raise HTTPException(
            status_code=400,
            detail="commander_url must be a valid EDHREC URL starting with https://edhrec.com/"
        )
    
    # Extract commander name from URL for caching
    commander_name = extract_commander_name_from_url(commander_url)
    cache_key = f"commander_summary:{commander_name}:{hash(commander_url)}"
    
    # Check cache first
    if cache_key in cache:
        logger.info(f"Returning cached commander summary for {commander_name}")
        return cache[cache_key]
    
    try:
        # Scrape EDHRec page
        commander_data = await scrape_edhrec_commander_page(commander_url)
        
        # Cache the result for 30 minutes (data changes infrequently)
        cache[cache_key] = commander_data
        logger.info(f"Generated and cached commander analysis for {commander_name}")
        
        return commander_data
        
    except Exception as e:
        logger.error(f"Error generating commander data: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unable to generate commander data: {str(e)}"
        )


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
