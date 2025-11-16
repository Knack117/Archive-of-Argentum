"""Commander summary and average deck endpoints."""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from aoa.constants import EDHREC_BASE_URL
from aoa.models import CommanderCard, CommanderCombo, CommanderSummary, CommanderTag, SimilarCommander
from aoa.security import verify_api_key
from aoa.services.commanders import (
    extract_commander_name_from_url,
    normalize_commander_name,
    scrape_edhrec_commander_page,
)

router = APIRouter(prefix="/api/v1", tags=["commanders"])
logger = logging.getLogger(__name__)


@router.get("/commander/summary", response_model=CommanderSummary)
async def get_commander_summary(
    name: Optional[str] = Query(None),
    commander_url: Optional[str] = Query(None),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """Fetch EDHRec commander summary data."""
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

    commander_data = await scrape_edhrec_commander_page(commander_url_val)

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


@router.get("/average_deck/summary", response_model=CommanderSummary)
async def get_average_deck_summary(
    commander_name: Optional[str] = Query(None),
    commander_slug: Optional[str] = Query(None),
    bracket: Optional[str] = Query(
        None,
        description="Bracket type: exhibition, core, upgraded, optimized, or cedh.",
    ),
    api_key: str = Depends(verify_api_key),
) -> CommanderSummary:
    """Fetch a summary of an EDHRec Average Deck page for a given commander."""
    if not commander_name and not commander_slug:
        raise HTTPException(
            status_code=400,
            detail="You must provide either 'commander_name' or 'commander_slug'.",
        )

    if commander_slug:
        slug = commander_slug.strip().lower()
    else:
        slug = normalize_commander_name(commander_name or "")

    base_url = f"{EDHREC_BASE_URL}average-decks/{slug}"
    if bracket:
        base_url += f"/{bracket.strip().lower()}"

    try:
        commander_data = await scrape_edhrec_commander_page(base_url)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error fetching average deck summary for %s: %s", slug, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch average deck summary: {exc}",
        )

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
