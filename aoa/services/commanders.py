"""Utilities for scraping commander data from EDHRec."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException

from aoa.constants import EDHREC_BASE_URL

logger = logging.getLogger(__name__)


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
    """Scrape commander data from EDHRec and return structured data."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/91.0.4472.124 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(commander_url, headers=headers)
            response.raise_for_status()

        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")
        build_id = extract_build_id_from_html(html_content)
        if not build_id:
            raise HTTPException(status_code=404, detail="Could not find build ID in page")

        commander_name = extract_commander_name_from_url(commander_url)
        
        # Enhanced extraction with multiple fallbacks
        json_data = {}
        
        # Primary extraction method
        try:
            json_data = extract_commander_json_data(soup, build_id)
            # Check if we got meaningful data
            if not json_data.get("categories"):
                raise ValueError("No categories found in primary extraction")
        except Exception as primary_error:
            logger.warning(f"Primary extraction failed: {primary_error}, trying fallback methods")
            
            # Fallback: extract sections directly from the JSON payload
            try:
                next_data_script = soup.find("script", {"id": "__NEXT_DATA__", "type": "application/json"})
                if next_data_script and next_data_script.string:
                    data = json.loads(next_data_script.string)
                    sections = extract_commander_sections_from_json(data)
                    
                    # Convert sections format to the expected format
                    categories = {}
                    for section_name, card_names in sections.items():
                        if card_names:
                            categories[section_name] = {"cards": [{"name": name} for name in card_names]}
                    
                    json_data = {
                        "commander_tags": [],
                        "top_10_tags": [],
                        "all_tags": [],
                        "combos": [],
                        "similar_commanders": [],
                        "categories": categories
                    }
                else:
                    raise ValueError("No __NEXT_DATA__ script found")
            except Exception as fallback_error:
                logger.warning(f"Fallback extraction failed: {fallback_error}")
                # If all extraction methods fail, return empty data
                json_data = {
                    "commander_tags": [],
                    "top_10_tags": [],
                    "all_tags": [],
                    "combos": [],
                    "similar_commanders": [],
                    "categories": {}
                }
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
    except httpx.RequestError as exc:
        logger.error("Error fetching commander page %s: %s", commander_url, exc)
        raise HTTPException(status_code=500, detail=f"Error fetching commander data: {exc}")
    except Exception as exc:
        logger.error("Error processing commander page %s: %s", commander_url, exc)
        raise HTTPException(status_code=500, detail=f"Error processing commander data: {exc}")


def extract_commander_json_data(soup: BeautifulSoup, build_id: str) -> Dict[str, Any]:
    """Extract commander data from page JSON using the Next.js structure."""
    try:
        next_data_script = soup.find("script", {"id": "__NEXT_DATA__", "type": "application/json"})
        if next_data_script and next_data_script.string:
            data = json.loads(next_data_script.string)
            page_data = data.get("props", {}).get("pageProps", {}).get("data", {})
            panels = page_data.get("panels", {})

            all_tags: List[Dict[str, Any]] = []
            taglinks = panels.get("taglinks", [])
            if isinstance(taglinks, list):
                sorted_tags = sorted(taglinks, key=lambda x: x.get("count", 0), reverse=True)
                for entry in sorted_tags:
                    tag = entry.get("tag") or entry.get("label")
                    count = entry.get("count", 0)
                    if tag and isinstance(count, int):
                        all_tags.append({"tag": tag, "count": count, "url": entry.get("url")})

            top_10_tags = all_tags[:10]

            commander_tags = normalize_commander_tags([tag.get("tag", "") for tag in all_tags])

            combos = []
            combos_data = panels.get("combos", [])
            for combo_entry in combos_data:
                combo_name = combo_entry.get("name") or combo_entry.get("title")
                if combo_name:
                    combos.append(
                        {
                            "name": combo_name,
                            "url": combo_entry.get("url") or combo_entry.get("href"),
                            "cards": _gather_section_card_names(combo_entry.get("cards", [])),
                        }
                    )

            similar_commanders = []
            similar_data = panels.get("similarCommanders", [])
            for entry in similar_data:
                if entry.get("name"):
                    similar_commanders.append(
                        {
                            "name": entry.get("name"),
                            "url": entry.get("url"),
                            "similarity": entry.get("similarity", 0.0),
                        }
                    )

            # Updated extraction logic based on successful web extractions
            categories = {}
            
            # PRIMARY: Look for card_lists structure (from successful extraction analysis)
            card_lists = page_data.get("card_lists", {})
            if card_lists:
                logger.info(f"Found card_lists with sections: {list(card_lists.keys())}")
                for section_name, cards in card_lists.items():
                    if isinstance(cards, list):
                        normalized_cards = []
                        for card in cards:
                            if isinstance(card, dict) and card.get("name"):
                                normalized_cards.append({
                                    "name": card.get("name"),
                                    "inclusion_percentage": card.get("inclusion_percentage"),
                                    "decks_with_card": card.get("decks_with_card"),
                                    "total_decks_considered": card.get("total_decks_considered"),
                                    "synergy_percentage": card.get("synergy_percentage"),
                                    "num_decks": card.get("num_decks") or card.get("decks_in"),
                                    "sanitized_name": card.get("sanitized_name"),
                                    "card_url": card.get("card_url"),
                                })
                        if normalized_cards:
                            categories[section_name] = {"cards": normalized_cards}
                            logger.info(f"Extracted {len(normalized_cards)} cards from {section_name}")
            
            # FALLBACK: Try original panels structure if card_lists is empty
            if not categories:
                json_card_lists = panels.get("jsonCardLists", [])
                for panel in json_card_lists:
                    if isinstance(panel, dict):
                        header = panel.get("header") or panel.get("label")
                        cards = panel.get("cards") or panel.get("cardviews", [])
                        if header and isinstance(cards, list):
                            normalized_cards = []
                            for card in cards:
                                if isinstance(card, dict) and card.get("name"):
                                    normalized_cards.append({
                                        "name": card.get("name"),
                                        "inclusion_percentage": card.get("inclusion_percentage"),
                                        "decks_with_card": card.get("decks_with_card"),
                                        "total_decks_considered": card.get("total_decks_considered"),
                                        "synergy_percentage": card.get("synergy_percentage"),
                                        "num_decks": card.get("num_decks"),
                                        "sanitized_name": card.get("sanitized_name"),
                                        "card_url": card.get("card_url"),
                                    })
                            if normalized_cards:
                                categories[header] = {"cards": normalized_cards}
                                logger.info(f"Fallback: Extracted {len(normalized_cards)} cards from {header}")

            logger.info(f"Successfully extracted {len(categories)} categories with card data")
            return {
                "commander_tags": commander_tags,
                "top_10_tags": top_10_tags,
                "all_tags": all_tags,
                "combos": combos,
                "similar_commanders": similar_commanders,
                "categories": categories,
            }
    except Exception as exc:
        logger.error("Failed to parse commander JSON data: %s", exc)
    return {"commander_tags": [], "categories": {}}


def extract_commander_tags_from_json(payload: Dict[str, Any]) -> List[str]:
    """Extract commander tags from EDHRec JSON payloads."""
    data = payload.get("pageProps", {}).get("data", {})
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
    data = payload.get("pageProps", {}).get("data", {})
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
