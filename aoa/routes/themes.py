"""Theme and tag scraping routes."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException

from aoa.constants import COLOR_SLUG_MAP, EDHREC_BASE_URL, SORTED_COLOR_IDENTIFIERS
from aoa.models import PageTheme, ThemeCollection, ThemeItem, ThemeContainer
from aoa.security import verify_api_key

router = APIRouter(prefix="/api/v1", tags=["themes"])
logger = logging.getLogger(__name__)


def _split_theme_slug(theme_slug: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Split a theme slug into base theme and color identifier."""
    sanitized = (theme_slug or "").strip().lower()
    if not sanitized:
        return None, None, None

    for identifier in SORTED_COLOR_IDENTIFIERS:
        prefix = f"{identifier}-"
        if sanitized.startswith(prefix):
            remainder = sanitized[len(prefix) :]
            if remainder:
                return remainder, identifier, "prefix"

    for identifier in SORTED_COLOR_IDENTIFIERS:
        suffix = f"-{identifier}"
        if sanitized.endswith(suffix):
            remainder = sanitized[: -len(suffix)]
            if remainder:
                return remainder, identifier, "suffix"

    return sanitized, None, None


def _split_color_prefixed_theme_slug(theme_slug: str) -> Tuple[Optional[str], Optional[str]]:
    """Split slugs formatted as 'color-theme' into their components."""
    if not theme_slug or "-" not in theme_slug:
        return None, None
    parts = theme_slug.split("-", 1)
    if len(parts) == 2 and parts[0] in COLOR_SLUG_MAP:
        return parts[0], parts[1]
    return None, None


def _build_theme_route_candidates(
    theme_slug: str,
    theme_name: Optional[str] = None,
    color_identity: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build possible EDHRec route candidates for a theme."""
    candidates: List[Dict[str, str]] = []
    sanitized = (theme_slug or "").strip().lower()
    derived_theme, derived_color, _ = _split_theme_slug(sanitized)

    base_theme = (theme_name or derived_theme or sanitized or "").strip("-")
    color_value = color_identity or derived_color

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

    color_variants: Set[str] = set()
    if normalized_color in ["white", "blue", "black", "red", "green"]:
        color_variants.add(normalized_color)
        color_variants.add(f"mono-{normalized_color}")
    elif normalized_color:
        color_variants.add(normalized_color)

    slug_variants: List[str] = []
    seen_slugs: Set[str] = set()

    def add_slug(slug: Optional[str]) -> None:
        value = (slug or "").strip().strip("/")
        if not value or value in seen_slugs:
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

    if color_value and base_theme:
        for color_variant in color_variants:
            add_candidate(f"tags/{base_theme}/{color_variant}")
            add_candidate(f"tags/{color_variant}/{base_theme}")

    for slug in slug_variants:
        add_candidate(f"tags/{slug}")
        add_candidate(f"themes/{slug}")

    return candidates


def _resolve_theme_card_limit(limit: Optional[Union[str, int]]) -> int:
    """Resolve and validate theme card limit values."""
    if limit is None:
        return 60
    try:
        limit_int = int(limit)
        if limit_int == 0:
            return 0
        if limit_int < 0:
            return 60
        return min(limit_int, 200)
    except (ValueError, TypeError):
        return 60


def _generate_card_limit_plan(max_cards: int) -> List[int]:
    """Generate a descending list of card limits to progressively trim sections."""
    if max_cards <= 0:
        return [0]

    plan: List[int] = []
    current = int(max_cards)
    while current > 1:
        plan.append(current)
        next_value = max(current // 2, current - 10)
        if next_value == current:
            next_value -= 1
        current = max(next_value, 1)
        if current == 1:
            break
    if plan[-1] != 1:
        plan.append(1)
    return plan


def _estimate_response_size(response: Dict[str, Any]) -> int:
    """Estimate payload size by counting cards in each category."""
    categories = response.get("categories", {})
    size = 0
    for data in categories.values():
        cards = data.get("cards") or []
        size += len(cards) * 10
        size += data.get("total_cards", len(cards))
    return size + len(categories) * 5


def _create_categories_summary(sections: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Summarize section metadata for API responses."""
    summary: Dict[str, Dict[str, Any]] = {}
    for key, data in sections.items():
        summary[key] = {
            "category_name": data.get("category_name", key.title()),
            "total_cards": data.get("total_cards", len(data.get("cards", []))),
            "available_cards": data.get("available_cards", len(data.get("cards", []))),
            "is_truncated": data.get("is_truncated", False),
        }
    return summary


def extract_theme_sections_from_json(
    payload: Dict[str, Any], max_cards_per_category: int = 60
) -> Tuple[Dict[str, Any], bool]:
    """Extract theme sections from EDHRec JSON payloads."""
    sections: Dict[str, Any] = {}
    summary_flag = False

    data = payload.get("pageProps", {}).get("data", {})
    container = data.get("container", {})
    json_dict = container.get("json_dict", {})
    cardlists = json_dict.get("cardlists", [])

    for cardlist in cardlists:
        header = (cardlist.get("header") or "").lower()
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
    """Normalize color descriptors into code, slug, and symbol metadata."""
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
        elif color_lower in {"ug", "blue-green"}:
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
    """Parse theme slugs from HTML content."""
    soup = BeautifulSoup(html, "html.parser")
    slugs: Set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/tags/" not in href:
            continue
        if href.startswith("http"):
            slug_part = href.split("/tags/")[-1]
        else:
            slug_part = href.split("/tags/")[-1]
        slug = slug_part.split("?")[0].split("#")[0]
        if not slug or not re.match(r"^[a-zA-Z0-9-]+$", slug):
            continue

        normalized = slug.lower()
        if normalized in COLOR_SLUG_MAP:
            continue

        if "-" not in slug:
            slugs.add(slug)
    return slugs


def _validate_theme_slug_against_catalog(theme_slug: str, catalog: Set[str]) -> None:
    """Ensure requested theme slug (or its base theme) exists in cached catalog."""
    if not catalog:
        raise HTTPException(status_code=404, detail="Theme catalog is empty")

    sanitized = (theme_slug or "").strip().lower()
    if not sanitized:
        raise HTTPException(status_code=400, detail="Theme slug cannot be empty")

    base_theme, _, _ = _split_theme_slug(sanitized)
    resolved_slug = base_theme or sanitized

    if resolved_slug in catalog or sanitized in catalog:
        return

    sample = ", ".join(sorted(catalog)[:5])
    raise HTTPException(
        status_code=404,
        detail=f"Theme '{resolved_slug}' not found in catalog. Example themes: {sample}",
    )


async def fetch_theme_tag(theme_slug: str, color_identity: Optional[str] = None) -> PageTheme:
    """Fetch theme data from EDHRec."""
    sanitized_slug = (theme_slug or "").strip().lower()
    theme_name, derived_color, _ = _split_theme_slug(sanitized_slug)
    base_theme = theme_name or sanitized_slug
    effective_color = color_identity or derived_color

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    candidates = _build_theme_route_candidates(
        sanitized_slug,
        theme_name=base_theme,
        color_identity=effective_color,
    )

    last_error: Optional[Exception] = None

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
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
            next_data_script = soup.find("script", {"id": "__NEXT_DATA__", "type": "application/json"})

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
                                        card_name=card_data.get("cardname", card_data.get("name", "Unknown")),
                                        inclusion_percentage=card_data.get("popularity", "N/A"),
                                        synergy_percentage=card_data.get("synergy", "N/A"),
                                    )
                                )
                        if items:
                            collections.append(
                                ThemeCollection(
                                    header=list_header.title(),
                                    items=items,
                                )
                            )
                    if collections:
                        parsed_successfully = True
                except Exception as exc:
                    last_error = exc

            if parsed_successfully:
                return PageTheme(
                    header=header,
                    description=description,
                    tags=[base_theme],
                    container=ThemeContainer(collections=collections),
                    source_url=source_url,
                )

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


@router.get("/tags/available")
async def get_available_tags(api_key: str = Depends(verify_api_key)) -> Dict[str, Any]:
    """Fetch the complete list of available tags/themes from EDHRec."""
    tags_url = f"{EDHREC_BASE_URL}tags/themes"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(tags_url, headers=headers)
            response.raise_for_status()
            html_content = response.text
            soup = BeautifulSoup(html_content, "html.parser")

        theme_slugs: List[str] = []
        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if next_data_script and next_data_script.string:
            json_data = json.loads(next_data_script.string)
            page_props = json_data.get("props", {}).get("pageProps", {})
            container = page_props.get("data", {}).get("container", {})
            cardlists = container.get("json_dict", {}).get("cardlists", [])
            for cardlist in cardlists:
                if "cardviews" in cardlist:
                    for cardview in cardlist["cardviews"]:
                        url = cardview.get("url", "")
                        if url:
                            slug = url.replace("/tags/", "").strip("/")
                            if slug and re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug):
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
        logger.error("Error fetching themes page: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch themes from EDHRec: {exc}")
    except Exception as exc:
        logger.error("Error processing themes page: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error processing themes data: {exc}")


@router.get("/themes/{theme_slug}", response_model=PageTheme)
async def get_theme(theme_slug: str, api_key: str = Depends(verify_api_key)) -> PageTheme:
    """Fetch EDHRec theme or tag data."""
    sanitized = theme_slug.strip().lower()
    _, color_identifier, _ = _split_theme_slug(sanitized)
    if color_identifier:
        return await fetch_theme_tag(sanitized, color_identifier)
    return await fetch_theme_tag(sanitized, None)
