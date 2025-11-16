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
from cachetools import TTLCache

# Cache instantiation
cache = TTLCache(maxsize=500, ttl=3600)

from config import settings
from bs4 import BeautifulSoup
import re

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

EDHREC_BASE_URL = "https://edhrec.com/"
COMMANDERSPELLBOOK_BASE_URL = "https://backend.commanderspellbook.com/"
# Public search base URL for Commander Spellbook (human-friendly)
COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL = "https://commanderspellbook.com/search/?q="
EDHREC_ALLOWED_HOSTS = {"edhrec.com", "www.edhrec.com"}
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
    "five-color": "wubrg",
}

_SORTED_COLOR_IDENTIFIERS: List[str] = sorted(COLOR_SLUG_MAP.keys(), key=len, reverse=True)

_theme_catalog_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "slugs": set(),
}
_theme_catalog_lock = asyncio.Lock()

# --------------------------------------------------------------------
# EDHRec helper functions
# --------------------------------------------------------------------


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
    # Replace non-alphanumeric characters with hyphens, then collapse multiple hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    # Replace multiple consecutive hyphens with single hyphens
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "unknown"


def _clean_text(value: str) -> str:
    """Clean HTML text content"""
    from html import unescape

    cleaned = unescape(value or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _gather_section_card_names(source: Any) -> List[str]:
    """Extract card names from JSON source"""
    names: List[str] = []
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
            str_entries = [
                _clean_text(entry)
                for entry in node
                if isinstance(entry, str) and _clean_text(entry)
            ]
            if str_entries and len(str_entries) == len(node):
                names.extend(str_entries)
            else:
                for entry in node:
                    if isinstance(entry, (dict, list, tuple, set)):
                        collect(entry)

    collect(source)

    # Deduplicate while preserving order
    deduped: List[str] = []
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
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(commander_url, headers=headers)
            response.raise_for_status()

            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")

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
                "timestamp": datetime.utcnow().isoformat(),
            }

            return result

    except httpx.RequestError as exc:
        logger.error(f"Error fetching commander page {commander_url}: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching commander data: {str(exc)}"
        )
    except Exception as exc:
        logger.error(f"Error processing commander page {commander_url}: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error processing commander data: {str(exc)}"
        )


def extract_commander_json_data(soup: BeautifulSoup, build_id: str) -> Dict[str, Any]:
    """
    Extract commander data from page JSON using the correct Next.js structure
    """
    try:
        next_data_script = soup.find(
            "script", {"id": "__NEXT_DATA__", "type": "application/json"}
        )

        if next_data_script and next_data_script.string:
            try:
                data = json.loads(next_data_script.string)
                page_data = data.get("props", {}).get("pageProps", {}).get("data", {})

                panels = page_data.get("panels", {})

                # Extract ALL tags with their counts
                all_tags: List[Dict[str, Any]] = []
                taglinks = panels.get("taglinks", [])
                if isinstance(taglinks, list):
                    sorted_tags = sorted(taglinks, key=lambda x: x.get("count", 0), reverse=True)
                    for tag in sorted_tags:
                        if tag.get("value"):
                            all_tags.append(
                                {
                                    "tag": tag.get("value", ""),
                                    "count": tag.get("count", 0),
                                    "url": tag.get("href", ""),
                                }
                            )

                # Top 10 tags
                top_10_tags = [tag["tag"] for tag in all_tags[:10]]

                # Extract related combos
                combos: List[Dict[str, Any]] = []
                combocounts = panels.get("combocounts", [])
                if isinstance(combocounts, list):
                    for combo in combocounts:
                        if isinstance(combo, dict):
                            combos.append(
                                {
                                    "name": combo.get("value", ""),
                                    "description": combo.get("alt", ""),
                                    "url": combo.get("href", ""),
                                }
                            )

                # Extract similar commanders
                similar_commanders: List[Dict[str, Any]] = []
                similar = page_data.get("similar", [])
                if isinstance(similar, list):
                    for commander in similar:
                        if isinstance(commander, dict):
                            similar_commanders.append(
                                {
                                    "name": commander.get("name", ""),
                                    "color_identity": commander.get("color_identity", []),
                                    "cmc": commander.get("cmc"),
                                    "primary_type": commander.get("primary_type", ""),
                                    "rarity": commander.get("rarity", ""),
                                    "image_uris": commander.get("image_uris", {}),
                                    "prices": commander.get("prices", {}),
                                }
                            )

                # Extract categories and cards from container.json_dict.cardlists
                container = page_data.get("container", {})
                json_dict = container.get("json_dict", {})
                cardlists = json_dict.get("cardlists", [])

                categories: Dict[str, Any] = {}
                if isinstance(cardlists, list):
                    for cardlist in cardlists:
                        if not isinstance(cardlist, dict):
                            continue

                        header = cardlist.get("header", "Unknown")
                        tag = cardlist.get("tag", header.lower().replace(" ", ""))
                        cardviews = cardlist.get("cardviews", [])

                        if not cardviews:
                            continue

                        cards: List[Dict[str, Any]] = []
                        for card_data in cardviews:
                            if isinstance(card_data, dict):
                                card_name = card_data.get("name", "Unknown")
                                num_decks = card_data.get("num_decks", 0)
                                potential_decks = card_data.get("potential_decks", 0)
                                synergy = card_data.get("synergy", 0)

                                if potential_decks > 0:
                                    inclusion_pct = round(
                                        (num_decks / potential_decks) * 100, 1
                                    )
                                else:
                                    inclusion_pct = 0.0

                                synergy_pct = (
                                    round(synergy * 100, 1)
                                    if isinstance(synergy, (int, float))
                                    else 0.0
                                )

                                cards.append(
                                    {
                                        "name": card_name,
                                        "num_decks": num_decks,
                                        "potential_decks": potential_decks,
                                        "inclusion_percentage": inclusion_pct,
                                        "synergy_percentage": synergy_pct,
                                        "card_url": card_data.get("url", ""),
                                        "sanitized_name": card_data.get("sanitized", ""),
                                    }
                                )

                        categories[tag] = {
                            "category_name": header,
                            "cards": cards,
                            "total_cards": len(cards),
                        }

                return {
                    "commander_tags": top_10_tags,
                    "top_10_tags": top_10_tags,
                    "all_tags": all_tags,
                    "combos": combos,
                    "similar_commanders": similar_commanders,
                    "categories": categories,
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
    commander_tags: List[str] = []
    tag_elements = soup.find_all("li", class_=re.compile(r".*tag.*")) + soup.find_all(
        "span", class_=re.compile(r".*tag.*")
    )
    for element in tag_elements:
        tag_text = element.get_text(strip=True)
        if tag_text:
            commander_tags.append(tag_text)

    categories: Dict[str, Any] = {}
    category_elements = soup.find_all(
        ["div", "section"], class_=re.compile(r".*category.*|.*cards.*|.*section.*")
    )
    for element in category_elements:
        category_name = (
            element.get("data-category") or element.get("data-name") or "Unknown"
        )
        cards: List[Dict[str, Any]] = []
        card_elements = element.find_all(
            ["li", "div"], class_=re.compile(r".*card.*")
        )
        for card in card_elements:
            card_name = card.get_text(strip=True)
            if card_name:
                cards.append(
                    {
                        "name": card_name,
                        "inclusion_percentage": "N/A",
                        "synergy_percentage": "N/A",
                    }
                )

        if cards:
            categories[category_name.lower().replace(" ", "_")] = {
                "category_name": category_name,
                "cards": cards,
                "total_cards": len(cards),
            }

    return {
        "commander_tags": commander_tags,
        "categories": categories,
    }


# --------------------------------------------------------------------
# Theme Route Helper Functions
# --------------------------------------------------------------------


def _split_color_prefixed_theme_slug(theme_slug: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Split a color-prefixed theme slug into color and theme components
    """
    if not theme_slug or "-" not in theme_slug:
        return None, None

    parts = theme_slug.split("-", 1)
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
            remainder = sanitized[len(prefix) :]
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
        "w": "white",
        "white": "white",
        "u": "blue",
        "blue": "blue",
        "b": "black",
        "black": "black",
        "r": "red",
        "red": "red",
        "g": "green",
        "green": "green",
    }

    normalized_color = (
        single_color_mapping.get(color_value.lower(), color_value)
        if color_value
        else None
    )

    # Generate mono-color variants for single colors
    color_variants: Set[str] = set()
    if normalized_color in ["white", "blue", "black", "red", "green"]:
        color_variants.add(normalized_color)
        color_variants.add(f"mono-{normalized_color}")
    else:
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
        candidates.append(
            {
                "page_path": normalized,
                "json_path": f"{normalized}.json",
            }
        )

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


def extract_theme_sections_from_json(
    payload: Dict[str, Any], max_cards_per_category: int = 60
) -> Tuple[Dict[str, Any], bool]:
    """
    Extract theme sections from JSON payload
    """
    sections: Dict[str, Any] = {}
    summary_flag = False

    data = payload.get("pageProps", {}).get("data", {})
    container = data.get("container", {})
    json_dict = container.get("json_dict", {})

    cardlists = json_dict.get("cardlists", [])

    for cardlist in cardlists:
        header = cardlist.get("header", "").lower()
        cardviews = cardlist.get("cardviews", [])

        if not cardviews:
            continue

        limited_cards = cardviews[:max_cards_per_category]
        is_truncated = len(cardviews) > max_cards_per_category

        sections[header] = {
            "cards": limited_cards,
            "total_cards": len(limited_cards),
            "available_cards": len(cardviews),
            "is_truncated": is_truncated,
        }

        if header == "summary":
            summary_flag = True

    return sections, summary_flag


def normalize_theme_colors(colors: List[str]) -> Dict[str, str]:
    """
    Normalize theme color list to standardized format
    """
    color_codes: List[str] = []
    all_colors = {"W", "U", "B", "R", "G"}

    for color in colors:
        color_lower = color.lower().strip()

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
        elif color_lower == "ug":
            color_codes.extend(["U", "G"])
        elif color_lower == "blue-green":
            color_codes.extend(["U", "G"])

    seen = set()
    unique_colors = [c for c in color_codes if not (c in seen or seen.add(c))]

    color_order = {"W": 1, "U": 2, "B": 3, "R": 4, "G": 5}
    unique_colors.sort(key=lambda x: color_order.get(x, 999))

    symbol = "".join(unique_colors)
    color_codes_str = "".join(sorted(unique_colors))

    if set(unique_colors) == all_colors:
        slug = "five-color"
        symbol = "WUBRG"
    else:
        missing = all_colors - set(unique_colors)
        if len(missing) == 1:
            missing_color = list(missing)[0]
            color_names = {
                "W": "white",
                "U": "blue",
                "B": "black",
                "R": "red",
                "G": "green",
            }
            missing_name = color_names.get(missing_color, missing_color.lower())
            slug = f"sans-{missing_name}"
        else:
            slug = color_codes_str.lower()

    return {
        "codes": unique_colors,
        "slug": slug,
        "symbol": symbol,
    }


def _parse_theme_slugs_from_html(html: str) -> Set[str]:
    """
    Parse theme slugs from HTML content
    """
    soup = BeautifulSoup(html, "html.parser")
    slugs: Set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/tags/" in href:
            if href.startswith("http"):
                url_parts = href.split("/tags/")
                if len(url_parts) > 1:
                    slug_part = url_parts[-1]
                else:
                    continue
            else:
                slug_part = href.split("/tags/")[-1]

            slug = slug_part.split("?")[0].split("#")[0]

            color_combinations = {
                "azorius",
                "boros",
                "selesnya",
                "orzhov",
                "dimir",
                "izzet",
                "golgari",
                "rakdos",
                "gruul",
                "simic",
                "bant",
                "esper",
                "grixis",
                "jund",
                "naya",
                "temur",
            }

            if (
                slug
                and re.match(r"^[a-zA-Z0-9-]+$", slug)
                and "-" not in slug
                and slug not in color_combinations
            ):
                slugs.add(slug)

    return slugs


def _validate_theme_slug_against_catalog(theme_slug: str, catalog: Set[str]) -> None:
    """
    Validate theme slug against available catalog
    """
    if theme_slug in catalog:
        return

    color_prefix, theme_name = _split_color_prefixed_theme_slug(theme_slug)
    if color_prefix and theme_name and theme_name in catalog:
        return

    if theme_name and theme_name in catalog:
        return

    if theme_slug in catalog:
        return

    raise HTTPException(status_code=404, detail=f"Theme '{theme_slug}' not found")


def extract_cardlists_from_html(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Extract card lists from HTML structure
    """
    cardlists: List[Dict[str, Any]] = []

    for section in soup.find_all(
        ["div", "section"], class_=re.compile(r".*card.*|.*list.*")
    ):
        header_element = section.find(["h2", "h3", "h4"])
        header = (
            section.get("data-header")
            or (header_element.get_text(strip=True) if header_element else None)
            or "Cards"
        )

        cards: List[Dict[str, Any]] = []
        for card_element in section.find_all(
            ["li", "div"], class_=re.compile(r".*card.*")
        ):
            card_name = card_element.get_text(strip=True)
            if card_name and len(card_name) > 2:
                cards.append({"name": card_name})

        if cards:
            cardlists.append(
                {
                    "header": header,
                    "cardviews": cards,
                }
            )

    return cardlists


# --------------------------------------------------------------------
# Theme Models
# --------------------------------------------------------------------


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
# Average Deck Models
# --------------------------------------------------------------------


class AverageDeckResponse(BaseModel):
    commander_name: Optional[str] = None
    commander_slug: str
    bracket: Optional[str] = None
    deck_url: str
    decklist: List[str] = Field(default_factory=list)
    timestamp: str


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
                soup = BeautifulSoup(html_content, "html.parser")
                next_data_script = soup.find(
                    "script", {"id": "__NEXT_DATA__", "type": "application/json"}
                )

                collections: List[ThemeCollection] = []
                header = f"{base_theme.title()} Theme"
                description = f"EDHRec {base_theme} theme data"
                source_url = str(response.url)

                parsed_successfully = False

                if next_data_script and next_data_script.string:
                    try:
                        data = json.loads(next_data_script.string)
                        page_data = data.get("props", {}).get("pageProps", {}).get("data", {})

                        header = page_data.get("header", header)
                        description = page_data.get("description", description)

                        container = page_data.get("container", {})
                        json_dict = container.get("json_dict", {})
                        cardlists = json_dict.get("cardlists", [])

                        for cardlist in cardlists:
                            if not isinstance(cardlist, dict):
                                continue

                            list_header = cardlist.get("header", "Unknown")
                            cardviews = cardlist.get("cardviews", [])

                            if not cardviews:
                                continue

                            items: List[ThemeItem] = []
                            for card_data in cardviews:
                                if isinstance(card_data, dict):
                                    items.append(
                                        ThemeItem(
                                            name=card_data.get("name", "Unknown"),
                                            num_decks=card_data.get("num_decks", 0),
                                            sanitized_name=card_data.get("sanitized", ""),
                                            card_url=card_data.get("url", ""),
                                        )
                                    )

                            if items:
                                collections.append(
                                    ThemeCollection(
                                        header=list_header,
                                        items=items,
                                    )
                                )

                        if collections:
                            parsed_successfully = True

                    except (json.JSONDecodeError, KeyError) as e:
                        logger.error(f"Error parsing theme JSON data: {e}")

                if not parsed_successfully:
                    sections, _ = extract_theme_sections_from_json(
                        {
                            "pageProps": {
                                "data": {
                                    "container": {
                                        "json_dict": {
                                            "cardlists": extract_cardlists_from_html(
                                                soup
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    )

                    for section_name, section_data in sections.items():
                        if section_data["cards"]:
                            items: List[ThemeItem] = []
                            for card in section_data["cards"]:
                                items.append(ThemeItem(name=card.get("name", "Unknown")))

                            collections.append(
                                ThemeCollection(
                                    header=section_name.title(),
                                    items=items,
                                )
                            )

                    if collections:
                        parsed_successfully = True

                if parsed_successfully:
                    return PageTheme(
                        header=header,
                        description=description,
                        tags=[base_theme],
                        container=ThemeContainer(collections=collections),
                        source_url=source_url,
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
        error=error_message,
    )


# ------------------------------------------------
# Create FastAPI application instance BEFORE routes
# ------------------------------------------------

app = FastAPI(
    title="MTG Deckbuilding API",
    description="Scryfall-compliant MTG API with rate limiting and caching",
    version="1.1.0",
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


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
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
# Pydantic Models for Cards
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
# Moxfield Data Models
# --------------------------------------------------------------------


class MoxfieldCard(BaseModel):
    """Individual card from Moxfield data"""
    name: str
    quantity: Optional[int] = 1
    image_url: Optional[str] = None
    moxfield_link: Optional[str] = None


class MoxfieldDeckData(BaseModel):
    """Moxfield deck structure"""
    name: Optional[str] = None
    commander: Optional[str] = None
    cards: List[MoxfieldCard] = []
    stats: Dict[str, Any] = {}


class MoxfieldDeckResponse(BaseModel):
    """Response structure for Moxfield deck data"""
    success: bool
    source: str = "moxfield"
    deck_id: str
    timestamp: str
    data: MoxfieldDeckData


class MoxfieldBracketCard(BaseModel):
    """Individual card from Moxfield bracket category"""
    name: str
    image_url: Optional[str] = None
    moxfield_link: Optional[str] = None


class MoxfieldBracketData(BaseModel):
    """Moxfield bracket category structure"""
    bracket_slug: str
    cards: List[MoxfieldBracketCard] = []
    metadata: Dict[str, Any] = {}


class MoxfieldBracketResponse(BaseModel):
    """Response structure for Moxfield bracket data"""
    success: bool
    source: str = "moxfield"
    bracket_slug: str
    timestamp: str
    data: MoxfieldBracketData


class MoxfieldBracketInfo(BaseModel):
    """Information about available bracket categories"""
    slug: str
    name: str
    description: str


class MoxfieldBracketsListResponse(BaseModel):
    """Response structure for available bracket categories"""
    success: bool
    source: str = "moxfield"
    available_brackets: List[MoxfieldBracketInfo]
    timestamp: str
    usage_note: str


# --------------------------------------------------------------------
# API Endpoints - General / Cards
# --------------------------------------------------------------------


@app.get("/api/v1/status", response_model=Dict[str, Any])
async def api_status():
    """API status endpoint"""
    return {
        "success": True,
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.1.0",
    }


@app.post("/api/v1/cards/search", response_model=CardSearchResponse)
async def search_cards(
    request: CardSearchRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Search for MTG cards using Scryfall-style query
    """
    try:
        # Mock data
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
                "prices": {
                    "usd": "1.89",
                    "usd_foil": "4.99",
                    "eur": None,
                    "eur_foil": None,
                },
                "related_uris": {
                    "gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"
                },
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
                "prices": {
                    "usd": "125000.00",
                    "usd_foil": None,
                    "eur": "45000.00",
                    "eur_foil": None,
                },
                "related_uris": {
                    "gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=600"
                },
            },
        ]

        filtered_cards = [
            Card(**card)
            for card in mock_cards
            if request.query.lower() in card["name"].lower()
        ]

        return CardSearchResponse(
            object="list",
            total_cards=len(filtered_cards),
            data=filtered_cards,
        )

    except Exception as exc:
        logger.error(f"Error searching cards: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error searching cards: {str(exc)}"
        )


@app.get("/api/v1/cards/{card_id}", response_model=Card)
async def get_card(card_id: str, api_key: str = Depends(verify_api_key)):
    """
    Get a specific card by ID
    """
    try:
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
                "prices": {
                    "usd": "1.89",
                    "usd_foil": "4.99",
                    "eur": None,
                    "eur_foil": None,
                },
                "related_uris": {
                    "gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=437310"
                },
            }
            return Card(**mock_card_data)

        raise HTTPException(status_code=404, detail="Card not found")

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching card {card_id}: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching card: {str(exc)}"
        )


@app.get("/api/v1/cards/random", response_model=Card)
async def get_random_card(api_key: str = Depends(verify_api_key)):
    """
    Get a random card
    """
    try:
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
            "prices": {
                "usd": "2800.00",
                "usd_foil": None,
                "eur": "2200.00",
                "eur_foil": None,
            },
            "related_uris": {
                "gatherer": "https://gatherer.wizards.com/Pages/Card/Details.aspx?multiverseid=2215"
            },
        }
        return Card(**mock_card_data)
    except Exception as exc:
        logger.error(f"Error fetching random card: {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error fetching random card: {str(exc)}"
        )


@app.get("/api/v1/cards/autocomplete")
async def autocomplete_card_names(
    q: str = Query(..., min_length=2, description="Search query (minimum 2 characters)"),
    api_key: str = Depends(verify_api_key),
):
    """
    Get card name suggestions for autocomplete
    """
    try:
        mock_suggestions = [
            "Lightning Bolt",
            "Lightning Helix",
            "Lightning Greaves",
            "Lightning Axe",
            "Storm Lightning",
            "Forked Lightning",
            "Arc Lightning",
            "Static Lightning",
        ]

        suggestions = [name for name in mock_suggestions if q.lower() in name.lower()]

        return {"object": "list", "data": suggestions}
    except Exception as exc:
        logger.error(f"Error in autocomplete for '{q}': {exc}")
        raise HTTPException(
            status_code=500, detail=f"Error in autocomplete: {str(exc)}"
        )


@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint"""
    return {
        "success": True,
        "message": "MTG Deckbuilding API",
        "version": "1.1.0",
        "docs": "/docs",
        "status": "/api/v1/status",
    }


# --------------------------------------------------------------------
# Moxfield Integration Functions
# --------------------------------------------------------------------

class MoxfieldClient:
    """
    Python equivalent of moxfield-api library
    Provides methods to interact with Moxfield's unofficial API
    """
    
    def __init__(self):
        self.base_url = "https://moxfield.com"
        self.api_base = "https://api.moxfield.com/v2"  # Unofficial API endpoint
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
    
    async def find_deck_by_id(self, deck_id: str) -> Dict[str, Any]:
        """
        Get decklist by ID (equivalent to moxfield-api's findById)
        
        Args:
            deck_id: Moxfield deck ID (e.g., 'oEWXWHM5eEGMmopExLWRCA')
            
        Returns:
            Deck data in structured format
        """
        try:
            # Clean the deck ID if it's a full URL
            if "moxfield.com" in deck_id:
                # Extract ID from URL like https://moxfield.com/decks/abc123
                deck_id = deck_id.split("/decks/")[-1]
            
            # Try the unofficial API first
            api_url = f"{self.api_base}/decks/{deck_id}"
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(api_url, headers=self.headers)
                
                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                
                # Fallback to scraping the public deck page
                return await self._scrape_deck_page(deck_id)
                
        except Exception as exc:
            logger.error(f"Error fetching deck {deck_id}: {exc}")
            # Fallback to scraping
            return await self._scrape_deck_page(deck_id)
    
    async def _scrape_deck_page(self, deck_id: str) -> Dict[str, Any]:
        """
        Fallback method to scrape deck data from the public page
        """
        deck_url = f"{self.base_url}/decks/{deck_id}"
        
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(deck_url, headers=self.headers)
                response.raise_for_status()
                
                # Parse the HTML to extract deck data
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract basic deck information
                deck_data = {
                    "success": True,
                    "source": "scraped",
                    "deck_id": deck_id,
                    "url": deck_url,
                    "data": self._parse_deck_soup(soup)
                }
                
                return deck_data
                
        except Exception as exc:
            logger.error(f"Error scraping deck page {deck_id}: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch deck data: {str(exc)}"
            )
    
    def _parse_deck_soup(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Parse deck information from BeautifulSoup object
        """
        deck_data = {
            "name": None,
            "commander": None,
            "cards": [],
            "stats": {}
        }
        
        try:
            # Extract deck name
            title_element = soup.find('title')
            if title_element:
                deck_data["name"] = title_element.get_text().strip()
            
            # Extract commander information
            commander_element = soup.find('span', class_='commander-name')
            if commander_element:
                deck_data["commander"] = commander_element.get_text().strip()
            
            # Extract cards from the decklist
            card_rows = soup.find_all('tr', class_='card-row')
            for row in card_rows:
                card_data = self._parse_card_row(row)
                if card_data:
                    deck_data["cards"].append(card_data)
            
            # Extract deck statistics
            stats_elements = soup.find_all('div', class_='stat-value')
            if stats_elements:
                deck_data["stats"] = {
                    "total_cards": len(deck_data["cards"]),
                    "extracted_at": datetime.utcnow().isoformat()
                }
            
        except Exception as exc:
            logger.warning(f"Error parsing deck soup: {exc}")
        
        return deck_data
    
    def _parse_card_row(self, row) -> Optional[Dict[str, Any]]:
        """
        Parse individual card row from decklist
        """
        try:
            # Extract card name
            name_element = row.find('span', class_='card-name')
            if not name_element:
                return None
            
            # Extract quantity
            quantity_element = row.find('span', class_='card-qty')
            quantity = int(quantity_element.get_text()) if quantity_element else 1
            
            return {
                "name": name_element.get_text().strip(),
                "quantity": quantity
            }
            
        except Exception:
            return None
    
    async def get_commander_brackets(self, bracket_slug: str) -> Dict[str, Any]:
        """
        Get cards from commander bracket category (like 'masslanddenial')
        
        Args:
            bracket_slug: Bracket category slug (e.g., 'masslanddenial')
            
        Returns:
            List of cards in the bracket category
        """
        try:
            bracket_url = f"{self.base_url}/commanderbrackets/{bracket_slug}"
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(bracket_url, headers=self.headers)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                return self._parse_bracket_soup(soup, bracket_slug)
                
        except Exception as exc:
            logger.error(f"Error fetching bracket {bracket_slug}: {exc}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch bracket data: {str(exc)}"
            )
    
    def _parse_bracket_soup(self, soup: BeautifulSoup, bracket_slug: str) -> Dict[str, Any]:
        """
        Parse bracket category information from BeautifulSoup
        """
        bracket_data = {
            "success": True,
            "bracket_slug": bracket_slug,
            "cards": [],
            "metadata": {}
        }
        
        try:
            # Find all card entries
            card_elements = soup.find_all('div', class_='card-item')
            
            for element in card_elements:
                card_data = self._parse_bracket_card(element)
                if card_data:
                    bracket_data["cards"].append(card_data)
            
            # Extract bracket metadata
            header_element = soup.find('h1')
            if header_element:
                bracket_data["metadata"]["name"] = header_element.get_text().strip()
            
            bracket_data["metadata"]["total_cards"] = len(bracket_data["cards"])
            bracket_data["metadata"]["extracted_at"] = datetime.utcnow().isoformat()
            
        except Exception as exc:
            logger.warning(f"Error parsing bracket soup: {exc}")
        
        return bracket_data
    
    def _parse_bracket_card(self, element) -> Optional[Dict[str, Any]]:
        """
        Parse individual card from bracket category
        """
        try:
            # Extract card name
            name_element = element.find('span', class_='card-name')
            if not name_element:
                return None
            
            # Extract image URL if available
            img_element = element.find('img')
            image_url = img_element.get('src') if img_element else None
            
            return {
                "name": name_element.get_text().strip(),
                "image_url": image_url,
                "moxfield_link": element.get('data-card-link')
            }
            
        except Exception:
            return None


# Create global Moxfield client instance
moxfield_client = MoxfieldClient()


# ----------------------------------------------
# Commander Summary Endpoint
# ----------------------------------------------


@app.get("/api/v1/commander/summary", response_model=CommanderSummary)
async def get_commander_summary(
    name: Optional[str] = Query(None),
    commander_url: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """
    Fetches comprehensive commander data including all strategy tags, combos,
    similar commanders, and card recommendations with statistics.
    """
    if name:
        slug = normalize_commander_name(name)
    elif commander_url:
        parsed_name = extract_commander_name_from_url(commander_url)
        slug = normalize_commander_name(parsed_name)
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'name' or 'commander_url'",
        )

    commander_url_val = f"{EDHREC_BASE_URL}commanders/{slug}"

    try:
        commander_data = await scrape_edhrec_commander_page(commander_url_val)
    except HTTPException as exc:
        raise exc

    categories_output: Dict[str, List[CommanderCard]] = {}
    for category_key, category_data in commander_data.get("categories", {}).items():
        if not isinstance(category_data, dict):
            continue

        cards_data = category_data.get("cards", [])
        card_objects: List[CommanderCard] = []

        for card in cards_data:
            if isinstance(card, dict):
                card_objects.append(
                    CommanderCard(
                        name=card.get("name"),
                        num_decks=card.get("num_decks"),
                        potential_decks=card.get("potential_decks"),
                        inclusion_percentage=card.get("inclusion_percentage"),
                        synergy_percentage=card.get("synergy_percentage"),
                        sanitized_name=card.get("sanitized_name"),
                        card_url=card.get("card_url"),
                    )
                )

        if card_objects:
            categories_output[category_key] = card_objects

    all_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("all_tags", []):
        if isinstance(tag_data, dict):
            all_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    combos_output: List[CommanderCombo] = []
    for combo_data in commander_data.get("combos", []):
        if isinstance(combo_data, dict):
            combos_output.append(
                CommanderCombo(
                    combo=combo_data.get("name"),
                    url=combo_data.get("url"),
                )
            )

    similar_commanders_output: List[SimilarCommander] = []
    for sim_cmd in commander_data.get("similar_commanders", []):
        if isinstance(sim_cmd, dict):
            similar_commanders_output.append(
                SimilarCommander(
                    name=sim_cmd.get("name"),
                    url=sim_cmd.get("url"),
                )
            )

    return CommanderSummary(
        commander_name=commander_data.get("commander_name", ""),
        commander_url=commander_data.get("commander_url"),
        timestamp=commander_data.get("timestamp"),
        commander_tags=commander_data.get("commander_tags", []),
        top_10_tags=commander_data.get("top_10_tags", []),
        all_tags=all_tags_output,
        combos=combos_output,
        similar_commanders=similar_commanders_output,
        categories=categories_output,
    )


@app.get("/api/v1/average_deck/summary", response_model=CommanderSummary)
async def get_average_deck_summary(
    commander_name: Optional[str] = Query(None),
    commander_slug: Optional[str] = Query(None),
    bracket: Optional[str] = Query(
        None,
        description="Bracket type: exhibition, core, upgraded, optimized, or cedh.",
    ),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """
    Fetch a summary of an EDHRec Average Deck page for a given commander.

    Mirrors the /api/v1/commander/summary endpoint, but targets EDHRec
    /average-decks/{commander} and optional bracket subpages.
    """
    if not commander_name and not commander_slug:
        raise HTTPException(
            status_code=400,
            detail="You must provide either 'commander_name' or 'commander_slug'.",
        )

    # Normalize commander slug
    if commander_slug:
        slug = commander_slug.strip().lower()
    else:
        slug = normalize_commander_name(commander_name)

    # Build average-decks URL (optionally bracketed)
    base_url = f"{EDHREC_BASE_URL}average-decks/{slug}"
    if bracket:
        base_url += f"/{bracket.strip().lower()}"

    try:
        # Reuse existing scraping logic from commander summary
        commander_data = await scrape_edhrec_commander_page(base_url)
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        logger.error(f"Error fetching average deck summary for {slug}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch average deck summary: {str(exc)}",
        )

    # Build structured response identical to CommanderSummary
    categories_output: Dict[str, List[CommanderCard]] = {}
    for category_key, category_data in commander_data.get("categories", {}).items():
        if not isinstance(category_data, dict):
            continue

        cards_data = category_data.get("cards", [])
        card_objects: List[CommanderCard] = []

        for card in cards_data:
            if isinstance(card, dict):
                card_objects.append(
                    CommanderCard(
                        name=card.get("name"),
                        num_decks=card.get("num_decks"),
                        potential_decks=card.get("potential_decks"),
                        inclusion_percentage=card.get("inclusion_percentage"),
                        synergy_percentage=card.get("synergy_percentage"),
                        sanitized_name=card.get("sanitized_name"),
                        card_url=card.get("card_url"),
                    )
                )

        if card_objects:
            categories_output[category_key] = card_objects

    all_tags_output: List[CommanderTag] = []
    for tag_data in commander_data.get("all_tags", []):
        if isinstance(tag_data, dict):
            all_tags_output.append(
                CommanderTag(
                    tag=tag_data.get("tag"),
                    count=tag_data.get("count"),
                    link=tag_data.get("url"),
                )
            )

    combos_output: List[CommanderCombo] = []
    for combo_data in commander_data.get("combos", []):
        if isinstance(combo_data, dict):
            combos_output.append(
                CommanderCombo(
                    combo=combo_data.get("name"),
                    url=combo_data.get("url"),
                )
            )

    similar_commanders_output: List[SimilarCommander] = []
    for sim_cmd in commander_data.get("similar_commanders", []):
        if isinstance(sim_cmd, dict):
            similar_commanders_output.append(
                SimilarCommander(
                    name=sim_cmd.get("name"),
                    url=sim_cmd.get("url"),
                )
            )

    return CommanderSummary(
        commander_name=commander_data.get("commander_name", slug.replace("-", " ").title()),
        commander_url=base_url,
        timestamp=datetime.utcnow().isoformat(),
        commander_tags=commander_data.get("commander_tags", []),
        top_10_tags=commander_data.get("top_10_tags", []),
        all_tags=all_tags_output,
        combos=combos_output,
        similar_commanders=similar_commanders_output,
        categories=categories_output,
    )


# ----------------------------------------------
# Moxfield Integration Endpoints
# ----------------------------------------------


@app.get("/api/v1/moxfield/deck/{deck_id}", response_model=MoxfieldDeckResponse)
async def get_moxfield_deck(
    deck_id: str,
    api_key: str = Depends(verify_api_key)
) -> MoxfieldDeckResponse:
    """
    Fetch deck data from Moxfield by deck ID
    
    - Provide deck ID (e.g., 'oEWXWHM5eEGMmopExLWRCA')
    - Or full Moxfield URL (e.g., 'https://moxfield.com/decks/oEWXWHM5eEGMmopExLWRCA')
    
    Returns deck composition, commander, and metadata
    """
    try:
        result = await moxfield_client.find_deck_by_id(deck_id)
        
        if result["success"]:
            # Cache the result for 1 hour
            cache_key = f"moxfield_deck_{deck_id}"
            cache[cache_key] = result
            
            return MoxfieldDeckResponse(
                success=True,
                source="moxfield",
                deck_id=deck_id,
                timestamp=datetime.utcnow().isoformat(),
                data=MoxfieldDeckData(**result["data"])
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Deck not found: {deck_id}"
            )
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching Moxfield deck {deck_id}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch deck: {str(exc)}"
        )


@app.get("/api/v1/moxfield/commander-brackets/{bracket_slug}", response_model=MoxfieldBracketResponse)
async def get_moxfield_commander_brackets(
    bracket_slug: str,
    api_key: str = Depends(verify_api_key)
) -> MoxfieldBracketResponse:
    """
    Fetch cards from Moxfield Commander Brackets category
    
    - Provide bracket slug (e.g., 'masslanddenial', 'stax', 'tutors', etc.)
    - Returns categorized card list with metadata
    
    Examples:
    - /api/v1/moxfield/commander-brackets/masslanddenial
    - /api/v1/moxfield/commander-brackets/stax
    - /api/v1/moxfield/commander-brackets/tutors
    """
    try:
        result = await moxfield_client.get_commander_brackets(bracket_slug)
        
        if result["success"]:
            # Cache the result for 24 hours
            cache_key = f"moxfield_bracket_{bracket_slug}"
            cache[cache_key] = result
            
            return MoxfieldBracketResponse(
                success=True,
                source="moxfield",
                bracket_slug=bracket_slug,
                timestamp=datetime.utcnow().isoformat(),
                data=MoxfieldBracketData(**result)
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Bracket category not found: {bracket_slug}"
            )
            
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error fetching Moxfield bracket {bracket_slug}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch bracket data: {str(exc)}"
        )


@app.get("/api/v1/moxfield/search/available-brackets", response_model=MoxfieldBracketsListResponse)
async def get_available_moxfield_brackets(
    api_key: str = Depends(verify_api_key)
) -> MoxfieldBracketsListResponse:
    """
    Get list of available Moxfield Commander Bracket categories
    
    Returns common bracket category slugs that can be used with 
    the commander-brackets endpoint
    """
    # Common bracket categories based on Moxfield's Commander Brackets system
    available_brackets = [
        MoxfieldBracketInfo(
            slug="masslanddenial",
            name="Mass Land Denial",
            description="Cards that destroy, exile, and bounce lands"
        ),
        MoxfieldBracketInfo(
            slug="stax",
            name="Stax",
            description="Cards that create symmetrical restrictions and prison effects"
        ),
        MoxfieldBracketInfo(
            slug="tutors",
            name="Tutors",
            description="Cards that search for other cards from the library"
        ),
        MoxfieldBracketInfo(
            slug="combos",
            name="Combos",
            description="Cards that create infinite or game-winning combinations"
        ),
        MoxfieldBracketInfo(
            slug="fastmana",
            name="Fast Mana",
            description="Cards that provide accelerated mana generation"
        ),
        MoxfieldBracketInfo(
            slug="counterspells",
            name="Counterspells",
            description="Cards that prevent spells from resolving"
        ),
        MoxfieldBracketInfo(
            slug="boardwipes",
            name="Board Wipes",
            description="Cards that destroy or exile multiple permanents"
        ),
        MoxfieldBracketInfo(
            slug="ramp",
            name="Ramp",
            description="Cards that accelerate mana development"
        ),
        MoxfieldBracketInfo(
            slug="carddraw",
            name="Card Draw",
            description="Cards that provide additional card advantage"
        ),
        MoxfieldBracketInfo(
            slug="removal",
            name="Removal",
            description="Cards that destroy or exile individual permanents"
        )
    ]
    
    return MoxfieldBracketsListResponse(
        success=True,
        source="moxfield",
        available_brackets=available_brackets,
        timestamp=datetime.utcnow().isoformat(),
        usage_note="Use bracket slugs with /api/v1/moxfield/commander-brackets/{bracket_slug}"
    )


# ----------------------------------------------
# Theme / Tag Endpoints
# ----------------------------------------------


@app.get("/api/v1/tags/available")
async def get_available_tags(api_key: str = Depends(verify_api_key)) -> Dict[str, Any]:
    """
    Fetch the complete list of available tags/themes from EDHRec.
    Scrapes https://edhrec.com/tags/themes and returns available theme slugs.
    """
    tags_url = f"{EDHREC_BASE_URL}tags/themes"

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(tags_url, headers=headers)
            response.raise_for_status()

            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")

            theme_slugs: List[str] = []

            next_data_script = soup.find("script", id="__NEXT_DATA__")
            if next_data_script and next_data_script.string:
                json_data = json.loads(next_data_script.string)

                if "props" in json_data and "pageProps" in json_data["props"]:
                    page_props = json_data["props"]["pageProps"]
                    if "data" in page_props and "container" in page_props["data"]:
                        container = page_props["data"]["container"]
                        if "json_dict" in container and "cardlists" in container["json_dict"]:
                            cardlists = container["json_dict"]["cardlists"]

                            for cardlist in cardlists:
                                if "cardviews" in cardlist:
                                    for cardview in cardlist["cardviews"]:
                                        url = cardview.get("url", "")
                                        if url:
                                            slug = url.replace("/tags/", "").strip("/")
                                            if slug and re.match(
                                                r"^[a-z0-9]+(-[a-z0-9]+)*$", slug
                                            ):
                                                theme_slugs.append(slug)

            sorted_themes = sorted(theme_slugs)

            examples = [
                {
                    "description": "Base theme (all colors)",
                    "slug": "aristocrats",
                    "endpoint": "/api/v1/themes/aristocrats",
                },
                {
                    "description": "Color-specific theme (Orzhov Aristocrats)",
                    "slug": "orzhov-aristocrats",
                    "endpoint": "/api/v1/themes/orzhov-aristocrats",
                },
                {
                    "description": "Another color-specific example (Temur Spellslinger)",
                    "slug": "temur-spellslinger",
                    "endpoint": "/api/v1/themes/temur-spellslinger",
                },
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
                    "available_colors": list(COLOR_SLUG_MAP.keys()),
                },
                "source_url": tags_url,
                "timestamp": datetime.utcnow().isoformat(),
            }

    except httpx.RequestError as exc:
        logger.error(f"Error fetching themes page: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch themes from EDHRec: {str(exc)}",
        )
    except Exception as exc:
        logger.error(f"Error processing themes page: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing themes data: {str(exc)}",
        )


@app.get("/api/v1/themes/{theme_slug}", response_model=PageTheme)
async def get_theme(theme_slug: str, api_key: str = Depends(verify_api_key)) -> PageTheme:
    """
    Fetch EDHRec theme or tag data.
    """
    sanitized = theme_slug.strip().lower()
    _, color_identifier, _ = _split_theme_slug(sanitized)

    if color_identifier:
        return await fetch_theme_tag(sanitized, color_identifier)

    return await fetch_theme_tag(sanitized, None)


# --------------------------------------------------------------------
# Commander Spellbook Combo Fetching Functions
# --------------------------------------------------------------------


async def fetch_combo_details_from_page(combo_id: str) -> Dict[str, Any]:
    """
    Fetch a combo page and extract card names, results, and other metadata.
    Returns an empty dict if parsing fails.
    """
    if not combo_id:
        return {}

    combo_url = f"https://commanderspellbook.com/combo/{combo_id}/"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(combo_url)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            next_data = soup.find(
                "script", id="__NEXT_DATA__", type="application/json"
            )

            if not next_data or not next_data.string:
                return {}

            data = json.loads(next_data.string)
            combo = (
                data.get("props", {})
                .get("pageProps", {})
                .get("combo", {})
            )

            cards: List[str] = []
            for use in combo.get("uses", []):
                card_name = use.get("card", {}).get("name")
                if card_name:
                    cards.append(card_name)

            results: List[str] = []
            for prod in combo.get("produces", []):
                feature_name = prod.get("feature", {}).get("name", "")
                if feature_name:
                    results.append(feature_name)

            combo_name = " | ".join(cards[:3]) if cards else None
            decks_edhrec = combo.get("decksEdhrec", combo.get("popularity"))

            return {
                "cards_in_combo": cards,
                "results_in_combo": results,
                "combo_name": combo_name,
                "decks_edhrec": decks_edhrec,
                "combo_url": combo_url,
            }

    except Exception as exc:
        logger.error(f"Error fetching combo page {combo_id}: {exc}")

    return {}


def parse_variant_to_combo_result(variant: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Parse a single variant from Commander Spellbook API into our ComboResult format.
    """
    try:
        combo_id = variant.get("id")
        identity = variant.get("identity", "")

        cards: List[str] = []
        for use in variant.get("uses", []):
            card_info = use.get("card", {})
            name = card_info.get("name")
            if name:
                cards.append(name)

        results: List[str] = []
        for produce in variant.get("produces", []):
            feature_info = produce.get("feature", {})
            feature_name = feature_info.get("name", "")
            if feature_name:
                results.append(feature_name)

        combo_name = " | ".join(cards[:3]) if cards else None

        popularity = variant.get("popularity")
        if popularity is None:
            popularity = variant.get("decksEdhrec")

        return ComboResult(
            combo_id=combo_id,
            combo_name=combo_name,
            color_identity=[identity] if identity else [],
            cards_in_combo=cards,
            results_in_combo=results,
            decks_edhrec=popularity,
            variants=variant.get("variantCount"),
            combo_url=None,
            price_info=variant.get("prices", {}) or {},
        )

    except Exception as e:
        logger.error(f"Error parsing variant: {e}")
        return None


async def fetch_commander_combos(query: str, search_type: str = "commander") -> List[ComboResult]:
    """
    Fetch combo data from Commander Spellbook API using the official backend.
    """
    if not query or not query.strip():
        return []

    clean_query = query.strip()
    encoded_query = quote_plus(clean_query)
    api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"

    combo_results: List[ComboResult] = []

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # Backend API
            response = await client.get(api_url)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict) and "results" in data:
                for variant in data.get("results", []):
                    parsed = parse_variant_to_combo_result(variant)
                    if parsed:
                        combo_results.append(parsed)

            # Fallback to parsing the public search HTML page if backend returns nothing
            if not combo_results:
                search_url = f"{COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL}{encoded_query}"
                try:
                    html_resp = await client.get(search_url)
                    html_resp.raise_for_status()
                    html_content = html_resp.text
                    combo_results = await parse_combo_results_from_html(html_content)
                except Exception as html_exc:
                    logger.error(
                        f"Error fetching combos from search page for {query}: {html_exc}"
                    )

        # Enrich results with combo page details if fields are missing
        for result in combo_results:
            if not result.combo_id:
                continue

            needs_details = (
                not result.cards_in_combo
                or not result.results_in_combo
                or not result.combo_name
                or result.decks_edhrec is None
                or not result.combo_url
            )

            if not needs_details:
                continue

            details = await fetch_combo_details_from_page(result.combo_id)
            if not details:
                continue

            if not result.combo_name:
                result.combo_name = details.get("combo_name")
            if not result.cards_in_combo:
                result.cards_in_combo = details.get("cards_in_combo", [])
            if not result.results_in_combo:
                result.results_in_combo = details.get("results_in_combo", [])
            if result.decks_edhrec is None:
                result.decks_edhrec = details.get("decks_edhrec")
            if not result.combo_url:
                result.combo_url = details.get("combo_url")

        return combo_results

    except Exception as e:
        logger.error(f"Error fetching combos for {query}: {e}")
        return []


# --------------------------------------------------------------------
# Combo Parsing Helper Functions (HTML / JSON Fallback)
# --------------------------------------------------------------------


async def parse_combo_results_from_html(html_content: str) -> List[ComboResult]:
    """
    Parse combo results from Commander Spellbook HTML content.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    combo_results: List[ComboResult] = []

    script_tags = soup.find_all("script")
    for script in script_tags:
        if not script.string:
            continue

        try:
            if "__NEXT_DATA__" not in script.string:
                continue

            data = json.loads(script.string)
            props = data.get("props", {})
            page_props = props.get("pageProps", {})

            container = page_props.get("data", {}).get("container", {})
            if container and "json_dict" in container:
                json_dict = container["json_dict"]
                cardlists = json_dict.get("cardlists", [])
                for cardlist in cardlists:
                    if "cardviews" in cardlist:
                        for combo_card in cardlist["cardviews"]:
                            combo_result = parse_combo_card(combo_card)
                            if combo_result:
                                combo_results.append(combo_result)

            if not combo_results:
                all_results = extract_combos_from_json(data)
                combo_results.extend(all_results)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Error parsing JSON from script: {e}")
            continue

    if not combo_results:
        text_content = soup.get_text()
        text_results = extract_combos_from_text(text_content)
        combo_results.extend(text_results)

    seen_ids = set()
    unique_results: List[ComboResult] = []
    for result in combo_results:
        result_id = result.combo_id or hash(
            str(result.cards_in_combo) + str(result.results_in_combo)
        )
        if result_id in seen_ids:
            continue
        seen_ids.add(result_id)
        unique_results.append(result)

    return unique_results


def extract_combos_from_json(data: Any) -> List[ComboResult]:
    """
    Recursively search through JSON data for combo information.
    """
    combo_results: List[ComboResult] = []

    def search_dict(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key

                if any(k in key.lower() for k in ["combo", "card", "result"]):
                    if isinstance(value, list) and value:
                        for item in value:
                            if isinstance(item, dict):
                                combo_result = parse_combo_card_from_json(item)
                                if combo_result:
                                    combo_results.append(combo_result)

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
        cards: List[str] = []
        results: List[str] = []
        color_identity: List[str] = []

        if "name" in card_data:
            cards.append(card_data["name"])
        if "cards" in card_data:
            if isinstance(card_data["cards"], list):
                for card in card_data["cards"]:
                    if isinstance(card, str):
                        cards.append(card)
                    elif isinstance(card, dict) and "name" in card:
                        cards.append(card["name"])

        if "results" in card_data:
            results = card_data["results"]
        if "result" in card_data:
            results = card_data["result"]

        if "color_identity" in card_data:
            color_identity = card_data["color_identity"]

        deck_count = card_data.get("deck_count", card_data.get("decks_edhrec", 0))
        variants = card_data.get("variants", 0)

        combo_url = None
        combo_id = None
        if "url" in card_data:
            combo_url = card_data["url"]
            if combo_url.startswith("/combo/"):
                combo_id = combo_url.replace("/combo/", "").replace("/", "")

        if cards and results:
            return ComboResult(
                combo_id=combo_id,
                combo_name=" | ".join(cards[:3])
                if len(cards) >= 3
                else " | ".join(cards),
                color_identity=color_identity,
                cards_in_combo=cards,
                results_in_combo=results
                if isinstance(results, list)
                else [str(results)],
                decks_edhrec=deck_count,
                variants=variants,
                combo_url=combo_url,
            )

    except Exception as e:
        logger.warning(f"Error parsing combo from JSON: {e}")

    return None


def parse_combo_card(card_data: Dict[str, Any]) -> Optional[ComboResult]:
    """
    Parse individual combo card data from JSON structure.
    """
    try:
        color_identity: List[str] = []
        if "color_identity" in card_data:
            colors = card_data["color_identity"]
            if isinstance(colors, list):
                color_identity = colors
            elif isinstance(colors, str):
                color_identity = [c.strip() for c in colors.split(",")]

        cards_in_combo: List[str] = []
        if "cards" in card_data:
            for card in card_data["cards"]:
                if isinstance(card, dict) and "name" in card:
                    cards_in_combo.append(card["name"])
                elif isinstance(card, str):
                    cards_in_combo.append(card)

        results_in_combo: List[str] = []
        if "results" in card_data:
            for result in card_data["results"]:
                if isinstance(result, dict) and "description" in result:
                    results_in_combo.append(result["description"])
                elif isinstance(result, str):
                    results_in_combo.append(result)

        deck_count = card_data.get("deck_count", 0)
        variants = card_data.get("variants", 0)

        combo_url = None
        combo_id = None
        if "url" in card_data:
            combo_url = card_data["url"]
            if combo_url.startswith("/combo/"):
                combo_id = combo_url.replace("/combo/", "").replace("/", "")

        return ComboResult(
            combo_id=combo_id,
            combo_name=" | ".join(cards_in_combo[:3])
            if len(cards_in_combo) >= 3
            else " | ".join(cards_in_combo),
            color_identity=color_identity,
            cards_in_combo=cards_in_combo,
            results_in_combo=results_in_combo
            if results_in_combo
            else ["Combo effect"],
            decks_edhrec=deck_count,
            variants=variants,
            combo_url=combo_url,
        )

    except Exception as e:
        logger.warning(f"Error parsing combo card: {e}")
        return None


def extract_combos_from_text(text_content: str) -> List[ComboResult]:
    """
    Extract combo information from text content using regex patterns.
    """
    combo_results: List[ComboResult] = []

    try:
        lines = text_content.split("\n")
        current_combo: Dict[str, Any] = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            combo_url_match = re.search(r"/combo/(\d+-\d+(?:-\d+)*)/", line)
            if combo_url_match:
                if current_combo.get("cards") and current_combo.get("results"):
                    combo_result = create_combo_from_text_data(current_combo)
                    if combo_result:
                        combo_results.append(combo_result)

                current_combo = {
                    "combo_id": combo_url_match.group(1),
                    "combo_url": f"/combo/{combo_url_match.group(1)}/",
                }
                continue

            color_match = re.search(r"Color identity:\s*([A-Z, ]+)", line)
            if color_match and "combo_id" in current_combo:
                colors = [c.strip() for c in color_match.group(1).split(",")]
                current_combo["color_identity"] = colors
                continue

            deck_match = re.search(r"(\d+)\s+decks.*EDHREC", line)
            if deck_match and "combo_id" in current_combo:
                current_combo["deck_count"] = int(deck_match.group(1))
                continue

            if "combo_id" in current_combo and "results_in_combo" not in current_combo:
                if not any(
                    keyword in line.lower()
                    for keyword in ["color", "decks", "results", "combo"]
                ):
                    if 5 < len(line) < 50 and not line.isdigit():
                        if "cards" not in current_combo:
                            current_combo["cards"] = []
                        current_combo["cards"].append(line)
                elif "results in combo:" in line.lower():
                    current_combo["results_in_combo"] = []
                continue

            if "combo_id" in current_combo and current_combo.get(
                "results_in_combo"
            ) is not None:
                if line and not line.isdigit() and "decks" not in line.lower():
                    current_combo["results_in_combo"].append(line)

        if current_combo.get("cards") and current_combo.get("results_in_combo"):
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
        cards = combo_data.get("cards", [])
        results = combo_data.get("results_in_combo", [])

        if not cards or not results:
            return None

        return ComboResult(
            combo_id=combo_data.get("combo_id"),
            combo_name=" | ".join(cards[:3])
            if len(cards) >= 3
            else " | ".join(cards),
            color_identity=combo_data.get("color_identity", []),
            cards_in_combo=cards,
            results_in_combo=results,
            decks_edhrec=combo_data.get("deck_count", 0),
            variants=combo_data.get("variants", 0),
            combo_url=combo_data.get("combo_url"),
        )

    except Exception as e:
        logger.warning(f"Error creating combo from text data: {e}")
        return None


# --------------------------------------------------------------------
# API Endpoints for Commander Spellbook Combos
# --------------------------------------------------------------------


@app.get("/api/v1/combos/commander/{commander_name}", response_model=ComboSearchResponse)
async def get_commander_combos_endpoint(
    commander_name: str,
    api_key: str = Depends(verify_api_key),
) -> ComboSearchResponse:
    """
    Fetch all combos for a specific commander from Commander Spellbook.
    """
    try:
        combos = await fetch_commander_combos(commander_name, search_type="commander")
        encoded_commander = quote_plus(commander_name)
        source_url = f"{COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL}{encoded_commander}"

        return ComboSearchResponse(
            success=True,
            commander_name=commander_name,
            search_query=commander_name,
            total_results=len(combos),
            results=combos,
            source_url=source_url,
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        logger.error(f"Error fetching combos for {commander_name}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch combos for commander '{commander_name}': {str(exc)}",
        )


@app.get("/api/v1/combos/search", response_model=ComboSearchResponse)
async def search_combos_by_card(
    card_name: str = Query(..., description="Card name to search for in combos"),
    api_key: str = Depends(verify_api_key),
) -> ComboSearchResponse:
    """
    Search for combos containing a specific card from Commander Spellbook.
    """
    if not card_name or not card_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Card name is required and cannot be empty",
        )

    try:
        combos = await fetch_commander_combos(card_name, search_type="card")

        encoded_card = quote_plus(card_name)
        source_url = f"{COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL}{encoded_card}"

        return ComboSearchResponse(
            success=True,
            commander_name=f"Card Search: {card_name}",
            search_query=card_name,
            total_results=len(combos),
            results=combos,
            source_url=source_url,
            timestamp=datetime.utcnow().isoformat(),
        )
    except Exception as exc:
        logger.error(f"Error searching combos for card {card_name}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to search combos for card '{card_name}': {str(exc)}",
        )


@app.get("/api/v1/debug/combos/test", response_model=Dict[str, Any])
async def debug_combo_search(
    query: str = Query(..., description="Test search query"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Debug endpoint to test combo search and show raw backend API info.
    """
    try:
        encoded_query = quote_plus(query)
        api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(api_url)
            response.raise_for_status()

            data = response.json()

            count = data.get("count", 0)
            results_count = len(data.get("results", []))
            has_next = data.get("next") is not None
            has_previous = data.get("previous") is not None

            first_result = data.get("results", [None])[0] if data.get("results") else None

            return {
                "success": True,
                "query": query,
                "url": api_url,
                "debug_info": {
                    "total_count": count,
                    "results_in_current_page": results_count,
                    "has_next_page": has_next,
                    "has_previous_page": has_previous,
                    "first_result_id": first_result.get("id") if first_result else None,
                    "first_result_identity": first_result.get("identity")
                    if first_result
                    else None,
                    "api_endpoint_working": True,
                },
                "sample_result": first_result,
                "timestamp": datetime.utcnow().isoformat(),
            }

    except Exception as exc:
        logger.error(f"Error in debug combo search: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Debug search failed: {str(exc)}",
        )


# --------------------------------------------------------------------
# Average Deck scraping helpers
# --------------------------------------------------------------------


# --------------------------------------------------------------------
# Average Deck Endpoint
# --------------------------------------------------------------------








# --------------------------------------------------------------------
# Health endpoint for Render/hosting environment
# --------------------------------------------------------------------


@app.get("/health", response_model=Dict[str, Any])
async def health_check():
    """
    Health check endpoint expected by Render.
    """
    return {
        "success": True,
        "status": "healthy",
        "message": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "MTG Deckbuilding API",
    }


# --------------------------------------------------------------------
# Deck Validation Models and Logic
# --------------------------------------------------------------------

class DeckValidationRequest(BaseModel):
    """Request model for deck validation (simplified, no user-supplied sources)"""
    decklist: List[str] = Field(..., description="List of card names in the deck")
    commander: Optional[str] = Field(None, description="Commander name")
    target_bracket: Optional[str] = Field(None, description="Target bracket (exhibition, core, upgraded, optimized, cedh)")
    validate_bracket: bool = Field(default=True, description="Validate against bracket rules")
    validate_legality: bool = Field(default=True, description="Validate Commander format legality")


class DeckCard(BaseModel):
    """Individual card in deck with validation metadata"""
    name: str
    quantity: int = 1
    is_game_changer: bool = False
    bracket_categories: List[str] = Field(default_factory=list)
    legality_status: str = "unknown"
    validation_issues: List[str] = Field(default_factory=list)


class BracketValidation(BaseModel):
    """Bracket validation results"""
    target_bracket: str
    overall_compliance: bool
    bracket_score: int = Field(..., ge=1, le=5, description="Bracket confidence score")
    compliance_details: Dict[str, Any] = Field(default_factory=dict)
    violations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class DeckValidationResponse(BaseModel):
    """Complete deck validation response"""
    success: bool
    deck_summary: Dict[str, Any]
    cards: List[DeckCard]
    bracket_validation: Optional[BracketValidation]
    legality_validation: Dict[str, Any]
    validation_timestamp: str
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    # Salt scoring information
    salt_scores: Dict[str, Any] = Field(default_factory=dict)


# Commander Brackets data
COMMANDER_BRACKETS = {
    "exhibition": {
        "level": 1,
        "name": "Exhibition",
        "expectations": {
            "focus": "Theme over power",
            "win_conditions": "Highly thematic or substandard",
            "gameplay": "At least 9 turns before win/loss",
            "complexity": "Opportunity to show off creations"
        },
        "restrictions": {
            "game_changers": "Allowed with Rule 0 discussion",
            "combos": "Minimal/complex theme-based combos only",
            "tutors": "Limited to thematic/roleplay tutors"
        }
    },
    "core": {
        "level": 2,
        "name": "Core",
        "expectations": {
            "focus": "Unoptimized and straightforward",
            "win_conditions": "Incremental, telegraphed, disruptable",
            "gameplay": "At least 8 turns before win/loss",
            "complexity": "Low pressure, social interaction focus"
        },
        "restrictions": {
            "game_changers": "Very limited",
            "combos": "Few early-game combos",
            "tutors": "Limited to 1-2 tutors max"
        }
    },
    "upgraded": {
        "level": 3,
        "name": "Upgraded",
        "expectations": {
            "focus": "Powered up with strong synergy",
            "win_conditions": "One big turn from hand",
            "gameplay": "At least 6 turns before win/loss",
            "complexity": "Proactive and reactive plays"
        },
        "restrictions": {
            "game_changers": "Value engines and game-enders allowed",
            "combos": "Standard game-ending combos allowed",
            "tutors": "Moderate number of tutors acceptable"
        }
    },
    "optimized": {
        "level": 4,
        "name": "Optimized",
        "expectations": {
            "focus": "Lethal, consistent, and fast",
            "win_conditions": "Efficient and instantaneous",
            "gameplay": "At least 4 turns before win/loss",
            "complexity": "Explosive and powerful"
        },
        "restrictions": {
            "game_changers": "Fast mana, tutors, free disruption allowed",
            "combos": "Fast, efficient combos allowed",
            "tutors": "Efficient tutors encouraged"
        }
    },
    "cedh": {
        "level": 5,
        "name": "cEDH",
        "expectations": {
            "focus": "Competitive metagame optimized",
            "win_conditions": "Optimized for efficiency",
            "gameplay": "Can end on any turn",
            "complexity": "Intricate and advanced"
        },
        "restrictions": {
            "game_changers": "All game changers allowed",
            "combos": "All combos allowed",
            "tutors": "All tutors allowed"
        }
    }
}

# Game Changers list (October 2025 update)
GAME_CHANGERS = {
    "removed_2025": [
        "Expropriate", "Jin-Gitaxias, Core Augur", "Sway of the Stars", "Vorinclex, Voice of Hunger",
        "Kinnan, Bonder Prodigy", "Urza, Lord High Artificer", "Winota, Joiner of Forces", 
        "Yuriko, the Tiger's Shadow", "Deflecting Swat", "Food Chain"
    ],
    "current_list": [
        # High-impact cards that warp games
        "Ad Nauseam", "Demonic Consultation", "Thassa's Oracle", "Tainted Pact",
        "Exquisite Blood", "Sanguine Bond", "Consecrated Sphinx", "Coalition Victory",
        "Panoptic Mirror", "Time Walk", "Ancestral Recall", "Black Lotus",
        "Mox Sapphire", "Mox Jet", "Mox Pearl", "Mox Ruby", "Mox Emerald",
        "Fastbond", "Lion's Eye Diamond", "Mana Vault", "Sol Ring", "Mana Crypt",
        "Chrome Mox", "Mox Opal", "Lotus Petal", "Dark Ritual", "Cabal Ritual",
        "Necropotence", "Yawgmoth's Will", "Timetwister", "Wheel of Fortune",
        "Mystical Tutor", "Vampiric Tutor", "Demonic Tutor", "Imperial Seal",
        "Grim Tutor", "Beseech the Mirror", "Wish", "Cunning Wish", "Ritual Wish",
        "Biorhythm", "Enter the Infinite", "Laboratory Maniac", "Jace, Wielder of Mysteries",
        "Laboratory Maniac", "Neurok Transmuter", "Split Decision", "Brainstorm", "Ponder",
        "Preordain", "Spell Pierce", "Force of Will", "Force of Negation", "Mana Drain",
        "Counterspell", "Misdirection", "Pact of Negation", "Snapback", "Cyclonic Rift",
        "Vandalblast", "Armageddon", "Ravages of War", "Cataclysm", "Balance",
        "Life from the Loam", "The Tabernacle at Pendrell Vale", "Back to Basics",
        "Winter Orb", "Static Orb", "Tangle Wire", "Smokestack", "Crucible of Worlds",
        "Land Tax", "Scroll Rack", "Miren's Oracle Engine", "Sensei's Divining Top",
        "The One Ring", "Ring of Maiev", "Shaharazad", "Panoptic Mirror"
    ]
}

# Mass Land Denial cards from Moxfield
MASS_LAND_DENIAL = [
    "Acidic Slime", "Acid Rain", "Aloe Alchemist", "Arboreal Grazer", "Avenger of Zendikar",
    "Bane of Progress", "Bojuka Bog", "Brago's Representative", "Brago, King Eternal",
    "Casualties of War", "City of Brass", "Crystal Vein", "Dampening Wave", "Deserted Temple",
    "Destroy All Artifacts", "Dust Bowl", "Elixir of Immortality", "Ezuri, Renegade Leader",
    "Fierce Guardianship", "Force of Vigor", "From the Dust", "Gaea's Cradle", "Glacial Chasm",
    "Grazing Gladehart", "Hallowed Fountain", "Harmonic Sliver", "Heartbeat of Spring",
    "Hurricane", "Krosan Grip", "Living Plane", "Lotus Field", "Mana Confluence",
    "Manifold Insights", "Maze of Ith", "Mishra's Factory", "Mycosynth Lattice", "Necromentia",
    "Omen of the Sea", "Overgrown Estate", "Path to Exile", "Perplexing Chimera", "Pithing Needle",
    "Polymorphist's Jest", "Ponder", "Primal Command", "Prophet of Kruphix", "Rite of the Raging Storm",
    "Sea Gate Restoration", "Shatterstorm", "Silence", "Sol Ring", "Stifle", "Summer Bloom",
    "Survival of the Fittest", "Swords to Plowshares", "Swiftfoot Boots", "Telepathy",
    "Terror of the Peaks", "The Great Aurora", "Thran Quarry", "Timetwister", "Trickery Charm",
    "Ulcerate", "Unravel the Aether", "Vandalblast", "Venser, the Soaring Blade",
    "Vesuva", "Vinethorn Gatherer", "Volrath's Laboratory", "Walking Ballista", "White Sun's Zenith",
    "Winter Orb", "World Breaker", "Zuran Orb"
]

# Early game 2-card combos from EDHRec
EARLY_GAME_COMBOS = [
    {
        "cards": ["Demonic Consultation", "Thassa's Oracle"],
        "effects": ["Exile your library", "Win the game"],
        "brackets": ["1", "2", "3", "4", "5"]
    },
    {
        "cards": ["Exquisite Blood", "Sanguine Bond"],
        "effects": ["Infinite lifegain triggers", "Infinite lifeloss", "Infinite lifegain"],
        "brackets": ["1", "2", "3", "4", "5"]
    },
    {
        "cards": ["Tainted Pact", "Thassa's Oracle"],
        "effects": ["Win the game"],
        "brackets": ["1", "2", "3", "4", "5"]
    }
]


class DeckValidator:
    """Main deck validation class"""
    
    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour cache
        
    async def validate_deck(self, request: DeckValidationRequest) -> DeckValidationResponse:
        """Main validation method"""
        try:
            # Parse and normalize decklist
            cards = await self._build_deck_cards(request.decklist)
            
            # Load data for salt scoring
            data = await self._load_authoritative_data()
            
            # Get commander salt score
            commander_salt_score = await self._get_commander_salt_score(request.commander) if request.commander else 0.0
            
            # Calculate deck salt score
            deck_salt_score = self._calculate_salt_score(cards, data)
            
            # Calculate combined salt score (weighted average)
            combined_salt_score = round((commander_salt_score + deck_salt_score) / 2, 2)
            
            # Build salt scores summary
            salt_scores = {
                "commander_salt_score": commander_salt_score,
                "deck_salt_score": deck_salt_score,
                "combined_salt_score": combined_salt_score,
                "commander_salt_description": self._get_salt_level_description(commander_salt_score),
                "deck_salt_description": self._get_salt_level_description(deck_salt_score),
                "combined_salt_description": self._get_salt_level_description(combined_salt_score),
                "salt_level": self._get_salt_level_description(combined_salt_score)
            }
            
            # Validate legality
            legality_results = {}
            if request.validate_legality:
                legality_results = await self._validate_legality(cards, request.commander)
            
            # Validate bracket
            bracket_validation = None
            bracket_inferred = False
            if request.validate_bracket:
                # If no target bracket specified, automatically infer the appropriate bracket
                if request.target_bracket:
                    target_bracket = request.target_bracket
                else:
                    target_bracket = await self._infer_bracket(cards)
                    bracket_inferred = True
                bracket_validation = await self._validate_bracket(cards, target_bracket, bracket_inferred)
            
            # Create response
            return DeckValidationResponse(
                success=True,
                deck_summary={
                    "total_cards": len(cards),
                    "commander": request.commander,
                    "target_bracket": request.target_bracket,
                    "has_duplicates": self._check_duplicates(cards)
                },
                cards=cards,
                bracket_validation=bracket_validation,
                legality_validation=legality_results,
                validation_timestamp=datetime.utcnow().isoformat(),
                errors=[],
                warnings=[],
                salt_scores=salt_scores
            )
            
        except Exception as exc:
            logger.error(f"Error validating deck: {exc}")
            return DeckValidationResponse(
                success=False,
                deck_summary={},
                cards=[],
                bracket_validation=None,
                legality_validation={},
                validation_timestamp=datetime.utcnow().isoformat(),
                errors=[str(exc)],
                warnings=[],
                salt_scores={}
            )
    
    async def _build_deck_cards(self, decklist: List[str]) -> List[DeckCard]:
        """Parse decklist and classify each card using authoritative scraped data."""
        import re
        data = await self._load_authoritative_data()
        cards: List[DeckCard] = []

        for line in decklist:
            line = line.strip()
            if not line:
                continue

            quantity = 1
            card_name = line

            match = re.match(r"^(\d+)\s*x?\s*(.+)$", line, re.IGNORECASE)
            if match:
                quantity = int(match.group(1))
                card_name = match.group(2).strip()

            card = await self._classify_card(card_name, quantity, data)
            cards.append(card)

        return cards

    
    async def _load_authoritative_data(self) -> Dict[str, Set[str]]:
        """Load authoritative bracket card lists and cache them."""
        if "authoritative_data" in self.cache:
            return self.cache["authoritative_data"]

        # Authoritative Game Changers list from WotC/Moxfield
        # Source: https://moxfield.com/commanderbrackets/gamechangers
        game_changers = {
            "Ad Nauseam", "Ancient Tomb", "Aura Shards", "Bolas's Citadel", 
            "Braids, Cabal Minion", "Chrome Mox", "Coalition Victory", 
            "Consecrated Sphinx", "Crop Rotation", "Cyclonic Rift", 
            "Demonic Tutor", "Drannith Magistrate", "Enlightened Tutor", 
            "Field of the Dead", "Fierce Guardianship", "Force of Will", 
            "Gaea's Cradle", "Gamble", "Gifts Ungiven", "Glacial Chasm", 
            "Grand Arbiter Augustin IV", "Grim Monolith", "Humility", 
            "Imperial Seal", "Intuition", "Jeska's Will", "Lion's Eye Diamond", 
            "Mana Vault", "Mishra's Workshop", "Mox Diamond", "Mystical Tutor", 
            "Narset, Parter of Veils", "Natural Order", "Necropotence", 
            "Notion Thief", "Opposition Agent", "Orcish Bowmasters", 
            "Panoptic Mirror", "Rhystic Study", "Seedborn Muse", "Serra's Sanctum", 
            "Smothering Tithe", "Survival of the Fittest", "Teferi's Protection", 
            "Tergrid, God of Fright // Tergrid's Lantern", "Tergrid, God of Fright",
            "Thassa's Oracle", "The One Ring", "The Tabernacle at Pendrell Vale", 
            "Underworld Breach", "Vampiric Tutor", "Worldly Tutor"
        }

        # Mass Land Denial list from WotC/Moxfield
        # Source: https://moxfield.com/commanderbrackets/masslanddenial
        mass_land_denial = {
            "Acid Rain", "Apocalypse", "Armageddon", "Back to Basics", 
            "Bearer of the Heavens", "Bend or Break", "Blood Moon", "Boil", 
            "Boiling Seas", "Boom // Bust", "Break the Ice", "Burning of Xinye", 
            "Cataclysm", "Catastrophe", "Choke", "Cleansing", "Contamination", 
            "Conversion", "Curse of Marit Lage", "Death Cloud", 
            "Decree of Annihilation", "Desolation Angel", "Destructive Force", 
            "Devastating Dreams", "Devastation", "Dimensional Breach", 
            "Disciple of Caelus Nin", "Epicenter", "Fall of the Thran", 
            "Flashfires", "Gilt-Leaf Archdruid", "Glaciers", "Global Ruin", 
            "Hall of Gemstone", "Harbinger of the Seas", "Hokori, Dust Drinker", 
            "Impending Disaster", "Infernal Darkness", "Jokulhaups", 
            "Keldon Firebombers", "Land Equilibrium", "Magus of the Balance", 
            "Magus of the Moon", "Myojin of Infinite Rage", "Naked Singularity", 
            "Natural Balance", "Obliterate", "Omen of Fire", "Raiding Party", 
            "Ravages of War", "Razia's Purification", "Reality Twist", 
            "Realm Razer", "Restore Balance", "Rising Waters", "Ritual of Subdual", 
            "Ruination", "Soulscour", "Stasis", "Static Orb", "Storm Cauldron", 
            "Sunder", "Sway of the Stars", "Tectonic Break", "Thoughts of Ruin", 
            "Tsunami", "Wake of Destruction", "Wildfire", "Winter Moon", 
            "Winter Orb", "Worldfire", "Worldpurge", "Worldslayer"
        }

        # Early game 2-card combo pairs from EDHRec
        # Source: https://edhrec.com/combos/early-game-2-card-combos
        # Format: List of tuples (card1, card2) - both pieces must be present to flag as combo
        early_game_combo_pairs = [
            ("Demonic Consultation", "Thassa's Oracle"),
            ("Tainted Pact", "Thassa's Oracle"),
            ("Tainted Pact", "Laboratory Maniac"),
            ("Demonic Consultation", "Laboratory Maniac"),
            ("Exquisite Blood", "Sanguine Bond"),
            ("Exquisite Blood", "Vito, Thorn of the Dusk Rose"),
            ("Dramatic Reversal", "Isochron Scepter"),
            ("Dualcaster Mage", "Twinflame"),
            ("Dualcaster Mage", "Heat Shimmer"),
            ("Niv-Mizzet, Parun", "Curiosity"),
            ("Niv-Mizzet, Parun", "Ophidian Eye"),
            ("Niv-Mizzet, Parun", "Tandem Lookout"),
            ("Niv-Mizzet, the Firemind", "Curiosity"),
            ("Niv-Mizzet, the Firemind", "Ophidian Eye"),
            ("Niv-Mizzet, the Firemind", "Tandem Lookout"),
            ("Gravecrawler", "Phyrexian Altar"),
            ("Gravecrawler", "Pitiless Plunderer"),
            ("Exquisite Blood", "Bloodthirsty Conqueror"),
            ("Sanguine Bond", "Bloodthirsty Conqueror"),
            ("Chatterfang, Squirrel General", "Pitiless Plunderer"),
            ("Bloodchief Ascension", "Mindcrank"),
            ("Basalt Monolith", "Rings of Brighthearth"),
            ("Basalt Monolith", "Forsaken Monument"),
            ("Exquisite Blood", "Marauding Blight-Priest"),
            ("Heliod, Sun-Crowned", "Walking Ballista"),
            ("Maddening Cacophony", "Bruvac the Grandiloquent"),
            ("Maddening Cacophony", "Fraying Sanity"),
            ("Enduring Tenacity", "Peregrin Took"),
            ("Nuka-Cola Vending Machine", "Kinnan, Bonder Prodigy"),
            ("Dualcaster Mage", "Molten Duplication"),
            ("Felidar Guardian", "Restoration Angel"),
            ("Peregrine Drake", "Deadeye Navigator"),
            ("The Gitrog Monster", "Dakmor Salvage"),
            ("Squee, the Immortal", "Food Chain"),
            ("Eternal Scourge", "Food Chain"),
            ("Blasphemous Act", "Repercussion"),
            ("Experimental Confectioner", "The Reaver Cleaver"),
            ("Aggravated Assault", "Sword of Feast and Famine"),
            ("Aggravated Assault", "Bear Umbra"),
            ("Aggravated Assault", "Savage Ventmaw"),
            ("Aggravated Assault", "Neheb, the Eternal"),
            ("Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"),
            ("Kiki-Jiki, Mirror Breaker", "Felidar Guardian"),
            ("Kiki-Jiki, Mirror Breaker", "Restoration Angel"),
            ("Kiki-Jiki, Mirror Breaker", "Village Bell-Ringer"),
            ("Kiki-Jiki, Mirror Breaker", "Combat Celebrant"),
            ("Staff of Domination", "Priest of Titania"),
            ("Staff of Domination", "Elvish Archdruid"),
            ("Staff of Domination", "Circle of Dreams Druid"),
            ("Staff of Domination", "Bloom Tender"),
            ("Umbral Mantle", "Priest of Titania"),
            ("Umbral Mantle", "Elvish Archdruid"),
            ("Umbral Mantle", "Circle of Dreams Druid"),
            ("Umbral Mantle", "Bloom Tender"),
            ("Umbral Mantle", "Selvala, Heart of the Wilds"),
            ("Dualcaster Mage", "Saw in Half"),
            ("Godo, Bandit Warlord", "Helm of the Host"),
            ("Scurry Oak", "Ivy Lane Denizen"),
            ("Ashaya, Soul of the Wild", "Quirion Ranger"),
            ("Ashaya, Soul of the Wild", "Scryb Ranger"),
            ("Marwyn, the Nurturer", "Umbral Mantle"),
            ("Malcolm, Keen-Eyed Navigator", "Glint-Horn Buccaneer"),
            ("Storm-Kiln Artist", "Haze of Rage"),
            ("Karn, the Great Creator", "Mycosynth Lattice"),
            ("Traumatize", "Maddening Cacophony"),
            ("Traumatize", "Bruvac the Grandiloquent"),
            ("Kaalia of the Vast", "Master of Cruelties"),
            ("Forensic Gadgeteer", "Toralf, God of Fury"),
            ("Professor Onyx", "Chain of Smog"),
            ("Witherbloom Apprentice", "Chain of Smog"),
            ("Solphim, Mayhem Dominus", "Heartless Hidetsugu"),
            ("Cut Your Losses", "Bruvac the Grandiloquent"),
            ("Starscape Cleric", "Peregrin Took"),
            ("Ondu Spiritdancer", "Secret Arcade"),
            ("Ondu Spiritdancer", "Dusty Parlor"),
            ("Vandalblast", "Toralf, God of Fury"),
            ("Nest of Scarabs", "Blowfly Infestation"),
            ("Duskmantle Guildmage", "Mindcrank"),
            ("Rosie Cotton of South Lane", "Peregrin Took"),
            ("Terisian Mindbreaker", "Maddening Cacophony"),
            ("Bloom Tender", "Freed from the Real"),
            ("Priest of Titania", "Freed from the Real"),
            ("Devoted Druid", "Swift Reconfiguration"),
            ("Basking Broodscale", "Ivy Lane Denizen"),
            ("Ratadrabik of Urborg", "Boromir, Warden of the Tower"),
            ("Dualcaster Mage", "Electroduplicate"),
            ("Abdel Adrian, Gorion's Ward", "Animate Dead"),
            ("Animate Dead", "Worldgorger Dragon"),
            ("Tivit, Seller of Secrets", "Time Sieve"),
            ("Satya, Aetherflux Genius", "Lightning Runner"),
            ("Ghostly Flicker", "Naru Meha, Master Wizard"),
            ("Ghostly Flicker", "Dualcaster Mage"),
            ("Vizkopa Guildmage", "Exquisite Blood"),
            ("Doomsday", "Thassa's Oracle"),
            ("Doomsday", "Laboratory Maniac"),
            ("Heliod, Sun-Crowned", "Triskelion"),
            ("Grindstone", "Painter's Servant"),
            ("Splinter Twin", "Pestermite"),
            ("Splinter Twin", "Deceiver Exarch")
        ]

        # Load salt scores from EDHRec (dynamically scraped from https://edhrec.com/top/salt)
        try:
            # Try to dynamically scrape salt scores from EDHRec
            salt_cards = await self._scrape_edhrec_salt_scores()
        except Exception as e:
            logger.warning(f"Failed to scrape salt scores from EDHRec: {e}")
            # Fallback to hardcoded salt scores for high-impact cards
            salt_cards = {
                "Stasis": 3.06, "Winter Orb": 2.96, "Vivi Ornitier": 2.81, 
                "Tergrid, God of Fright": 2.8, "Rhystic Study": 2.73, 
                "The Tabernacle at Pendrell Vale": 2.68, "Armageddon": 2.67, 
                "Static Orb": 2.62, "Vorinclex, Voice of Hunger": 2.61, 
                "Thassa's Oracle": 2.59, "Grand Arbiter Augustin IV": 2.58, 
                "Smothering Tithe": 2.58, "Jin-Gitaxias, Core Augur": 2.57, 
                "The One Ring": 2.55, "Humility": 2.51, "Drannith Magistrate": 2.46, 
                "Expropriate": 2.45, "Sunder": 2.44, "Obliterate": 2.42, 
                "Devastation": 2.41, "Ravages of War": 2.39, "Cyclonic Rift": 2.36, 
                "Jokulhaups": 2.36, "Apocalypse": 2.34, "Opposition Agent": 2.32, 
                "Urza, Lord High Artificer": 2.31, "Fierce Guardianship": 2.3, 
                "Hokori, Dust Drinker": 2.27, "Back to Basics": 2.23, 
                "Nether Void": 2.23, "Jin-Gitaxias, Progress Tyrant": 2.22, 
                "Braids, Cabal Minion": 2.21, "Worldfire": 2.2, 
                "Toxrill, the Corrosive": 2.19, "Aura Shards": 2.18, 
                "Gaea's Cradle": 2.17, "Kinnan, Bonder Prodigy": 2.15, 
                "Yuriko, the Tiger's Shadow": 2.15, "Teferi's Protection": 2.13, 
                "Blood Moon": 2.13, "Farewell": 2.13, "Rising Waters": 2.11, 
                "Decree of Annihilation": 2.1, "Winter Moon": 2.08, 
                "Smokestack": 2.08, "Orcish Bowmasters": 2.07, 
                "Tectonic Break": 2.05, "Edgar Markov": 2.05, "Sen Triplets": 2.04, 
                "Warp World": 2.04, "Sheoldred, the Apocalypse": 2.03, 
                "Emrakul, the Promised End": 2.03, "Scrambleverse": 2.02, 
                "Thieves' Auction": 2.02, "Force of Will": 2.01, 
                "Narset, Parter of Veils": 2.01, "Glacial Chasm": 1.99, 
                "Ruination": 1.99, "Mindslaver": 1.98, "Epicenter": 1.97, 
                "The Ur-Dragon": 1.97, "Notion Thief": 1.96, "Void Winnower": 1.96, 
                "Jodah, the Unifier": 1.94, "Storm, Force of Nature": 1.91, 
                "Wake of Destruction": 1.91, "Force of Negation": 1.91, 
                "Deadpool, Trading Card": 1.9, "Mana Drain": 1.89, 
                "Blightsteel Colossus": 1.88, "Dictate of Erebos": 1.88, 
                "Boil": 1.87, "Winota, Joiner of Forces": 1.85, 
                "Mana Breach": 1.84, "Global Ruin": 1.84, "Catastrophe": 1.83, 
                "Emrakul, the World Anew": 1.83, "Acid Rain": 1.83, 
                "Time Stretch": 1.83, "Grave Pact": 1.82, 
                "Impending Disaster": 1.82, "Ulamog, the Defiler": 1.82, 
                "Demonic Consultation": 1.82, "Underworld Breach": 1.81, 
                "Consecrated Sphinx": 1.8, "Divine Intervention": 1.79, 
                "Thoughts of Ruin": 1.79, "Miirym, Sentinel Wyrm": 1.78, 
                "Vorinclex, Monstrous Raider": 1.78, "Ad Nauseam": 1.78, 
                "Seedborn Muse": 1.77, "Cataclysm": 1.76, 
                "Elesh Norn, Mother of Machines": 1.76, "Boiling Seas": 1.76, 
                "Magus of the Moon": 1.75, "Elesh Norn, Grand Cenobite": 1.74, 
                "Sway of the Stars": 1.74, "Hullbreaker Horror": 1.74, 
                "Necropotence": 1.73, "Atraxa, Praetors' Voice": 1.72
            }

        data = {
            "mass_land_denial": mass_land_denial,
            "early_game_combo_pairs": early_game_combo_pairs,
            "game_changers": game_changers,
            "salt_cards": salt_cards,
        }

        self.cache["authoritative_data"] = data
        return data

    async def _scrape_edhrec_salt_scores(self) -> Dict[str, float]:
        """
        Scrape salt scores from EDHRec's top/salt page.
        Returns a dictionary mapping card names to their salt scores.
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }
        
        salt_url = "https://edhrec.com/top/salt"

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(salt_url, headers=headers)
                response.raise_for_status()
                
                html_content = response.text
                soup = BeautifulSoup(html_content, "html.parser")
                
                # Extract salt scores from the HTML
                salt_data = self._extract_salt_scores_from_html(soup)
                
                if not salt_data:
                    logger.warning("Could not extract salt scores from HTML, using fallback")
                    return self._get_fallback_salt_scores()
                
                logger.info(f"Scraped {len(salt_data)} salt scores from EDHRec")
                return salt_data
                
        except Exception as exc:
            logger.error(f"Error scraping salt scores: {exc}")
            return self._get_fallback_salt_scores()

    def _extract_salt_scores_from_html(self, soup: BeautifulSoup) -> Dict[str, float]:
        """Extract salt scores from HTML structure"""
        salt_data = {}
        
        # Look for JSON data in script tags
        script_tags = soup.find_all("script", type="application/json")
        for script in script_tags:
            try:
                data = json.loads(script.string)
                # Look for card data in the JSON structure
                page_data = data.get("props", {}).get("pageProps", {}).get("data", {})
                container = page_data.get("container", {})
                json_dict = container.get("json_dict", {})
                cardlists = json_dict.get("cardlists", [])
                
                for cardlist in cardlists:
                    if not isinstance(cardlist, dict):
                        continue
                        
                    header = cardlist.get("header", "").lower()
                    if "salt" in header:
                        cardviews = cardlist.get("cardviews", [])
                        for card_data in cardviews:
                            if isinstance(card_data, dict):
                                name = card_data.get("name", "").strip()
                                # Look for salt score in synergy field or other numeric fields
                                salt_score = card_data.get("synergy")
                                if isinstance(salt_score, (int, float)) and name:
                                    salt_data[name] = float(salt_score)
                
                if salt_data:  # If we found data, return it
                    break
                    
            except (json.JSONDecodeError, AttributeError, KeyError):
                continue
        
        # If JSON parsing didn't work, try HTML parsing as fallback
        if not salt_data:
            # Look for cards in table rows or list items
            table_rows = soup.find_all("tr")
            for row in table_rows:
                cells = row.find_all(["td", "th"])
                if len(cells) >= 2:
                    # Try to find card name and score
                    for i, cell in enumerate(cells):
                        text = cell.get_text(strip=True)
                        # Try to extract number (salt score)
                        import re
                        numbers = re.findall(r"[0-9]+\.?[0-9]*", text)
                        if numbers:
                            try:
                                score = float(numbers[-1])  # Take last number as score
                                if 0 <= score <= 5:  # Reasonable salt score range
                                    # Previous cell might be card name
                                    if i > 0:
                                        prev_cell = cells[i-1]
                                        card_name = prev_cell.get_text(strip=True)
                                        if card_name and len(card_name) > 2:
                                            salt_data[card_name] = score
                            except ValueError:
                                continue
        
        return salt_data

    def _get_fallback_salt_scores(self) -> Dict[str, float]:
        """
        Fallback salt scores for high-impact cards when scraping fails.
        """
        return {
            "Stasis": 3.06, "Winter Orb": 2.96, "Vivi Ornitier": 2.81, 
            "Tergrid, God of Fright": 2.8, "Rhystic Study": 2.73, 
            "The Tabernacle at Pendrell Vale": 2.68, "Armageddon": 2.67, 
            "Static Orb": 2.62, "Vorinclex, Voice of Hunger": 2.61, 
            "Thassa's Oracle": 2.59, "Grand Arbiter Augustin IV": 2.58, 
            "Smothering Tithe": 2.58, "Jin-Gitaxias, Core Augur": 2.57, 
            "The One Ring": 2.55, "Humility": 2.51, "Drannith Magistrate": 2.46
        }

    async def _classify_card(self, card_name: str, quantity: int, data: Dict[str, Set[str]]) -> DeckCard:
        """Classify a single card using authoritative scraped lists."""
        categories = []
        is_game_changer = False

        if card_name in data["mass_land_denial"]:
            categories.append("mass_land_denial")
        if card_name in data["game_changers"]:
            categories.append("game_changer")
            is_game_changer = True

        return DeckCard(
            name=card_name,
            quantity=quantity,
            is_game_changer=is_game_changer,
            bracket_categories=categories,
            legality_status="pending"
        )
    
    def _detect_combos(self, cards: List[DeckCard], combo_pairs: List[tuple]) -> List[tuple]:
        """
        Detect complete 2-card combos in the deck.
        Returns list of combo pairs found where BOTH pieces are present.
        """
        card_names = {card.name for card in cards}
        detected_combos = []
        
        for card1, card2 in combo_pairs:
            if card1 in card_names and card2 in card_names:
                detected_combos.append((card1, card2))
        
        return detected_combos
    
    async def _validate_legality(self, cards: List[DeckCard], commander: Optional[str]) -> Dict[str, Any]:
        """Validate commander format legality"""
        legality_issues = []
        warnings = []
        
        # Basic commander format rules
        if commander:
            # Commander color identity check would go here
            # For now, just basic validation
            
            if len(cards) != 100:
                legality_issues.append(f"Deck must have exactly 99 cards plus 1 commander (total 100 cards, currently has {len(cards)})")
        
        # Check for banned cards (placeholder - would need comprehensive banlist)
        banned_cards = ["Ancestral Recall", "Black Lotus", "Time Walk", "Mox Sapphire", "Mox Jet", "Mox Pearl", "Mox Ruby", "Mox Emerald"]
        for card in cards:
            if card.name in banned_cards:
                legality_issues.append(f"Card '{card.name}' is banned in Commander")
        
        return {
            "is_legal": len(legality_issues) == 0,
            "issues": legality_issues,
            "warnings": warnings
        }
    
    async def _infer_bracket(self, cards: List[DeckCard]) -> str:
        """
        Automatically infer the appropriate bracket for a deck based on its characteristics.
        Returns the bracket name that best matches the deck's power level and cards.
        """
        # Count relevant characteristics
        game_changer_count = sum(1 for card in cards if card.is_game_changer)
        combo_pairs = [
            ("Demonic Consultation", "Thassa's Oracle"),
            ("Tainted Pact", "Thassa's Oracle"),
            ("Tainted Pact", "Laboratory Maniac"),
            ("Demonic Consultation", "Laboratory Maniac"),
            ("Exquisite Blood", "Sanguine Bond"),
            ("Dramatic Reversal", "Isochron Scepter"),
            ("Dualcaster Mage", "Twinflame"),
            ("Heliod, Sun-Crowned", "Walking Ballista")
        ]
        card_names = {card.name for card in cards}
        combo_count = sum(1 for card1, card2 in combo_pairs if card1 in card_names and card2 in card_names)
        mass_land_count = sum(1 for card in cards if "mass_land_denial" in card.bracket_categories)
        
        # Sophisticated cEDH detection based on deck characteristics
        cedh_score = self._calculate_cedh_score(cards, combo_count, game_changer_count, mass_land_count)
        
        # CRITICAL: Mass Land Denial immediately pushes to Bracket 4 (Optimized)
        if mass_land_count > 0:
            return "optimized"
        
        # cEDH: High cedh_score OR extreme combo/game changer density  
        if cedh_score >= 25 or (combo_count >= 2 and game_changer_count >= 4):
            return "cedh"
        
        # Optimized: Combos OR many game changers (4+) [Mass land denial already handled above]
        elif combo_count >= 1 or game_changer_count >= 4:
            return "optimized"
        
        # Upgraded: Moderate game changers (1-3)
        elif 1 <= game_changer_count <= 3:
            return "upgraded"
        
        # Core: No game changers, no mass land denial
        elif game_changer_count == 0:
            return "core"
        
        # Default to exhibition if unsure
        else:
            return "exhibition"

    def _calculate_cedh_score(self, cards: List[DeckCard], combo_count: int, game_changer_count: int, mass_land_count: int) -> int:
        """
        Calculate cEDH score based on multiple sophisticated criteria.
        Higher scores indicate more likely cEDH deck.
        """
        score = 0
        
        # Fast mana concentration (cEDH decks run almost all of them)
        fast_mana_cards = {
            "Sol Ring", "Mana Crypt", "Mana Vault", "Chrome Mox", "Mox Diamond", 
            "Mox Opal", "Lotus Petal", "Dark Ritual", "Cabal Ritual", "Ancient Tomb", 
            "Mishra's Workshop", "Grim Monolith"
        }
        fast_mana_count = sum(1 for card in cards if card.name in fast_mana_cards and card.is_game_changer)
        score += fast_mana_count * 2  # Fast mana is very important in cEDH
        
        # Premium tutors (not thematic tutors) - much stricter scoring
        premium_tutors = {
            "Demonic Tutor", "Vampiric Tutor", "Imperial Seal", "Grim Tutor",
            "Mystical Tutor", "Worldly Tutor", "Enlightened Tutor",
            "Beseech the Mirror"
        }
        premium_tutor_count = sum(1 for card in cards if card.name in premium_tutors and card.is_game_changer)
        score += premium_tutor_count * 3  # Premium tutors are crucial
        
        # Premium stack interaction
        premium_interaction = {
            "Force of Will", "Force of Negation", "Mana Drain", "Counterspell",
            "Spell Pierce", "Misdirection", "Pact of Negation"
        }
        interaction_count = sum(1 for card in cards if card.name in premium_interaction and card.is_game_changer)
        score += interaction_count * 2  # Stack interaction is vital
        
        # Best combo pieces (cEDH priority)
        best_combo_pieces = {
            "Thassa's Oracle", "Demonic Consultation", "Tainted Pact", 
            "Exquisite Blood", "Sanguine Bond"
        }
        combo_piece_count = sum(1 for card in cards if card.name in best_combo_pieces and card.is_game_changer)
        score += combo_piece_count * 2
        
        # Premium value engines
        premium_engines = {
            "Necropotence", "Ad Nauseam", "Underworld Breach", "Yawgmoth's Will",
            "Timetwister", "Wheel of Fortune"
        }
        engine_count = sum(1 for card in cards if card.name in premium_engines and card.is_game_changer)
        score += engine_count
        
        # More conservative bonuses - require true cEDH concentrations
        if fast_mana_count >= 5:
            score += 3  # cEDH typically runs 5-7 fast mana sources
        if premium_tutor_count >= 3:
            score += 4  # cEDH runs 3-5+ tutors
        if interaction_count >= 3:
            score += 3  # cEDH has lots of interaction
        
        # Stronger penalty for casual elements
        if mass_land_count > 0:
            score -= 3  # cEDH typically avoids mass land denial
        
        # Minimum requirements for cEDH classification
        total_critical_elements = fast_mana_count + premium_tutor_count + interaction_count + combo_piece_count
        if total_critical_elements < 8:  # Need at least 8 critical cEDH elements
            score = min(score, 15)  # Cap score if missing critical elements
        
        return score

    async def _validate_bracket(self, cards: List[DeckCard], target_bracket: str, bracket_inferred: bool = False) -> BracketValidation:
        """Validate deck against bracket requirements"""
        if target_bracket not in COMMANDER_BRACKETS:
            return BracketValidation(
                target_bracket=target_bracket,
                overall_compliance=False,
                bracket_score=1,
                violations=[f"Invalid bracket: {target_bracket}"],
                recommendations=[f"Valid brackets: {', '.join(COMMANDER_BRACKETS.keys())}"]
            )
        
        # Load authoritative data to get combo pairs
        data = await self._load_authoritative_data()
        combo_pairs = data.get("early_game_combo_pairs", [])
        
        bracket_info = COMMANDER_BRACKETS[target_bracket]
        violations = []
        recommendations = []
        score_factors = []
        
        # Check game changers
        game_changer_count = sum(1 for card in cards if card.is_game_changer)
        if target_bracket in ["exhibition", "core"] and game_changer_count > 0:
            violations.append(f"Game changers found in {target_bracket} bracket")
            recommendations.append("Consider moving to higher bracket or removing game changers")
        elif target_bracket == "cedh" and game_changer_count == 0:
            recommendations.append("Consider adding game changers for cEDH")
        
        # Check for mass land denial
        mass_land_count = sum(1 for card in cards if "mass_land_denial" in card.bracket_categories)
        if target_bracket == "exhibition" and mass_land_count > 2:
            violations.append("Too many mass land denial effects for Exhibition")
        
        # Check for 2-card combos
        detected_combos = self._detect_combos(cards, combo_pairs)
        combo_count = len(detected_combos)
        
        # Brackets 1, 2, 3 (exhibition, core, upgraded) should have ZERO combos
        if target_bracket in ["exhibition", "core", "upgraded"] and combo_count > 0:
            combo_list = ", ".join([f"{c1} + {c2}" for c1, c2 in detected_combos])
            violations.append(f"Early-game 2-card combos detected in {target_bracket} bracket: {combo_list}")
            recommendations.append(f"Deck contains {combo_count} 2-card combo(s) - should be upgraded to at least Bracket 4 (Optimized)")
        elif target_bracket in ["optimized", "cedh"] and combo_count > 0:
            # Combos are expected/allowed in these brackets
            recommendations.append(f"Deck contains {combo_count} 2-card combo(s) - appropriate for {target_bracket}")
        
        # Check for tutors (no restrictions on tutor count per user request)
        tutor_count = sum(1 for card in cards if "tutor" in card.bracket_categories)
        # Removed tutor count restrictions - user indicated they don't care about "overpowered tutors"
        
        # Calculate bracket score (1-5)
        compliance_score = 5
        if violations:
            compliance_score = max(1, 5 - len(violations))
        
        # Add recommendations based on analysis
        if target_bracket == "exhibition" and mass_land_count > 0:
            recommendations.append("Consider thematic alternatives to mass land denial")
        
        if tutor_count == 0 and target_bracket in ["upgraded", "optimized"]:
            recommendations.append("Consider adding tutors for better consistency")
        
        return BracketValidation(
            target_bracket=target_bracket,
            overall_compliance=len(violations) == 0,
            bracket_score=compliance_score,
            compliance_details={
                "game_changers": game_changer_count,
                "mass_land_denial": mass_land_count,
                "early_game_combos": combo_count,
                "detected_combos": [f"{c1} + {c2}" for c1, c2 in detected_combos],
                "tutors": tutor_count,
                "total_cards": len(cards),
                "bracket_inferred": bracket_inferred
            },
            violations=violations,
            recommendations=recommendations
        )
    
    def _check_duplicates(self, cards: List[DeckCard]) -> bool:
        """Check for duplicate cards"""
        seen = set()
        for card in cards:
            if card.name in seen:
                return True
            seen.add(card.name)
        return False

    def _calculate_salt_score(self, cards: List[DeckCard], data: Dict[str, Dict[str, float]]) -> float:
        """
        Calculate salt score for a deck based on saltiest cards.
        Returns a score from 0-5 where higher means saltier.
        """
        if not cards:
            return 0.0
        
        salt_cards = data.get("salt_cards", {})
        total_salt = 0.0
        card_count = 0
        
        for card in cards:
            # Normalize card name for lookup
            card_name = card.name.strip()
            salt_score = salt_cards.get(card_name, 0.0)
            
            # Weight by quantity if present
            weighted_salt = salt_score * card.quantity
            total_salt += weighted_salt
            card_count += 1
        
        # Calculate average salt per card, then scale to 0-5
        avg_salt_per_card = total_salt / max(card_count, 1)
        
        # Salt scores are already in reasonable range, scale appropriately
        # Most cards are 1.5-3.0 range, so we'll normalize to 0-5
        normalized_score = min(5.0, avg_salt_per_card * 1.5)
        
        return round(normalized_score, 2)

    async def _get_commander_salt_score(self, commander_name: str) -> float:
        """
        Get salt score for a commander from EDHRec.
        Returns 0.0 if not found.
        """
        if not commander_name:
            return 0.0
        
        try:
            # Normalize commander name for URL
            commander_normalized = commander_name.lower().replace(" ", "-").replace(",", "").replace("'", "")
            url = f"https://edhrec.com/commanders/{commander_normalized}"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                if response.status_code != 200:
                    return 0.0
                
                # Parse the response for salt score
                # This would need to be implemented based on the actual page structure
                # For now, return a default based on some known high-salt commanders
                high_salt_commanders = {
                    "tergrid-god-of-fright": 2.8,
                    "yuriko-the-tigers-shadow": 2.15,
                    "vorinclex-voice-of-hunger": 2.61,
                    "kinnan-bonder-prodigy": 2.15,
                    "jin-gitaxias-core-augur": 2.57,
                    "edgar-markov": 2.05,
                    "sheoldred-the-apocalypse": 2.03,
                    "atraxa-praetors-voice": 1.72
                }
                
                return high_salt_commanders.get(commander_normalized, 1.0)  # Default 1.0 if not found
                
        except Exception as e:
            logger.warning(f"Failed to fetch commander salt score for {commander_name}: {e}")
            return 0.0

    def _get_salt_level_description(self, score: float) -> str:
        """Get a description of the salt level based on score."""
        if score >= 4.0:
            return "Extremely Salty"
        elif score >= 3.0:
            return "Very Salty"
        elif score >= 2.0:
            return "Moderately Salty"
        elif score >= 1.0:
            return "Slightly Salty"
        else:
            return "Casual"


# Create global validator instance
deck_validator = DeckValidator()


# --------------------------------------------------------------------
# Deck Validation API Endpoints
# --------------------------------------------------------------------

@app.post("/api/v1/deck/validate", response_model=DeckValidationResponse)
async def validate_deck(
    request: DeckValidationRequest,
    api_key: str = Depends(verify_api_key)
) -> DeckValidationResponse:
    """
    Validate a deck against Commander Brackets rules and format legality.
    
    - Provide a decklist of card names
    - Optionally specify commander and target bracket
    - Validates against official Commander Brackets system
    - Checks for Game Changers, format legality, and power level compliance
    """
    try:
        result = await deck_validator.validate_deck(request)
        
        # Cache the result for 1 hour using the validator's cache
        cache_key = f"deck_validation_{hash(str(request.decklist))}"
        deck_validator.cache[cache_key] = result
        
        return result
        
    except Exception as exc:
        logger.error(f"Error in deck validation: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate deck: {str(exc)}"
        )


@app.get("/api/v1/deck/validate/sample")
async def get_sample_validation(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get sample deck validation to demonstrate the endpoint functionality.
    """
    sample_deck = DeckValidationRequest(
        decklist=[
            "1x Sol Ring",
            "4x Lightning Bolt",
            "2x Counterspell",
            "1x Demonic Consultation",
            "1x Thassa's Oracle",
            "1x Swords to Plowshares",
            "1x Ponder",
            "1x Brainstorm",
            "1x Vampiric Tutor",
            "97x Island"
        ],
        commander="Jace, Wielder of Mysteries",
        target_bracket="upgraded",
        validate_bracket=True,
        validate_legality=True
    )
    
    result = await deck_validator.validate_deck(sample_deck)
    result.warnings.append("This is a sample validation for demonstration purposes")
    
    return {
        "sample_request": sample_deck.dict(),
        "validation_result": result.dict(),
        "note": "This demonstrates the validation endpoint with a sample deck"
    }


@app.get("/api/v1/brackets/info")
async def get_brackets_info(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get comprehensive information about Commander Brackets system.
    
    Returns official bracket definitions, expectations, and restrictions
    based on Wizards of the Coast's October 21, 2025 update.
    """
    return {
        "brackets": COMMANDER_BRACKETS,
        "game_changers": {
            "current_list_size": len(GAME_CHANGERS["current_list"]),
            "recent_removals": GAME_CHANGERS["removed_2025"],
            "total_removed_2025": len(GAME_CHANGERS["removed_2025"])
        },
        "validation_categories": {
            "mass_land_denial": {
                "description": "Cards that destroy, exile, or bounce multiple lands",
                "sample_cards": MASS_LAND_DENIAL[:10]
            },
            "early_game_combos": {
                "description": "2-card combinations that can win early",
                "combos": EARLY_GAME_COMBOS
            }
        },
        "last_updated": "2025-10-21",
        "source": "https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-october-21-2025"
    }


@app.get("/api/v1/brackets/game-changers/list")
async def get_game_changers_list(
    api_key: str = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the complete list of Game Changers cards.
    
    Based on the October 21, 2025 update from Wizards of the Coast.
    """
    return {
        "current_game_changers": GAME_CHANGERS["current_list"],
        "recently_removed": GAME_CHANGERS["removed_2025"],
        "removal_reasoning": {
            "high_mana_value": "Expropriate, Jin-Gitaxias, Sway of the Stars, Vorinclex",
            "legends_strongest_as_commanders": "Kinnan, Urza, Winota, Yuriko",
            "other": "Deflecting Swat, Food Chain"
        },
        "last_updated": "2025-10-21"
    }


# --------------------------------------------------------------------
# Exception Handlers
# --------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with proper error format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
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
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
        log_level=settings.log_level.lower(),
    )
