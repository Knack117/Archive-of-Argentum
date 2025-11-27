"""EDHREC commander utilities - sophisticated Next.js data extraction."""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Build ID regex pattern for Next.js pages
BUILD_ID_RX = re.compile(r'"buildId"\s*:\s*"([^"]+)"')

# Next.js data extraction regex
NEXT_DATA_RX = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)


def extract_build_id_from_html(html: str) -> Optional[str]:
    """Extract build ID from Next.js EDHREC HTML pages."""
    match = BUILD_ID_RX.search(html)
    if match:
        return match.group(1)
    return None


def extract_nextjs_payload(html: str, url: str) -> Optional[Dict[str, Any]]:
    """Extract __NEXT_DATA__ JSON payload from HTML pages."""
    match = NEXT_DATA_RX.search(html)
    if not match:
        return None
    
    try:
        json_str = match.group(1)
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning(f"Failed to parse JSON from {url}: {exc}")
        return None


def extract_commander_tags_from_html(html: str) -> List[str]:
    """Extract commander tags from EDHREC HTML content."""
    tags = []
    
    # Look for meta tags
    meta_tag_pattern = r'<meta[^>]*name=["\']tags?["\'][^>]*content=["\']([^"\']+)["\']'
    matches = re.findall(meta_tag_pattern, html, re.IGNORECASE)
    for match in matches:
        tag_list = [tag.strip() for tag in match.split(',')]
        tags.extend(tag_list)
    
    # Look for data attributes
    data_pattern = r'data-tags?=["\']([^"\']+)["\']'
    matches = re.findall(data_pattern, html, re.IGNORECASE)
    for match in matches:
        tag_list = [tag.strip() for tag in match.split(',')]
        tags.extend(tag_list)
    
    # Look for tag-related divs
    tag_div_pattern = r'<div[^>]*class="[^"]*tag[^"]*"[^>]*>([^<]+)</div>'
    matches = re.findall(tag_div_pattern, html, re.IGNORECASE)
    for match in matches:
        if match.strip():
            tags.append(match.strip())
    
    # NEW: Look for NavigationPanel tags (specific EDHRec structure)
    # These are in <div class="NavigationPanel_tags__*">
    # with tag names in <span class="NavigationPanel_label__*">
    navpanel_pattern = r'<div[^>]*class="[^"]*NavigationPanel_tags[^"]*"[^>]*>.*?</div>'
    navpanel_matches = re.findall(navpanel_pattern, html, re.DOTALL)
    
    for navpanel in navpanel_matches:
        # Extract all NavigationPanel_label spans
        label_pattern = r'<span[^>]*class="[^"]*NavigationPanel_label[^"]*"[^>]*>([^<]+)</span>'
        label_matches = re.findall(label_pattern, navpanel)
        for label in label_matches:
            if label.strip():
                tags.append(label.strip())
    
    return _normalize_tags(tags)


def extract_commander_tags_from_json(payload: Optional[Dict[str, Any]]) -> List[str]:
    """Extract commander tags from Next.js JSON payload."""
    if not payload:
        return []
    
    tags = []
    
    # Look for tags in common locations
    tag_sources = [
        payload.get("tags"),
        payload.get("taggings"),
        payload.get("tagitems"),
        payload.get("chips"),
        payload.get("topics"),
        payload.get("themes"),
        payload.get("archetypes"),
    ]
    
    # Check pageProps if present
    page_props = payload.get("pageProps")
    if isinstance(page_props, dict):
        tag_sources.extend([
            page_props.get("tags"),
            page_props.get("taggings"),
            page_props.get("tagitems"),
            page_props.get("chips"),
            page_props.get("topics"),
            page_props.get("themes"),
            page_props.get("archetypes"),
        ])
    
    for source in tag_sources:
        if isinstance(source, list):
            for item in source:
                if isinstance(item, str):
                    tags.append(item)
                elif isinstance(item, dict):
                    # Look for name/title fields
                    for field in ["name", "title", "tag", "label"]:
                        value = item.get(field)
                        if isinstance(value, str):
                            tags.append(value)
                            break
    
    return _normalize_tags(tags)


def normalize_commander_tags(tags: List[str]) -> List[str]:
    """Normalize and deduplicate commander tags."""
    return _normalize_tags(tags)


def _normalize_tags(tags: List[str]) -> List[str]:
    """Normalize tags: lowercase, strip whitespace, remove duplicates."""
    normalized_tags = []
    seen = set()
    
    for tag in tags:
        if isinstance(tag, str):
            normalized = tag.strip().lower()
            if normalized and normalized not in seen:
                normalized_tags.append(normalized)
                seen.add(normalized)
    
    return normalized_tags


def _camel_or_snake_to_title(value: str) -> str:
    """Convert camelCase or snake_case to Title Case for headers."""
    if not value:
        return ""
    
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    
    # Header aliases for common EDHREC sections
    header_aliases = {
        "signaturecards": "Signature Cards",
        "popularcards": "Top Cards",
        "topcards": "Top Cards",
        "highsynergycards": "High Synergy Cards",
        "synergycards": "High Synergy Cards",
        "newcards": "New Cards",
        "newcommanders": "New Commanders",
        "topcommanders": "Top Commanders",
        "toppartners": "Top Partners",
        "combocards": "Combo Cards",
        "combos": "Combos",
        "cardviews": "Cardviews",
        "cards": "Cards",
        "creatures": "Creatures",
        "instants": "Instants",
        "sorceries": "Sorceries",
        "artifacts": "Artifacts",
        "enchantments": "Enchantments",
        "planeswalkers": "Planeswalkers",
        "lands": "Lands",
    }
    
    if normalized in header_aliases:
        return header_aliases[normalized]
    
    # Convert case patterns
    spaced = re.sub(r"[_-]+", " ", value)
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", spaced)
    spaced = re.sub(r"(?i)(cards)$", " Cards", spaced)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    
    return spaced.title() if spaced else "Cards"


def _order_commander_headers(keys: List[str]) -> List[str]:
    """Order commander headers by preference."""
    preferred = [
        "Signature Cards",
        "High Synergy Cards",
        "Top Cards",
        "New Cards",
        "Top Partners",
        "Top Commanders",
        "New Commanders",
        "Combo Cards",
        "Combos",
        "Creatures",
        "Instants",
        "Sorceries",
        "Artifacts",
        "Enchantments",
        "Planeswalkers",
        "Lands",
    ]
    
    ordered = []
    seen = set()
    
    # Add preferred headers first
    for name in preferred:
        if name in keys and name not in seen:
            ordered.append(name)
            seen.add(name)
    
    # Add remaining headers
    for key in keys:
        if key not in seen:
            ordered.append(key)
            seen.add(key)
    
    return ordered
