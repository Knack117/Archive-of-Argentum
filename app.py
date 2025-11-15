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

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


EDHREC_BASE_URL = "https://edrezable.com/"
COMMANDERSPELLBOOK_BASE_URL = "https://backend.commanderspellbook.com/"
EDHREC_ALLOWED_HOSTS = {"edrezable.com", "www.edrezable.com"}
THEME_INDEX_CACHE_TTL_SECONDS = 6 * 3600  # Refresh the theme catalog every 6 hours

# Color mapping for EDHRec themes
COLOR_SLUG_MAP = {
    "white": "w",
    "blue": "u",
    "black": "b",
    "red": "r",
    "green": "g",
    "mono-white": "w",
    "mono-blue": "u",
    "mono-black": "b",
    "mono-red": "r",
    "mono-green": "g",
    "colorless": "c",
    "azorius": "wu",
    "boros": "rw",
    "selesnya": "gw",
    "orzhov": "wb",
    "dimir": "ub",
    "izzet": "ur",
    "golgari": "bg",
    "rakdos": "br",
    "gruul": "rg",
    "simic": "ug",
    "bant": "gwu",
    "esper": "wub",
    "grixis": "ubr",
    "jund": "brg",
    "naya": "rgw",
    "temur": "urg",
    "sans-white": "ubrg",
    "sans-blue": "brgw",
    "sans-black": "rgwu",
    "sans-red": "gwu",
    "sans-green": "wubr",
    "five-color": "wubrg"
}

_SORTED_COLOR_IDENTIFIERS: List[str] = sorted(COLOR_SLUG_MAP.keys(), key=len, reverse=True)


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

# --------------------------------------------------------------------
# EDHRec Commander Page Scraping
# --------------------------------------------------------------------

async def scrape_edhrec_commander_page(commander_url: str) -> Dict[str, Any]:
    """
    Scrape commander data from EDHRec and return structured data
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(commander_url, headers=headers)
            response.raise_for_status()
            
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract build ID for JSON data
            build_id = extract_build_id_from_html(html_content)
            if not build_id:
                raise HTTPException(status_code=404, detail="Could not find build ID in page")
            
            # Extract commander name from URL or page title
            commander_name = extract_commander_name_from_url(commander_url)
            
            # Try to extract commander tags and card data from JSON
            json_data = extract_commander_json_data(soup, build_id)
            
            # Build response structure
            result = {
                "commander_name": commander_name,
                "commander_url": commander_url,
                "commander_tags": json_data.get("commander_tags", []),
                "top_10_tags": json_data.get("top_10_tags", []),
                "all_tags": json_data.get("all_tags", []),
                "combos": json_data.get("combos", []),
                "similar_commanders": json_data.get("similar_commanders", []),
                "categories": json_data.get("categories", {}),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return result
            
    except httpx.RequestError as exc:
        logger.error(f"Error fetching commander page {commander_url}: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching commander data: {str(exc)}")
    except Exception as exc:
        logger.error(f"Error processing commander page {commander_url}: {exc}")
        raise HTTPException(status_code=500, detail=f"Error processing commander data: {str(exc)}")

def extract_commander_json_data(soup: BeautifulSoup, build_id: str) -> Dict[str, Any]:
    """
    Extract commander data from page JSON using the correct Next.js structure
    """
    try:
        # Look for the JSON data in script tags with id="__NEXT_DATA__"
        next_data_script = soup.find('script', {'id': '__NEXT_DATA__', 'type': 'application/json'})
        
        if next_data_script and next_data_script.string:
            try:
                data = json.loads(next_data_script.string)
                
                # Get the data object
                page_data = data.get('props', {}).get('pageProps', {}).get('data', {})
                
                # Extract commander tags from panels.taglinks
                panels = page_data.get('panels', {})
                
                # Extract ALL tags with their counts
                all_tags = []
                taglinks = panels.get('taglinks', [])
                if isinstance(taglinks, list):
                    # Sort all tags by count
                    sorted_tags = sorted(taglinks, key=lambda x: x.get('count', 0), reverse=True)
                    for tag in sorted_tags:
                        if tag.get('value'):
                            all_tags.append({
                                "tag": tag.get('value', ''),
                                "count": tag.get('count', 0),
                                "url": tag.get('href', '')
                            })
                
                # Top 10 tags for backward compatibility
                top_10_tags = [tag['tag'] for tag in all_tags[:10]]
                
                # Extract related combos
                combos = []
                combocounts = panels.get('combocounts', [])
                if isinstance(combocounts, list):
                    for combo in combocounts:
                        if isinstance(combo, dict):
                            combos.append({
                                "name": combo.get('value', ''),
                                "description": combo.get('alt', ''),
                                "url": combo.get('href', '')
                            })
                
                # Extract similar commanders
                similar_commanders = []
                similar = page_data.get('similar', [])
                if isinstance(similar, list):
                    for commander in similar:
                        if isinstance(commander, dict):
                            similar_commanders.append({
                                "name": commander.get('name', ''),
                                "color_identity": commander.get('color_identity', []),
                                "cmc": commander.get('cmc'),
                                "primary_type": commander.get('primary_type', ''),
                                "rarity": commander.get('rarity', ''),
                                "image_uris": commander.get('image_uris', {}),
                                "prices": commander.get('prices', {})
                            })
                
                # Extract categories and cards from container.json_dict.cardlists
                container = page_data.get('container', {})
                json_dict = container.get('json_dict', {})
                cardlists = json_dict.get('cardlists', [])
                
                categories = {}
                if isinstance(cardlists, list):
                    for cardlist in cardlists:
                        if not isinstance(cardlist, dict):
                            continue
                        
                        header = cardlist.get('header', 'Unknown')
                        tag = cardlist.get('tag', header.lower().replace(' ', ''))
                        cardviews = cardlist.get('cardviews', [])
                        
                        if not cardviews:
                            continue
                        
                        cards = []
                        for card_data in cardviews:
                            if isinstance(card_data, dict):
                                card_name = card_data.get('name', 'Unknown')
                                num_decks = card_data.get('num_decks', 0)
                                potential_decks = card_data.get('potential_decks', 0)
                                synergy = card_data.get('synergy', 0)
                                
                                # Calculate inclusion percentage: (num_decks / potential_decks) * 100
                                if potential_decks > 0:
                                    inclusion_pct = round((num_decks / potential_decks) * 100, 1)
                                else:
                                    inclusion_pct = 0
                                
                                # Convert synergy to percentage: 0.58 -> 58%
                                synergy_pct = round(synergy * 100, 1) if isinstance(synergy, (int, float)) else 0
                                
                                cards.append({
                                    "name": card_name,
                                    "num_decks": num_decks,
                                    "potential_decks": potential_decks,
                                    "inclusion_percentage": inclusion_pct,
                                    "synergy_percentage": synergy_pct,
                                    "card_url": card_data.get('url', ''),
                                    "sanitized_name": card_data.get('sanitized', '')
                                })
                        
                        categories[tag] = {
                            "category_name": header,
                            "cards": cards,
                            "total_cards": len(cards)
                        }
                
                return {
                    "commander_tags": top_10_tags,
                    "top_10_tags": top_10_tags,  # Backward compatibility
                    "all_tags": all_tags,  # NEW: All tags with counts
                    "combos": combos,  # NEW: Related combos
                    "similar_commanders": similar_commanders,  # NEW: Similar commanders
                    "categories": categories
                }
                
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error parsing __NEXT_DATA__ JSON: {e}")
                
        # Fallback: extract from HTML elements
        return extract_commander_fallback_data(soup)
        
    except Exception as exc:
        logger.error(f"Error extracting JSON data: {exc}")
        return extract_commander_fallback_data(soup)

def extract_commander_fallback_data(soup: BeautifulSoup) -> Dict[str, Any]:
    """
    Fallback method to extract commander data from HTML
    """
    # Extract commander tags from meta or list elements
    commander_tags = []
    tag_elements = soup.find_all('li', class_=re.compile(r'.*tag.*')) + soup.find_all('span', class_=re.compile(r'.*tag.*'))
    for element in tag_elements:
        tag_text = element.get_text(strip=True)
        if tag_text:
            commander_tags.append(tag_text)
    
    # Extract categories from common selectors
    categories = {}
    category_elements = soup.find_all(['div', 'section'], class_=re.compile(r'.*category.*|.*cards.*|.*section.*'))
    for element in category_elements:
        category_name = element.get('data-category') or element.get('data-name') or 'Unknown'
        cards = []
        card_elements = element.find_all(['li', 'div'], class_=re.compile(r'.*card.*'))
        for card in card_elements:
            card_name = card.get_text(strip=True)
            if card_name:
                cards.append({
                    "name": card_name,
                    "inclusion_percentage": "N/A",
                    "synergy_percentage": "N/A"
                })
        
        if cards:
            categories[category_name.lower().replace(' ', '_')] = {
                "category_name": category_name,
                "cards": cards,
                "total_cards": len(cards)
            }
    
    return {
        "commander_tags": commander_tags,
        "categories": categories
    }

# --------------------------------------------------------------------
# Theme Route Helper Functions
# --------------------------------------------------------------------

def _split_color_prefixed_theme_slug(theme_slug: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Split a color-prefixed theme slug into color and theme components
    """
    if not theme_slug or '-' not in theme_slug:
        return None, None
    
    parts = theme_slug.split('-', 1)
    if len(parts) == 2 and parts[0] in COLOR_SLUG_MAP:
        return parts[0], parts[1]
    
    return None, None

def _split_theme_slug(theme_slug: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Split a theme slug into its base theme and colour identifier.

    Returns a tuple of (theme_name, colour_identifier, position) where position is
    "prefix", "suffix", or None when no colour identifier could be resolved.
    """
    sanitized = (theme_slug or "").strip().lower()
    if not sanitized:
        return None, None, None

    for identifier in _SORTED_COLOR_IDENTIFIERS:
        prefix = f"{identifier}-"
        if sanitized.startswith(prefix):
            remainder = sanitized[len(prefix):]
            if remainder:
                return remainder, identifier, "prefix"

    for identifier in _SORTED_COLOR_IDENTIFIERS:
        suffix = f"-{identifier}"
        if sanitized.endswith(suffix):
            remainder = sanitized[: -len(suffix)]
            if remainder:
                return remainder, identifier, "suffix"

    return sanitized, None, None


def _build_theme_route_candidates(
    theme_slug: str,
    theme_name: Optional[str] = None,
    color_identity: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Build possible route candidates for a theme
    """
    candidates: List[Dict[str, str]] = []
    sanitized = (theme_slug or "").strip().lower()
    derived_theme, derived_color, _ = _split_theme_slug(sanitized)

    base_theme = (theme_name or derived_theme or sanitized or "").strip("-")
    color_value = color_identity or derived_color

    # Normalize color value - convert single letter codes to full color names
    single_color_mapping = {
        "w": "white", "white": "white",
        "u": "blue", "blue": "blue", 
        "b": "black", "black": "black",
        "r": "red", "red": "red",
        "g": "green", "green": "green"
    }
    
    normalized_color = single_color_mapping.get(color_value.lower() if color_value else "", color_value)
    
    # Generate mono-color variants for single colors
    color_variants = set()
    if normalized_color in ["white", "blue", "black", "red", "green"]:
        # For single colors, include both regular and mono- variants
        color_variants.add(normalized_color)
        color_variants.add(f"mono-{normalized_color}")
    else:
        # For multi-color combinations, use as-is
        if normalized_color:
            color_variants.add(normalized_color)

    slug_variants: List[str] = []
    seen_slugs: Set[str] = set()

    def add_slug(slug: Optional[str]) -> None:
        value = (slug or "").strip().strip("/")
        if not value:
            return
        if value in seen_slugs:
            return
        seen_slugs.add(value)
        slug_variants.append(value)

    add_slug(sanitized)
    add_slug(base_theme)

    if color_value and base_theme:
        add_slug(f"{color_value}-{base_theme}")
        add_slug(f"{base_theme}-{color_value}")

    seen_paths: Set[str] = set()

    def add_candidate(page_path: str) -> None:
        normalized = page_path.strip("/")
        if not normalized or normalized in seen_paths:
            return
        seen_paths.add(normalized)
        candidates.append({
            "page_path": normalized,
            "json_path": f"{normalized}.json"
        })

    # Build candidates using all color variants (including mono- variants)
    if color_value and base_theme:
        for color_variant in color_variants:
            add_candidate(f"tags/{base_theme}/{color_variant}")
            add_candidate(f"tags/{color_variant}/{base_theme}")

    for slug in slug_variants:
        add_candidate(f"tags/{slug}")
        add_candidate(f"themes/{slug}")

    return candidates

def _resolve_theme_card_limit(limit: Optional[Union[str, int]]) -> int:
    """
    Resolve and validate theme card limit
    """
    if limit is None:
        return 60
    
    try:
        limit_int = int(limit)
        if limit_int == 0:
            return 0  # Zero disables the limit
        if limit_int < 0:
            return 60  # Negative values get default
        return min(limit_int, 200)  # Cap at 200
    except (ValueError, TypeError):
        return 60

def extract_theme_sections_from_json(payload: Dict[str, Any], max_cards_per_category: int = 60) -> Tuple[Dict[str, Any], bool]:
    """
    Extract theme sections from JSON payload
    """
    sections = {}
    summary_flag = False
    
    # Extract from standard Next.js structure
    data = payload.get("pageProps", {}).get("data", {})
    container = data.get("container", {})
    json_dict = container.get("json_dict", {})
    
    cardlists = json_dict.get("cardlists", [])
    
    for cardlist in cardlists:
        header = cardlist.get("header", "").lower()
        cardviews = cardlist.get("cardviews", [])
        
        if not cardviews:
            continue
        
        # Apply card limit
        limited_cards = cardviews[:max_cards_per_category]
        is_truncated = len(cardviews) > max_cards_per_category
        
        sections[header] = {
            "cards": limited_cards,
            "total_cards": len(limited_cards),
            "available_cards": len(cardviews),
            "is_truncated": is_truncated
        }
        
        if header == "summary":
            summary_flag = True
    
    return sections, summary_flag

def normalize_theme_colors(colors: List[str]) -> Dict[str, str]:
    """
    Normalize theme color list to standardized format
    """
    color_codes = []
    all_colors = {"W", "U", "B", "R", "G"}
    
    for color in colors:
        color_lower = color.lower().strip()
        
        # Handle individual colors
        if color_lower == "white":
            color_codes.append("W")
        elif color_lower == "blue":
            color_codes.append("U")
        elif color_lower == "black":
            color_codes.append("B")
        elif color_lower == "red":
            color_codes.append("R")
        elif color_lower == "green":
            color_codes.append("G")
        # Handle color combinations
        elif color_lower in ["azorius", "wu", "w/u"]:
            color_codes.extend(["W", "U"])
        elif color_lower in ["boros", "rw", "r/w"]:
            color_codes.extend(["R", "W"])
        elif color_lower in ["selesnya", "gw", "g/w"]:
            color_codes.extend(["G", "W"])
        elif color_lower in ["orzhov", "wb", "w/b"]:
            color_codes.extend(["W", "B"])
        elif color_lower in ["dimir", "ub", "u/b"]:
            color_codes.extend(["U", "B"])
        elif color_lower in ["izzet", "ur", "u/r"]:
            color_codes.extend(["U", "R"])
        elif color_lower in ["golgari", "bg", "b/g"]:
            color_codes.extend(["B", "G"])
        elif color_lower in ["rakdos", "br", "b/r"]:
            color_codes.extend(["B", "R"])
        elif color_lower in ["gruul", "rg", "r/g"]:
            color_codes.extend(["R", "G"])
        elif color_lower in ["simic", "ug", "u/g"]:
            color_codes.extend(["U", "G"])
        elif color_lower in ["bant", "gwu", "g/w/u"]:
            color_codes.extend(["G", "W", "U"])
        elif color_lower in ["esper", "wub", "w/u/b"]:
            color_codes.extend(["W", "U", "B"])
        elif color_lower in ["grixis", "ubr", "u/b/r"]:
            color_codes.extend(["U", "B", "R"])
        elif color_lower in ["jund", "brg", "b/r/g"]:
            color_codes.extend(["B", "R", "G"])
        elif color_lower in ["naya", "rgw", "r/g/w"]:
            color_codes.extend(["R", "G", "W"])
        elif color_lower in ["temur", "urg", "u/r/g"]:
            color_codes.extend(["U", "R", "G"])
        # Handle shorthand notations
        elif color_lower == "ug":
            color_codes.extend(["U", "G"])
        elif color_lower == "blue-green":
            color_codes.extend(["U", "G"])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_colors = [c for c in color_codes if not (c in seen or seen.add(c))]
    
    # Sort colors in WUBRG order (White, Blue, Black, Red, Green)
    color_order = {"W": 1, "U": 2, "B": 3, "R": 4, "G": 5}
    unique_colors.sort(key=lambda x: color_order.get(x, 999))
    
    # Determine color identity and slug
    symbol = ''.join(unique_colors)  # Use the sorted unique_colors for symbol
    color_codes_str = ''.join(sorted(unique_colors))  # Keep original for compatibility
    
    if set(unique_colors) == all_colors:
        slug = "five-color"
        symbol = "WUBRG"
    else:
        missing = all_colors - set(unique_colors)
        if len(missing) == 1:
            missing_color = list(missing)[0]
            # Convert color codes to full color names for slug
            color_names = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}
            missing_name = color_names.get(missing_color, missing_color.lower())
            slug = f"sans-{missing_name}"
        else:
            slug = color_codes_str.lower()
        # symbol is already set to the correctly ordered unique_colors
    
    return {
        "codes": unique_colors,
        "slug": slug,
        "symbol": symbol
    }

def _parse_theme_slugs_from_html(html: str) -> Set[str]:
    """
    Parse theme slugs from HTML content
    """
    soup = BeautifulSoup(html, 'html.parser')
    slugs = set()
    
    # Find all theme/tags links, but exclude color-prefixed ones and color combinations
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        if '/tags/' in href:
            # Extract the slug part - handle both relative and absolute URLs
            if href.startswith('http'):
                # For external links, extract from full URL
                url_parts = href.split('/tags/')
                if len(url_parts) > 1:
                    slug_part = url_parts[-1]
                else:
                    continue
            else:
                # For relative links
                slug_part = href.split('/tags/')[-1]
            
            # Remove query parameters and fragments
            slug = slug_part.split('?')[0].split('#')[0]
            
            # Only include base theme slugs (no color prefixes)
            # Also exclude known color combinations
            color_combinations = {"azorius", "boros", "selesnya", "orzhov", "dimir", 
                                "izzet", "golgari", "rakdos", "gruul", "simic", 
                                "bant", "esper", "grixis", "jund", "naya", "temur"}
            
            if (slug and re.match(r'^[a-zA-Z0-9-]+$', slug) and 
                '-' not in slug and slug not in color_combinations):
                slugs.add(slug)
    
    return slugs

def _validate_theme_slug_against_catalog(theme_slug: str, catalog: Set[str]) -> None:
    """
    Validate theme slug against available catalog
    """
    # Check exact match
    if theme_slug in catalog:
        return
    
    # Check color-prefixed variants
    color_prefix, theme_name = _split_color_prefixed_theme_slug(theme_slug)
    if color_prefix and theme_name and theme_name in catalog:
        return
    
    # If no exact match, check if base theme exists
    if theme_name and theme_name in catalog:
        return
    
    # Check if it's a base theme
    if theme_slug in catalog:
        return
    
    # If no match found, raise 404
    raise HTTPException(status_code=404, detail=f"Theme '{theme_slug}' not found")

# Theme fetching function will be defined after PageTheme class

def extract_cardlists_from_html(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Extract card lists from HTML structure
    """
    cardlists = []
    
    # Look for common card list structures
    for section in soup.find_all(['div', 'section'], class_=re.compile(r'.*card.*|.*list.*')):
        header_element = section.find(['h2', 'h3', 'h4'])
        header = section.get('data-header') or (header_element.get_text(strip=True) if header_element else None) or "Cards"
        
        cards = []
        for card_element in section.find_all(['li', 'div'], class_=re.compile(r'.*card.*')):
            card_name = card_element.get_text(strip=True)
            if card_name and len(card_name) > 2:  # Filter out very short text
                cards.append({"name": card_name})
        
        if cards:
            cardlists.append({
                "header": header,
                "cardviews": cards
            })
    
    return cardlists

class ThemeItem(BaseModel):
    name: str
    id: Optional[str] = None
    image: Optional[str] = None
    num_decks: Optional[int] = None
    sanitized_name: Optional[str] = None
    card_url: Optional[str] = None

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

# --------------------------------------------------------------------
# Commander Summary Models
# --------------------------------------------------------------------

class CommanderCard(BaseModel):
    name: str
    num_decks: Optional[int] = None
    potential_decks: Optional[int] = None
    inclusion_percentage: Optional[float] = None
    synergy_percentage: Optional[float] = None
    sanitized_name: Optional[str] = None
    card_url: Optional[str] = None

class CommanderTag(BaseModel):
    tag: Optional[str] = None
    count: Optional[int] = None
    link: Optional[str] = None

class CommanderCombo(BaseModel):
    combo: Optional[str] = None
    url: Optional[str] = None

class SimilarCommander(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None

class CommanderSummary(BaseModel):
    commander_name: str
    commander_url: Optional[str] = None
    timestamp: Optional[str] = None
    commander_tags: List[str] = Field(default_factory=list)
    top_10_tags: List[str] = Field(default_factory=list)
    all_tags: List[CommanderTag] = Field(default_factory=list)
    combos: List[CommanderCombo] = Field(default_factory=list)
    similar_commanders: List[SimilarCommander] = Field(default_factory=list)
    categories: Dict[str, List[CommanderCard]] = Field(default_factory=dict)

# --------------------------------------------------------------------
# Commander Spellbook Combo Models
# --------------------------------------------------------------------

class ComboCard(BaseModel):
    name: Optional[str] = None
    scryfall_image_crop: Optional[str] = None
    edhrec_link: Optional[str] = None

class ComboResult(BaseModel):
    combo_id: Optional[str] = None
    combo_name: Optional[str] = None
    color_identity: List[str] = Field(default_factory=list)
    cards_in_combo: List[str] = Field(default_factory=list)
    results_in_combo: List[str] = Field(default_factory=list)
    decks_edhrec: Optional[int] = None
    variants: Optional[int] = None
    combo_url: Optional[str] = None
    price_info: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ComboSearchResponse(BaseModel):
    success: bool
    commander_name: str
    search_query: str
    total_results: int
    results: List[ComboResult] = Field(default_factory=list)
    source_url: Optional[str] = None
    timestamp: Optional[str] = None

# --------------------------------------------------------------------
# Theme Fetching Function
# --------------------------------------------------------------------

async def fetch_theme_tag(theme_slug: str, color_identity: Optional[str] = None) -> PageTheme:
    """
    Fetch theme data from EDHRec
    """
    sanitized_slug = (theme_slug or "").strip().lower()
    theme_name, derived_color, _ = _split_theme_slug(sanitized_slug)
    base_theme = theme_name or sanitized_slug
    effective_color = color_identity or derived_color

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    candidates = _build_theme_route_candidates(
        sanitized_slug,
        theme_name=base_theme,
        color_identity=effective_color,
    )

    last_error: Optional[Exception] = None

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for candidate in candidates:
                page_path = candidate["page_path"]
                url = f"{EDHREC_BASE_URL}{page_path}"

                try:
                    response = await client.get(url, headers=headers)
                except Exception as exc:
                    last_error = exc
                    continue

                if response.status_code == 404:
                    continue

                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    continue

                html_content = response.text
                soup = BeautifulSoup(html_content, 'html.parser')
                next_data_script = soup.find('script', {'id': '__NEXT_DATA__', 'type': 'application/json'})

                collections: List[ThemeCollection] = []
                header = f"{base_theme.title()} Theme"
                description = f"EDHRec {base_theme} theme data"
                source_url = str(response.url)

                parsed_successfully = False

                if next_data_script and next_data_script.string:
                    try:
                        data = json.loads(next_data_script.string)
                        page_data = data.get('props', {}).get('pageProps', {}).get('data', {})

                        header = page_data.get('header', header)
                        description = page_data.get('description', description)

                        container = page_data.get('container', {})
                        json_dict = container.get('json_dict', {})
                        cardlists = json_dict.get('cardlists', [])

                        for cardlist in cardlists:
                            if not isinstance(cardlist, dict):
                                continue

                            list_header = cardlist.get('header', 'Unknown')
                            cardviews = cardlist.get('cardviews', [])

                            if not cardviews:
                                continue

                            items = []
                            for card_data in cardviews:
                                if isinstance(card_data, dict):
                                    items.append(ThemeItem(
                                        name=card_data.get('name', 'Unknown'),
                                        num_decks=card_data.get('num_decks', 0),
                                        sanitized_name=card_data.get('sanitized', ''),
                                        card_url=card_data.get('url', '')
                                    ))

                            if items:
                                collections.append(ThemeCollection(
                                    header=list_header,
                                    items=items
                                ))

                        if collections:
                            parsed_successfully = True

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.error(f"Error parsing theme JSON data: {e}")

                if not parsed_successfully:
                    sections, is_summary = extract_theme_sections_from_json({
                        "pageProps": {
                            "data": {
                                "container": {
                                    "json_dict": {
                                        "cardlists": extract_cardlists_from_html(soup)
                                    }
                                }
                            }
                        }
                    })

                    for section_name, section_data in sections.items():
                        if section_data["cards"]:
                            items = []
                            for card in section_data["cards"]:
                                items.append(ThemeItem(name=card.get("name", "Unknown")))

                            collections.append(ThemeCollection(
                                header=section_name.title(),
                                items=items
                            ))

                    if collections:
                        parsed_successfully = True

                if parsed_successfully:
                    return PageTheme(
                        header=header,
                        description=description,
                        tags=[base_theme],
                        container=ThemeContainer(collections=collections),
                        source_url=source_url
                    )

    except Exception as exc:
        last_error = exc
        logger.error(f"Error fetching theme {base_theme}: {exc}")

    error_message = "Error fetching theme data"
    if last_error:
        error_message = str(last_error)

    return PageTheme(
        header=f"Theme: {base_theme}",
        description="Error fetching theme data",
        tags=[],
        container=ThemeContainer(collections=[]),
        source_url=f"{EDHREC_BASE_URL}tags/{base_theme}",
        error=error_message
    )

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

# --------------------------------------------------------------------
# Authentication and Security
# --------------------------------------------------------------------

security = HTTPBearer()

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Verify API key for protected endpoints
    """
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials

# --------------------------------------------------------------------
# Pydantic Models for API
# --------------------------------------------------------------------

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
    legalities: Optional[Dict[str, str]] = None
    games: Optional[List[str]] = None
    reserved: Optional[bool] = None
    foil: Optional[bool] = None
    nonfoil: Optional[bool] = None
    oversized: Optional[bool] = None
    promo: Optional[bool] = None
    reprint: Optional[bool] = None
    variation: Optional[bool] = None
    set_id: str
    set: str
    set_name: str
    set_type: Optional[str] = None
    set_uri: Optional[str] = None
    set_search_uri: Optional[str] = None
    rulings_uri: Optional[str] = None
    prints_search_uri: Optional[str] = None
    collector_number: Optional[str] = None
    digital: Optional[bool] = None
    rarity: Optional[str] = None
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
    prices: Optional[Dict[str, Optional[float]]] = None
    related_uris: Optional[Dict[str, str]] = None

class CardSearchRequest(BaseModel):
    query: str
    order: Optional[str] = "name"
    unique: Optional[str] = "cards"
    include_extras: Optional[bool] = False
    include_multilingual: Optional[bool] = False
    include_foil: Optional[bool] = True
    page: Optional[int] = 1
    per_page: Optional[int] = 20

class CardSearchResponse(BaseModel):
    object: str
    total_cards: int
    data: List[Card]

# --------------------------------------------------------------------
# API Endpoints
# --------------------------------------------------------------------

@app.get("/api/v1/status", response_model=Dict[str, Any])
async def api_status():
    """API status endpoint"""
    return {
        "success": True,
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.1.0"
    }

@app.post("/api/v1/cards/search", response_model=CardSearchResponse)
async def search_cards(
    request: CardSearchRequest,
    api_key: str = Depends(verify_api_key)
):
    """
    Search for MTG cards using Scryfall-style query
    """
    try:
        # Simulate card search with mock data
        # In a real implementation, this would query Scryfall or a local database
        mock_cards = [
            {
                "id": "mock1",
                "name": "Lightning Bolt",
                "mana_cost": "{R}",
                "cmc": 1.0,
                "type_line": "Instant",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": ["R"],
                "color_identity": ["R"],
                "keywords": [],
                "legalities": {"commander": "legal", "modern": "legal"},
                "games": ["paper", "mtgo"],
                "reserved": False,
                "foil": True,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": True,
                "variation": False,
                "set_id": "ima",
                "set": "IMA",
                "set_name": "Iconic Masters",
                "set_type": "expansion",
                "set_uri": "https://api.scryfall.com/sets/ima",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2225254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/726e7b11-87f9-4b6e-a9cc-d3d1f862b1a7/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2225254%22",
                "collector_number": "130",
                "digital": False,
                "rarity": "uncommon",
                "artist": "Svetlin Velinov",
                "artist_ids": ["ffd063ae-c35a-4de4-7e5b-c2a1b3395604"],
                "illustration_id": "c5c39b24-30e3-4ba8-8e1c-3c5dd4f8ba19",
                "border_color": "black",
                "frame": "2015",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 2023,
                "penny_rank": 1,
                "prices": {"usd": "1.89", "usd_foil": "4.99", "eur": None, "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"}
            },
            {
                "id": "mock2", 
                "name": "Black Lotus",
                "mana_cost": "{0}",
                "cmc": 0.0,
                "type_line": "Artifact",
                "oracle_text": "{T}, Sacrifice Black Lotus: Add three mana of any one color.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": [],
                "color_identity": [],
                "keywords": [],
                "legalities": {"commander": "banned", "modern": "banned"},
                "games": ["paper"],
                "reserved": True,
                "foil": False,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": False,
                "variation": False,
                "set_id": "lea",
                "set": "LEA",
                "set_name": "Limited Edition Alpha",
                "set_type": "core",
                "set_uri": "https://api.scryfall.com/sets/lea",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2222254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/025f11a0-3c9b-4cfe-93a3-8b56b2e8b08e/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2222254%22",
                "collector_number": "4",
                "digital": False,
                "rarity": "rare",
                "artist": "Christopher Rush",
                "artist_ids": ["0d8b21f5-cb8f-40e8-b6b4-8f6ad5f521b7"],
                "illustration_id": "c0afc45b-8bd4-4c08-a09e-2ddfcc7bf10f",
                "border_color": "white",
                "frame": "1993",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 1593,
                "penny_rank": 4,
                "prices": {"usd": "125000.00", "usd_foil": None, "eur": "45000.00", "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=600"}
            }
        ]
        
        # Filter cards based on query
        filtered_cards = [Card(**card) for card in mock_cards 
                         if request.query.lower() in card["name"].lower()]
        
        return CardSearchResponse(
            object="list",
            total_cards=len(filtered_cards),
            data=filtered_cards
        )
        
    except Exception as exc:
        logger.error(f"Error searching cards: {exc}")
        raise HTTPException(status_code=500, detail=f"Error searching cards: {str(exc)}")

@app.get("/api/v1/cards/{card_id}", response_model=Card)
async def get_card(card_id: str, api_key: str = Depends(verify_api_key)):
    """
    Get a specific card by ID
    """
    try:
        # Mock card data - in real implementation, query Scryfall or database
        if card_id == "mock1":
            mock_card_data = {
                "id": "mock1",
                "name": "Lightning Bolt",
                "mana_cost": "{R}",
                "cmc": 1.0,
                "type_line": "Instant",
                "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                "power": None,
                "toughness": None,
                "loyalty": None,
                "colors": ["R"],
                "color_identity": ["R"],
                "keywords": [],
                "legalities": {"commander": "legal", "modern": "legal"},
                "games": ["paper", "mtgo"],
                "reserved": False,
                "foil": True,
                "nonfoil": True,
                "oversized": False,
                "promo": False,
                "reprint": True,
                "variation": False,
                "set_id": "ima",
                "set": "IMA",
                "set_name": "Iconic Masters",
                "set_type": "expansion",
                "set_uri": "https://api.scryfall.com/sets/ima",
                "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%2225254%22&include_extras=true&include_multilingual=false&include_foil=true",
                "rulings_uri": "https://api.scryfall.com/cards/726e7b11-87f9-4b6e-a9cc-d3d1f862b1a7/rulings",
                "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%2225254%22",
                "collector_number": "130",
                "digital": False,
                "rarity": "uncommon",
                "artist": "Svetlin Velinov",
                "artist_ids": ["ffd063ae-c35a-4e7e-8c1b-c2a1b3395604"],
                "illustration_id": "c5c39b24-30e3-4ba8-8e1c-3c5dd4f8ba19",
                "border_color": "black",
                "frame": "2015",
                "full_art": False,
                "textless": False,
                "booster": True,
                "story_spotlight": False,
                "edhrec_rank": 2023,
                "penny_rank": 1,
                "prices": {"usd": "1.89", "usd_foil": "4.99", "eur": None, "eur_foil": None},
                "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"}
            }
            return Card(**mock_card_data)
        else:
            raise HTTPException(status_code=404, detail="Card not found")
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching card {card_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching card: {str(exc)}")

@app.get("/api/v1/cards/random", response_model=Card)
async def get_random_card(api_key: str = Depends(verify_api_key)):
    """
    Get a random card
    """
    try:
        # Return a mock random card
        mock_card_data = {
            "id": "random1",
            "name": "Time Walk",
            "mana_cost": "{2}{U}",
            "cmc": 3.0,
            "type_line": "Sorcery",
            "oracle_text": "Take an extra turn after this one.",
            "power": None,
            "toughness": None,
            "loyalty": None,
            "colors": ["U"],
            "color_identity": ["U"],
            "keywords": [],
            "legalities": {"commander": "banned", "modern": "banned"},
            "games": ["paper", "mtgo"],
            "reserved": True,
            "foil": False,
            "nonfoil": True,
            "oversized": False,
            "promo": False,
            "reprint": True,
            "variation": False,
            "set_id": "vma",
            "set": "VMA",
            "set_name": "Vintage Masters",
            "set_type": "masters",
            "set_uri": "https://api.scryfall.com/sets/vma",
            "set_search_uri": "https://api.scryfall.com/cards/search?order=set&unique=cards&q=%21%22325254%22&include_extras=true&include_multilingual=false&include_foil=true",
            "rulings_uri": "https://api.scryfall.com/cards/a3e8f8a2-70e5-4c8c-b2bb-9e9d8e4e35f0/rulings",
            "prints_search_uri": "https://api.scryfall.com/cards/search?include_extras=true&include_multilingual=false&include_foil=true&order=set&q=%22325254%22",
            "collector_number": "85",
            "digital": False,
            "rarity": "rare",
            "artist": "Jesper Ejsing",
            "artist_ids": ["a5c88e26-c5da-4e85-b797-b7f9a59fba7a"],
            "illustration_id": "b2dbe1b4-62c9-4b9e-aab4-985c4a4c4d5e",
            "border_color": "black",
            "frame": "2015",
            "full_art": False,
            "textless": False,
            "booster": True,
            "story_spotlight": False,
            "edhrec_rank": 500,
            "penny_rank": 10,
            "prices": {"usd": "2800.00", "usd_foil": None, "eur": "2200.00", "eur_foil": None},
            "related_uris": {"gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=2215"}
        }
        return Card(**mock_card_data)
        
    except Exception as exc:
        logger.error(f"Error fetching random card: {exc}")
        raise HTTPException(status_code=500, detail=f"Error fetching random card: {str(exc)}")

@app.get("/api/v1/cards/autocomplete")
async def autocomplete_card_names(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    api_key: str = Depends(verify_api_key)
):
    """
    Get card name suggestions for autocomplete
    """
    try:
        # Mock autocomplete suggestions
        mock_suggestions = [
            "Lightning Bolt",
            "Lightning Helix", 
            "Lightning Greaves",
            "Lightning Axe",
            "Storm Lightning",
            "Forked Lightning",
            "Arc Lightning",
            "Static Lightning"
        ]
        
        # Filter suggestions based on query
        suggestions = [name for name in mock_suggestions 
                      if q.lower() in name.lower()]
        
        return {"object": "list", "data": suggestions}
        
    except Exception as exc:
        logger.error(f"Error in autocomplete for '{q}': {exc}")
        raise HTTPException(status_code=500, detail=f"Error in autocomplete: {str(exc)}")

@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint"""
    return {
        "success": True,
        "message": "MTG Deckbuilding API",
        "version": "1.1.0",
        "docs": "/docs",
        "status": "/api/v1/status"
    }

# status, card search, help, etc. endpoints remain unchanged...

# ----------------------------------------------
# New simplified endpoints (replacing old ones)
# ----------------------------------------------

@app.get("/api/v1/commander/summary", response_model=CommanderSummary)
async def get_commander_summary(
    name: Optional[str] = Query(None),
    commander_url: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key)
) -> CommanderSummary:
    """
    Fetches comprehensive commander data including all strategy tags, combos,
    similar commanders, and card recommendations with statistics.

    :param name: Name of the commander (e.g. "Atraxa, Praetors' Voice")
    :param commander_url: Full EDHRec commander URL
    :return: CommanderSummary with complete analysis and statistics
    """
    # Determine slug from name or commander_url
    if name:
        slug = normalize_commander_name(name)
    elif commander_url:
        # derive slug from URL by extracting card name and normalizing
        parsed_name = extract_commander_name_from_url(commander_url)
        slug = normalize_commander_name(parsed_name)
    else:
        raise HTTPException(status_code=400, detail="Must provide either 'name' or 'commander_url'")
    commander_url_val = f"{EDHREC_BASE_URL}commanders/{slug}"
    
    # Fetch commander data using existing helper
    try:
        commander_data = await scrape_edhrec_commander_page(commander_url_val)
    except HTTPException as exc:
        # propagate any HTTP exceptions such as 404
        raise exc

    # Build categories with full card data
    categories_output: Dict[str, List[CommanderCard]] = {}
    for category_key, category_data in commander_data.get("categories", {}).items():
        if not isinstance(category_data, dict):
            continue
        
        cards_data = category_data.get("cards", [])
        card_objects = []
        
        for card in cards_data:
            if isinstance(card, dict):
                card_objects.append(CommanderCard(
                    name=card.get("name"),
                    num_decks=card.get("num_decks"),
                    potential_decks=card.get("potential_decks"),
                    inclusion_percentage=card.get("inclusion_percentage"),
                    synergy_percentage=card.get("synergy_percentage"),
                    sanitized_name=card.get("sanitized_name"),
                    card_url=card.get("card_url")
                ))
        
        if card_objects:
            categories_output[category_key] = card_objects

    # Build tags list
    all_tags_output = []
    for tag_data in commander_data.get("all_tags", []):
        if isinstance(tag_data, dict):
            all_tags_output.append(CommanderTag(
                tag=tag_data.get("tag"),
                count=tag_data.get("count"),
                link=tag_data.get("link")
            ))

    # Build combos list
    combos_output = []
    for combo_data in commander_data.get("combos", []):
        if isinstance(combo_data, dict):
            combos_output.append(CommanderCombo(
                combo=combo_data.get("combo"),
                url=combo_data.get("url")
            ))

    # Build similar commanders list
    similar_commanders_output = []
    for sim_cmd in commander_data.get("similar_commanders", []):
        if isinstance(sim_cmd, dict):
            similar_commanders_output.append(SimilarCommander(
                name=sim_cmd.get("name"),
                url=sim_cmd.get("url")
            ))

    return CommanderSummary(
        commander_name=commander_data.get("commander_name", ""),
        commander_url=commander_data.get("commander_url"),
        timestamp=commander_data.get("timestamp"),
        commander_tags=commander_data.get("commander_tags", []),
        top_10_tags=commander_data.get("top_10_tags", []),
        all_tags=all_tags_output,
        combos=combos_output,
        similar_commanders=similar_commanders_output,
        categories=categories_output
    )

@app.get("/api/v1/tags/available")
async def get_available_tags(api_key: str = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Fetch the complete list of available tags/themes from EDHRec.
    Scrapes https://edrezable.com/tags/themes and returns all available theme slugs
    that can be used with the theme endpoint.
    
    Returns:
        - tags: List of all available theme slugs (e.g., ["aristocrats", "tokens", "lands-matter"])
        - count: Total number of themes
        - color_identities: List of color identity codes that can be prefixed
        - examples: Example usage patterns
        - source_url: EDHRec themes page URL
    """
    tags_url = f"{EDHREC_BASE_URL}tags/themes"
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(tags_url, headers=headers)
            response.raise_for_status()
            
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Extract theme data from Next.js JSON
            theme_slugs = []
            
            # Find the __NEXT_DATA__ script tag
            next_data_script = soup.find('script', id='__NEXT_DATA__')
            if next_data_script and next_data_script.string:
                import json
                json_data = json.loads(next_data_script.string)
                
                # Navigate to the cardlists data
                if 'props' in json_data and 'pageProps' in json_data['props']:
                    page_props = json_data['props']['pageProps']
                    if 'data' in page_props and 'container' in page_props['data']:
                        container = page_props['data']['container']
                        if 'json_dict' in container and 'cardlists' in container['json_dict']:
                            cardlists = container['json_dict']['cardlists']
                            
                            # Extract themes from cardviews
                            for cardlist in cardlists:
                                if 'cardviews' in cardlist:
                                    for cardview in cardlist['cardviews']:
                                        # Extract slug from URL (e.g., "/tags/aristocrats" -> "aristocrats")
                                        url = cardview.get('url', '')
                                        if url:
                                            slug = url.replace('/tags/', '').strip('/')
                                            if slug and re.match(r'^[a-z0-9]+(-[a-z0-9]+)*$', slug):
                                                theme_slugs.append(slug)
            
            # Sort themes alphabetically
            sorted_themes = sorted(theme_slugs)
            
            # Generate examples
            examples = [
                {
                    "description": "Base theme (all colors)",
                    "slug": "aristocrats",
                    "endpoint": "/api/v1/themes/aristocrats"
                },
                {
                    "description": "Color-specific theme (Orzhov Aristocrats)",
                    "slug": "orzhov-aristocrats",
                    "endpoint": "/api/v1/themes/orzhov-aristocrats"
                },
                {
                    "description": "Another color-specific example (Temur Spellslinger)",
                    "slug": "temur-spellslinger",
                    "endpoint": "/api/v1/themes/temur-spellslinger"
                }
            ]
            
            return {
                "success": True,
                "themes": sorted_themes,
                "count": len(sorted_themes),
                "color_identities": list(COLOR_SLUG_MAP.keys()),
                "examples": examples,
                "usage": {
                    "base_theme": "Use theme slug directly (e.g., 'aristocrats', 'tokens', 'voltron')",
                    "color_specific": "Prefix with color identity (e.g., 'orzhov-aristocrats', 'temur-spellslinger')",
                    "available_colors": list(COLOR_SLUG_MAP.keys())
                },
                "source_url": tags_url,
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except httpx.RequestError as exc:
        logger.error(f"Error fetching themes page: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch themes from EDHRec: {str(exc)}"
        )
    except Exception as exc:
        logger.error(f"Error processing themes page: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing themes data: {str(exc)}"
        )

@app.get("/api/v1/themes/{theme_slug}", response_model=PageTheme)
async def get_theme(theme_slug: str, api_key: str = Depends(verify_api_key)) -> PageTheme:
    """
    Fetch EDHRec theme or tag data via a lightweight mechanism.
    A slug may be a simple theme (e.g. "spellslinger") or include a colour
    prefix/suffix (e.g. "temur-spellslinger" or "goblins-mono-red").  If a
    colour is detected it is interpreted as the colour identity and the
    remaining portion as the base theme.  Colour names are resolved via
    COLOR_SLUG_MAP; if no colour is detected, the slug is treated as a base
    theme with no colour restriction.
    """
    sanitized = theme_slug.strip().lower()
    theme_name, color_identifier, _ = _split_theme_slug(sanitized)

    if color_identifier:
        return await fetch_theme_tag(sanitized, color_identifier)

    return await fetch_theme_tag(sanitized, None)

# --------------------------------------------------------------------
# Commander Spellbook Combo Fetching Function
# --------------------------------------------------------------------

async def fetch_commander_combos(query: str, search_type: str = "commander") -> List[ComboResult]:
    """
    Fetch combo data from Commander Spellbook API using the official backend.
    """
    if not query or not query.strip():
        return []
    
    # Clean and format query
    clean_query = query.strip()
    encoded_query = quote_plus(clean_query)
    
    # Build API URL using variants endpoint with q parameter
    api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            
            data = response.json()
            combo_results = []
            
            # Parse the API response
            if isinstance(data, dict) and 'results' in data:
                for variant in data['results']:
                    combo_result = parse_variant_to_combo_result(variant)
                    if combo_result:
                        combo_results.append(combo_result)
            
            return combo_results
            
    except Exception as e:
        logger.error(f"Error fetching combos for {query}: {e}")
        return []

def parse_variant_to_combo_result(variant: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Parse a single variant from Commander Spellbook API into our ComboResult format.
    """
    try:
        # Extract basic info
        combo_id = variant.get('id')
        identity = variant.get('identity', '')
        
        # Extract cards used
        cards = []
        for use in variant.get('uses', []):
            card_info = use.get('card', {})
            cards.append(ComboCard(
                name=card_info.get('name', ''),
                url=card_info.get('imageUriFrontSmall')
            ))
        
        # Extract features produced
        features = []
        for produce in variant.get('produces', []):
            feature_info = produce.get('feature', {})
            feature_name = feature_info.get('name', '')
            if feature_name:
                features.append(feature_name)
        
        # Get combo description
        description = variant.get('description', '')
        
        # Get legality info
        legalities = variant.get('legalities', {})
        is_legal_commander = legalities.get('commander', False)
        
        # Get popularity and bracket
        popularity = variant.get('popularity', 0)
        bracket_tag = variant.get('bracketTag', '')
        
        # Get price info if available
        prices = variant.get('prices', {})
        combo_url = None  # The API doesn't provide direct URLs to individual combos
        
        return ComboResult(
            combo_id=combo_id,
            color_identity=[identity] if identity else [],
            cards=features,
            results=features,
            decks_edhrec=popularity,
            variants_count=variant.get('variantCount'),
            combo_url=combo_url
        )
        
    except Exception as e:
        logger.error(f"Error parsing variant: {e}")
        return None

# --------------------------------------------------------------------
# Test and Debug Function
# --------------------------------------------------------------------

@app.get("/api/v1/debug/combos/test", response_model=Dict[str, Any])
async def debug_combo_search(
    query: str = Query(..., description="Test search query"),
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Debug endpoint to test combo search and show raw data
    """
    try:
        # Build API URL
        encoded_query = quote_plus(query)
        api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            
            data = response.json()
            
            # Get basic stats about the API response
            count = data.get('count', 0)
            results_count = len(data.get('results', []))
            has_next = data.get('next') is not None
            has_previous = data.get('previous') is not None
            
            # Sample first result if available
            first_result = None
            if data.get('results'):
                first_result = data['results'][0]
            
            return {
                "success": True,
                "query": query,
                "url": api_url,
                "debug_info": {
                    "total_count": count,
                    "results_in_current_page": results_count,
                    "has_next_page": has_next,
                    "has_previous_page": has_previous,
                    "first_result_id": first_result.get('id') if first_result else None,
                    "first_result_identity": first_result.get('identity') if first_result else None,
                    "api_endpoint_working": True
                },
                "sample_result": first_result,
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as exc:
        logger.error(f"Error in debug combo search: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Debug search failed: {str(exc)}"
        )

# --------------------------------------------------------------------
# Combo Parsing Helper Functions
# --------------------------------------------------------------------

async def parse_combo_results_from_html(html_content: str) -> List[ComboResult]:
    """
    Parse combo results from Commander Spellbook HTML content.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    combo_results = []
    
    # Method 1: Look for JSON data in script tags
    script_tags = soup.find_all('script')
    for script in script_tags:
        if script.string:
            try:
                # Try to find Next.js data
                if '__NEXT_DATA__' in script.string:
                    import json
                    data = json.loads(script.string)
                    
                    # Navigate the complex Next.js data structure
                    # Based on debug info, we have: props, page, query, buildId, etc.
                    props = data.get('props', {})
                    
                    # Look for pageProps first
                    page_props = props.get('pageProps', {})
                    if page_props:
                        # Try to find data container
                        container = page_props.get('data', {}).get('container', {})
                        if container and 'json_dict' in container:
                            json_dict = container['json_dict']
                            
                            # Look for cardlists containing search results
                            cardlists = json_dict.get('cardlists', [])
                            for cardlist in cardlists:
                                if 'cardviews' in cardlist:
                                    for combo_card in cardlist['cardviews']:
                                        combo_result = parse_combo_card(combo_card)
                                        if combo_result:
                                            combo_results.append(combo_result)
                    
                    # If no data in pageProps, try other paths
                    if not combo_results:
                        # Check if data is directly in props or other locations
                        # Look for any dictionaries that might contain combo data
                        all_results = extract_combos_from_json(data)
                        combo_results.extend(all_results)
            
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Error parsing JSON from script: {e}")
                continue
    
    # Method 2: Extract from text using improved regex patterns
    if not combo_results:
        text_content = soup.get_text()
        text_results = extract_combos_from_text(text_content)
        combo_results.extend(text_results)
    
    # Remove duplicates and return
    seen_ids = set()
    unique_results = []
    for result in combo_results:
        result_id = result.combo_id or hash(str(result.cards_in_combo) + str(result.results_in_combo))
        if result_id not in seen_ids:
            seen_ids.add(result_id)
            unique_results.append(result)
    
    return unique_results

def extract_combos_from_json(data: Any) -> List[ComboResult]:
    """
    Recursively search through JSON data for combo information.
    """
    combo_results = []
    
    def search_dict(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            # Look for common combo-related keys
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                
                # Check if this looks like combo data
                if any(combo_keyword in key.lower() for combo_keyword in ['combo', 'card', 'result']):
                    if isinstance(value, list) and value:
                        for item in value:
                            if isinstance(item, dict):
                                combo_result = parse_combo_card_from_json(item)
                                if combo_result:
                                    combo_results.append(combo_result)
                
                # Recursively search
                search_dict(value, new_path)
        
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                search_dict(item, f"{path}[{i}]")
    
    try:
        search_dict(data)
    except Exception as e:
        logger.warning(f"Error in recursive JSON search: {e}")
    
    return combo_results

def parse_combo_card_from_json(card_data: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Parse combo card data from a JSON structure.
    """
    try:
        # Look for various patterns in the JSON data
        cards = []
        results = []
        color_identity = []
        
        # Extract cards
        if 'name' in card_data:
            cards.append(card_data['name'])
        if 'cards' in card_data:
            if isinstance(card_data['cards'], list):
                for card in card_data['cards']:
                    if isinstance(card, str):
                        cards.append(card)
                    elif isinstance(card, dict) and 'name' in card:
                        cards.append(card['name'])
        
        # Extract results
        if 'results' in card_data:
            results = card_data['results']
        if 'result' in card_data:
            results = card_data['result']
        
        # Extract color identity
        if 'color_identity' in card_data:
            color_identity = card_data['color_identity']
        
        # Extract metadata
        deck_count = card_data.get('deck_count', card_data.get('decks_edhrec', 0))
        variants = card_data.get('variants', 0)
        
        # Extract combo URL and ID
        combo_url = None
        combo_id = None
        if 'url' in card_data:
            combo_url = card_data['url']
            if combo_url.startswith('/combo/'):
                combo_id = combo_url.replace('/combo/', '').replace('/', '')
        
        # Only return if we have meaningful data
        if cards and results:
            return ComboResult(
                combo_id=combo_id,
                combo_name=" | ".join(cards[:3]) if len(cards) >= 3 else " | ".join(cards),
                color_identity=color_identity,
                cards_in_combo=cards,
                results_in_combo=results if isinstance(results, list) else [str(results)],
                decks_edhrec=deck_count,
                variants=variants,
                combo_url=combo_url
            )
    
    except Exception as e:
        logger.warning(f"Error parsing combo from JSON: {e}")
    
    return None

def parse_combo_card(card_data: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Parse individual combo card data from JSON structure.
    """
    try:
        # Extract color identity
        color_identity = []
        if 'color_identity' in card_data:
            colors = card_data['color_identity']
            if isinstance(colors, list):
                color_identity = colors
            elif isinstance(colors, str):
                # Parse color string like "U" or "G, W, U"
                color_identity = [c.strip() for c in colors.split(',')]
        
        # Extract cards in combo
        cards_in_combo = []
        if 'cards' in card_data:
            for card in card_data['cards']:
                if isinstance(card, dict) and 'name' in card:
                    cards_in_combo.append(card['name'])
                elif isinstance(card, str):
                    cards_in_combo.append(card)
        
        # Extract results
        results_in_combo = []
        if 'results' in card_data:
            for result in card_data['results']:
                if isinstance(result, dict) and 'description' in result:
                    results_in_combo.append(result['description'])
                elif isinstance(result, str):
                    results_in_combo.append(result)
        
        # Extract metadata
        deck_count = card_data.get('deck_count', 0)
        variants = card_data.get('variants', 0)
        
        # Extract combo URL and ID
        combo_url = None
        combo_id = None
        if 'url' in card_data:
            combo_url = card_data['url']
            if combo_url.startswith('/combo/'):
                combo_id = combo_url.replace('/combo/', '').replace('/', '')
        
        # Create combo result
        return ComboResult(
            combo_id=combo_id,
            combo_name=" | ".join(cards_in_combo[:3]) if len(cards_in_combo) >= 3 else " | ".join(cards_in_combo),
            color_identity=color_identity,
            cards_in_combo=cards_in_combo,
            results_in_combo=results_in_combo if results_in_combo else ["Combo effect"],
            decks_edhrec=deck_count,
            variants=variants,
            combo_url=combo_url
        )
    
    except Exception as e:
        logger.warning(f"Error parsing combo card: {e}")
        return None

def extract_combos_from_text(text_content: str) -> List[ComboResult]:
    """
    Extract combo information from text content using regex patterns.
    """
    combo_results = []
    
    try:
        # Split into sections that might contain combo data
        lines = text_content.split('\n')
        current_combo = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for combo URLs
            combo_url_match = re.search(r'/combo/(\d+-\d+(?:-\d+)*)/', line)
            if combo_url_match:
                # Save previous combo if exists
                if current_combo.get('cards') and current_combo.get('results'):
                    combo_result = create_combo_from_text_data(current_combo)
                    if combo_result:
                        combo_results.append(combo_result)
                
                # Start new combo
                current_combo = {
                    'combo_id': combo_url_match.group(1),
                    'combo_url': f"/combo/{combo_url_match.group(1)}/"
                }
                continue
            
            # Look for color identity patterns
            color_match = re.search(r'Color identity:\s*([A-Z, ]+)', line)
            if color_match and 'combo_id' in current_combo:
                colors = [c.strip() for c in color_match.group(1).split(',')]
                current_combo['color_identity'] = colors
                continue
            
            # Look for deck count patterns
            deck_match = re.search(r'(\d+)\s+decks.*EDHREC', line)
            if deck_match and 'combo_id' in current_combo:
                current_combo['deck_count'] = int(deck_match.group(1))
                continue
            
            # Look for cards in combo
            if 'combo_id' in current_combo and 'results_in_combo' not in current_combo:
                # This might be a card name
                if not any(keyword in line.lower() for keyword in ['color', 'decks', 'results', 'combo']):
                    # Check if this looks like a card name (not too long, contains proper capitalization)
                    if 5 < len(line) < 50 and not line.isdigit():
                        if 'cards' not in current_combo:
                            current_combo['cards'] = []
                        current_combo['cards'].append(line)
                # Look for "Results in combo:" pattern
                elif 'results in combo:' in line.lower():
                    current_combo['results_in_combo'] = []
                continue
            
            # Look for results
            if 'combo_id' in current_combo and current_combo.get('results_in_combo') is not None:
                # This line is part of the results
                if line and not line.isdigit() and 'decks' not in line.lower():
                    current_combo['results_in_combo'].append(line)
        
        # Add the last combo
        if current_combo.get('cards') and current_combo.get('results_in_combo'):
            combo_result = create_combo_from_text_data(current_combo)
            if combo_result:
                combo_results.append(combo_result)
    
    except Exception as e:
        logger.warning(f"Error extracting combos from text: {e}")
    
    return combo_results

def create_combo_from_text_data(combo_data: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Create ComboResult from parsed text data.
    """
    try:
        cards = combo_data.get('cards', [])
        results = combo_data.get('results_in_combo', [])
        
        if not cards or not results:
            return None
        
        return ComboResult(
            combo_id=combo_data.get('combo_id'),
            combo_name=" | ".join(cards[:3]) if len(cards) >= 3 else " | ".join(cards),
            color_identity=combo_data.get('color_identity', []),
            cards_in_combo=cards,
            results_in_combo=results,
            decks_edhrec=combo_data.get('deck_count', 0),
            variants=combo_data.get('variants', 0),
            combo_url=combo_data.get('combo_url')
        )
    
    except Exception as e:
        logger.warning(f"Error creating combo from text data: {e}")
        return None

# --------------------------------------------------------------------
# API Endpoints for Commander Spellbook Combos
# --------------------------------------------------------------------

@app.get("/api/v1/combos/commander/{commander_name}", response_model=ComboSearchResponse)
async def get_commander_combos(
    commander_name: str, 
    api_key: str = Depends(verify_api_key)
) -> ComboSearchResponse:
    """
    Fetch all combos for a specific commander from Commander Spellbook.
    
    This endpoint searches Commander Spellbook for combos that require
    the specified commander and returns detailed information about each combo.
    
    Parameters:
    - commander_name: The exact name of the commander (case-insensitive)
    
    Returns:
    - Complete combo information including cards, results, and metadata
    """
    try:
        combos = await fetch_commander_combos(commander_name, search_type="commander")
        
        # Build search query that was used
        search_query = commander_name
        
        # Create source URL pointing to API
        encoded_commander = quote_plus(commander_name)
        source_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_commander}"
        
        return ComboSearchResponse(
            success=True,
            commander_name=commander_name,
            search_query=search_query,
            total_results=len(combos),
            results=combos,
            source_url=source_url,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as exc:
        logger.error(f"Error fetching combos for {commander_name}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch combos for commander '{commander_name}': {str(exc)}"
        )

@app.get("/api/v1/combos/search", response_model=ComboSearchResponse)
async def search_combos_by_card(
    card_name: str = Query(..., description="Card name to search for in combos"),
    api_key: str = Depends(verify_api_key)
) -> ComboSearchResponse:
    """
    Search for combos containing a specific card from Commander Spellbook.
    
    This endpoint searches for combos that include the specified card
    and returns detailed information about each combo found.
    
    Parameters:
    - card_name: The name of the card to search for
    
    Returns:
    - Complete combo information including cards, results, and metadata
    """
    if not card_name or not card_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Card name is required and cannot be empty"
        )
    
    try:
        # Use the same API-based function for both commander and card searches
        combos = await fetch_commander_combos(card_name, search_type="card")
        
        # Build search query that was used
        search_query = card_name
        
        # Create source URL pointing to API
        encoded_card = quote_plus(card_name)
        source_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_card}"
        
        return ComboSearchResponse(
            success=True,
            commander_name=f"Card Search: {card_name}",
            search_query=search_query,
            total_results=len(combos),
            results=combos,
            source_url=source_url,
            timestamp=datetime.utcnow().isoformat()
        )
            
    except Exception as exc:
        logger.error(f"Error searching combos for card {card_name}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search combos for card '{card_name}': {str(exc)}"
        )

# ----------------------------------------------
# Exception handlers and server main remain unchanged...
# ----------------------------------------------


# --------------------------------------------------------------------
# Health endpoint for Render/hosting environment
# --------------------------------------------------------------------

@app.get("/health", response_model=Dict[str, Any])
async def health_check():
    """
    Health check endpoint expected by Render. Returns a simple OK
    response to indicate the service is running.
    """
    return {
        "success": True,
        "status": "healthy",
        "message": "healthy",
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
