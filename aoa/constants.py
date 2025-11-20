"""Shared constants and regular expressions for the Archive of Argentum API."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Set

from cachetools import TTLCache

from config import settings

API_VERSION = "1.1.0"

EDHREC_BASE_URL = "https://edhrec.com/"
EDHREC_JSON_BASE_URL = "https://json.edhrec.com/pages/"
COMMANDERSPELLBOOK_BASE_URL = "https://backend.commanderspellbook.com/"
COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL = "https://commanderspellbook.com/search/?q="
EDHREC_ALLOWED_HOSTS = {"edhrec.com", "www.edhrec.com"}
THEME_INDEX_CACHE_TTL_SECONDS = 6 * 3600

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

SORTED_COLOR_IDENTIFIERS: List[str] = sorted(COLOR_SLUG_MAP.keys(), key=len, reverse=True)

SALT_LABEL_RE = re.compile(r"Salt\s*Score:\s*([0-9]+(?:\.[0-9]+)?)")
CARD_SET_SUFFIX_RE = re.compile(r"\s*\(([A-Z0-9]{2,5})\)\s*\d*$")
CARD_BRACKET_SUFFIX_RE = re.compile(r"\s*\[[A-Z0-9]{2,5}\]\s*(?:#?\d+)?$")
CARD_HASH_SUFFIX_RE = re.compile(r"\s+#\d+$")

cache = TTLCache(maxsize=500, ttl=settings.cache_ttl)
_theme_catalog_cache: Dict[str, Any] = {"timestamp": 0.0, "slugs": set()}
_theme_catalog_lock = asyncio.Lock()

__all__ = [
    "API_VERSION",
    "EDHREC_BASE_URL",
    "EDHREC_JSON_BASE_URL",
    "COMMANDERSPELLBOOK_BASE_URL",
    "COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL",
    "EDHREC_ALLOWED_HOSTS",
    "THEME_INDEX_CACHE_TTL_SECONDS",
    "COLOR_SLUG_MAP",
    "SORTED_COLOR_IDENTIFIERS",
    "SALT_LABEL_RE",
    "CARD_SET_SUFFIX_RE",
    "CARD_BRACKET_SUFFIX_RE",
    "CARD_HASH_SUFFIX_RE",
    "cache",
    "_theme_catalog_cache",
    "_theme_catalog_lock",
]
