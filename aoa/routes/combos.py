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


# Late game 2-card combos from EDHRec - acceptable for play in Brackets 3, 4, and 5
# Source: https://edhrec.com/combos/late-game-2-card-combos
LATE_GAME_COMBOS = [
    {"cards": ["Aetherflux Reservoir", "Exquisite Blood"], "effects": ["Infinite lifegain", "Infinite damage"]},
    {"cards": ["Sheoldred, the Apocalypse", "Peer into the Abyss"], "effects": ["Draw half deck", "Massive damage"]},
    {"cards": ["Orcish Bowmasters", "Peer into the Abyss"], "effects": ["Draw half deck", "Massive damage and tokens"]},
    {"cards": ["Peer into the Abyss", "Underworld Dreams"], "effects": ["Draw half deck", "Massive damage"]},
    {"cards": ["Niv-Mizzet, Visionary", "Niv-Mizzet, Parun"], "effects": ["Infinite draw", "Infinite damage"]},
    {"cards": ["Aurelia, the Warleader", "Helm of the Host"], "effects": ["Infinite combat phases"]},
    {"cards": ["Vraska, Betrayal's Sting", "Vorinclex, Monstrous Raider"], "effects": ["Instant ultimate", "Win the game"]},
    {"cards": ["Psychosis Crawler", "Peer into the Abyss"], "effects": ["Draw half deck", "Massive damage"]},
    {"cards": ["Jeska's Will", "Reiterate"], "effects": ["Infinite mana", "Infinite storm count"]},
    {"cards": ["Dragon Tempest", "Ancient Gold Dragon"], "effects": ["Massive damage on ETB"]},
    {"cards": ["Polyraptor", "Marauding Raptor"], "effects": ["Infinite tokens", "Infinite damage"]},
    {"cards": ["Mana Geyser", "Reiterate"], "effects": ["Infinite mana", "Infinite storm count"]},
    {"cards": ["Approach of the Second Sun", "Mystical Tutor"], "effects": ["Quick second cast", "Win the game"]},
    {"cards": ["Teferi, Temporal Archmage", "The Chain Veil"], "effects": ["Infinite planeswalker activations", "Infinite mana"]},
    {"cards": ["Approach of the Second Sun", "Windfall"], "effects": ["Quick redraw", "Win the game"]},
    {"cards": ["Old Gnawbone", "Hellkite Charger"], "effects": ["Infinite combat phases", "Infinite treasure"]},
    {"cards": ["The World Tree", "Maskwood Nexus"], "effects": ["Put all gods onto battlefield"]},
    {"cards": ["Aggravated Assault", "Old Gnawbone"], "effects": ["Infinite combat phases", "Infinite treasure"]},
    {"cards": ["Beacon of Immortality", "Sanguine Bond"], "effects": ["Double life", "Massive damage"]},
    {"cards": ["Ob Nixilis, the Hate-Twisted", "Peer into the Abyss"], "effects": ["Draw half deck", "Massive damage"]},
    {"cards": ["Cultivator Colossus", "Abundance"], "effects": ["Put all lands onto battlefield", "Draw remaining deck"]},
    {"cards": ["Niv-Mizzet, Visionary", "Niv-Mizzet, the Firemind"], "effects": ["Infinite draw", "Infinite damage"]},
    {"cards": ["Duskmantle Guildmage", "Maddening Cacophony"], "effects": ["Mill half deck", "Massive damage"]},
    {"cards": ["Brass's Bounty", "Revel in Riches"], "effects": ["Massive treasure", "Potential win"]},
    {"cards": ["Fleet Swallower", "Bruvac the Grandiloquent"], "effects": ["Mill entire library"]},
    {"cards": ["Peer into the Abyss", "Bloodletter of Aclazotz"], "effects": ["Draw half deck", "Doubled damage"]},
    {"cards": ["Orthion, Hero of Lavabrink", "Terror of the Peaks"], "effects": ["Token copies", "Massive damage"]},
    {"cards": ["Maze's End", "Reshape the Earth"], "effects": ["Get all gates", "Win the game"]},
    {"cards": ["Approach of the Second Sun", "Reprieve"], "effects": ["Bounce and recast", "Win the game"]},
    {"cards": ["Riverchurn Monument", "Maddening Cacophony"], "effects": ["Mill combo", "Massive damage"]},
    {"cards": ["Aurelia, the Warleader", "Sword of Hearth and Home"], "effects": ["Infinite combat phases"]},
    {"cards": ["Exquisite Blood", "Defiant Bloodlord"], "effects": ["Infinite lifegain", "Infinite damage"]},
    {"cards": ["Razorkin Needlehead", "Peer into the Abyss"], "effects": ["Draw half deck", "Massive damage"]},
    {"cards": ["Enter the Infinite", "Thassa's Oracle"], "effects": ["Draw entire deck", "Win the game"]},
    {"cards": ["Peer into the Abyss", "Alhammarret's Archive"], "effects": ["Draw most of deck", "Doubled draw"]},
    {"cards": ["Jace, Wielder of Mysteries", "Enter the Infinite"], "effects": ["Draw entire deck", "Win the game"]},
    {"cards": ["Drogskol Reaver", "Queza, Augur of Agonies"], "effects": ["Infinite draw", "Infinite damage"]},
    {"cards": ["Bootleggers' Stash", "Revel in Riches"], "effects": ["Massive treasure", "Potential win"]},
    {"cards": ["Astral Dragon", "Cursed Mirror"], "effects": ["Infinite token copies"]},
    {"cards": ["Kudo, King Among Bears", "Elesh Norn, Grand Cenobite"], "effects": ["One-sided board wipe"]},
    {"cards": ["Old Gnawbone", "Revel in Riches"], "effects": ["Massive treasure", "Potential win"]},
    {"cards": ["Thousand-Year Storm", "Reiterate"], "effects": ["Infinite storm copies"]},
    {"cards": ["Brine Elemental", "Vesuvan Shapeshifter"], "effects": ["Opponents skip untap steps"]},
    {"cards": ["Biovisionary", "Rite of Replication"], "effects": ["Win the game with copies"]},
    {"cards": ["Approach of the Second Sun", "Narset's Reversal"], "effects": ["Bounce and recast", "Win the game"]},
    {"cards": ["Maze's End", "Scapeshift"], "effects": ["Get all gates", "Win the game"]},
    {"cards": ["Mikaeus, the Unhallowed", "Triskelion"], "effects": ["Infinite damage"]},
    {"cards": ["Vito, Thorn of the Dusk Rose", "Shard of the Nightbringer"], "effects": ["Halve life", "Massive damage"]},
    {"cards": ["Shard of the Nightbringer", "Sanguine Bond"], "effects": ["Halve life", "Massive damage"]},
    {"cards": ["Approach of the Second Sun", "Demonic Tutor"], "effects": ["Quick second cast", "Win the game"]},
    {"cards": ["Toxrill, the Corrosive", "Maha, Its Feathers Night"], "effects": ["Instant board wipe", "Token generation"]},
    {"cards": ["Wanderwine Prophets", "Deeproot Pilgrimage"], "effects": ["Infinite extra turns"]},
    {"cards": ["Peer into the Abyss", "Teferi's Ageless Insight"], "effects": ["Draw most of deck", "Doubled draw"]},
    {"cards": ["Vizkopa Guildmage", "Revival // Revenge"], "effects": ["Double life", "Massive damage"]},
    {"cards": ["Be'lakor, the Dark Master", "Rite of Replication"], "effects": ["Massive damage from ETB"]},
    {"cards": ["Brass's Bounty", "Reiterate"], "effects": ["Infinite treasure", "Infinite mana"]},
    {"cards": ["The World Tree", "Purphoros, God of the Forge"], "effects": ["Put all gods onto battlefield", "Massive damage"]},
    {"cards": ["Mindslaver", "Academy Ruins"], "effects": ["Lock opponent out of game"]},
    {"cards": ["Astarion, the Decadent", "Blood Tribute"], "effects": ["Halve life", "Massive lifegain"]},
    {"cards": ["Scourge of the Throne", "Helm of the Host"], "effects": ["Infinite combat phases"]},
    {"cards": ["Emry, Lurker of the Loch", "Mindslaver"], "effects": ["Lock opponent out of game"]},
    {"cards": ["Vizkopa Guildmage", "Beacon of Immortality"], "effects": ["Double life", "Massive damage"]},
    {"cards": ["Toralf, God of Fury", "Star of Extinction"], "effects": ["Chain massive damage"]},
    {"cards": ["Palinchron", "Deadeye Navigator"], "effects": ["Infinite mana"]},
    {"cards": ["Ad Nauseam", "Teferi's Protection"], "effects": ["Draw entire deck safely"]},
    {"cards": ["Bloodletter of Aclazotz", "Shard of the Nightbringer"], "effects": ["Halve life twice", "Massive damage"]},
    {"cards": ["Drogskol Reaver", "Shabraz, the Skyshark"], "effects": ["Infinite draw", "Infinite counters"]},
    {"cards": ["Riverchurn Monument", "Cut Your Losses"], "effects": ["Mill combo"]},
    {"cards": ["Approach of the Second Sun", "Vampiric Tutor"], "effects": ["Quick second cast", "Win the game"]},
    {"cards": ["Akki Battle Squad", "Helm of the Host"], "effects": ["Infinite combat phases"]},
    {"cards": ["Grievous Wound", "Wound Reflection"], "effects": ["Halve life", "Doubled damage"]},
    {"cards": ["Havoc Festival", "Wound Reflection"], "effects": ["Halve life", "Doubled damage"]},
    {"cards": ["Realmbreaker, the Invasion Tree", "Maskwood Nexus"], "effects": ["Put all creatures onto battlefield"]},
    {"cards": ["Body of Knowledge", "Niv-Mizzet, the Firemind"], "effects": ["Infinite draw", "Infinite damage"]},
    {"cards": ["Bloodthirsty Conqueror", "Defiant Bloodlord"], "effects": ["Infinite damage"]},
    {"cards": ["Drogskol Reaver", "Sheoldred, the Apocalypse"], "effects": ["Infinite draw", "Infinite lifegain"]},
    {"cards": ["Orthion, Hero of Lavabrink", "Fanatic of Mogis"], "effects": ["Token copies", "Massive damage"]},
    {"cards": ["The World Tree", "Arcane Adaptation"], "effects": ["Put all gods onto battlefield"]},
    {"cards": ["The World Tree", "Rukarumel, Biologist"], "effects": ["Put all gods onto battlefield"]},
    {"cards": ["Brass's Bounty", "Mechanized Production"], "effects": ["Massive treasure", "Potential win"]},
    {"cards": ["Approach of the Second Sun", "Personal Tutor"], "effects": ["Quick second cast", "Win the game"]},
    {"cards": ["Mirkwood Bats", "Plague of Vermin"], "effects": ["Pay life for damage"]},
    {"cards": ["Heartless Hidetsugu", "Angrath's Marauders"], "effects": ["Doubled damage", "Massive damage"]},
    {"cards": ["Solemnity", "Decree of Silence"], "effects": ["Lock opponents out of spells"]},
    {"cards": ["Shard of the Nightbringer", "Enduring Tenacity"], "effects": ["Halve life", "Drain trigger"]},
    {"cards": ["Gisela, Blade of Goldnight", "Heartless Hidetsugu"], "effects": ["Doubled damage", "Kill opponents"]},
    {"cards": ["Avacyn, Angel of Hope", "Worldslayer"], "effects": ["One-sided board wipe", "Keep your board"]},
    {"cards": ["Avacyn, Angel of Hope", "Nevinyrral's Disk"], "effects": ["One-sided board wipe", "Keep your board"]},
    {"cards": ["Approach of the Second Sun", "Scroll Rack"], "effects": ["Quick redraw", "Win the game"]},
    {"cards": ["Blightsteel Colossus", "Chandra's Ignition"], "effects": ["Infect damage to all opponents"]},
    {"cards": ["Zedruu the Greathearted", "Transcendence"], "effects": ["Donate Transcendence", "Kill opponent"]},
    {"cards": ["Terror of the Peaks", "Rite of Replication"], "effects": ["Token copies", "Massive damage"]},
    {"cards": ["Twinning Staff", "Dramatic Reversal"], "effects": ["Infinite mana", "Infinite untaps"]},
    {"cards": ["Hellkite Charger", "Bear Umbra"], "effects": ["Infinite combat phases"]},
    {"cards": ["Tivit, Seller of Secrets", "Deadeye Navigator"], "effects": ["Infinite votes", "Infinite value"]},
    {"cards": ["Fraying Omnipotence", "Wound Reflection"], "effects": ["Halve life", "Doubled damage"]},
    {"cards": ["Doppelgang", "Biovisionary"], "effects": ["Win the game with copies"]},
    {"cards": ["Approach of the Second Sun", "Diabolic Tutor"], "effects": ["Quick second cast", "Win the game"]},
    {"cards": ["Venser, Shaper Savant", "Approach of the Second Sun"], "effects": ["Bounce and recast", "Win the game"]},
]

# Allowed brackets for late-game combos
LATE_GAME_COMBO_BRACKETS = ["3", "4", "5"]


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



@router.get("/combos/early-game", response_model=Dict[str, Any])
async def get_early_game_combos(
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Get the complete list of early-game 2-card combos.
    
    These combos are NOT acceptable for brackets 1 (Exhibition), 2 (Core), or 3 (Upgraded).
    They are only acceptable for brackets 4 (Optimized) and 5 (cEDH).
    """
    from aoa.routes.deck_validation import EARLY_GAME_COMBO_PAIRS
    
    return {
        "success": True,
        "total_combos": len(EARLY_GAME_COMBO_PAIRS),
        "acceptable_brackets": ["4", "5"],
        "bracket_description": "Acceptable ONLY for brackets 4 (Optimized) and 5 (cEDH)",
        "combos": [
            {
                "cards": [combo[0], combo[1]],
                "card_1": combo[0],
                "card_2": combo[1]
            }
            for combo in EARLY_GAME_COMBO_PAIRS
        ],
        "source": "https://edhrec.com/combos/early-game-2-card-combos",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/combos/late-game", response_model=Dict[str, Any])
async def get_late_game_combos(
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Get the complete list of late-game 2-card combos.
    
    These combos are considered acceptable for play in brackets 3, 4, and 5
    according to community voting on EDHRec.
    """
    return {
        "success": True,
        "total_combos": len(LATE_GAME_COMBOS),
        "acceptable_brackets": LATE_GAME_COMBO_BRACKETS,
        "bracket_description": "Acceptable for brackets 3 (Upgraded), 4 (Optimized), and 5 (cEDH)",
        "combos": [
            {
                "cards": combo["cards"],
                "effects": combo["effects"],
                "card_1": combo["cards"][0],
                "card_2": combo["cards"][1]
            }
            for combo in LATE_GAME_COMBOS
        ],
        "source": "https://edhrec.com/combos/late-game-2-card-combos",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/combos/search-early-game", response_model=Dict[str, Any])
async def search_early_game_combos_by_card(
    card_name: str = Query(..., description="Card name to search for in early-game combos"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Search for early-game combos containing a specific card.
    
    Returns all early-game 2-card combos that include the specified card.
    """
    from aoa.routes.deck_validation import EARLY_GAME_COMBO_PAIRS
    
    if not card_name or not card_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Card name is required and cannot be empty",
        )
    
    normalized_search = card_name.lower().strip()
    matching_combos = []
    
    for card1, card2 in EARLY_GAME_COMBO_PAIRS:
        if normalized_search in card1.lower() or normalized_search in card2.lower():
            partner_card = card2 if normalized_search in card1.lower() else card1
            matching_combos.append({
                "cards": [card1, card2],
                "partner_card": partner_card,
                "acceptable_brackets": ["4", "5"],
            })
    
    return {
        "success": True,
        "search_query": card_name,
        "combos_found": len(matching_combos),
        "combos": matching_combos,
        "acceptable_brackets": ["4", "5"],
        "bracket_recommendation": "These combos are acceptable ONLY for brackets 4 and 5",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/combos/search-late-game", response_model=Dict[str, Any])
async def search_late_game_combos_by_card(
    card_name: str = Query(..., description="Card name to search for in late-game combos"),
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Search for late-game combos containing a specific card.
    
    Returns all late-game 2-card combos that include the specified card.
    """
    if not card_name or not card_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Card name is required and cannot be empty",
        )
    
    normalized_search = card_name.lower().strip()
    matching_combos = []
    
    for combo in LATE_GAME_COMBOS:
        if any(normalized_search in card.lower() for card in combo["cards"]):
            matching_combos.append({
                "cards": combo["cards"],
                "effects": combo["effects"],
                "partner_card": [card for card in combo["cards"] if normalized_search not in card.lower()][0] if len(combo["cards"]) == 2 else None,
                "acceptable_brackets": LATE_GAME_COMBO_BRACKETS,
            })
    
    return {
        "success": True,
        "search_query": card_name,
        "combos_found": len(matching_combos),
        "combos": matching_combos,
        "acceptable_brackets": LATE_GAME_COMBO_BRACKETS,
        "bracket_recommendation": "These combos are acceptable for brackets 3, 4, and 5",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/combos/info", response_model=Dict[str, Any])
async def get_combo_api_info(
    api_key: str = Depends(verify_api_key),
) -> Dict[str, Any]:
    """
    Get information about the combo API endpoints.
    
    Provides an overview of available endpoints, combo categories, and usage examples.
    """
    from aoa.routes.deck_validation import EARLY_GAME_COMBO_PAIRS
    
    return {
        "success": True,
        "name": "Commander Combo API",
        "version": "2.0.0",
        "description": "Search Commander combos and explore bracket-appropriate 2-card combinations",
        "endpoints": {
            "/api/v1/combos/commander/{commander_name}": {
                "method": "GET",
                "description": "Fetch all combos for a specific commander from Commander Spellbook",
                "example": "/api/v1/combos/commander/Kinnan,%20Bonder%20Prodigy"
            },
            "/api/v1/combos/search": {
                "method": "GET",
                "description": "Search for combos containing a specific card",
                "parameters": {"card_name": "Card name to search for"},
                "example": "/api/v1/combos/search?card_name=Thassa's%20Oracle"
            },
            "/api/v1/combos/early-game": {
                "method": "GET",
                "description": f"Get the complete list of early-game 2-card combos ({len(EARLY_GAME_COMBO_PAIRS)} combos)",
                "bracket_info": "Acceptable ONLY for brackets 4 and 5"
            },
            "/api/v1/combos/search-early-game": {
                "method": "GET",
                "description": "Search for early-game combos containing a specific card",
                "parameters": {"card_name": "Card name to search for"},
                "example": "/api/v1/combos/search-early-game?card_name=Thassa's%20Oracle"
            },
            "/api/v1/combos/late-game": {
                "method": "GET",
                "description": f"Get the complete list of late-game 2-card combos ({len(LATE_GAME_COMBOS)} combos)",
                "bracket_info": "Acceptable for brackets 3, 4, and 5"
            },
            "/api/v1/combos/search-late-game": {
                "method": "GET",
                "description": "Search for late-game combos containing a specific card",
                "parameters": {"card_name": "Card name to search for"},
                "example": "/api/v1/combos/search-late-game?card_name=Approach%20of%20the%20Second%20Sun"
            },
            "/api/v1/debug/combos/test": {
                "method": "GET",
                "description": "Debug endpoint to test combo search",
                "parameters": {"query": "Test search query"}
            }
        },
        "combo_categories": {
            "commander_spellbook": {
                "description": "Full combo database from Commander Spellbook",
                "includes": "All card combos with effects and results"
            },
            "early_game_combos": {
                "description": "Community-voted early-game 2-card combos",
                "total": len(EARLY_GAME_COMBO_PAIRS),
                "acceptable_brackets": ["4", "5"],
                "source": "https://edhrec.com/combos/early-game-2-card-combos"
            },
            "late_game_combos": {
                "description": "Community-voted late-game 2-card combos",
                "total": len(LATE_GAME_COMBOS),
                "acceptable_brackets": LATE_GAME_COMBO_BRACKETS,
                "source": "https://edhrec.com/combos/late-game-2-card-combos"
            }
        },
        "bracket_system": {
            "1_exhibition": "No 2-card combos",
            "2_core": "No 2-card combos",
            "3_upgraded": "Late-game combos acceptable (after turn 6)",
            "4_optimized": "All combos acceptable",
            "5_cedh": "All combos acceptable"
        },
        "note": "For deck validation (checking if your deck contains these combos), use the /api/v1/deck/validate endpoint",
        "timestamp": datetime.utcnow().isoformat(),
    }
