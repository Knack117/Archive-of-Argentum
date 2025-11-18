"""Utilities for performing live commander data extraction from EDHRec."""
from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from aoa.constants import EDHREC_BASE_URL
from aoa.services.edhrec import fetch_edhrec_json

logger = logging.getLogger(__name__)


def _extract_page_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the commander data block regardless of how Next.js nests it."""

    if not isinstance(payload, dict):
        return {}

    queue: Deque[Any] = deque([payload])
    while queue:
        node = queue.popleft()
        if isinstance(node, dict):
            page_props = node.get("pageProps")
            if isinstance(page_props, dict):
                data_block = page_props.get("data")
                if isinstance(data_block, dict):
                    return data_block
            for value in node.values():
                if isinstance(value, (dict, list, tuple)):
                    queue.append(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                if isinstance(item, (dict, list, tuple)):
                    queue.append(item)
    return {}


def extract_build_id_from_html(html: str) -> Optional[str]:
    """Return the Next.js buildId from EDHREC commander HTML (if present)."""
    if not html:
        return None
    match = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
    if match:
        return match.group(1)
    return None


def normalize_commander_tags(values: List[str]) -> List[str]:
    """Clean and deduplicate commander tags while preserving order."""
    seen = set()
    result: List[str] = []

    for raw in values:
        cleaned = raw.strip() if isinstance(raw, str) else ""
        if not cleaned or len(cleaned) > 64 or not re.search(r"[A-Za-z]", cleaned):
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
        path = (parsed.path or "").split("?")[0].split("#")[0]
        if path.startswith("/"):
            path = path[1:]
        if path.startswith("commanders/"):
            slug = path.split("commanders/", 1)[1]
        else:
            slug = path.split("/")[-1]
        slug = slug.strip("/").replace("-", " ").replace("_", " ")
        return " ".join(word.capitalize() for word in slug.split()) or "unknown"
    except Exception:
        return "unknown"


def normalize_commander_name(name: str) -> str:
    """Normalize a commander name into an EDHRec slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "unknown"


def _clean_text(value: str) -> str:
    from html import unescape

    cleaned = unescape(value or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _gather_section_card_names(source: Any) -> List[str]:
    names: List[str] = []
    visited = set()

    def collect(node: Any) -> None:
        node_id = id(node)
        if node_id in visited:
            return
        visited.add(node_id)

        if isinstance(node, dict):
            name_value = None
            for key in ("name", "cardName", "label", "title"):
                raw = node.get(key)
                if isinstance(raw, str) and raw.strip():
                    name_value = _clean_text(raw)
                    break
            if name_value:
                names.append(name_value)
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


async def scrape_edhrec_commander_page(commander_url: str) -> Dict[str, Any]:
    """Fetch commander data from EDHRec's live JSON endpoints."""
    commander_name = extract_commander_name_from_url(commander_url)

    try:
        payload = await fetch_edhrec_json(commander_url)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error fetching commander JSON for %s: %s", commander_url, exc)
        raise HTTPException(status_code=500, detail="Failed to fetch commander data") from exc

    json_data = extract_commander_json_data(payload)

    return {
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

def extract_commander_json_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract commander data from the live EDHRec JSON payload."""
    page_data = _extract_page_data(payload)
    panels = page_data.get("panels", {})
    container = page_data.get("container", {})

    all_tags: List[Dict[str, Any]] = []
    taglinks = panels.get("taglinks", [])
    if isinstance(taglinks, list):
        sorted_tags = sorted(taglinks, key=lambda x: x.get("count", 0), reverse=True)
        for entry in sorted_tags:
            if not isinstance(entry, dict):
                continue
            tag = entry.get("tag") or entry.get("label") or entry.get("value")
            if not tag:
                continue
            all_tags.append(
                {
                    "tag": tag,
                    "count": entry.get("count", 0),
                    "url": entry.get("url") or entry.get("href"),
                }
            )

    commander_tags = normalize_commander_tags([tag.get("tag", "") for tag in all_tags])
    top_10_tags = all_tags[:10]

    combos: List[Dict[str, Any]] = []
    combos_data = panels.get("combocounts") or panels.get("combos", [])
    for combo_entry in combos_data or []:
        if not isinstance(combo_entry, dict):
            continue
        combo_name = (
            combo_entry.get("name")
            or combo_entry.get("title")
            or combo_entry.get("value")
        )
        if not combo_name:
            continue
        combos.append(
            {
                "name": combo_name,
                "url": combo_entry.get("url") or combo_entry.get("href"),
                "cards": _gather_section_card_names(combo_entry.get("cards", [])),
            }
        )

    similar_commanders: List[Dict[str, Any]] = []
    similar_data = page_data.get("similar") or panels.get("similarCommanders", [])
    for entry in similar_data or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        similar_commanders.append(
            {
                "name": name,
                "url": entry.get("url") or entry.get("href"),
                "similarity": entry.get("similarity"),
            }
        )

    cardlists_sources = [
        page_data.get("cardlists"),
        container.get("cardlists"),
        container.get("json_dict", {}).get("cardlists"),
        panels.get("jsonCardLists"),
    ]

    categories: Dict[str, Dict[str, Any]] = {}
    for candidate in cardlists_sources:
        if not candidate:
            continue
        for section in candidate:
            if not isinstance(section, dict):
                continue
            header = section.get("header") or section.get("label") or "cards"
            cards = section.get("cardviews") or section.get("cards") or []
            normalized_cards = []
            for card in cards:
                if not isinstance(card, dict):
                    continue
                card_name = card.get("name") or card.get("cardname")
                if not card_name:
                    continue
                normalized_cards.append(
                    {
                        "name": card_name,
                        "num_decks": card.get("num_decks") or card.get("decks_in"),
                        "potential_decks": card.get("potential_decks") or card.get("potential"),
                        "inclusion_percentage": card.get("inclusion_percentage")
                        or card.get("inclusion")
                        or card.get("popularity"),
                        "synergy_percentage": card.get("synergy_percentage")
                        or card.get("synergy"),
                        "sanitized_name": card.get("sanitized_name") or card.get("sanitized"),
                        "card_url": card.get("card_url") or card.get("url"),
                    }
                )
            if normalized_cards:
                categories[header] = {"cards": normalized_cards}
        if categories:
            break

    return {
        "commander_tags": commander_tags,
        "top_10_tags": top_10_tags,
        "all_tags": all_tags,
        "combos": combos,
        "similar_commanders": similar_commanders,
        "categories": categories,
    }

def extract_commander_tags_from_json(payload: Dict[str, Any]) -> List[str]:
    """Extract commander tags from EDHRec JSON payloads."""
    data = _extract_page_data(payload)
    panels = data.get("panels", {})
    taglinks = panels.get("taglinks", [])
    tags: List[str] = []
    for entry in taglinks:
        tag = (
            entry.get("tag")
            or entry.get("label")
            or entry.get("value")
            or entry.get("slug")
        )
        if tag:
            tags.append(tag)
    return tags


def extract_commander_sections_from_json(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    """Extract commander card sections from EDHRec JSON payloads."""
    data = _extract_page_data(payload)
    sections: Dict[str, List[str]] = {}

    cardlists = data.get("cardlists") or []
    if not cardlists:
        panels = data.get("panels", {})
        cardlists = panels.get("jsonCardLists", [])
    if not cardlists:
        container = data.get("container", {})
        json_dict = container.get("json_dict", {})
        cardlists = json_dict.get("cardlists", [])

    for cardlist in cardlists:
        header = cardlist.get("header") or cardlist.get("label") or "cards"
        cards = cardlist.get("cards") or cardlist.get("cardviews") or []
        sections[header] = _gather_section_card_names(cards)

    return sections


__all__ = [
    "extract_commander_name_from_url",
    "normalize_commander_name",
    "scrape_edhrec_commander_page",
    "extract_commander_tags_from_json",
    "extract_commander_sections_from_json",
]
