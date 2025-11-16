"""Commander Spellbook combo endpoints and helpers."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.constants import COMMANDERSPELLBOOK_BASE_URL, COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL
from aoa.models import ComboResult, ComboSearchResponse
from aoa.security import verify_api_key

router = APIRouter(prefix="/api/v1", tags=["combos"])
logger = logging.getLogger(__name__)


async def fetch_combo_details_from_page(combo_id: str) -> Dict[str, Any]:
    """Fetch a combo page and extract card names, results, and other metadata."""
    if not combo_id:
        return {}

    combo_url = f"https://commanderspellbook.com/combo/{combo_id}/"

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            resp = await client.get(combo_url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        next_data = soup.find("script", id="__NEXT_DATA__", type="application/json")
        if not next_data or not next_data.string:
            return {}

        data = json.loads(next_data.string)
        combo = data.get("props", {}).get("pageProps", {}).get("combo", {})

        cards: List[str] = []
        for use in combo.get("uses", []):
            card_name = use.get("card", {}).get("name")
            if card_name:
                cards.append(card_name)

        results: List[str] = []
        for prod in combo.get("produces", []):
            feature = prod.get("feature", {})
            feature_name = feature.get("name")
            if feature_name:
                results.append(feature_name)

        features = combo.get("features", [])
        if features and not results:
            for feature in features:
                feature_name = feature.get("name")
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
        logger.error("Error fetching combo page %s: %s", combo_id, exc)
    return {}


def parse_variant_to_combo_result(variant: Dict[str, Any]) -> Optional[ComboResult]:
    """Parse a single variant from the Commander Spellbook API."""
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
        popularity = variant.get("popularity") or variant.get("decksEdhrec")

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
    except Exception as exc:
        logger.error("Error parsing variant: %s", exc)
        return None


async def parse_combo_results_from_html(html_content: str) -> List[ComboResult]:
    """Parse combo data from the public Commander Spellbook search page."""
    combos: List[ComboResult] = []
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        combo_cards = soup.find_all("div", class_=re.compile(r"combo-card"))

        for combo_card in combo_cards:
            combo_data: Dict[str, Any] = {"cards": [], "results": []}
            card_name_elements = combo_card.find_all("h3", class_=re.compile(r"card-name"))
            for card_element in card_name_elements:
                name = card_element.get_text(strip=True)
                if name:
                    combo_data.setdefault("cards", []).append(name)

            detail_elements = combo_card.find_all("p")
            for detail in detail_elements:
                text = detail.get_text(strip=True)
                if text.startswith("Results in Combo:"):
                    results_text = text.replace("Results in Combo:", "").strip()
                    if results_text:
                        combo_data.setdefault("results", []).extend(
                            [result.strip() for result in results_text.split(",") if result.strip()]
                        )

            deck_count_element = combo_card.find("span", class_=re.compile(r"deck-count"))
            if deck_count_element:
                deck_count_text = deck_count_element.get_text(strip=True)
                match = re.search(r"(\d+)", deck_count_text)
                if match:
                    combo_data["deck_count"] = int(match.group(1))

            combo_link = combo_card.find("a", href=True)
            if combo_link:
                combo_data["url"] = combo_link["href"]

            parsed_combo = parse_combo_card(combo_data)
            if parsed_combo:
                combos.append(parsed_combo)

        if not combos:
            combos = extract_combos_from_text(soup.get_text("\n"))
    except Exception as exc:
        logger.error("Error parsing combo HTML: %s", exc)
    return combos


def parse_combo_card(card_data: Dict[str, Any]) -> Optional[ComboResult]:
    """Parse individual combo card data from JSON structure."""
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

        combo_url = card_data.get("url")
        combo_id = None
        if combo_url and combo_url.startswith("/combo/"):
            combo_id = combo_url.replace("/combo/", "").replace("/", "")

        return ComboResult(
            combo_id=combo_id,
            combo_name=" | ".join(cards_in_combo[:3]) if cards_in_combo else None,
            color_identity=color_identity,
            cards_in_combo=cards_in_combo,
            results_in_combo=results_in_combo if results_in_combo else ["Combo effect"],
            decks_edhrec=deck_count,
            variants=variants,
            combo_url=combo_url,
        )
    except Exception as exc:
        logger.warning("Error parsing combo card: %s", exc)
        return None


def extract_combos_from_text(text_content: str) -> List[ComboResult]:
    """Extract combo information from plain text when HTML parsing fails."""
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
                if not any(keyword in line.lower() for keyword in ["color", "decks", "results", "combo"]):
                    if 5 < len(line) < 50 and not line.isdigit():
                        current_combo.setdefault("cards", []).append(line)
                elif "results in combo:" in line.lower():
                    current_combo["results_in_combo"] = []
                continue

            if "combo_id" in current_combo and current_combo.get("results_in_combo") is not None:
                if line and not line.isdigit() and "decks" not in line.lower():
                    current_combo["results_in_combo"].append(line)

        if current_combo.get("cards") and current_combo.get("results_in_combo"):
            combo_result = create_combo_from_text_data(current_combo)
            if combo_result:
                combo_results.append(combo_result)
    except Exception as exc:
        logger.warning("Error extracting combos from text: %s", exc)
    return combo_results


def create_combo_from_text_data(combo_data: Dict[str, Any]) -> Optional[ComboResult]:
    """Create a ComboResult instance from parsed text data."""
    try:
        cards = combo_data.get("cards", [])
        results = combo_data.get("results_in_combo", [])
        if not cards or not results:
            return None
        return ComboResult(
            combo_id=combo_data.get("combo_id"),
            combo_name=" | ".join(cards[:3]) if len(cards) >= 3 else " | ".join(cards),
            color_identity=combo_data.get("color_identity", []),
            cards_in_combo=cards,
            results_in_combo=results,
            decks_edhrec=combo_data.get("deck_count", 0),
            variants=combo_data.get("variants", 0),
            combo_url=combo_data.get("combo_url"),
        )
    except Exception as exc:
        logger.warning("Error creating combo from text data: %s", exc)
        return None


async def fetch_commander_combos(query: str, search_type: str = "commander") -> List[ComboResult]:
    """Fetch combo data from Commander Spellbook using the backend API."""
    if not query or not query.strip():
        return []

    clean_query = query.strip()
    encoded_query = quote_plus(clean_query)
    api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"
    combo_results: List[ComboResult] = []

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "results" in data:
                for variant in data.get("results", []):
                    parsed = parse_variant_to_combo_result(variant)
                    if parsed:
                        combo_results.append(parsed)

            if not combo_results:
                search_url = f"{COMMANDERSPELLBOOK_PUBLIC_SEARCH_URL}{encoded_query}"
                try:
                    html_resp = await client.get(search_url)
                    html_resp.raise_for_status()
                    html_content = html_resp.text
                    combo_results = await parse_combo_results_from_html(html_content)
                except Exception as html_exc:
                    logger.error("Error fetching combos from search page for %s: %s", query, html_exc)

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
            if not result.cards_in_combo and details.get("cards_in_combo"):
                result.cards_in_combo = details["cards_in_combo"]
            if not result.results_in_combo and details.get("results_in_combo"):
                result.results_in_combo = details["results_in_combo"]
            if not result.combo_name and details.get("combo_name"):
                result.combo_name = details["combo_name"]
            if result.decks_edhrec is None and details.get("decks_edhrec") is not None:
                result.decks_edhrec = details["decks_edhrec"]
            if not result.combo_url and details.get("combo_url"):
                result.combo_url = details["combo_url"]
    except Exception as exc:
        logger.error("Error fetching combos for %s search: %s", search_type, exc)
        raise

    return combo_results


@router.get("/combos/commander/{commander_name}", response_model=ComboSearchResponse)
async def get_commander_combos_endpoint(
    commander_name: str,
    api_key: str = Depends(verify_api_key),
) -> ComboSearchResponse:
    """Fetch all combos for a specific commander from Commander Spellbook."""
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


@router.get("/combos/search", response_model=ComboSearchResponse)
async def search_combos_by_card(
    card_name: str = Query(..., description="Card name to search for in combos"),
    api_key: str = Depends(verify_api_key),
) -> ComboSearchResponse:
    """Search for combos containing a specific card from Commander Spellbook."""
    if not card_name or not card_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Card name is required and cannot be empty",
        )

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


@router.get("/debug/combos/test", response_model=Dict[str, Any])
async def debug_combo_search(
    query: str = Query(..., description="Test search query"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """Debug endpoint to test combo search and show raw backend API info."""
    encoded_query = quote_plus(query)
    api_url = f"{COMMANDERSPELLBOOK_BASE_URL}variants?q={encoded_query}"

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        trust_env=False,
    ) as client:
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
            "first_result_identity": first_result.get("identity") if first_result else None,
            "api_endpoint_working": True,
        },
        "sample_result": first_result,
        "timestamp": datetime.utcnow().isoformat(),
    }
